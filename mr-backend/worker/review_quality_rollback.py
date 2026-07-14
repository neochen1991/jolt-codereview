from __future__ import annotations

import json
import hashlib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from config import common_base_url, internal_service_token, normalize_review_quality_config


FAILURE_STATUSES = {"failed", "dead_letter", "cancelled", "too_large"}
RUNTIME_WINDOW_SIZE = 10
MAX_FAILURE_RATE = 0.20


def _is_runtime_failure(row: dict[str, Any]) -> bool:
    return (
        str(row.get("status") or "").lower() in FAILURE_STATUSES
        or str(row.get("context_health_status") or "").lower() == "blocked"
    )


def runtime_safety_decision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate newest-first production outcomes, once per distinct MR."""
    distinct: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        merge_request_id = str(row.get("merge_request_id") or "")
        if not merge_request_id or merge_request_id in seen:
            continue
        seen.add(merge_request_id)
        distinct.append(row)

    newest_three = distinct[:3]
    if len(newest_three) == 3 and all(_is_runtime_failure(row) for row in newest_three):
        return {
            "rollback_required": True,
            "trigger": "three_consecutive_failures",
            "distinct_mr_count": len(newest_three),
            "failed_count": 3,
            "failure_rate": 1.0,
        }

    window = distinct[:RUNTIME_WINDOW_SIZE]
    failed_count = sum(1 for row in window if _is_runtime_failure(row))
    failure_rate = round(failed_count / len(window), 4) if window else 0.0
    if len(window) < RUNTIME_WINDOW_SIZE:
        trigger = "insufficient_runtime_window"
        rollback_required = False
    else:
        rollback_required = failure_rate > MAX_FAILURE_RATE
        trigger = "failure_rate_exceeded" if rollback_required else "runtime_window_healthy"
    return {
        "rollback_required": rollback_required,
        "trigger": trigger,
        "distinct_mr_count": len(window),
        "failed_count": failed_count,
        "failure_rate": failure_rate,
    }


def build_rollback_payload(
    project_id: str,
    decision: dict[str, Any],
    *,
    source_run_id: str,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "target_context_engine": "v1",
        "trigger": str(decision.get("trigger") or "runtime_safety_threshold"),
        "source_run_id": source_run_id,
        "evidence": {
            "distinct_mr_count": int(decision.get("distinct_mr_count") or 0),
            "failed_count": int(decision.get("failed_count") or 0),
            "failure_rate": float(decision.get("failure_rate") or 0.0),
        },
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }


def load_recent_runtime_rows(conn: Any, project_id: str, source_run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT j.merge_request_id, j.status,
               COALESCE(rr.coverage_json::jsonb #>> '{context_health,status}', '') AS context_health_status
        FROM review_jobs j
        JOIN merge_requests mr ON mr.id = j.merge_request_id
        JOIN repositories repo ON repo.id = mr.repository_id
        LEFT JOIN LATERAL (
          SELECT id, coverage_json, completed_at, started_at
          FROM review_runs
          WHERE review_job_id = j.id
          ORDER BY COALESCE(completed_at, started_at) DESC
          LIMIT 1
        ) rr ON TRUE
        WHERE repo.project_id = %s
          AND j.execution_kind = 'production_review'
          AND (
            COALESCE(rr.coverage_json::jsonb #>> '{context_health,context_engine}', '') = 'v2'
            OR rr.id = %s
          )
        ORDER BY j.updated_at DESC
        LIMIT 50
        """,
        (project_id, source_run_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _post_rollback(config: dict[str, Any], project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = internal_service_token()
    if not token:
        raise RuntimeError("JOLT_INTERNAL_SERVICE_TOKEN is required for automatic review quality rollback")
    request = urllib.request.Request(
        f"{common_base_url(config)}/internal/models/projects/{project_id}/review-quality/rollback",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json", "x-internal-service-token": token},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"automatic review quality rollback failed: {exc.code} {detail}") from exc


def request_review_quality_rollback(
    conn: Any,
    config: dict[str, Any],
    project_id: str,
    *,
    trigger: str,
    source_run_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "project_id": project_id,
        "target_context_engine": "v1",
        "trigger": trigger,
        "source_run_id": source_run_id,
        "evidence": evidence,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    digest = hashlib.sha256(json.dumps(payload["evidence"], sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]
    event_id = f"rollback_{project_id}_{trigger}_{digest}"
    conn.execute(
        """
        INSERT INTO review_quality_rollback_events (
          id, project_id, trigger, source_run_id, status, evidence_json
        ) VALUES (%s, %s, %s, %s, 'rollback_pending', %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (event_id, project_id, trigger, source_run_id, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    existing = conn.execute(
        "SELECT status, response_json FROM review_quality_rollback_events WHERE id = %s",
        (event_id,),
    ).fetchone()
    if existing and str(existing["status"]) == "rolled_back":
        try:
            response = json.loads(str(existing["response_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            response = {}
        return {"status": "rolled_back", "response": response, "idempotent": True}
    response = _post_rollback(config, project_id, payload)
    conn.execute(
        """
        UPDATE review_quality_rollback_events
        SET status = 'rolled_back', response_json = %s, error_message = '', updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (json.dumps(response, ensure_ascii=False), event_id),
    )
    conn.commit()
    return {"status": "rolled_back", "response": response}


def _evaluate_and_request_runtime_rollback(
    conn: Any,
    config: dict[str, Any],
    project_id: str,
    source_run_id: str,
) -> dict[str, Any]:
    quality = normalize_review_quality_config(config)
    if quality["context_engine"] != "v2" or not quality["auto_rollback_enabled"]:
        return {"status": "disabled"}
    decision = runtime_safety_decision(load_recent_runtime_rows(conn, project_id, source_run_id))
    if not decision["rollback_required"]:
        return {"status": "healthy", "decision": decision}

    payload = build_rollback_payload(project_id, decision, source_run_id=source_run_id)
    event_id = f"rollback_{project_id}_{source_run_id or decision['trigger']}"
    conn.execute(
        """
        INSERT INTO review_quality_rollback_events (
          id, project_id, trigger, source_run_id, status, evidence_json
        ) VALUES (%s, %s, %s, %s, 'rollback_pending', %s)
        ON CONFLICT (id) DO UPDATE SET
          status = 'rollback_pending', evidence_json = excluded.evidence_json,
          error_message = '', updated_at = CURRENT_TIMESTAMP
        """,
        (event_id, project_id, decision["trigger"], source_run_id, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    try:
        response = _post_rollback(config, project_id, payload)
        conn.execute(
            """
            UPDATE review_quality_rollback_events
            SET status = 'rolled_back', response_json = %s, error_message = '', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (json.dumps(response, ensure_ascii=False), event_id),
        )
        conn.commit()
        return {"status": "rolled_back", "decision": decision, "response": response}
    except Exception as exc:
        conn.execute(
            """
            UPDATE review_quality_rollback_events
            SET status = 'rollback_pending', error_message = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (str(exc), event_id),
        )
        conn.commit()
        return {"status": "rollback_pending", "decision": decision, "error_message": str(exc)}


def evaluate_and_request_runtime_rollback(
    conn: Any,
    config: dict[str, Any],
    project_id: str,
    source_run_id: str,
) -> dict[str, Any]:
    """Fail open: rollout monitoring must never turn a completed review into a failed review."""
    try:
        return _evaluate_and_request_runtime_rollback(conn, config, project_id, source_run_id)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"status": "monitoring_error", "error_message": str(exc)}
