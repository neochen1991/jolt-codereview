from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

from prompts.builder import build_prompt
from orchestration.nodes.run_experts import _bound_rule_batches, _coverage_retry_batch, _enforce_bound_batch_findings, _summarize_bound_review_coverage
from rules.skill_checkpoint_parser import parse_skill_checkpoints


SKILL_WITH_CHECKPOINTS = """# Security Skill

## SEC-CMD-001 命令注入检查
- severity: high
- applies_to: Java 后端

### 检查点
用户输入不能拼接进 Runtime.exec 或 ProcessBuilder。

### 证据要求
- 外部输入来源
- 命令执行 sink
- 缺少白名单或枚举映射

### 误报模式
- 固定常量命令
- 参数来自内部枚举

## SEC-PATH-002 路径穿越检查
- severity: medium

### 如何检查
请求参数参与文件读取时必须 normalize/canonical 并限制在基准目录内。
"""


def test_skill_markdown_is_parsed_into_auditable_checkpoints() -> None:
    checkpoints = parse_skill_checkpoints("secure-review-skill", SKILL_WITH_CHECKPOINTS)
    assert [item["checkpoint_id"] for item in checkpoints] == ["SEC-CMD-001", "SEC-PATH-002"], checkpoints
    first = checkpoints[0]
    assert first["skill_key"] == "secure-review-skill", first
    assert first["title"] == "命令注入检查", first
    assert first["severity"] == "high", first
    assert "Runtime.exec" in first["check"], first
    assert "命令执行 sink" in first["required_evidence"], first
    assert "固定常量命令" in first["false_positive_patterns"], first


def test_custom_skill_creates_skill_scoped_batch_without_free_review() -> None:
    batches = _bound_rule_batches(
        {
            "agent_id": "security_agent",
            "custom_skills": ["secure-review-skill"],
            "skill_assets": [
                {"skill_key": "secure-review-skill", "asset_path": "SKILL.md", "content": SKILL_WITH_CHECKPOINTS}
            ],
            "bound_rules": [],
        }
    )
    assert [batch["label"] for batch in batches] == [
        "bound_skill:secure-review-skill:SEC-CMD-001",
        "bound_skill:secure-review-skill:SEC-PATH-002",
    ], batches
    batch_agent = batches[0]["agent"]
    assert batch_agent["bound_skill_batch"]["skill_key"] == "secure-review-skill", batch_agent
    assert batch_agent["bound_skill_batch"]["checkpoint_id"] == "SEC-CMD-001", batch_agent
    assert batch_agent["bound_skill_batch"]["enforce_skill_scope"] is True, batch_agent
    assert batch_agent["custom_skills"] == ["secure-review-skill"], batch_agent
    assert batch_agent["skill_checkpoints"][0]["checkpoint_id"] == "SEC-CMD-001", batch_agent
    assert batch_agent["skill_assets"][0]["skill_key"] == "secure-review-skill", batch_agent


def test_skill_reference_checkpoints_are_batched_even_when_skill_md_is_entrypoint_only() -> None:
    batches = _bound_rule_batches(
        {
            "agent_id": "security_agent",
            "custom_skills": ["secure-review-skill"],
            "skill_assets": [
                {
                    "skill_key": "secure-review-skill",
                    "asset_path": "SKILL.md",
                    "asset_type": "skill",
                    "content": "# Security Skill\n\n请完整读取 references/security-rules.md 后逐条检查。",
                },
                {
                    "skill_key": "secure-review-skill",
                    "asset_path": "references/security-rules.md",
                    "asset_type": "reference",
                    "content": SKILL_WITH_CHECKPOINTS,
                },
            ],
            "bound_rules": [],
        }
    )

    assert [batch["label"] for batch in batches] == [
        "bound_skill:secure-review-skill:SEC-CMD-001",
        "bound_skill:secure-review-skill:SEC-PATH-002",
    ], batches
    checkpoints = [batch["agent"]["skill_checkpoints"][0] for batch in batches]
    assert [item["source_path"] for item in checkpoints] == [
        "references/security-rules.md",
        "references/security-rules.md",
    ], checkpoints
    assert all(item["parse_quality"] == "structured" for item in checkpoints), checkpoints


