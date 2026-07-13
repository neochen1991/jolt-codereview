from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "mr-backend/worker"))

from run_review_quality_shadow_case import (  # type: ignore[import-not-found]
    build_job_id,
    build_shadow_result,
    enqueue_shadow_job,
    score_shadow_findings,
    validate_case,
)


class FakeConnection:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.commits = 0

    def execute(self, sql: str, params: tuple):
        self.calls.append((sql, params))
        return self

    def commit(self):
        self.commits += 1


def sample_case() -> dict:
    return {
        "case_id": "case-1",
        "merge_request_id": "mr-1",
        "head_sha": "head-1",
        "input_snapshot_id": "snapshot-1",
        "input_artifact_sha256": "a" * 64,
        "execution_kind": "quality_shadow_v2",
        "gold_records": [
            {
                "id": "gold-cross-high",
                "mr_id": "mr-1",
                "file": "src/A.java",
                "line": 10,
                "rule_id": "AUTH-001",
                "severity": "high",
                "evidence_scope": "cross_file",
                "evidence_keywords": ["authorization"],
            },
            {
                "id": "gold-negative",
                "mr_id": "mr-1",
                "ground_truth": "negative",
                "file": "src/Safe.java",
                "rule_id": "SAFE-001",
            },
        ],
    }


def test_job_id_is_stable_and_engine_specific() -> None:
    case = sample_case()
    first = build_job_id(case)
    assert first == build_job_id(dict(case))
    changed = {**case, "execution_kind": "quality_shadow_v1"}
    assert first != build_job_id(changed)
    relabeled = {**case, "gold_records": [{**case["gold_records"][0], "line": 11}, case["gold_records"][1]]}
    assert first != build_job_id(relabeled)
    assert first.startswith("shadow_")


def test_case_requires_native_shadow_references_and_gold() -> None:
    validated = validate_case(sample_case())
    assert validated["context_engine"] == "v2"
    for missing in ("merge_request_id", "input_snapshot_id", "input_artifact_sha256", "gold_records"):
        invalid = sample_case()
        invalid.pop(missing)
        try:
            validate_case(invalid)
        except ValueError as exc:
            assert missing in str(exc)
        else:
            raise AssertionError(f"missing {missing} must fail")
    missing_gold_id = sample_case()
    missing_gold_id["gold_records"] = [{"mr_id": "mr-1", "file": "src/A.java", "line": 10}]
    try:
        validate_case(missing_gold_id)
    except ValueError as exc:
        assert "gold_records" in str(exc) and "id" in str(exc)
    else:
        raise AssertionError("every Gold record must have a stable id")


def test_enqueue_persists_explicit_kind_and_frozen_reference() -> None:
    conn = FakeConnection()
    case = validate_case(sample_case())
    job_id = enqueue_shadow_job(conn, case)
    assert job_id == build_job_id(case)
    assert conn.commits == 1
    sql, params = conn.calls[0]
    assert "execution_kind" in sql
    assert "quality_shadow_v2" in params
    context = json.loads(next(value for value in params if isinstance(value, str) and value.startswith("{")))
    assert context["input_snapshot_id"] == "snapshot-1"
    assert context["input_artifact_sha256"] == "a" * 64


def test_score_reports_cross_file_high_and_negative_metrics() -> None:
    case = validate_case(sample_case())
    findings = [
        {
            "id": "finding-1",
            "mr_id": "mr-1",
            "file_path": "src/A.java",
            "line_start": 10,
            "title": "Missing authorization",
            "problem_description": "authorization is not checked",
            "covered_rules": ["AUTH-001"],
        }
    ]
    score = score_shadow_findings(case, findings)
    assert score["expected_count"] == 1
    assert score["true_positive_count"] == 1
    assert score["cross_file_expected_count"] == 1
    assert score["cross_file_true_positive_count"] == 1
    assert score["critical_high_expected_count"] == 1
    assert score["critical_high_true_positive_count"] == 1
    assert score["negative_false_positive_count"] == 0


def test_result_contains_auditable_engine_snapshot_cost_and_zero_publish() -> None:
    case = validate_case(sample_case())
    run = {
        "id": "run-1",
        "status": "waiting_confirmation",
        "budget_used_json": json.dumps({"input_tokens": 100, "output_tokens": 20}),
        "duration_ms": 345,
    }
    result = build_shadow_result(case, run, [])
    assert result["execution_kind"] == "quality_shadow_v2"
    assert result["context_engine"] == "v2"
    assert result["input_artifact_sha256"] == "a" * 64
    assert result["tokens"] == 120
    assert result["duration_ms"] == 345
    assert result["publish_attempt_count"] == 0
    assert result["review_run_id"] == "run-1"


if __name__ == "__main__":
    test_job_id_is_stable_and_engine_specific()
    test_case_requires_native_shadow_references_and_gold()
    test_enqueue_persists_explicit_kind_and_frozen_reference()
    test_score_reports_cross_file_high_and_negative_metrics()
    test_result_contains_auditable_engine_snapshot_cost_and_zero_publish()
