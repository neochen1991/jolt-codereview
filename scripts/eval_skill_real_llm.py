from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "mr-backend" / "worker"
DEFAULT_EVAL_DIR = ROOT / "evaluation" / "skill_real_llm"
sys.path.insert(0, str(WORKER))

fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

from llm.client import call_llm
from orchestration.nodes.judge_findings import dedupe_same_line_same_issue_findings
from orchestration.nodes.run_experts import (
    _bound_review_coverage_record,
    _bound_rule_batches,
    _coverage_retry_batch,
    _enforce_bound_batch_findings,
    _is_bound_skip_marker,
    _summarize_bound_review_coverage,
)


class ChangedFile:
    def __init__(self, filename: str, patch: str):
        self.filename = filename
        self.status = "modified"
        self.patch = patch
        self.additions = sum(1 for line in patch.splitlines() if line.startswith("+"))
        self.deletions = sum(1 for line in patch.splitlines() if line.startswith("-"))
        self.changes = self.additions + self.deletions


class MemoryRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.llm_calls: list[dict[str, Any]] = []

    def event(self, span_id: str, event_type: str, message: str, fields: dict[str, Any] | None = None) -> None:
        self.events.append({"span_id": span_id, "type": event_type, "message": message, "fields": fields or {}})

    def llm_call(
        self,
        span_id: str,
        provider: str,
        model: str,
        prompt: str,
        status: str,
        duration_ms: int,
        input_tokens: int,
        output_tokens: int,
        request_id: str | None = None,
        request_messages: list[dict[str, Any]] | None = None,
        response_text: str = "",
    ) -> None:
        self.llm_calls.append(
            {
                "span_id": span_id,
                "provider": provider,
                "model": model,
                "status": status,
                "duration_ms": duration_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "request_id": request_id,
                "response_text": response_text,
                "prompt_preview": prompt[:1200],
            }
        )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), "utf-8")


def load_config(config_path: Path, *, provider: str | None, model: str | None, base_url: str | None, api_key: str | None) -> dict[str, Any]:
    config = json.loads(config_path.read_text("utf-8"))
    config["_project_id"] = "project_real_llm_refund_skill_eval"
    llm = config.setdefault("llm", {})
    llm["enable_response_cache"] = False
    llm["request_timeout_seconds"] = max(300, int(llm.get("request_timeout_seconds") or 300))
    llm["max_output_tokens"] = max(4096, int(llm.get("max_output_tokens") or 4096))
    if provider:
        llm["default_provider"] = provider
    if model and model != "current":
        llm["default_model"] = model
    if base_url:
        llm["default_base_url"] = base_url
    if api_key:
        llm["default_api_key"] = api_key
        llm["default_api_key_env"] = None
    return config


def load_changed_files(mr_path: Path) -> tuple[str, list[ChangedFile]]:
    fixture = json.loads(mr_path.read_text("utf-8"))
    mr_id = str(fixture.get("mr_id") or "mr_skill_real_llm")
    files: list[ChangedFile] = []
    for item in fixture.get("changed_files") or []:
        filename = str(item.get("filename") or "")
        if not filename:
            continue
        patch = item.get("patch")
        if not patch:
            patch = "\n".join(str(line) for line in (item.get("patch_lines") or [])) + "\n"
        files.append(ChangedFile(filename, str(patch)))
    return mr_id, files


def load_skill_assets(skill_dir: Path, skill_key: str) -> list[dict[str, Any]]:
    paths = [skill_dir / "SKILL.md"]
    references = sorted((skill_dir / "references").glob("**/*")) if (skill_dir / "references").exists() else []
    paths.extend(path for path in references if path.is_file())
    assets: list[dict[str, Any]] = []
    for path in paths:
        relative = path.relative_to(skill_dir).as_posix()
        assets.append(
            {
                "skill_key": skill_key,
                "asset_path": relative,
                "asset_type": "skill" if relative == "SKILL.md" else "reference",
                "content": path.read_text("utf-8"),
            }
        )
    return assets


def build_skill_summary(skill_dir: Path) -> str:
    chunks: list[str] = []
    paths = [skill_dir / "SKILL.md"]
    references = sorted((skill_dir / "references").glob("**/*")) if (skill_dir / "references").exists() else []
    paths.extend(path for path in references if path.is_file())
    for path in paths:
        chunks.append(f"# {path.relative_to(skill_dir).as_posix()}\n\n{path.read_text('utf-8')}")
    return "\n\n".join(chunks)


