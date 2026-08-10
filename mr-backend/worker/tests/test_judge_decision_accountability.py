from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.candidate_store import build_decision_reason_details, decision_status_for_rejection, upsert_candidate_finding
from orchestration.nodes.judge_findings import ensure_judge_decision_accountability


def test_empty_rejection_reason_is_never_persisted_silently() -> None:
    details = build_decision_reason_details([], status="rejected", stage="judge")
    assert details[0]["code"] == "judge_unclassified_rejection", details
    assert "未提供" in details[0]["message"], details


def test_known_reason_has_explicit_human_message() -> None:
    details = build_decision_reason_details(["bound_false_positive_pattern_match"], status="rejected", stage="judge")
    assert details == [
        {
            "code": "bound_false_positive_pattern_match",
            "message": "候选命中了 Skill 定义的误报排除模式。",
            "stage": "judge",
        }
    ], details


def test_deduplicated_candidate_is_recorded_as_merged() -> None:
    assert decision_status_for_rejection(["deduped_lower_rank"]) == "merged"
    assert decision_status_for_rejection(["deduped_final_llm_consolidation"]) == "merged"
    assert decision_status_for_rejection(["critic_rejected"]) == "rejected"


def test_final_consolidation_reason_has_explicit_human_message() -> None:
    details = build_decision_reason_details(["deduped_final_llm_consolidation"], status="merged", stage="judge")
    assert details == [
        {
            "code": "deduped_final_llm_consolidation",
            "message": "最终全局语义归并判定该候选与主问题重复，已合并。",
            "stage": "judge",
        }
    ]


def test_every_judge_input_gets_a_terminal_decision() -> None:
    inputs = [
        {"dedupe_hash": "a", "title": "A"},
        {"dedupe_hash": "b", "title": "B"},
        {"dedupe_hash": "c", "title": "C"},
    ]
    retained = [{"dedupe_hash": "a", "title": "A"}]
    rejected = [{"dedupe_hash": "b", "title": "B", "rejected_reasons": ["critic_rejected"]}]
    reconciled, anomaly = ensure_judge_decision_accountability(inputs, retained, rejected)
    assert anomaly == 1, (reconciled, anomaly)
    missing = next(item for item in reconciled if item["dedupe_hash"] == "c")
    assert missing["rejected_reasons"] == ["judge_unclassified_rejection"], missing


def test_existing_empty_rejection_is_upgraded_to_explicit_anomaly() -> None:
    reconciled, anomaly = ensure_judge_decision_accountability(
        [{"dedupe_hash": "a", "title": "A"}],
        [],
        [{"dedupe_hash": "a", "title": "A", "rejected_reasons": []}],
    )
    assert anomaly == 1, (reconciled, anomaly)
    assert reconciled[0]["rejected_reasons"] == ["judge_unclassified_rejection"], reconciled


def test_candidate_store_persists_reason_details_and_terminal_timestamp() -> None:
    class Result:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self):
            self.write = None

        def execute(self, sql, params=()):
            if "information_schema.tables" in sql:
                return Result({"name": "candidate_findings"})
            self.write = (sql, params)
            return Result()

    conn = Connection()
    upsert_candidate_finding(
        conn,
        review_run_id="run-1",
        item={"dedupe_hash": "x", "title": "X", "agent_id": "security_agent"},
        stage="judge",
        status="rejected",
        rejected_reasons=[],
    )
    sql, params = conn.write
    assert sql.count("%s") == len(params), (sql.count("%s"), len(params))
    assert "decision_reason_json" in sql
    assert "judge_unclassified_rejection" in str(params)


if __name__ == "__main__":
    test_empty_rejection_reason_is_never_persisted_silently()
    test_known_reason_has_explicit_human_message()
    test_deduplicated_candidate_is_recorded_as_merged()
    test_final_consolidation_reason_has_explicit_human_message()
    test_every_judge_input_gets_a_terminal_decision()
    test_existing_empty_rejection_is_upgraded_to_explicit_anomaly()
    test_candidate_store_persists_reason_details_and_terminal_timestamp()
    print({"ok": True, "verified": "judge_decision_accountability"})
