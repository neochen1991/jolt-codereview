from __future__ import annotations

import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from context.skill_requirements import collect_skill_context_requirements, normalize_checkpoint_requirement  # noqa: E402


def test_legacy_checkpoint_defaults_are_backward_compatible() -> None:
    result = normalize_checkpoint_requirement({"checkpoint_id": "LEGACY-1"})
    assert result["evidence_scope"] == "symbol"
    assert result["context_queries"] == ()
    assert result["max_dependency_hops"] == 1


def test_cross_file_queries_are_aggregated_for_context_planner() -> None:
    requirements = collect_skill_context_requirements([
        {
            "skill_checkpoint_manifests": {
                "secure-review": {
                    "checkpoints": [
                        {
                            "checkpoint_id": "AUTH-1",
                            "evidence_scope": "cross_file",
                            "context_queries": ["callers", "implementations", "tests"],
                            "max_dependency_hops": 2,
                        }
                    ]
                }
            }
        }
    ])
    assert requirements.evidence_scope == "cross_file"
    assert requirements.max_dependency_hops == 2
    assert requirements.context_queries == ("callers", "implementations", "tests")
    assert requirements.checkpoint_ids == ("AUTH-1",)


def test_unsupported_query_is_rejected_before_execution() -> None:
    try:
        normalize_checkpoint_requirement({"context_queries": ["internet_search"]})
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unsupported query must fail")


if __name__ == "__main__":
    test_legacy_checkpoint_defaults_are_backward_compatible()
    test_cross_file_queries_are_aggregated_for_context_planner()
    test_unsupported_query_is_rejected_before_execution()
    print("skill context requirement tests passed")
