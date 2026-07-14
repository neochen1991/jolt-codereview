from __future__ import annotations

import tempfile
from pathlib import Path

from verify_skill_bundle import validate_skill_bundle


GOOD_SKILL = """---
name: refund-risk-review-skill
description: Review refund flow risks.
---

# Refund Skill
"""


GOOD_RULES = """# Rules

## REDIS-TTL-002 退款缓存 TTL 检查

### 检查点
退款详情缓存写入 Redis 时必须设置 TTL。

### 证据要求
- redisTemplate.opsForValue().set 写入退款业务缓存
- 缺少 Duration、expire 或 setEx

### 误报模式
- 永久配置 key，例如 system:refund:config
- 代码紧随其后调用 expire

### 反例
- 永久配置、feature flag 或灰度开关 key

### 跳过条件
- 测试代码、demo 或只读查询

### 修复建议
为业务缓存设置 TTL。
"""


BAD_RULES = GOOD_RULES.replace("永久配置 key，例如 system:refund:config", "system:refund:config 永久配置 key")


def write_skill(root: Path, rules: str) -> Path:
    skill_dir = root / "refund-risk-review-skill"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(GOOD_SKILL, "utf-8")
    (skill_dir / "references" / "refund-review-rules.md").write_text(rules, "utf-8")
    return skill_dir


def test_validate_skill_bundle_accepts_parseable_reference_rules() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = validate_skill_bundle(write_skill(Path(tmp), GOOD_RULES))

    assert report["ok"] is True, report
    assert report["warnings"] == [], report
    assert report["checkpoints"][0]["checkpoint_id"] == "REDIS-TTL-002", report
    assert "system:refund:config" in report["checkpoints"][0]["false_positive_patterns"], report
    assert "feature flag" in report["checkpoints"][0]["negative_examples"], report
    assert "只读查询" in report["checkpoints"][0]["skip_conditions"], report


def test_validate_skill_bundle_rejects_parser_field_like_bullet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = validate_skill_bundle(write_skill(Path(tmp), BAD_RULES))

    assert report["ok"] is False, report
    assert report["warnings"], report
    assert report["warnings"][0]["line"] > 0, report
    assert "parser field syntax" in report["warnings"][0]["message"], report


if __name__ == "__main__":
    test_validate_skill_bundle_accepts_parseable_reference_rules()
    test_validate_skill_bundle_rejects_parser_field_like_bullet()
