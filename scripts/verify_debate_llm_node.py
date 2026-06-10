from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from budget import BudgetTracker
from config import load_config
from orchestration.nodes.run_targeted_debate import run_targeted_debate_with_llm
from review_runtime import ChangedFile, Recorder


def create_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agent_trace_spans (
          id TEXT PRIMARY KEY,
          review_run_id TEXT NOT NULL,
          parent_span_id TEXT,
          span_key TEXT NOT NULL,
          agent_id TEXT,
          status TEXT NOT NULL,
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          ended_at TEXT
        );
        CREATE TABLE agent_trace_events (
          id TEXT PRIMARY KEY,
          span_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          summary TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE agent_messages (
          id TEXT PRIMARY KEY,
          span_id TEXT NOT NULL,
          from_agent TEXT NOT NULL,
          to_agent TEXT NOT NULL,
          role TEXT NOT NULL,
          content_summary TEXT NOT NULL,
          artifact_id TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE llm_call_records (
          id TEXT PRIMARY KEY,
          span_id TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          request_id TEXT,
          prompt_hash TEXT,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          duration_ms INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    return conn


def main() -> None:
    conn = create_conn()
    recorder = Recorder(conn, "run_debate_verify")
    span = recorder.span("run_targeted_debate", "debate_moderator")
    budget = BudgetTracker(max_wall_seconds=180, max_cost_usd=1.0, max_llm_calls=4)
    findings = [
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.9,
            "dedupe_hash": "hash_sql",
            "file_path": "src/main/java/com/acme/payment/PaymentController.java",
            "line_start": 33,
            "title": "SQL 拼接存在注入风险",
            "problem_description": "用户输入 id 直接拼接到 SQL。",
            "recommendation": "改为参数化查询。",
            "evidence": "Statement statement = connection.createStatement();",
        }
    ]
    conflicts = [
        {
            "type": "high_severity_weak_evidence",
            "location": {"file_path": "src/main/java/com/acme/payment/PaymentController.java", "line_start": 33},
            "finding_hashes": ["hash_sql"],
            "agents": ["security_agent"],
            "summary": "高严重级别问题缺少足够直接证据",
        }
    ]
    files = [
        ChangedFile(
            "src/main/java/com/acme/payment/PaymentController.java",
            "modified",
            4,
            0,
            4,
            "@@ -30,4 +30,8 @@\n+String sql = \"select * from payments where id = \" + request.getId();\n+Statement statement = connection.createStatement();\n+ResultSet rs = statement.executeQuery(sql);\n",
        )
    ]
    transcripts, results = run_targeted_debate_with_llm(
        config=load_config(),
        recorder=recorder,
        span_id=span,
        conflicts=conflicts,
        findings=findings,
        files=files,
        tool_observations=[
            {
                "tool_name": "semgrep",
                "rule_id": "SEC-INJECT-003",
                "file_path": "src/main/java/com/acme/payment/PaymentController.java",
                "line_start": 33,
                "message": "SQL query built from user input",
            }
        ],
        budget_tracker=budget,
    )
    recorder.finish(span)
    recorder.flush()
    calls = conn.execute("SELECT status, provider, model, input_tokens, output_tokens FROM llm_call_records").fetchall()
    assert transcripts and results, (transcripts, results)
    assert any(call["status"] == "completed" for call in calls), [dict(call) for call in calls]
    assert budget.llm_calls >= 1, budget.snapshot()
    assert results[0]["verdict"] in {"keep", "drop", "downgrade"}, results
    print(
        json.dumps(
            {
                "transcript_count": len(transcripts),
                "result_count": len(results),
                "verdict": results[0],
                "llm_calls": [dict(call) for call in calls],
                "budget": budget.snapshot(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
