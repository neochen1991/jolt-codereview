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
    assert report["consolidation_input_finding_count"] == 8, report
    assert report["consolidation_output_finding_count"] == 6, report
    assert report["same_line_paraphrase_merge_rate"] == 1.0, report
    assert report["nearby_root_cause_merge_rate"] == 1.0, report
    assert report["false_merge_rate"] == 0.0, report
    assert report["consolidation_duplicate_rate_before"] == 0.25, report
    assert report["consolidation_duplicate_rate_after"] == 0.0, report
    assert quality_gate_failures(report) == [], report


def test_quality_gate_rejects_any_scope_violation() -> None:
    report = {
        "final_duplicate_rate": 0.0,
        "off_diff_published_count": 1,
        "unchanged_file_published_count": 0,
        "automatic_relocation_count": 0,
    }

    assert quality_gate_failures(report) == ["off_diff_published_count 1 > 0"]


def test_quality_gate_rejects_missed_duplicates_and_false_merges() -> None:
    report = {
        "final_duplicate_rate": 0.0,
        "off_diff_published_count": 0,
        "unchanged_file_published_count": 0,
        "automatic_relocation_count": 0,
        "same_line_paraphrase_merge_rate": 0.5,
        "nearby_root_cause_merge_rate": 0.8,
        "false_merge_rate": 0.02,
        "consolidation_duplicate_rate_after": 0.03,
    }

    assert quality_gate_failures(report) == [
        "same_line_paraphrase_merge_rate 0.5 < 1.0",
        "nearby_root_cause_merge_rate 0.8 < 0.9",
        "false_merge_rate 0.02 >= 0.02",
        "consolidation_duplicate_rate_after 0.03 >= 0.03",
    ]


if __name__ == "__main__":
    test_hardening_fixture_closes_duplicate_and_scope_fail_open_paths()
    test_quality_gate_rejects_any_scope_violation()
    test_quality_gate_rejects_missed_duplicates_and_false_merges()
