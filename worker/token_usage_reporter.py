from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

from file_logger import beijing_iso_timestamp, write_review_run_log, write_worker_log


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _token_usage_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("token_usage")
    return raw if isinstance(raw, dict) else {}


def _enabled(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _timeout_seconds(config: dict[str, Any]) -> int:
    try:
        return max(1, min(60, int(config.get("timeout_seconds") or 10)))
    except (TypeError, ValueError):
        return 10


def _auth_token(config: dict[str, Any]) -> str:
    token_env = str(config.get("auth_token_env") or "").strip()
    if token_env and os.environ.get(token_env):
        return str(os.environ[token_env])
    return str(config.get("auth_token") or "").strip()


def _employee_no(config: dict[str, Any], row: sqlite3.Row) -> str:
    configured = str(config.get("employee_no") or "").strip()
    if configured:
        return configured
    employee_env = str(config.get("employee_no_env") or "").strip()
    if employee_env and os.environ.get(employee_env):
        return str(os.environ[employee_env]).strip()
    for key in ("requested_username", "requested_display_name", "requested_by"):
        value = str(row[key] or "").strip() if key in row.keys() else ""
        if value:
            return value
    return str(config.get("default_employee_no") or "system").strip() or "system"


def _fetch_run_context(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
          rr.id AS review_run_id,
          rr.status AS run_status,
          rr.started_at,
          rr.completed_at,
          rj.id AS review_job_id,
          rj.requested_by,
          mr.id AS merge_request_id,
          mr.external_mr_id,
          mr.number AS merge_request_number,
          mr.title AS merge_request_title,
          mr.author AS merge_request_author,
          mr.latest_head_sha,
          repo.id AS repository_id,
          repo.name AS repository_name,
          repo.provider,
          repo.external_repo_id,
          p.id AS project_id,
          p.name AS project_name,
          u.username AS requested_username,
          u.display_name AS requested_display_name
        FROM review_runs rr
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories repo ON repo.id = mr.repository_id
        JOIN projects p ON p.id = repo.project_id
        LEFT JOIN users u ON u.id = rj.requested_by
        WHERE rr.id = ?
        """,
        (run_id,),
    ).fetchone()


def _usage_summary(conn: sqlite3.Connection, run_id: str) -> tuple[dict[str, int], list[dict[str, Any]]]:
    total_row = conn.execute(
        """
        SELECT
          COUNT(l.id) AS llm_calls,
          COALESCE(SUM(l.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(l.output_tokens), 0) AS output_tokens
        FROM llm_call_records l
        JOIN agent_trace_spans s ON s.id = l.span_id
        WHERE s.review_run_id = ?
        """,
        (run_id,),
    ).fetchone()
    model_rows = conn.execute(
        """
        SELECT
          l.provider,
          l.model,
          COUNT(l.id) AS llm_calls,
          COALESCE(SUM(l.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(l.output_tokens), 0) AS output_tokens,
          COALESCE(SUM(l.duration_ms), 0) AS duration_ms
        FROM llm_call_records l
        JOIN agent_trace_spans s ON s.id = l.span_id
        WHERE s.review_run_id = ?
        GROUP BY l.provider, l.model
        ORDER BY l.provider, l.model
        """,
        (run_id,),
    ).fetchall()
    usage = {
        "llm_calls": int(total_row["llm_calls"] or 0) if total_row else 0,
        "input_tokens": int(total_row["input_tokens"] or 0) if total_row else 0,
        "output_tokens": int(total_row["output_tokens"] or 0) if total_row else 0,
    }
    usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    models = [
        {
            "provider": row["provider"],
            "model": row["model"],
            "llm_calls": int(row["llm_calls"] or 0),
            "input_tokens": int(row["input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "total_tokens": int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0),
            "duration_ms": int(row["duration_ms"] or 0),
        }
        for row in model_rows
    ]
    return usage, models


def _build_payload(
    *,
    config: dict[str, Any],
    row: sqlite3.Row,
    usage: dict[str, int],
    model_usage: list[dict[str, Any]],
    employee_no: str,
    reported_at: str,
) -> dict[str, Any]:
    return {
        "service_name": str(config.get("service_name") or "jolt-codereview"),
        "task_type": "mr_review",
        "review_run_id": row["review_run_id"],
        "review_job_id": row["review_job_id"],
        "project": {
            "id": row["project_id"],
            "name": row["project_name"],
        },
        "repository": {
            "id": row["repository_id"],
            "name": row["repository_name"],
            "provider": row["provider"],
            "external_repo_id": row["external_repo_id"],
        },
        "merge_request": {
            "id": row["merge_request_id"],
            "external_mr_id": row["external_mr_id"],
            "number": row["merge_request_number"],
            "title": row["merge_request_title"],
            "author": row["merge_request_author"],
            "head_sha": row["latest_head_sha"],
        },
        "reporter": {
            "employee_no": employee_no,
            "requested_by": row["requested_by"],
        },
        "reported_at": reported_at,
        "run": {
            "status": row["run_status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        },
        "token_usage": usage,
        "model_usage": model_usage,
    }


def _save_report(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    employee_no: str,
    reported_at: str,
    usage: dict[str, int],
    status: str,
    endpoint: str,
    payload: dict[str, Any],
    response_status: int | None = None,
    response_body: str = "",
    error_message: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO token_usage_reports (
          id, review_run_id, review_job_id, merge_request_id, project_id, repository_id,
          employee_no, reported_at, input_tokens, output_tokens, total_tokens, llm_calls,
          status, endpoint, response_status, response_body, error_message, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_run_id) DO UPDATE SET
          employee_no = excluded.employee_no,
          reported_at = excluded.reported_at,
          input_tokens = excluded.input_tokens,
          output_tokens = excluded.output_tokens,
          total_tokens = excluded.total_tokens,
          llm_calls = excluded.llm_calls,
          status = excluded.status,
          endpoint = excluded.endpoint,
          response_status = excluded.response_status,
          response_body = excluded.response_body,
          error_message = excluded.error_message,
          payload_json = excluded.payload_json,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            _new_id("tur"),
            row["review_run_id"],
            row["review_job_id"],
            row["merge_request_id"],
            row["project_id"],
            row["repository_id"],
            employee_no,
            reported_at,
            usage["input_tokens"],
            usage["output_tokens"],
            usage["total_tokens"],
            usage["llm_calls"],
            status,
            endpoint,
            response_status,
            response_body[:2000],
            error_message[:1000],
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()


def report_token_usage(conn: sqlite3.Connection, config: dict[str, Any], run_id: str) -> dict[str, Any]:
    token_config = _token_usage_config(config)
    row = _fetch_run_context(conn, run_id)
    if not row:
        return {"status": "skipped_missing_run"}
    usage, model_usage = _usage_summary(conn, run_id)
    reported_at = beijing_iso_timestamp()
    employee_no = _employee_no(token_config, row)
    endpoint = str(token_config.get("endpoint") or "").strip()
    payload = _build_payload(
        config=token_config,
        row=row,
        usage=usage,
        model_usage=model_usage,
        employee_no=employee_no,
        reported_at=reported_at,
    )

    if not _enabled(token_config.get("enabled")):
        status = "skipped_disabled"
        _save_report(conn, row=row, employee_no=employee_no, reported_at=reported_at, usage=usage, status=status, endpoint=endpoint, payload=payload)
        write_worker_log(config, "token_usage_report_skipped", {"review_run_id": run_id, "status": status, "total_tokens": usage["total_tokens"]})
        write_review_run_log(config, run_id, "token_usage_report_skipped", {"status": status, "total_tokens": usage["total_tokens"]})
        return {"status": status, **usage}

    if not endpoint:
        status = "skipped_no_endpoint"
        _save_report(conn, row=row, employee_no=employee_no, reported_at=reported_at, usage=usage, status=status, endpoint=endpoint, payload=payload)
        write_worker_log(config, "token_usage_report_skipped", {"review_run_id": run_id, "status": status, "total_tokens": usage["total_tokens"]})
        write_review_run_log(config, run_id, "token_usage_report_skipped", {"status": status, "total_tokens": usage["total_tokens"]})
        return {"status": status, **usage}

    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Jolt-CodeReview-Worker/0.1"}
    token = _auth_token(token_config)
    if token:
        auth_header = str(token_config.get("auth_header") or "Authorization")
        headers[auth_header] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    method = str(token_config.get("method") or "POST").upper()
    request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds(token_config)) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            response_status = int(response.status)
        status = "reported" if 200 <= response_status < 300 else "failed"
        _save_report(
            conn,
            row=row,
            employee_no=employee_no,
            reported_at=reported_at,
            usage=usage,
            status=status,
            endpoint=endpoint,
            payload=payload,
            response_status=response_status,
            response_body=response_body,
        )
        write_worker_log(config, "token_usage_report_finished", {"review_run_id": run_id, "status": status, "response_status": response_status, "total_tokens": usage["total_tokens"]})
        write_review_run_log(config, run_id, "token_usage_report_finished", {"status": status, "response_status": response_status, "total_tokens": usage["total_tokens"]})
        return {"status": status, "response_status": response_status, **usage}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        status = "failed"
        _save_report(
            conn,
            row=row,
            employee_no=employee_no,
            reported_at=reported_at,
            usage=usage,
            status=status,
            endpoint=endpoint,
            payload=payload,
            error_message=str(exc),
        )
        write_worker_log(config, "token_usage_report_failed", {"review_run_id": run_id, "error_message": str(exc), "total_tokens": usage["total_tokens"]}, "error")
        write_review_run_log(config, run_id, "token_usage_report_failed", {"error_message": str(exc), "total_tokens": usage["total_tokens"]}, "error")
        return {"status": status, "error_message": str(exc), **usage}
