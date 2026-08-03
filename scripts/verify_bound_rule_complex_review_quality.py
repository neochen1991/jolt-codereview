from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "mr-backend" / "worker"
sys.path.insert(0, str(WORKER))

fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

from orchestration.nodes.judge_findings import _merge_finding_metadata
from orchestration.nodes.run_experts import (
    _bound_review_coverage_record,
    _bound_rule_batches,
    _enforce_bound_batch_findings,
    _is_bound_skip_marker,
    _summarize_bound_review_coverage,
)


SECURITY_SKILL = """# Secure Review Skill

## SEC-CMD-001 命令注入检查
- severity: high

### 检查点
外部输入不能拼接进入 Runtime.exec 或 ProcessBuilder。

### 证据要求
- 外部输入来源
- 命令执行 sink
- 缺少白名单或枚举映射

### 误报模式
- 固定常量命令
- 参数来自内部枚举

## SEC-PATH-002 路径穿越检查
- severity: high

### 检查点
请求路径参与文件读取时必须 normalize/canonical 并限制在基准目录内。

### 证据要求
- 外部输入来源
- 文件读取 sink
- 缺少路径规范化

## SEC-LOG-003 日志脱敏检查
- severity: medium

### 检查点
日志不能输出 token、password 等敏感字段。
"""


GOLD_RULE_IDS = {"SEC-CMD-001", "SEC-PATH-002", "TEAM-AUTH-001"}


def _agent_context() -> dict[str, Any]:
    return {
        "agent_id": "security_agent",
        "display_name": "安全专家",
        "applies_to": {
            "persona": "安全专家画像会检查命令注入、路径穿越和权限绕过。",
            "exclusive_scope": "安全问题",
            "review_scope": "Java Web MR",
        },
        "bound_rules": [
            {
                "rule_id": "TEAM-AUTH-001",
                "title": "管理接口必须服务端鉴权",
                "check": "新增 /admin 接口必须使用 @PreAuthorize 或等价服务端权限校验。",
                "required_evidence": "管理接口路径；缺少 @PreAuthorize；存在状态修改操作",
            }
        ],
        "custom_skills": ["secure-review-skill"],
        "skill_assets": [
            {
                "skill_key": "secure-review-skill",
                "asset_path": "SKILL.md",
                "asset_type": "skill",
                "content": SECURITY_SKILL,
            }
        ],
    }


def _finding(rule_id: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "severity": "high",
        "confidence": 0.91,
        "agent_id": "security_agent",
        "file_path": "src/main/java/com/acme/review/VulnerableController.java",
        "line_start": 42,
        "line_end": 42,
        "title": f"{rule_id} 命中",
        "problem_description": "复杂 MR 中的安全问题。",
        "recommendation": "按规则修复并补充测试。",
        "suggested_code": "@PreAuthorize(\"hasAuthority('ADMIN')\")",
        "evidence": "外部输入来源 request.getParameter 进入 Runtime.exec 命令执行 sink，缺少白名单或枚举映射。",
        "covered_rules": [rule_id],
        "skipped_rules": [],
        "rule_id": rule_id,
    }
    item.update(overrides)
    return item


def _outputs_for_batch(batch: dict[str, Any]) -> list[dict[str, Any]]:
    label = str(batch.get("label") or "")
    if label == "bound_rule:TEAM-AUTH-001":
        return [
            _finding(
                "TEAM-AUTH-001",
                evidence="管理接口路径 /admin/payments/force 缺少 @PreAuthorize，存在支付状态修改操作。",
                suggested_code='@PreAuthorize("hasAuthority(\'PAYMENT_ADMIN\')")',
            ),
            _finding(
                "PROFILE-AUTHZ-009",
                evidence="专家画像中的通用权限规则也描述了同一问题。",
                covered_rules=["PROFILE-AUTHZ-009"],
            ),
        ]
    if label == "bound_skill:secure-review-skill:SEC-CMD-001":
        return [
            _finding("SEC-CMD-001"),
            _finding(
                "SEC-CMD-001",
                title="固定常量命令不应输出",
                problem_description="这里是固定常量命令，命中 Skill 的误报模式。",
                evidence="Runtime.exec(\"date\") 是固定常量命令。",
            ),
            _finding(
                "SEC-INJECT-003",
                title="错误改写为相邻通用规则 ID",
                covered_rules=["SEC-INJECT-003"],
            ),
        ]
    if label == "bound_skill:secure-review-skill:SEC-PATH-002":
        return [
            _finding(
                "SEC-PATH-002",
                file_path="src/main/java/com/acme/review/FileController.java",
                line_start=88,
                line_end=88,
                evidence="外部输入来源 request.getParameter(\"path\") 进入 Files.readString 文件读取 sink，缺少路径规范化。",
                suggested_code="Path safe = base.resolve(input).normalize();",
            )
        ]
    if label == "bound_skill:secure-review-skill:SEC-LOG-003":
        return [{"covered_rules": [], "skipped_rules": ["SEC-LOG-003"]}]
    return []


def _rule_id(finding: dict[str, Any]) -> str:
    covered = [str(rule) for rule in (finding.get("covered_rules") or []) if str(rule or "").strip()]
    return str(finding.get("rule_id") or (covered[0] if covered else "")).strip()


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for finding in findings:
        rule_id = _rule_id(finding)
        unique.setdefault(rule_id, finding)
    return list(unique.values())