def test_skill_scoped_prompt_disables_expert_free_review() -> None:
    prompt, _safety = build_prompt(
        {
            "agent_id": "security_agent",
            "display_name": "Security Agent",
            "applies_to": {"persona": "安全专家", "exclusive_scope": "security", "review_scope": "安全问题"},
            "bound_skill_batch": {
                "skill_key": "secure-review-skill",
                "checkpoint_id": "SEC-CMD-001",
                "index": 1,
                "total": 1,
                "enforce_skill_scope": True,
            },
            "skill_checkpoints": [
                {
                    "skill_key": "secure-review-skill",
                    "checkpoint_id": "SEC-CMD-001",
                    "title": "命令注入检查",
                    "check": "用户输入不能拼接进 Runtime.exec 或 ProcessBuilder。",
                    "required_evidence": "外部输入来源；命令执行 sink；缺少白名单或枚举映射",
                    "false_positive_patterns": "固定常量命令；参数来自内部枚举",
                }
            ],
            "bound_rules": [],
            "tool_observations": [],
        },
        [
            SimpleNamespace(
                filename="src/App.java",
                status="modified",
                additions=1,
                deletions=0,
                patch="+Runtime.getRuntime().exec(cmd);",
            )
        ],
        "# SKILL.md\n\n只检查命令注入，不检查其他安全问题。",
    )
    assert "bound_skill_batch" in prompt, prompt
    assert "SEC-CMD-001" in prompt, prompt
    assert "skill_checkpoints" in prompt, prompt
    assert "只允许输出当前 bound_skill_batch.skill_key 对应 Skill 明确要求检查的问题" in prompt, prompt
    assert "当前 checkpoint" in prompt, prompt
    assert "禁止执行专家自由检视" in prompt, prompt


def test_skill_checkpoint_batch_attributes_unlabeled_findings_and_filters_off_scope() -> None:
    kept, rejected = _enforce_bound_batch_findings(
        {
            "label": "bound_skill:secure-review-skill:SEC-CMD-001",
            "rule_id": "",
            "skill_key": "secure-review-skill",
            "checkpoint_id": "SEC-CMD-001",
            "agent": {
                "skill_checkpoints": [
                    {
                        "checkpoint_id": "SEC-CMD-001",
                        "required_evidence": "外部输入来源；命令执行 sink；缺少白名单或枚举映射",
                        "false_positive_patterns": "固定常量命令；参数来自内部枚举",
                    }
                ]
            },
        },
        [
            {
                "title": "命令注入",
                "problem_description": "外部输入来源 request.getParameter 进入命令执行 sink Runtime.exec，缺少白名单。",
                "evidence": "request.getParameter(\"cmd\") 拼接后传给 Runtime.exec(cmd)，未看到白名单或枚举映射。",
                "file_path": "src/App.java",
                "line_start": 12,
            },
            {
                "title": "路径穿越",
                "problem_description": "文件名未 normalize。",
                "covered_rules": ["SEC-PATH-002"],
                "file_path": "src/App.java",
                "line_start": 30,
            },
        ],
    )

    assert len(kept) == 1, kept
    assert kept[0]["covered_rules"] == ["SEC-CMD-001"], kept
    assert kept[0]["rule_id"] == "SEC-CMD-001", kept
    assert kept[0]["skill_key"] == "secure-review-skill", kept
    assert kept[0]["checkpoint_id"] == "SEC-CMD-001", kept
    assert "bound_skill_checkpoint_attributed" in kept[0]["verification_flags"], kept
    assert kept[0]["bound_evidence_contract"]["status"] == "satisfied", kept
    assert kept[0]["bound_evidence_contract"]["missing_required_evidence"] == [], kept
    assert len(rejected) == 1, rejected
    assert rejected[0]["rejected_reasons"] == ["bound_skill_checkpoint_mismatch"], rejected


