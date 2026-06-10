from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from budget import BudgetTracker
from config import load_config
from review_runtime import ChangedFile, Recorder, merge_custom_agents, route_agents_with_llm


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
    config = load_config()
    agent_configs = merge_custom_agents(
        [
            {"agent_id": "security_agent", "display_name": "Security", "applies_to": {"review_scope": "security"}},
            {"agent_id": "frontend_agent", "display_name": "Frontend", "applies_to": {"review_scope": "tsx state and a11y"}},
            {"agent_id": "redis_agent", "display_name": "Redis", "applies_to": {"review_scope": "Redis TTL and key usage"}},
            {"agent_id": "coding_agent", "display_name": "Coding", "applies_to": {"review_scope": "general coding"}},
        ],
        {
            "routing": {
                "custom_agents": [
                    {
                        "id": "observability_agent",
                        "description": "日志、指标、链路追踪专家",
                        "file_patterns": ["**/observability/**"],
                        "triggers": ["traceId", "metric"],
                    }
                ]
            }
        },
    )
    conn = create_conn()
    recorder = Recorder(conn, "run_router_verify")
    span = recorder.span("route_agents", "router_agent")
    files = [
        ChangedFile("src/frontend/PaymentPanel.tsx", "modified", 12, 1, 13, "+setLoading(false)\n+<button onClick={submit}>Pay</button>\n"),
        ChangedFile("src/main/java/com/acme/cache/PaymentCache.java", "modified", 8, 0, 8, "+redisTemplate.opsForValue().set(key, value);\n"),
    ]
    routed = route_agents_with_llm(config, recorder, span, agent_configs, files, BudgetTracker(max_wall_seconds=120, max_llm_calls=4))
    recorder.finish(span)
    recorder.flush()
    calls = [dict(row) for row in conn.execute("SELECT status, provider, model, input_tokens, output_tokens FROM llm_call_records").fetchall()]
    valid_ids = {agent["agent_id"] for agent in agent_configs}
    assert routed, routed
    assert all(agent_id in valid_ids for agent_id in routed), routed
    assert any(row["status"] == "completed" for row in calls), calls
    assert "observability_agent" in {agent["agent_id"] for agent in agent_configs}, agent_configs
    print(json.dumps({"routed": routed, "llm_calls": calls, "custom_agent_loaded": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
