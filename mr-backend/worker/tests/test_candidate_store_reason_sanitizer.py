from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from tools.candidate_store import sanitize_rejected_reasons


def test_evidence_not_in_source_is_not_persisted_as_reject_reason() -> None:
    reasons = sanitize_rejected_reasons(["evidence_not_in_source", "below_confidence"])
    assert reasons == ["below_confidence"], reasons


def test_empty_after_evidence_not_in_source_becomes_soft_reason() -> None:
    reasons = sanitize_rejected_reasons(["evidence_not_in_source"])
    assert reasons == ["low_evidence_match"], reasons


if __name__ == "__main__":
    test_evidence_not_in_source_is_not_persisted_as_reject_reason()
    test_empty_after_evidence_not_in_source_becomes_soft_reason()