def test_skill_checkpoint_batch_rejects_explicit_false_positive_pattern() -> None:
    kept, rejected = _enforce_bound_batch_findings(
        {
            "label": "bound_skill:secure-review-skill:SEC-CMD-001",
            "rule_id": "",
            "skill_key": "secure-review-skill",
            "checkpoint_id": "SEC-CMD-001",
            "agent": {
                "skill_checkpoints": [
                    {
                        "checkpoint_id": "SEC-CMD-001",
                        "required_evidence": "外部输入来源；命令执行 sink；缺少白名单或枚举映射",
                        "false_positive_patterns": "固定常量命令；参数来自内部枚举",
                    }
                ]
            },
        },
        [
            {
                "title": "命令注入",
                "problem_description": "Runtime.exec 执行固定常量命令。",
                "evidence": "Runtime.getRuntime().exec(\"uptime\") 是固定常量命令。",
                "covered_rules": ["SEC-CMD-001"],
            },
            {
                "title": "命令注入",
                "problem_description": "外部输入来源进入命令执行 sink。",
                "evidence": "request.getParameter(\"cmd\") 传给 Runtime.exec(cmd)，未看到白名单。",
                "covered_rules": ["SEC-CMD-001"],
            },
        ],
    )

    assert len(kept) == 1, kept
    assert kept[0]["bound_evidence_contract"]["status"] == "satisfied", kept
    assert len(rejected) == 1, rejected
    assert rejected[0]["rejected_reasons"] == ["bound_false_positive_pattern_match"], rejected
    assert rejected[0]["bound_evidence_contract"]["false_positive_matches"] == ["固定常量命令"], rejected


def test_skill_checkpoint_batch_flags_missing_required_evidence_without_dropping() -> None:
    kept, rejected = _enforce_bound_batch_findings(
        {
            "label": "bound_skill:secure-review-skill:SEC-CMD-001",
            "rule_id": "",
            "skill_key": "secure-review-skill",
            "checkpoint_id": "SEC-CMD-001",
            "agent": {
                "skill_checkpoints": [
                    {
                        "checkpoint_id": "SEC-CMD-001",
                        "required_evidence": "外部输入来源；命令执行 sink；缺少白名单或枚举映射",
                    }
                ]
            },
        },
        [
            {
                "title": "命令注入待确认",
                "problem_description": "Runtime.exec 被调用。",
                "evidence": "Runtime.exec(cmd)",
                "covered_rules": ["SEC-CMD-001"],
            }
        ],
    )

    assert rejected == [], rejected
    assert len(kept) == 1, kept
    contract = kept[0]["bound_evidence_contract"]
    assert contract["status"] == "partial", contract
    assert "外部输入来源" in contract["missing_required_evidence"], contract
    assert "缺少白名单或枚举映射" in contract["missing_required_evidence"], contract
    assert "bound_required_evidence_incomplete" in kept[0]["verification_flags"], kept


def test_bound_rule_batch_filters_explicitly_mismatched_rule() -> None:
    kept, rejected = _enforce_bound_batch_findings(
        {
            "label": "bound_rule:JAVA-001",
            "rule_id": "JAVA-001",
        },
        [
            {"title": "命中规则", "covered_rules": ["JAVA-001"]},
            {"title": "缺少归属"},
            {"title": "越界规则", "covered_rules": ["JAVA-999"]},
        ],
    )

    assert [item["covered_rules"] for item in kept] == [["JAVA-001"], ["JAVA-001"]], kept
    assert kept[1]["rule_id"] == "JAVA-001", kept
    assert "bound_rule_attributed" in kept[1]["verification_flags"], kept
    assert len(rejected) == 1, rejected
    assert rejected[0]["rejected_reasons"] == ["bound_rule_mismatch"], rejected


