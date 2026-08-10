from __future__ import annotations

from verify_review_precision_hardening import build_hardening_report, quality_gate_failures


def test_hardening_fixture_closes_duplicate_and_scope_fail_open_paths() -> None:
    report = build_hardening_report()

    assert report["raw_duplicate_group_count"] == 1, report
    assert report["final_duplicate_group_count"] == 0, report
    assert report["canonical_finding_count"] == 3, report
    assert report["off_diff_published_count"] == 0, report
    assert report["unchanged_file_published_count"] == 0, report
    assert report["automatic_relocation_count"] == 0, report
    assert quality_gate_failures(report) == [], report


def test_quality_gate_rejects_any_scope_violation() -> None:
    report = {
        "final_duplicate_rate": 0.0,
        "off_diff_published_count": 1,
        "unchanged_file_published_count": 0,
        "automatic_relocation_count": 0,
    }

    assert quality_gate_failures(report) == ["off_diff_published_count 1 > 0"]


if __name__ == "__main__":
    test_hardening_fixture_closes_duplicate_and_scope_fail_open_paths()
    test_quality_gate_rejects_any_scope_violation()
