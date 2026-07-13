from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compare_review_quality_runs import compare_worker_runs  # noqa: E402
from verify_review_worker_repeatability import snapshot_from_rows  # noqa: E402


def test_repeatability_compares_candidates_and_final_findings() -> None:
    baseline = {
        "candidate_ids": ["c1", "c2"],
        "findings": [{"finding_id": "f1", "severity": "high"}],
        "decision_reasons": {"c2": ["not_reachable"]},
        "context_hashes": ["ctx-1"],
    }
    repeated = {
        "candidate_ids": ["c1"],
        "findings": [{"finding_id": "f1", "severity": "high"}],
        "decision_reasons": {},
        "context_hashes": ["ctx-1"],
    }

    report = compare_worker_runs(baseline, repeated)

    assert report["exact_match"] is False
    assert report["candidate_jaccard"] == 0.5
    assert report["finding_jaccard"] == 1.0
    assert report["decision_reason_match"] is False


def test_repeatability_detects_severity_and_context_drift() -> None:
    baseline = {
        "candidate_ids": ["c1"],
        "findings": [{"finding_id": "f1", "severity": "high"}],
        "decision_reasons": {"c1": ["retained"]},
        "context_hashes": ["ctx-1"],
    }
    repeated = {
        "candidate_ids": ["c1"],
        "findings": [{"finding_id": "f1", "severity": "medium"}],
        "decision_reasons": {"c1": ["retained"]},
        "context_hashes": ["ctx-2"],
    }

    report = compare_worker_runs(baseline, repeated)

    assert report["severity_agreement"] == 0.0
    assert report["context_hash_match"] is False
    assert report["exact_match"] is False


def test_repeatability_detects_llm_and_artifact_drift() -> None:
    baseline = {
        "candidate_ids": ["c1"],
        "findings": [{"finding_id": "f1", "severity": "high"}],
        "decision_reasons": {"c1": ["retained"]},
        "context_hashes": ["ctx-1"],
        "llm_fingerprints": ["expert|prompt-a|response-a"],
        "artifact_hashes": ["artifact-a"],
    }
    repeated = {
        "candidate_ids": ["c1"],
        "findings": [{"finding_id": "f1", "severity": "high"}],
        "decision_reasons": {"c1": ["retained"]},
        "context_hashes": ["ctx-1"],
        "llm_fingerprints": ["expert|prompt-a|response-b"],
        "artifact_hashes": ["artifact-b"],
    }

    report = compare_worker_runs(baseline, repeated)

    assert report["llm_fingerprint_match"] is False
    assert report["artifact_hash_match"] is False
    assert report["exact_match"] is False


def test_snapshot_uses_stable_dedupe_hashes_and_reason_codes() -> None:
    snapshot = snapshot_from_rows(
        run={"id": "run-a", "coverage_json": '{"context_health":{"context_hash":"ctx-a"}}'},
        candidates=[
            {
                "dedupe_hash": "cand-hash",
                "stage": "judge",
                "decision_reason_json": '[{"code":"not_reachable"}]',
            }
        ],
        findings=[{"dedupe_hash": "finding-hash", "severity": "high"}],
        llm_calls=[
            {
                "span_key": "expert",
                "provider": "openai",
                "model": "model-a",
                "prompt_hash": "prompt-a",
                "response_hash": "response-a",
            }
        ],
        artifacts=[{"sha256": "artifact-a", "metadata_json": '{"context_hash":"ctx-b"}'}],
    )

    assert snapshot["candidate_ids"] == ["cand-hash|judge"]
    assert snapshot["findings"] == [{"finding_id": "finding-hash", "severity": "high"}]
    assert snapshot["decision_reasons"] == {"cand-hash|judge": ["not_reachable"]}
    assert snapshot["context_hashes"] == ["ctx-a", "ctx-b"]
    assert snapshot["llm_fingerprints"] == ["expert|openai|model-a|prompt-a|response-a"]
    assert snapshot["artifact_hashes"] == ["artifact-a"]


if __name__ == "__main__":
    test_repeatability_compares_candidates_and_final_findings()
    test_repeatability_detects_severity_and_context_drift()
    test_repeatability_detects_llm_and_artifact_drift()
    test_snapshot_uses_stable_dedupe_hashes_and_reason_codes()
    print("review worker repeatability tests passed")
