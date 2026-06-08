from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from llm.client import fallback_pr_summary


def persist_pr_summary(conn: sqlite3.Connection, job_id: str, summary: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE review_jobs SET pr_summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(summary, ensure_ascii=False), job_id),
    )
    conn.commit()


def make_summarize_pr_node(
    *,
    conn: sqlite3.Connection,
    recorder: Any,
    job: Any,
    mr: Any,
    project_config: dict[str, Any],
    summarize_pr: Callable[..., dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def summarize_pr_node(state: dict[str, Any]) -> dict[str, Any]:
        span = recorder.span("summarize_pr", "summary_agent")
        summary = {
            "intent": "",
            "change_map": [],
            "risk_highlights": [],
            "test_coverage_gaps": [],
            "cross_file_couplings": [],
            "suggested_review_order": [],
            "source": "disabled",
            "skipped": True,
            "skip_reason": "disabled_by_product_design",
        }
        recorder.event(span, "pr_summary_disabled", "PR Summary 已禁用：检视页面只展示问题、进度、工具和专家证据", summary)
        persist_pr_summary(conn, job["id"], summary)
        recorder.finish(span)
        return {**state, "pr_summary": summary}

        files = state.get("files") or []
        final_findings = state.get("final_findings") or []
        effort = str(state.get("effort") or job["requested_effort_level"] or "standard")
        budget_tracker = state.get("budget_tracker")
        context_bundle = {
            "selected_agent_count": len(state.get("selected_agents") or []),
            "tool_observation_count": len(state.get("tool_observations") or []),
            "conflict_count": len(state.get("conflicts") or []),
            "fetch_degraded": bool(state.get("fetch_degraded")),
        }
        if effort in {"trivial", "fast"}:
            summary = fallback_pr_summary(
                mr,
                files,
                final_findings,
                source="fallback",
                skipped=True,
                skip_reason=f"effort_{effort}",
            )
            recorder.event(span, "pr_summary_skipped", f"{effort} 检视强度跳过 PR Summary LLM 调用", summary)
            persist_pr_summary(conn, job["id"], summary)
            recorder.finish(span)
            return {**state, "pr_summary": summary}
        try:
            summary = summarize_pr(
                project_config,
                recorder,
                span,
                mr,
                files,
                final_findings,
                context_bundle,
                budget_tracker,
            )
            recorder.event(
                span,
                "pr_summary_generated",
                f"PR Summary 已生成：{summary.get('source', 'unknown')}",
                {
                    "source": summary.get("source"),
                    "skipped": summary.get("skipped"),
                    "change_items": len(summary.get("change_map") or []),
                    "risk_items": len(summary.get("risk_highlights") or []),
                },
            )
        except Exception as exc:
            summary = fallback_pr_summary(mr, files, final_findings, source="fallback", skipped=True, skip_reason=type(exc).__name__)
            recorder.event(span, "pr_summary_failed", f"PR Summary 生成失败，使用兜底摘要：{exc}", {"error": str(exc)[:500]})
        persist_pr_summary(conn, job["id"], summary)
        recorder.finish(span)
        return {**state, "pr_summary": summary}

    return summarize_pr_node
