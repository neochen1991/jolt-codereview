from __future__ import annotations

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "mr-backend" / "worker"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(WORKER))

fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

from eval_skill_real_llm import build_agent_context, load_changed_files
from orchestration.nodes.run_experts import _bound_rule_batches
from verify_skill_bundle import validate_skill_bundle


EVAL_DIR = ROOT / "evaluation" / "skill_real_llm"
SKILL_KEY = "refund-risk-review-skill"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def test_refund_skill_bundle_has_parseable_checkpoints() -> None:
    report = validate_skill_bundle(EVAL_DIR / SKILL_KEY)
    assert report["ok"], report
    checkpoint_ids = {item["checkpoint_id"] for item in report["checkpoints"]}
    expected = set(json.loads((EVAL_DIR / "expected-thresholds.json").read_text("utf-8"))["required_checkpoint_ids"])
    assert expected <= checkpoint_ids


def test_refund_skill_batches_cover_expected_checkpoints() -> None:
    agent = build_agent_context(EVAL_DIR / SKILL_KEY, SKILL_KEY)
    batches = _bound_rule_batches(agent)
    checkpoint_ids = {str(batch.get("checkpoint_id") or "") for batch in batches}
    expected = set(json.loads((EVAL_DIR / "expected-thresholds.json").read_text("utf-8"))["required_checkpoint_ids"])
    assert expected == checkpoint_ids
    assert all(str(batch.get("label") or "").startswith(f"bound_skill:{SKILL_KEY}:") for batch in batches)


def test_refund_fixture_contains_positive_and_local_negative_gold() -> None:
    mr_id, files = load_changed_files(EVAL_DIR / "refund-business-mr.json")
    assert mr_id == "mr_online_biz_java_refund_20260707_001"
    assert {item.filename for item in files} >= {
        "src/main/java/com/acme/refund/api/RefundAdminController.java",
        "src/main/java/com/acme/refund/service/RefundService.java",
        "src/main/java/com/acme/refund/infra/RefundCache.java",
        "src/main/java/com/acme/refund/infra/SystemConfigCache.java",
    }
    gold = read_jsonl(EVAL_DIR / "refund-business-gold.jsonl")
    positives = [item for item in gold if item.get("ground_truth") != "negative"]
    negatives = [item for item in gold if item.get("ground_truth") == "negative"]
    assert {item["rule_id"] for item in positives} == {"BIZ-CONSISTENCY-001", "BIZ-AUDIT-001", "REDIS-TTL-002"}
    assert len(negatives) == 1
    assert negatives[0]["negative_scope"]["file"].endswith("SystemConfigCache.java")


if __name__ == "__main__":
    test_refund_skill_bundle_has_parseable_checkpoints()
    test_refund_skill_batches_cover_expected_checkpoints()
    test_refund_fixture_contains_positive_and_local_negative_gold()
