from __future__ import annotations

import json
import sqlite3
from typing import Any

from tools.tool_normalizer import sha1


def _candidate_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'candidate_findings'"
    ).fetchone()
    return bool(row)


def _candidate_id(review_run_id: str, dedupe_hash: str, stage: str) -> str:
    return "cand_" + sha1("|".join([review_run_id, dedupe_hash, stage]))[:16]


def _safe_json(value: Any, default: Any) -> str:
    try:
        return json.dumps(value if value is not None else default, ensure_ascii=False)
    except TypeError:
        return json.dumps(default, ensure_ascii=False)


def _candidate_dedupe_hash(item: dict[str, Any], stage: str) -> str:
    dedupe_hash = str(item.get("dedupe_hash") or "").strip()
    if dedupe_hash:
        return dedupe_hash
    return sha1(
        "|".join(
            [
                str(item.get("agent_id") or item.get("tool_name") or "unknown"),
                str(item.get("file_path") or ""),
                str(item.get("line_start") or ""),
                str(item.get("title") or item.get("message") or ""),
                stage,
            ]
        )
    )


def _source_type(item: dict[str, Any]) -> str:
    if item.get("source_tool_observation") or item.get("tool_name") or item.get("tool_rule_id"):
        return "tool"
    if item.get("agent_id"):
        return "agent"
    return "unknown"


def upsert_candidate_finding(
    conn: sqlite3.Connection,
    *,
    review_run_id: str,
    item: dict[str, Any],
    stage: str,
    status: str,
    rejected_reasons: list[str] | None = None,
    final_finding_id: str | None = None,
) -> None:
    if not _candidate_table_exists(conn):
        return
    dedupe_hash = _candidate_dedupe_hash(item, stage)
    rule_values = item.get("covered_rules") if isinstance(item.get("covered_rules"), list) else []
    rule_id = str(item.get("tool_rule_id") or item.get("rule_id") or (rule_values[0] if rule_values else "") or "")
    source_observations = item.get("source_observations") or item.get("source_observations_json") or []
    source_tool_observation = item.get("source_tool_observation")
    if source_tool_observation and not source_observations:
        source_observations = [source_tool_observation]
    conn.execute(
        """
        INSERT INTO candidate_findings (
          id, review_run_id, dedupe_hash, stage, status, source_type,
          agent_id, tool_name, rule_id, severity, confidence, file_path, line_start, line_end,
          title, problem_description, evidence, rejected_reasons_json, source_observations_json,
          raw_json, final_finding_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_run_id, dedupe_hash, stage) DO UPDATE SET
          status = excluded.status,
          source_type = excluded.source_type,
          agent_id = excluded.agent_id,
          tool_name = excluded.tool_name,
          rule_id = excluded.rule_id,
          severity = excluded.severity,
          confidence = excluded.confidence,
          file_path = excluded.file_path,
          line_start = excluded.line_start,
          line_end = excluded.line_end,
          title = excluded.title,
          problem_description = excluded.problem_description,
          evidence = excluded.evidence,
          rejected_reasons_json = excluded.rejected_reasons_json,
          source_observations_json = excluded.source_observations_json,
          raw_json = excluded.raw_json,
          final_finding_id = COALESCE(excluded.final_finding_id, candidate_findings.final_finding_id),
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            _candidate_id(review_run_id, dedupe_hash, stage),
            review_run_id,
            dedupe_hash,
            stage,
            status,
            _source_type(item),
            str(item.get("agent_id") or item.get("adopted_by_agent") or "") or None,
            str(item.get("tool_name") or "") or None,
            rule_id or None,
            str(item.get("severity") or "") or None,
            float(item.get("confidence") or 0),
            str(item.get("file_path") or ""),
            item.get("line_start"),
            item.get("line_end"),
            str(item.get("title") or item.get("message") or "")[:300],
            str(item.get("problem_description") or item.get("message") or item.get("title") or "")[:4000],
            str(item.get("evidence") or item.get("message") or "")[:4000],
            _safe_json(rejected_reasons or item.get("rejected_reasons") or [], []),
            _safe_json(source_observations, []),
            _safe_json(item, {}),
            final_finding_id,
        ),
    )


def upsert_candidate_findings(
    conn: sqlite3.Connection,
    *,
    review_run_id: str,
    items: list[dict[str, Any]],
    stage: str,
    status: str,
) -> None:
    for item in items:
        upsert_candidate_finding(
            conn,
            review_run_id=review_run_id,
            item=item,
            stage=stage,
            status=status,
            rejected_reasons=item.get("rejected_reasons") or [],
            final_finding_id=item.get("persisted_finding_id"),
        )
