from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "worker")

from review_runtime import (  # noqa: E402
    ChangedFile,
    apply_baseline_suppression,
    apply_project_rule_policy,
    dependency_check_args,
    osv_scanner_args,
    parse_tool_report_file,
    run_external_static_prescan,
    spotbugs_class_dirs,
    trivy_args,
)
from tools.tool_normalizer import normalize_tool_finding  # noqa: E402


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def tool_call(self, span_id: str, tool_name: str, status: str, duration_ms: int, **kwargs: object) -> None:
        self.calls.append(
            {
                "span_id": span_id,
                "tool_name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                **kwargs,
            }
        )


def sample_files() -> list[ChangedFile]:
    return [
        ChangedFile(
            filename="src/main/java/com/acme/payment/PaymentController.java",
            status="modified",
            additions=12,
            deletions=1,
            changes=13,
            patch="""
@@ -1,3 +1,7 @@
+@RestController
+class PaymentController {
+  String sql = "select * from user where id=" + id;
+}
""",
        ),
        ChangedFile(
            filename="pom.xml",
            status="modified",
            additions=14,
            deletions=0,
            changes=14,
            patch="""
@@ -0,0 +1,14 @@
+<project>
+  <modelVersion>4.0.0</modelVersion>
+  <groupId>com.acme</groupId>
+  <artifactId>payment-service</artifactId>
+  <version>1.0.0</version>
+  <dependencies>
+    <dependency>
+      <groupId>com.alibaba</groupId>
+      <artifactId>fastjson</artifactId>
+      <version>1.2.47</version>
+    </dependency>
+  </dependencies>
+</project>
""",
        ),
        ChangedFile(
            filename="deploy/k8s/deployment.yaml",
            status="modified",
            additions=4,
            deletions=0,
            changes=4,
            patch="containers:\n- name: app\n  image: app:latest\n",
        ),
        ChangedFile(
            filename="docs/openapi.yaml",
            status="modified",
            additions=8,
            deletions=0,
            changes=8,
            patch="openapi: 3.0.0\npaths: {}\n",
        ),
    ]


def verify_runner_inventory() -> dict[str, object]:
    recorder = Recorder()
    with tempfile.TemporaryDirectory(prefix="jolt-tool-runners-") as temp_dir:
        summary, findings = run_external_static_prescan(
            recorder,
            "span_verify",
            Path(temp_dir),
            sample_files(),
            "head_verify_static_tools",
            None,
            None,
            {"tool_policy": {"baseline": {"enabled": True}}},
        )
    tools = {item["tool"]: item["status"] for item in summary["tools"]}
    expected = {
        "semgrep",
        "gitleaks",
        "ruff",
        "bandit",
        "eslint",
        "pmd",
        "checkstyle",
        "spotbugs",
        "dependency-check",
        "osv-scanner",
        "trivy",
        "kics",
        "openapi-diff",
    }
    missing = sorted(expected - set(tools))
    assert not missing, missing
    assert tools["spotbugs"] in {"missing", "skipped_no_compiled_classes"}
    assert tools["openapi-diff"] in {"missing", "skipped_requires_baseline_spec"}
    return {
        "tool_statuses": tools,
        "tool_finding_count": len(findings),
        "recorded_calls": len(recorder.calls),
    }


def verify_policy_and_baseline() -> dict[str, object]:
    base = normalize_tool_finding(
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.9,
            "tool_name": "semgrep",
            "tool_rule_id": "SEC-SECRET-004",
            "file_path": "src/main/java/com/acme/payment/PaymentController.java",
            "line_start": 12,
            "line_end": 12,
            "title": "Semgrep 命中：SEC-SECRET-004",
            "problem_description": "secret",
            "recommendation": "remove secret",
            "suggested_code": "// remove secret",
            "evidence": "password=123456",
        }
    )
    disabled_findings, disabled_count, applied = apply_project_rule_policy(
        {"tool_policy": {"rule_overrides": {"SECRET_LEAK": {"enabled": False}}}},
        [base],
    )
    assert disabled_count == 1
    assert not disabled_findings
    assert applied[0]["action"] == "disabled"

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE review_baseline_suppressions (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          tool_name TEXT NOT NULL,
          rule_id TEXT,
          normalized_rule_category TEXT,
          file_path TEXT NOT NULL,
          line_start INTEGER,
          fingerprint TEXT NOT NULL,
          reason TEXT,
          expires_at TEXT,
          created_by TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(project_id, fingerprint)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO review_baseline_suppressions (
          id, project_id, tool_name, rule_id, normalized_rule_category, file_path, line_start, fingerprint, reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "baseline_1",
            "project_1",
            str(base["tool_name"]),
            str(base["tool_rule_id"]),
            str(base["normalized_rule_category"]),
            str(base["file_path"]),
            int(base["line_start"]),
            str(base["dedupe_hash"]),
            "legacy finding",
        ),
    )
    kept, suppressed = apply_baseline_suppression(conn, "project_1", {"tool_policy": {}}, [base])
    assert suppressed == 1
    assert kept == []
    return {"rule_policy_suppressed": disabled_count, "baseline_suppressed": suppressed}


