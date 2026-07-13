from __future__ import annotations

import hashlib
import json
from typing import Any, Callable
from skill_debug import production_side_effects_allowed


def _tool_aliases(tool_name: str) -> set[str]:
    raw = str(tool_name or "")
    aliases = {raw}
    if raw.startswith("static."):
        aliases.add(raw.removeprefix("static."))
    else:
        aliases.add(f"static.{raw}")
    if raw == "static.heuristic_prescan":
        aliases.update({"java_web_static", "jolt_builtin_static_analysis"})
    if raw in {"java_web_static", "jolt_builtin_static_analysis"}:
        aliases.add("static.heuristic_prescan")
    return aliases


def _history_id(merge_request_id: str, dedupe_hash: str) -> str:
    return "hist_" + hashlib.sha1(f"{merge_request_id}|{dedupe_hash}".encode("utf-8")).hexdigest()[:16]


def update_mr_finding_history(
    conn: Any,
    *,
    merge_request_id: str,
    head_sha: str,
    run_id: str,
    final_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    finding_rows = conn.execute(
        "SELECT id, dedupe_hash FROM review_findings WHERE review_run_id = %s",
        (run_id,),
    ).fetchall()
    finding_id_by_hash = {str(row["dedupe_hash"]): str(row["id"]) for row in finding_rows}
    current_hashes = {str(item.get("dedupe_hash") or "") for item in final_findings if item.get("dedupe_hash")}
    resolved_rows = conn.execute(
        """
        SELECT dedupe_hash, finding_id
        FROM mr_finding_history
        WHERE merge_request_id = %s AND status = 'active'
        """,
        (merge_request_id,),
    ).fetchall()
    resolved_hashes = [str(row["dedupe_hash"]) for row in resolved_rows if str(row["dedupe_hash"]) not in current_hashes]
    for finding in final_findings:
        dedupe_hash = str(finding.get("dedupe_hash") or "")
        if not dedupe_hash:
            continue
        conn.execute(
            """
            INSERT INTO mr_finding_history (
              id, merge_request_id, dedupe_hash, finding_id, first_seen_head_sha, last_seen_head_sha, status, resolved_in_commit
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'active', NULL)
            ON CONFLICT(merge_request_id, dedupe_hash) DO UPDATE SET
              finding_id = excluded.finding_id,
              last_seen_head_sha = excluded.last_seen_head_sha,
              status = 'active',
              resolved_in_commit = NULL,
              updated_at = CURRENT_TIMESTAMP
            """,
            (_history_id(merge_request_id, dedupe_hash), merge_request_id, dedupe_hash, finding_id_by_hash.get(dedupe_hash), head_sha, head_sha),
        )
    if resolved_hashes:
        conn.executemany(
            """
            UPDATE mr_finding_history
            SET status = 'resolved',
                resolved_in_commit = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE merge_request_id = %s AND dedupe_hash = %s
            """,
            [(head_sha, merge_request_id, dedupe_hash) for dedupe_hash in resolved_hashes],
        )
        conn.executemany(
            """
            UPDATE review_findings
            SET lifecycle_state = 'resolved'
            WHERE id = %s
            """,
            [(str(row["finding_id"]),) for row in resolved_rows if str(row["dedupe_hash"]) in resolved_hashes and row["finding_id"]],
        )
    return {"active": len(current_hashes), "resolved": len(resolved_hashes)}


def summarize_evidence_contracts(final_findings: list[dict[str, Any]]) -> dict[str, Any]:
    contracts: list[dict[str, Any]] = []
    for finding in final_findings:
        trace = finding.get("quality_trace") or {}
        if isinstance(trace, str):
            try:
                trace = json.loads(trace)
            except json.JSONDecodeError:
                trace = {}
        contract = trace.get("evidence_contract") if isinstance(trace, dict) else None
        if isinstance(contract, dict):
            contracts.append(contract)

    status_counts: dict[str, int] = {}
    missing_counts: dict[str, int] = {}
    score_total = 0.0
    for contract in contracts:
        status = str(contract.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        try:
            score_total += float(contract.get("score") or 0)
        except (TypeError, ValueError):
            pass
        for missing in contract.get("missing") or []:
            key = str(missing)
            missing_counts[key] = missing_counts.get(key, 0) + 1

    complete_contract_rate = round(status_counts.get("satisfied", 0) / len(contracts), 4) if contracts else 0
    weak_contract_count = status_counts.get("weak", 0)
    partial_contract_count = status_counts.get("partial", 0)
    quality_risk = "needs_attention" if weak_contract_count else "watch" if partial_contract_count else "ok"
    return {
        "version": "evidence_contract_summary_v1",
        "finding_count": len(final_findings),
        "contract_count": len(contracts),
        "status_counts": status_counts,
        "missing_counts": missing_counts,
        "average_score": round(score_total / len(contracts), 4) if contracts else 0,
        "complete_contract_rate": complete_contract_rate,
        "weak_contract_count": weak_contract_count,
        "partial_contract_count": partial_contract_count,
        "quality_risk": quality_risk,
        "findings_missing_rule": missing_counts.get("has_rule", 0),
        "findings_missing_tool_evidence": missing_counts.get("has_tool_evidence", 0),
        "findings_missing_suggested_code": missing_counts.get("has_suggested_code", 0),
    }


def make_finalize_node(
    *,
    conn: Any,
    job: Any,
    mr: Any,
    run_id: str,
    recorder: Any | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
        if recorder and hasattr(recorder, "flush"):
            recorder.flush()
        final_findings = state["final_findings"]
        status = "waiting_confirmation" if final_findings else "no_issue"
        usage = conn.execute(
            """
            SELECT
              COUNT(l.id) AS llm_calls,
              COALESCE(SUM(l.input_tokens), 0) AS input_tokens,
              COALESCE(SUM(l.output_tokens), 0) AS output_tokens,
              COALESCE(SUM(l.duration_ms), 0) AS llm_duration_ms
            FROM llm_call_records l
            JOIN agent_trace_spans s ON s.id = l.span_id
            WHERE s.review_run_id = %s
            """,
            (run_id,),
        ).fetchone()
        tool_usage = conn.execute(
            """
            SELECT COUNT(t.id) AS tool_calls, COALESCE(SUM(t.duration_ms), 0) AS tool_duration_ms
            FROM tool_call_records t
            JOIN agent_trace_spans s ON s.id = t.span_id
            WHERE s.review_run_id = %s
            """,
            (run_id,),
        ).fetchone()
        tool_coverage_rows = conn.execute(
            """
            SELECT
              t.tool_name,
              COUNT(*) AS calls,
              SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) AS completed_calls,
              SUM(CASE WHEN t.status LIKE 'skipped%%' THEN 1 ELSE 0 END) AS skipped_calls,
              SUM(CASE WHEN t.status IN ('failed', 'timeout', 'output_missing') OR t.status LIKE 'failed:%%' THEN 1 ELSE 0 END) AS failed_calls,
              COALESCE(SUM(t.duration_ms), 0) AS duration_ms
            FROM tool_call_records t
            JOIN agent_trace_spans s ON s.id = t.span_id
            WHERE s.review_run_id = %s
            GROUP BY t.tool_name
            ORDER BY t.tool_name
            """,
            (run_id,),
        ).fetchall()
        observation_rows = conn.execute(
            """
            SELECT tool_name, COUNT(*) AS hits, COUNT(DISTINCT rule_id) AS rules_hit, COUNT(DISTINCT file_path) AS files_hit
            FROM tool_observations
            WHERE review_run_id = %s
            GROUP BY tool_name
            """,
            (run_id,),
        ).fetchall()
        observations_by_tool = {str(row["tool_name"]): dict(row) for row in observation_rows}

        def observation_metric(tool_name: str, key: str) -> int:
            return sum(int((observations_by_tool.get(alias) or {}).get(key) or 0) for alias in _tool_aliases(tool_name))

        agent_rows = conn.execute(
            """
            SELECT s.agent_id, COUNT(*) AS starts
            FROM agent_trace_spans s
            JOIN agent_trace_events e ON e.span_id = s.id
            WHERE review_run_id = %s AND agent_id IS NOT NULL AND agent_id <> ''
              AND e.event_type = 'agent_started'
            GROUP BY s.agent_id
            ORDER BY s.agent_id
            """,
            (run_id,),
        ).fetchall()
        coverage = {
            "tools": [
                {
                    "id": str(row["tool_name"]),
                    "calls": int(row["calls"] or 0),
                    "completed_calls": int(row["completed_calls"] or 0),
                    "skipped_calls": int(row["skipped_calls"] or 0),
                    "failed_calls": int(row["failed_calls"] or 0),
                    "duration_ms": int(row["duration_ms"] or 0),
                    "hits": observation_metric(str(row["tool_name"]), "hits"),
                    "rules_hit": observation_metric(str(row["tool_name"]), "rules_hit"),
                    "files_hit": observation_metric(str(row["tool_name"]), "files_hit"),
                }
                for row in tool_coverage_rows
            ],
            "agents_executed": [str(row["agent_id"]) for row in agent_rows],
            "finding_count": len(final_findings),
            "candidate_quality": state.get("candidate_quality") or {},
            "evidence_contracts": summarize_evidence_contracts(final_findings),
        }
        budget_used = {
            "llm_calls": int(usage["llm_calls"] or 0),
            "input_tokens": int(usage["input_tokens"] or 0),
            "output_tokens": int(usage["output_tokens"] or 0),
            "llm_duration_ms": int(usage["llm_duration_ms"] or 0),
            "tool_calls": int(tool_usage["tool_calls"] or 0),
            "tool_duration_ms": int(tool_usage["tool_duration_ms"] or 0),
            "finding_count": len(final_findings),
        }
        budget_tracker = state.get("budget_tracker")
        if budget_tracker:
            budget_used.update(budget_tracker.snapshot())
        history_summary = {"active": 0, "resolved": 0, "skipped": "skill_debug"}
        if production_side_effects_allowed(job):
            history_summary = update_mr_finding_history(
                conn,
                merge_request_id=mr["id"],
                head_sha=job["head_sha"],
                run_id=run_id,
                final_findings=final_findings,
            )
        summary = f"输出 {len(final_findings)} 个问题"
        if budget_used.get("truncated_reason"):
            summary = f"{summary}；预算截断：{budget_used['truncated_reason']}"
        conn.execute(
            "UPDATE review_runs SET status = %s, report_summary = %s, budget_used_json = %s, coverage_json = %s, completed_at = CURRENT_TIMESTAMP WHERE id = %s",
            (status, summary, json.dumps(budget_used, ensure_ascii=False), json.dumps(coverage, ensure_ascii=False), run_id),
        )
        conn.execute("UPDATE review_jobs SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (status, job["id"]))
        if not production_side_effects_allowed(job):
            conn.execute(
                """
                UPDATE skill_debug_sessions
                SET status = CASE
                      WHEN EXISTS (
                        SELECT 1 FROM review_jobs
                        WHERE debug_session_id = skill_debug_sessions.id
                          AND id <> %s
                          AND status IN ('queued','fetching','pre_scanning','reviewing','judging','running')
                      ) THEN 'running'
                      ELSE 'completed'
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (job["id"], job.get("debug_session_id")),
            )
        if production_side_effects_allowed(job):
            conn.execute(
                "UPDATE merge_requests SET review_status = %s WHERE id = %s AND review_status NOT IN ('merged', 'closed')",
                (status, mr["id"]),
            )
        if recorder and production_side_effects_allowed(job):
            span = recorder.span("incremental_history", "history_tracker")
            recorder.event(span, "mr_finding_history_updated", "MR finding history 已更新", history_summary)
            recorder.finish(span)
        conn.commit()
        return {**state, "status": status}

    return finalize_node