def test_bound_review_coverage_summary_tracks_hits_and_misses() -> None:
    summary = _summarize_bound_review_coverage(
        [
            {
                "agent_id": "security_agent",
                "batch_label": "bound_rule:SEC-AUTH-001",
                "type": "rule",
                "rule_id": "SEC-AUTH-001",
                "checked": True,
                "finding_count": 1,
                "rejected_count": 0,
            },
            {
                "agent_id": "security_agent",
                "batch_label": "bound_skill:secure-review-skill:SEC-CMD-001",
                "type": "skill_checkpoint",
                "skill_key": "secure-review-skill",
                "checkpoint_id": "SEC-CMD-001",
                "checked": True,
                "finding_count": 1,
                "rejected_count": 1,
            },
            {
                "agent_id": "security_agent",
                "batch_label": "bound_skill:secure-review-skill:SEC-PATH-002",
                "type": "skill_checkpoint",
                "skill_key": "secure-review-skill",
                "checkpoint_id": "SEC-PATH-002",
                "checked": True,
                "finding_count": 0,
                "rejected_count": 0,
            },
        ]
    )

    assert summary["required_count"] == 3, summary
    assert summary["checked_count"] == 3, summary
    assert summary["hit_count"] == 2, summary
    assert summary["missed_count"] == 1, summary
    assert summary["coverage_rate"] == 1.0, summary
    assert summary["hit_rate"] == round(2 / 3, 4), summary
    assert summary["rule_count"] == 1, summary
    assert summary["skill_checkpoint_count"] == 2, summary
    assert summary["rejected_count"] == 1, summary
    assert summary["missed"][0]["checkpoint_id"] == "SEC-PATH-002", summary


def test_coverage_retry_batch_focuses_prompt_on_missed_bound_rule() -> None:
    batch = {
        "label": "bound_rule:SEC-AUTH-001",
        "rule_id": "SEC-AUTH-001",
        "agent": {
            "agent_id": "security_agent",
            "display_name": "安全专家",
            "applies_to": {"persona": "安全检视", "exclusive_scope": "security"},
            "bound_rules": [{"rule_id": "SEC-AUTH-001", "title": "接口鉴权", "required_evidence": "入口方法；鉴权调用"}],
            "bound_rule_batch": {"index": 1, "total": 1, "rule_id": "SEC-AUTH-001"},
        },
    }

    retry = _coverage_retry_batch(batch, reason="missing_after_first_pass")
    assert retry is not None, retry
    assert retry["label"] == "bound_rule:SEC-AUTH-001:coverage_retry", retry
    assert retry["agent"]["bound_rule_batch"]["coverage_retry"] is True, retry
    assert retry["agent"]["bound_rule_batch"]["retry_reason"] == "missing_after_first_pass", retry
    prompt, _ = build_prompt(retry["agent"], [], "")
    parsed = __import__("json").loads(prompt)
    assert parsed["review_rules"]["coverage_retry"]["enabled"] is True, parsed["review_rules"]
    assert parsed["review_rules"]["coverage_retry"]["target_id"] == "SEC-AUTH-001", parsed["review_rules"]
    assert "补检视" in parsed["task"], parsed["task"]


if __name__ == "__main__":
    test_skill_markdown_is_parsed_into_auditable_checkpoints()
    test_custom_skill_creates_skill_scoped_batch_without_free_review()
    test_skill_reference_checkpoints_are_batched_even_when_skill_md_is_entrypoint_only()
    test_skill_scoped_prompt_disables_expert_free_review()
    test_skill_checkpoint_batch_attributes_unlabeled_findings_and_filters_off_scope()
    test_skill_checkpoint_batch_rejects_explicit_false_positive_pattern()
    test_skill_checkpoint_batch_flags_missing_required_evidence_without_dropping()
    test_bound_rule_batch_filters_explicitly_mismatched_rule()
    test_bound_review_coverage_summary_tracks_hits_and_misses()
    test_coverage_retry_batch_focuses_prompt_on_missed_bound_rule()
