from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from audit_real_pr_dataset import audit


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", "utf-8")


def test_audit_reports_manifest_gold_and_negative_mismatches() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        manifest_dir = root / "real_prs"
        manifest_dir.mkdir()
        (manifest_dir / "repo-1-11.json").write_text(
            json.dumps({
                "id": "repo-1-11",
                "repository": {"owner": "acme", "repo": "service"},
                "pull_number": 11
            }),
            "utf-8",
        )
        gold = root / "gold.jsonl"
        findings = root / "findings.jsonl"
        write_jsonl(gold, [
            {
                "id": "gold-1",
                "mr_id": "mr_real_project_default_acme_service_11",
                "rule_id": "SEC-AUTH-001",
                "file_path": "src/Auth.java",
                "ground_truth": "true_positive",
            },
            {
                "id": "gold-neg",
                "mr_id": "mr_real_project_default_acme_service_12",
                "ground_truth": "negative",
            },
        ])
        write_jsonl(findings, [
            {
                "finding_id": "finding-neg",
                "mr_id": "mr_real_project_default_acme_service_12",
                "covered_rules": ["SEC-AUTH-001"],
            }
        ])
        report = audit(argparse.Namespace(
            manifest_dir=str(manifest_dir),
            gold=str(gold),
            findings=str(findings),
            project_id="project_default",
            min_manifests=2,
            min_positive_mrs=2,
            min_gold=3,
            min_negative_mrs=2,
            require_manifest_for_gold=True,
            require_gold_for_manifest=True,
            require_finding_for_positive_mr=True,
            require_negative_no_findings=True,
            require_gold_for_finding=True,
        ))
        assert not report["ok"], report
        assert "mr_real_project_default_acme_service_12" in report["missing_manifest_for_gold"], report
        assert "mr_real_project_default_acme_service_11" in report["positive_mrs_without_findings"], report
        assert "mr_real_project_default_acme_service_12" in report["negative_mrs_with_findings"], report
        assert any("manifest_count 1 < 2" == failure for failure in report["failures"]), report
        assert any("positive_gold_mr_count 1 < 2" == failure for failure in report["failures"]), report
        assert any("gold_count 1 < 3" == failure for failure in report["failures"]), report
        assert any("negative_gold_mr_count 1 < 2" == failure for failure in report["failures"]), report


def test_audit_accepts_complete_dataset_shape() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        manifest_dir = root / "real_prs"
        manifest_dir.mkdir()
        (manifest_dir / "repo-1-11.json").write_text(
            json.dumps({
                "id": "repo-1-11",
                "repository": {"owner": "acme", "repo": "service"},
                "pull_number": 11
            }),
            "utf-8",
        )
        gold = root / "gold.jsonl"
        findings = root / "findings.jsonl"
        write_jsonl(gold, [
            {
                "id": "gold-1",
                "mr_id": "mr_real_project_default_acme_service_11",
                "rule_id": "SEC-AUTH-001",
                "file_path": "src/Auth.java",
                "ground_truth": "true_positive",
            }
        ])
        write_jsonl(findings, [
            {
                "finding_id": "finding-1",
                "mr_id": "mr_real_project_default_acme_service_11",
                "covered_rules": ["SEC-AUTH-001"],
            }
        ])
        report = audit(argparse.Namespace(
            manifest_dir=str(manifest_dir),
            gold=str(gold),
            findings=str(findings),
            project_id="project_default",
            min_manifests=1,
            min_positive_mrs=1,
            min_gold=1,
            min_negative_mrs=0,
            require_manifest_for_gold=True,
            require_gold_for_manifest=True,
            require_finding_for_positive_mr=True,
            require_negative_no_findings=True,
            require_gold_for_finding=True,
        ))
        assert report["ok"], report
        assert report["manifest_count"] == 1, report
        assert report["positive_gold_mr_count"] == 1, report


if __name__ == "__main__":
    test_audit_reports_manifest_gold_and_negative_mismatches()
    test_audit_accepts_complete_dataset_shape()