def verify_configurable_runner_args() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jolt-tool-config-") as temp_dir:
        root = Path(temp_dir)
        worktree = root / "repo"
        output_dir = root / "out" / "dependency-check"
        osv_output = root / "out" / "osv.json"
        trivy_output = root / "out" / "trivy.json"
        classes = root / "custom-classes"
        classes.mkdir(parents=True)
        project_config = {
            "tool_policy": {
                "static_runners": {
                    "dependency-check": {
                        "nvd_api_key_env": "JOLT_TEST_NVD_KEY",
                        "data_directory": "data/cache/dependency-check",
                        "nvd_api_delay_ms": 1000,
                        "nvd_api_results_per_page": 2000,
                        "noupdate": True,
                        "disable_version_check": True,
                    },
                    "osv-scanner": {
                        "offline": True,
                        "allow_no_lockfiles": True,
                    },
                    "spotbugs": {
                        "class_dirs": [str(classes)]
                    },
                    "trivy": {
                        "cache_dir": "data/cache/trivy",
                        "skip_db_update": True,
                        "offline_scan": True,
                        "scanners": ["vuln", "secret", "misconfig"],
                    },
                }
            }
        }
        old_value = os.environ.get("JOLT_TEST_NVD_KEY")
        os.environ["JOLT_TEST_NVD_KEY"] = "test-nvd-key"
        try:
            dependency_args = dependency_check_args(project_config, worktree, output_dir)
        finally:
            if old_value is None:
                os.environ.pop("JOLT_TEST_NVD_KEY", None)
            else:
                os.environ["JOLT_TEST_NVD_KEY"] = old_value
        osv_args = osv_scanner_args(project_config, worktree, osv_output)
        trivy_runner_args = trivy_args(project_config, worktree, trivy_output)
        spotbugs_dirs = spotbugs_class_dirs(project_config, worktree)

    assert dependency_args[:6] == ["--project", "jolt-mr", "--scan", str(worktree), "--format", "JSON"]
    assert "--nvdApiKey" in dependency_args
    assert "test-nvd-key" in dependency_args
    assert "-d" in dependency_args
    assert "--nvdApiDelay" in dependency_args
    assert "--nvdApiResultsPerPage" in dependency_args
    assert "--noupdate" in dependency_args
    assert "--disableVersionCheck" in dependency_args
    assert osv_args[:3] == ["scan", "source", "--recursive"]
    assert "--no-ignore" in osv_args
    assert "--output-file" in osv_args
    assert "--offline" in osv_args
    assert "--allow-no-lockfiles" in osv_args
    assert "--cache-dir" in trivy_runner_args
    assert "--skip-db-update" in trivy_runner_args
    assert "--offline-scan" in trivy_runner_args
    assert "vuln,secret,misconfig" in trivy_runner_args
    assert [path.as_posix() for path in spotbugs_dirs] == [classes.as_posix()]
    return {
        "dependency_check_args": dependency_args,
        "osv_scanner_args": osv_args,
        "trivy_args": trivy_runner_args,
        "spotbugs_class_dirs": [path.as_posix() for path in spotbugs_dirs],
    }


def verify_checkstyle_noise_filter() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jolt-checkstyle-filter-") as temp_dir:
        root = Path(temp_dir)
        report = root / "checkstyle.xml"
        report.write_text(
            """<?xml version="1.0"?>
<checkstyle>
  <file name="src/main/java/com/acme/payment/PaymentService.java">
    <error line="10" severity="error" message="缺少 Javadoc。" source="com.puppycrawl.tools.checkstyle.checks.javadoc.MissingJavadocMethodCheck"/>
    <error line="11" severity="error" message="本行字符数 120个，最多：100个。" source="com.puppycrawl.tools.checkstyle.checks.sizes.LineLengthCheck"/>
    <error line="12" severity="error" message="Catching 'Exception' is not allowed." source="com.puppycrawl.tools.checkstyle.checks.coding.IllegalCatchCheck"/>
  </file>
</checkstyle>
""",
            "utf-8",
        )
        files = {
            "src/main/java/com/acme/payment/PaymentService.java": ChangedFile(
                filename="src/main/java/com/acme/payment/PaymentService.java",
                status="modified",
                additions=3,
                deletions=0,
                changes=3,
                patch="",
            )
        }
        findings = parse_tool_report_file("checkstyle", "xml", report, files, "head_checkstyle_filter")
    assert len(findings) == 1, findings
    assert "IllegalCatch" in str(findings[0].get("tool_rule_id")), findings
    return {"kept_findings": len(findings), "kept_rule": findings[0].get("tool_rule_id")}


def main() -> None:
    result = {
        "ok": True,
        "configurable_runner_args": verify_configurable_runner_args(),
        "runner_inventory": verify_runner_inventory(),
        "policy_and_baseline": verify_policy_and_baseline(),
        "checkstyle_noise_filter": verify_checkstyle_noise_filter(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