def build_agent_context(skill_dir: Path, skill_key: str) -> dict[str, Any]:
    return {
        "agent_id": "refund_risk_skill_agent",
        "display_name": "退款风险 Skill 专家",
        "max_findings_per_mr": 4,
        "min_confidence": 0.6,
        "applies_to": {
            "persona": "专注退款审核链路的一致性、审计和缓存安全。",
            "exclusive_scope": "只检查绑定 Skill 中定义的退款业务风险规则。",
            "review_scope": "Java Spring 退款审核 MR",
            "custom_prompt": "严格逐条使用 Skill checkpoint；命中时必须使用 Skill 原始 rule_id，不要输出 Skill 之外的问题。",
        },
        "custom_skills": [skill_key],
        "skill_assets": load_skill_assets(skill_dir, skill_key),
        "bound_rules": [],
    }


def normalize_finding(item: dict[str, Any], *, mr_id: str, checkpoint_id: str) -> dict[str, Any]:
    row = dict(item)
    row.setdefault("mr_id", mr_id)
    row.setdefault("merge_request_id", mr_id)
    row.setdefault(
        "finding_id",
        f"real-llm-{checkpoint_id}-{abs(hash(json.dumps(row, ensure_ascii=False, sort_keys=True))) % 1000000}",
    )
    trace = row.get("quality_trace") if isinstance(row.get("quality_trace"), dict) else {}
    trace.setdefault("consensus_agents", ["refund_risk_skill_agent"])
    trace.setdefault("critic_verdict", {"verdict": "real_llm_unjudged", "source": "skill_real_llm_eval"})
    trace.setdefault(
        "evidence_score",
        {
            "score": 0.7,
            "components": {
                "tool_backing": 0.0,
                "snippet_quote": 0.2,
                "line_precision": 0.1,
                "rule_alignment": 0.3,
                "consensus": 0.1,
            },
        },
    )
    row["quality_trace"] = trace
    return row


def score_findings(gold_path: Path, findings_path: Path, report_path: Path) -> dict[str, Any]:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "score_real_pr_reviews.py"),
            "--gold",
            str(gold_path),
            "--findings",
            str(findings_path),
            "--out",
            str(report_path),
            "--min-precision",
            "0.0",
            "--min-recall",
            "0.0",
            "--max-negative-fp",
            "999",
        ],
        cwd=ROOT,
        check=True,
    )
    return json.loads(report_path.read_text("utf-8"))


