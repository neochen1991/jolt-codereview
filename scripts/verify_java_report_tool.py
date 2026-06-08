from __future__ import annotations

import json
import sqlite3
import sys

sys.path.insert(0, "worker")

from review_runtime import ChangedFile, external_report_findings


HEAD_SHA = "head_java_report_verify"
MR_ID = "mr_java_report_verify"


def insert_report(conn: sqlite3.Connection, report_id: str, report_type: str, report_format: str, payload: object) -> None:
    conn.execute(
        """
        INSERT INTO external_review_reports (
          id, merge_request_id, report_type, commit_sha, report_format, payload_json, status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'received')
        """,
        (report_id, MR_ID, report_type, HEAD_SHA, report_format, json.dumps(payload)),
    )


def main() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE external_review_reports (
          id TEXT PRIMARY KEY,
          merge_request_id TEXT NOT NULL,
          report_type TEXT NOT NULL,
          commit_sha TEXT NOT NULL,
          report_format TEXT NOT NULL,
          report_url TEXT,
          payload_json TEXT NOT NULL DEFAULT '{}',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'received',
          created_by TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    changed = ChangedFile(
        filename="src/main/java/com/acme/payment/PaymentController.java",
        status="modified",
        additions=10,
        deletions=0,
        changes=10,
        patch="",
    )
    files_by_name = {changed.filename: changed}

    insert_report(
        conn,
        "pmd_1",
        "pmd",
        "xml",
        {
            "content": """
            <pmd>
              <file name="src/main/java/com/acme/payment/PaymentController.java">
                <violation beginline="12" endline="12" rule="AvoidCatchingGenericException" priority="2">Avoid catching Exception</violation>
              </file>
            </pmd>
            """
        },
    )
    insert_report(
        conn,
        "checkstyle_1",
        "error-prone",
        "xml",
        {
            "content": """
            <checkstyle>
              <file name="src/main/java/com/acme/payment/PaymentController.java">
                <error line="20" severity="error" source="NullAway" message="possible null dereference"/>
              </file>
            </checkstyle>
            """
        },
    )
    insert_report(
        conn,
        "spotbugs_1",
        "spotbugs",
        "xml",
        {
            "content": """
            <BugCollection>
              <BugInstance type="SQL_INJECTION_JDBC" priority="1">
                <LongMessage>SQL injection risk</LongMessage>
                <SourceLine sourcepath="src/main/java/com/acme/payment/PaymentController.java" start="33" end="33"/>
              </BugInstance>
            </BugCollection>
            """
        },
    )
    insert_report(
        conn,
        "codeql_1",
        "codeql",
        "sarif",
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "CodeQL", "rules": [{"id": "java/sql-injection", "defaultConfiguration": {"level": "error"}}]}},
                    "results": [
                        {
                            "ruleId": "java/sql-injection",
                            "message": {"text": "SQL injection"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "src/main/java/com/acme/payment/PaymentController.java"},
                                        "region": {"startLine": 33, "endLine": 33},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )
    insert_report(
        conn,
        "jacoco_1",
        "jacoco",
        "xml",
        {
            "content": """
            <report>
              <package name="com/acme/payment">
                <sourcefile name="PaymentController.java">
                  <line nr="28" mi="1" ci="0" mb="0" cb="0"/>
                </sourcefile>
              </package>
            </report>
            """
        },
    )

    findings, reports = external_report_findings(conn, MR_ID, HEAD_SHA, files_by_name)
    tools = {item["tool_name"] for item in findings}
    agents = {item["agent_id"] for item in findings}
    assert len(reports) == 5, reports
    assert len(findings) == 5, findings
    assert {"pmd", "error-prone", "spotbugs", "codeql", "jacoco"} <= tools, tools
    assert {"coding_agent", "security_agent", "test_agent"} <= agents, agents
    assert all(item["head_sha"] == HEAD_SHA for item in findings)
    assert all(item["file_path"] == changed.filename for item in findings)

    print(
        json.dumps(
            {
                "ok": True,
                "report_count": len(reports),
                "finding_count": len(findings),
                "tools": sorted(tools),
                "agents": sorted(agents),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
