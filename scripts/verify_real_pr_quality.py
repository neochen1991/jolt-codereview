from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def finding_id(finding: dict[str, Any]) -> str:
    return str(finding.get("finding_id") or finding.get("id") or finding.get("dedupe_hash") or "<unknown>")


def quality_trace(finding: dict[str, Any]) -> dict[str, Any]:
    value = finding.get("quality_trace")
    return value if isinstance(value, dict) else {}


def evidence_score(finding: dict[str, Any]) -> dict[str, Any]:
    direct = finding.get("evidence_score")
    if isinstance(direct, dict):
        return direct
    trace_score = quality_trace(finding).get("evidence_score")
    return trace_score if isinstance(trace_score, dict) else {}


def consensus_agents(finding: dict[str, Any]) -> list[Any]:
    direct = finding.get("consensus_agents")
    if isinstance(direct, list):
        return direct
    trace_agents = quality_trace(finding).get("consensus_agents")
    return trace_agents if isinstance(trace_agents, list) else []


def critic_verdict(finding: dict[str, Any]) -> dict[str, Any]:
    verdict = quality_trace(finding).get("critic_verdict")
    return verdict if isinstance(verdict, dict) else {}


def validate_quality_fields(findings: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for finding in findings:
        fid = finding_id(finding)
        score = evidence_score(finding)
        if not score:
            failures.append(f"{fid}: missing evidence_score")
        else:
            try:
                value = float(score.get("score"))
            except (TypeError, ValueError):
                failures.append(f"{fid}: evidence_score.score is not numeric")
            else:
                if value < 0 or value > 1:
                    failures.append(f"{fid}: evidence_score.score {value} outside [0, 1]")
            components = score.get("components")
            if not isinstance(components, dict) or not components:
                failures.append(f"{fid}: missing evidence_score.components")
        if not consensus_agents(finding):
            failures.append(f"{fid}: missing consensus_agents")
        verdict = critic_verdict(finding)
        if not verdict:
            failures.append(f"{fid}: missing quality_trace.critic_verdict")
        elif not str(verdict.get("verdict") or "").strip():
            failures.append(f"{fid}: critic_verdict.verdict is empty")
    return failures


def run_score(args: argparse.Namespace, report_path: Path) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/score_real_pr_reviews.py",
        "--gold",
        args.gold,
        "--findings",
        args.findings,
        "--out",
        str(report_path),
        "--min-precision",
        str(args.min_precision),
        "--min-recall",
        str(args.min_recall),
        "--max-negative-fp",
        str(args.max_negative_fp),
    ]
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)
    return json.loads(report_path.read_text("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default="evaluation/real_gold_set.jsonl")
    parser.add_argument("--findings", default="evaluation/real_findings.jsonl")
    parser.add_argument("--min-precision", type=float, default=0.80)
    parser.add_argument("--min-recall", type=float, default=0.65)
    parser.add_argument("--min-high-severity-accuracy", type=float, default=0.80)
    parser.add_argument("--max-negative-fp", type=int, default=0)
    args = parser.parse_args()

    findings = read_jsonl(ROOT / args.findings)
    with tempfile.TemporaryDirectory(prefix="jolt-real-pr-quality-") as tmpdir:
        report_path = Path(tmpdir) / "real-pr-report.json"
        report = run_score(args, report_path)

    failures = validate_quality_fields(findings)
    high_accuracy = float(report.get("high_severity_accuracy") or report.get("high_recall") or 0)
    if high_accuracy < args.min_high_severity_accuracy:
        failures.append(f"high_severity_accuracy {high_accuracy} < {args.min_high_severity_accuracy}")
    if failures:
        raise SystemExit("real PR quality gate failed: " + "; ".join(failures))

    print(
        json.dumps(
            {
                "ok": True,
                "verified": "real_pr_quality",
                "precision": report.get("precision"),
                "recall": report.get("recall"),
                "high_severity_accuracy": high_accuracy,
                "finding_count": report.get("finding_count"),
                "gold_count": report.get("gold_count"),
                "negative_false_positive_count": report.get("negative_false_positive_count"),
                "quality_fields_checked": len(findings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
