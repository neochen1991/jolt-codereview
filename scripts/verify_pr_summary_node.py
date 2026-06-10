from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from budget import BudgetTracker
from config import load_config
from llm.client import summarize_pr_with_llm
from orchestration.nodes.summarize_pr import make_summarize_pr_node
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
        CREATE TABLE review_jobs (
          id TEXT PRIMARY KEY,
          requested_effort_level TEXT NOT NULL DEFAULT 'standard',
          pr_summary TEXT NOT NULL DEFAULT '{}',
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    return conn


def mr_sample(index: int) -> tuple[dict[str, object], list[ChangedFile], list[dict[str, object]]]:
    samples = [
        (
            {
                "id": "mr_summary_auth",
                "number": 284,
                "title": "修复项目权限更新接口",
                "source_branch": "feat/project-setting",
                "target_branch": "master",
                "author": "陈旭",
                "repository_name": "payment-service",
                "risk_score": 86,
            },
            [
                ChangedFile(
                    "src/main/java/com/acme/project/ProjectController.java",
                    "modified",
                    18,
                    2,
                    20,
                    "@@ -80,6 +80,12 @@\n+public void update(ProjectRequest request) {\n+  projectService.update(request);\n+}\n",
                ),
                ChangedFile("src/test/java/com/acme/project/ProjectControllerTest.java", "modified", 10, 0, 10, "+shouldRejectNonAdminUser();\n"),
            ],
            [
                {
                    "severity": "high",
                    "agent_id": "security_agent",
                    "file_path": "src/main/java/com/acme/project/ProjectController.java",
                    "line_start": 88,
                    "title": "缺少项目管理员权限校验",
                    "recommendation": "在入口处校验 project_admin 权限。",
                }
            ],
        ),
        (
            {
                "id": "mr_summary_cache",
                "number": 285,
                "title": "订单缓存刷新逻辑优化",
                "source_branch": "feat/order-cache",
                "target_branch": "master",
                "author": "林珂",
                "repository_name": "order-service",
                "risk_score": 72,
            },
            [
                ChangedFile("src/main/java/com/acme/order/OrderCacheService.java", "modified", 26, 3, 29, "+redisTemplate.keys(\"order:*\").forEach(redisTemplate::delete);\n"),
                ChangedFile("src/main/java/com/acme/order/OrderService.java", "modified", 11, 1, 12, "+orderCacheService.refreshAll();\n"),
            ],
            [
                {
                    "severity": "high",
                    "agent_id": "redis_agent",
                    "file_path": "src/main/java/com/acme/order/OrderCacheService.java",
                    "line_start": 41,
                    "title": "使用 Redis KEYS 扫描生产 keyspace",
                    "recommendation": "改为 scan 或按业务 key 精确删除。",
                }
            ],
        ),
        (
            {
                "id": "mr_summary_migration",
                "number": 286,
                "title": "支付表增加渠道字段",
                "source_branch": "feat/payment-channel",
                "target_branch": "master",
                "author": "王琪",
                "repository_name": "payment-service",
                "risk_score": 91,
            },
            [
                ChangedFile("src/main/resources/db/migration/V20260607__payment_channel.sql", "added", 2, 0, 2, "+ALTER TABLE payments ADD COLUMN channel VARCHAR(32) NOT NULL;\n+ALTER TABLE payments DROP COLUMN legacy_remark;\n"),
                ChangedFile("src/main/java/com/acme/payment/PaymentEntity.java", "modified", 8, 0, 8, "+private String channel;\n"),
            ],
            [
                {
                    "severity": "critical",
                    "agent_id": "database_agent",
                    "file_path": "src/main/resources/db/migration/V20260607__payment_channel.sql",
                    "line_start": 1,
                    "title": "新增 NOT NULL 列缺少默认值和回填方案",
                    "recommendation": "拆分为 nullable 新增、回填、校验后再收紧约束。",
                }
            ],
        ),
    ]
    return samples[index]


def main() -> None:
    config = load_config()
    conn = create_conn()
    completed = 0
    summaries: list[dict[str, object]] = []
    for index in range(3):
        job_id = f"job_summary_{index}"
        run_id = f"run_summary_{index}"
        mr, files, findings = mr_sample(index)
        conn.execute("INSERT INTO review_jobs (id, requested_effort_level) VALUES (?, 'standard')", (job_id,))
        recorder = Recorder(conn, run_id)
        node = make_summarize_pr_node(
            conn=conn,
            recorder=recorder,
            job={"id": job_id, "requested_effort_level": "standard"},
            mr=mr,
            project_config=config,
            summarize_pr=summarize_pr_with_llm,
        )
        state = node(
            {
                "effort": "standard",
                "files": files,
                "final_findings": findings,
                "selected_agents": [{"agent_id": item["agent_id"]} for item in findings],
                "tool_observations": [],
                "conflicts": [],
                "fetch_degraded": False,
                "budget_tracker": BudgetTracker(max_wall_seconds=300, max_llm_calls=8),
            }
        )
        recorder.flush()
        persisted = json.loads(conn.execute("SELECT pr_summary FROM review_jobs WHERE id = ?", (job_id,)).fetchone()["pr_summary"])
        calls = conn.execute(
            """
            SELECT l.*
            FROM llm_call_records l
            JOIN agent_trace_spans s ON s.id = l.span_id
            WHERE s.review_run_id = ? AND s.span_key = 'summarize_pr'
            """,
            (run_id,),
        ).fetchall()
        completed += sum(1 for call in calls if call["status"] == "completed")
        assert persisted.get("intent"), persisted
        assert persisted.get("change_map"), persisted
        assert persisted.get("suggested_review_order"), persisted
        assert state["budget_tracker"].llm_calls >= 1, state["budget_tracker"].snapshot()
        summaries.append(
            {
                "job_id": job_id,
                "source": persisted.get("source"),
                "intent": persisted.get("intent"),
                "change_count": len(persisted.get("change_map") or []),
                "risk_count": len(persisted.get("risk_highlights") or []),
                "llm_statuses": [call["status"] for call in calls],
                "budget": state["budget_tracker"].snapshot(),
            }
        )
    assert completed == 3, summaries
    print(json.dumps({"summary_count": len(summaries), "completed_llm_calls": completed, "summaries": summaries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