def _score(findings: list[dict[str, Any]]) -> dict[str, Any]:
    accepted_ids = {_rule_id(item) for item in findings if _rule_id(item)}
    tp = sorted(accepted_ids & GOLD_RULE_IDS)
    fp = sorted(accepted_ids - GOLD_RULE_IDS)
    fn = sorted(GOLD_RULE_IDS - accepted_ids)
    precision = round(len(tp) / (len(tp) + len(fp)), 4) if tp or fp else 1.0
    recall = round(len(tp) / (len(tp) + len(fn)), 4) if tp or fn else 1.0
    return {
        "precision": precision,
        "recall": recall,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def _assert_priority_merge(accepted: list[dict[str, Any]]) -> None:
    by_rule = {_rule_id(item): item for item in accepted}
    skill_cmd = dict(by_rule["SEC-CMD-001"])
    skill_merged = _merge_finding_metadata(
        skill_cmd,
        _finding(
            "TEAM-AUTH-001",
            covered_rules=["TEAM-AUTH-001"],
            skipped_rules=["TEAM-AUTH-001"],
            review_batch_label="bound_rule:TEAM-AUTH-001",
        ),
    )
    if skill_merged["covered_rules"] != ["SEC-CMD-001"]:
        raise AssertionError(f"Skill priority was not preserved: {skill_merged}")
    if skill_merged["skipped_rules"]:
        raise AssertionError(f"Lower-priority rule leaked into Skill skipped_rules: {skill_merged}")

    bound_rule = dict(by_rule["TEAM-AUTH-001"])
    rule_merged = _merge_finding_metadata(
        bound_rule,
        _finding(
            "PROFILE-AUTHZ-009",
            covered_rules=["PROFILE-AUTHZ-009"],
            skipped_rules=["PROFILE-AUTHZ-009"],
        ),
    )
    if rule_merged["covered_rules"] != ["TEAM-AUTH-001"]:
        raise AssertionError(f"Bound markdown rule priority was not preserved: {rule_merged}")
    if rule_merged["skipped_rules"]:
        raise AssertionError(f"Lower-priority profile rule leaked into skipped_rules: {rule_merged}")


def main() -> None:
    batches = _bound_rule_batches(_agent_context())
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    coverage_records: list[dict[str, Any]] = []

    for batch in batches:
        kept, rejected_items = _enforce_bound_batch_findings(batch, _outputs_for_batch(batch))
        accepted.extend(item for item in kept if not _is_bound_skip_marker(item))
        rejected.extend(rejected_items)
        record = _bound_review_coverage_record("security_agent", batch, kept, rejected_items)
        if record:
            coverage_records.append(record)

    accepted = _dedupe_findings(accepted)
    _assert_priority_merge(accepted)
    attributable = [
        item
        for item in accepted
        if str(item.get("bound_attribution_status") or "") not in {"missing", "mismatch"}
    ]
    attribution_issues = [item for item in accepted if item not in attributable]
    score = _score(attributable)
    coverage = _summarize_bound_review_coverage(coverage_records)
    rejected_reasons = sorted({reason for item in rejected for reason in (item.get("rejected_reasons") or [])})
    attribution_reasons = sorted({str(item.get("bound_attribution_reason") or "") for item in attribution_issues if item.get("bound_attribution_reason")})

    failures: list[str] = []
    if score["precision"] < 1.0:
        failures.append(f"precision {score['precision']} < 1.0")
    if score["recall"] < 1.0:
        failures.append(f"recall {score['recall']} < 1.0")
    if coverage.get("required_count") != 4 or coverage.get("resolved_count") != 4:
        failures.append(f"unexpected bound coverage summary: {coverage}")
    if "bound_skill_checkpoint_mismatch" not in attribution_reasons:
        failures.append(f"missing rewritten Skill ID attribution marker: {attribution_reasons}")
    if "bound_rule_mismatch" not in attribution_reasons:
        failures.append(f"missing rewritten bound rule ID attribution marker: {attribution_reasons}")
    if "bound_false_positive_pattern_match" not in rejected_reasons:
        failures.append(f"missing Skill false-positive rejection: {rejected_reasons}")

    report = {
        "ok": not failures,
        "verified": "complex_bound_rule_skill_review_quality",
        "gold_rule_ids": sorted(GOLD_RULE_IDS),
        "accepted_rule_ids": sorted(_rule_id(item) for item in attributable),
        "retained_attribution_issue_rule_ids": sorted(_rule_id(item) for item in attribution_issues),
        "attribution_reasons": attribution_reasons,
        "rejected_reasons": rejected_reasons,
        "precision": score["precision"],
        "recall": score["recall"],
        "tp": score["tp"],
        "fp": score["fp"],
        "fn": score["fn"],
        "coverage": {
            "required_count": coverage.get("required_count"),
            "resolved_count": coverage.get("resolved_count"),
            "hit_count": coverage.get("hit_count"),
            "skipped_count": coverage.get("skipped_count"),
            "rejected_count": coverage.get("rejected_count"),
            "resolution_rate": coverage.get("resolution_rate"),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("complex bound review quality gate failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
