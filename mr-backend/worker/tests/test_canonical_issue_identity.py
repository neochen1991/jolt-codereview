from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.quality.issue_identity import canonical_issue_fingerprint, cluster_canonical_issues


def auth_finding(**overrides: object) -> dict:
    item = {
        "agent_id": "security_agent",
        "severity": "high",
        "confidence": 0.91,
        "dedupe_hash": "surface-a",
        "file_path": "src/AuthController.java",
        "line_start": 42,
        "line_end": 42,
        "title": "缺少权限验证",
        "problem_description": "更新接口没有验证当前用户是否可以修改目标记录。",
        "evidence": "repository.update(request);",
        "recommendation": "更新前执行资源级权限检查。",
        "covered_rules": ["SEC-AUTH-001"],
    }
    item.update(overrides)
    return item


def test_cross_agent_paraphrases_merge_despite_different_rules() -> None:
    first = auth_finding()
    second = auth_finding(
        agent_id="backend_agent",
        dedupe_hash="surface-b",
        title="接口没有鉴权保护",
        problem_description="调用 repository.update 前未校验操作者对目标资源的授权。",
        covered_rules=["BE-API-001"],
    )

    merged, duplicates = cluster_canonical_issues([first, second])

    assert len(merged) == 1, merged
    assert len(duplicates) == 1, duplicates
    assert merged[0]["dedupe_hash"].startswith("issue_v2_")
    assert merged[0]["merged_agent_ids"] == ["backend_agent", "security_agent"]
    assert merged[0]["covered_rules"] == ["BE-API-001", "SEC-AUTH-001"]
    canonical = merged[0]["quality_trace"]["canonical_issue"]
    assert canonical["root_cause"] == "MISSING_AUTHORIZATION"
    assert canonical["merged_count"] == 2


def test_same_line_distinct_root_causes_remain_independent() -> None:
    sql = auth_finding(
        title="SQL 字符串拼接存在注入风险",
        problem_description="用户输入直接拼接到 SQL 并执行。",
        evidence='String sql = "select * from t where id=" + request.getId();',
        covered_rules=["SEC-INJECT-003"],
    )
    unbounded = auth_finding(
        agent_id="performance_agent",
        title="查询缺少分页或结果上限",
        problem_description="该查询可能一次返回全部数据。",
        evidence="repository.findAll(request);",
        covered_rules=["PERF-QUERY-001"],
    )

    merged, duplicates = cluster_canonical_issues([sql, unbounded])

    assert len(merged) == 2, merged
    assert duplicates == []


def test_same_rule_at_different_lines_remains_independent() -> None:
    first = auth_finding(line_start=42, line_end=42, evidence="repository.updateOne(request);")
    second = auth_finding(line_start=88, line_end=88, evidence="repository.updateTwo(request);")

    merged, duplicates = cluster_canonical_issues([first, second])

    assert len(merged) == 2, merged
    assert duplicates == []


def test_fingerprint_is_stable_across_agent_title_and_input_order() -> None:
    first = auth_finding()
    second = auth_finding(
        agent_id="backend_agent",
        title="接口没有鉴权保护",
        problem_description="目标资源更新缺少授权判断。",
        covered_rules=["BE-API-001"],
    )

    forward, _ = cluster_canonical_issues([first, second])
    reverse, _ = cluster_canonical_issues([second, first])

    assert canonical_issue_fingerprint(first) == canonical_issue_fingerprint(second)
    assert forward[0]["dedupe_hash"] == reverse[0]["dedupe_hash"]
    assert forward[0]["covered_rules"] == reverse[0]["covered_rules"]


def test_llm_and_tool_finding_for_same_root_merge() -> None:
    llm = auth_finding()
    tool = auth_finding(
        agent_id="security_agent",
        tool_name="semgrep",
        source_type="tool",
        title="missing authorization before repository update",
        problem_description="repository update is reachable without an authorization guard",
        covered_rules=["semgrep.auth.missing-check"],
        verification_flags=["tool_promoted"],
    )

    merged, duplicates = cluster_canonical_issues([llm, tool])

    assert len(merged) == 1, merged
    assert len(duplicates) == 1
    assert "semgrep" in merged[0]["quality_trace"]["canonical_issue"]["sources"]


if __name__ == "__main__":
    test_cross_agent_paraphrases_merge_despite_different_rules()
    test_same_line_distinct_root_causes_remain_independent()
    test_same_rule_at_different_lines_remains_independent()
    test_fingerprint_is_stable_across_agent_title_and_input_order()
    test_llm_and_tool_finding_for_same_root_merge()