def threshold_failures(report: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    tp = int(report.get("tp") or 0)
    true_fp = int(report.get("true_fp_count") or 0)
    true_precision = round(tp / max(1, tp + true_fp), 4)
    checks = [
        ("recall", float(report.get("recall") or 0), float(thresholds.get("min_recall") or 0)),
        ("true_precision", true_precision, float(thresholds.get("min_true_precision") or 0)),
        ("precision", float(report.get("precision") or 0), float(thresholds.get("min_precision") or 0)),
    ]
    for name, actual, expected in checks:
        if actual < expected:
            failures.append(f"{name} {actual} < {expected}")
    if int(report.get("duplicate_fp_count") or 0) > int(thresholds.get("max_duplicate_fp_count") or 0):
        failures.append(f"duplicate_fp_count {report.get('duplicate_fp_count')} > {thresholds.get('max_duplicate_fp_count')}")
    if int(report.get("negative_fp_count") or 0) > int(thresholds.get("max_negative_fp_count") or 0):
        failures.append(f"negative_fp_count {report.get('negative_fp_count')} > {thresholds.get('max_negative_fp_count')}")
    return failures


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    eval_dir = Path(args.eval_dir)
    skill_dir = eval_dir / args.skill
    mr_id, files = load_changed_files(eval_dir / "refund-business-mr.json")
    config = load_config(
        Path(args.config),
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
    )
    recorder = MemoryRecorder()
    summary = build_skill_summary(skill_dir)
    agent = build_agent_context(skill_dir, args.skill)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    coverage_records: list[dict[str, Any]] = []
    raw_batches: list[dict[str, Any]] = []

    started = time.time()
    for batch in _bound_rule_batches(agent):
        checkpoint_id = str(batch.get("checkpoint_id") or "")
        span_id = f"skill_real_llm_{checkpoint_id}"
        batch_agent = batch["agent"]
        raw_items = call_llm(config, recorder, span_id, batch_agent, files, summary)
        kept, rejected_items = _enforce_bound_batch_findings(batch, raw_items)
        retry_used = False
        if not kept and checkpoint_id:
            retry_batch = _coverage_retry_batch(batch, reason="missing_after_first_pass")
            if retry_batch:
                retry_used = True
                retry_items = call_llm(config, recorder, f"{span_id}_retry", retry_batch["agent"], files, summary)
                retry_kept, retry_rejected = _enforce_bound_batch_findings(batch, retry_items)
                raw_items.extend(retry_items)
                kept.extend(retry_kept)
                rejected_items.extend(retry_rejected)
        accepted.extend(normalize_finding(item, mr_id=mr_id, checkpoint_id=checkpoint_id) for item in kept if not _is_bound_skip_marker(item))
        rejected.extend(rejected_items)
        record = _bound_review_coverage_record("refund_risk_skill_agent", batch, kept, rejected_items)
        if record:
            record["retry_count"] = 1 if retry_used else 0
            record["retry_hit"] = bool(kept) and retry_used
            coverage_records.append(record)
        raw_batches.append(
            {
                "label": batch.get("label"),
                "checkpoint_id": checkpoint_id,
                "raw_count": len(raw_items),
                "accepted_count": len([item for item in kept if not _is_bound_skip_marker(item)]),
                "skip_count": len([item for item in kept if _is_bound_skip_marker(item)]),
                "rejected_count": len(rejected_items),
                "raw_items": raw_items,
                "accepted_items": kept,
                "rejected_items": rejected_items,
            }
        )

    deduped, dedupe_rejected = dedupe_same_line_same_issue_findings(accepted)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    findings_path = out_dir / "real_llm_skill_findings.jsonl"
    report_path = out_dir / "real_llm_skill_report.json"
    trace_path = out_dir / "real_llm_skill_trace.json"
    write_jsonl(findings_path, deduped)
    report = score_findings(eval_dir / "refund-business-gold.jsonl", findings_path, report_path)
    thresholds = json.loads((eval_dir / "expected-thresholds.json").read_text("utf-8"))
    failures = threshold_failures(report, thresholds)
    token_totals = {
        "input": sum(int(call.get("input_tokens") or 0) for call in recorder.llm_calls),
        "output": sum(int(call.get("output_tokens") or 0) for call in recorder.llm_calls),
    }
    trace = {
        "duration_ms": int((time.time() - started) * 1000),
        "skill_dir": str(skill_dir),
        "coverage": _summarize_bound_review_coverage(coverage_records),
        "accepted_rule_ids": [rule for item in deduped for rule in item.get("covered_rules", [])],
        "rejected_reasons": sorted({reason for item in rejected + dedupe_rejected for reason in item.get("rejected_reasons", [])}),
        "llm_calls": recorder.llm_calls,
        "token_totals": token_totals,
        "events": recorder.events,
        "batches": raw_batches,
        "dedupe_rejected": dedupe_rejected,
        "score": {
            **{key: report.get(key) for key in ["tp", "fp", "fn", "precision", "recall", "high_severity_accuracy"]},
            "true_fp_count": report.get("true_fp_count"),
            "duplicate_fp_count": report.get("duplicate_fp_count"),
            "negative_fp_count": report.get("negative_fp_count"),
            "negative_false_positive_count": report.get("negative_false_positive_count"),
            "missed_gold_ids": report.get("missed_gold_ids"),
            "false_positive_findings": report.get("false_positive_findings"),
        },
        "threshold_failures": failures,
    }
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), "utf-8")
    printable = {
        **trace["score"],
        "accepted_rule_ids": trace["accepted_rule_ids"],
        "rejected_reasons": trace["rejected_reasons"],
        "llm_call_count": len(recorder.llm_calls),
        "tokens": token_totals,
        "duration_ms": trace["duration_ms"],
        "trace_path": str(trace_path),
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("skill real LLM eval failed thresholds: " + "; ".join(failures))
    return trace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-dir", default=str(DEFAULT_EVAL_DIR))
    parser.add_argument("--skill", default="refund-risk-review-skill")
    parser.add_argument("--config", default=str(ROOT / "mr-backend" / "config.json"))
    parser.add_argument("--out-dir", default=str(ROOT / "outputs" / "skill-real-llm"))
    parser.add_argument("--provider")
    parser.add_argument("--model", default="current")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key")
    run_eval(parser.parse_args())


if __name__ == "__main__":
    main()
