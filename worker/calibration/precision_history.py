from __future__ import annotations

import sqlite3
from typing import Any


def load_rule_precision_history(conn: sqlite3.Connection, project_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    columns = {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1])
        for row in conn.execute("PRAGMA table_info(rule_precision_history)").fetchall()
    }
    has_recent_counts = {"recent_accepted_count", "recent_rejected_count"}.issubset(columns)
    recent_select = (
        "recent_accepted_count, recent_rejected_count,"
        if has_recent_counts
        else "accepted_count AS recent_accepted_count, rejected_count AS recent_rejected_count,"
    )
    rows = conn.execute(
        f"""
        SELECT agent_id, rule_id, accepted_count, rejected_count,
               {recent_select} auto_suppress
        FROM rule_precision_history
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchall()
    return {
        (str(row["agent_id"]), str(row["rule_id"])): {
            "accepted_count": int(row["accepted_count"] or 0),
            "rejected_count": int(row["rejected_count"] or 0),
            "recent_accepted_count": int(row["recent_accepted_count"] or 0),
            "recent_rejected_count": int(row["recent_rejected_count"] or 0),
            "auto_suppress": bool(row["auto_suppress"]),
        }
        for row in rows
    }


def calibrate_findings_with_history(
    findings: list[dict[str, Any]],
    history: dict[tuple[str, str], dict[str, Any]],
    *,
    min_samples: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calibrated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for finding in findings:
        item = dict(finding)
        agent_id = str(item.get("agent_id") or "")
        matched_histories = []
        for rule_id in item.get("covered_rules") or []:
            record = history.get((agent_id, str(rule_id)))
            if record:
                matched_histories.append((str(rule_id), record))
        if not matched_histories:
            calibrated.append(item)
            continue
        total_recent_accepted = sum(int(record.get("recent_accepted_count") or 0) for _rule, record in matched_histories)
        total_recent_rejected = sum(int(record.get("recent_rejected_count") or 0) for _rule, record in matched_histories)
        use_recent = total_recent_accepted + total_recent_rejected > 0
        total_accepted = total_recent_accepted if use_recent else sum(int(record["accepted_count"]) for _rule, record in matched_histories)
        total_rejected = total_recent_rejected if use_recent else sum(int(record["rejected_count"]) for _rule, record in matched_histories)
        total = total_accepted + total_rejected
        confidence = float(item.get("confidence") or 0)
        auto_suppressed = any(record.get("auto_suppress") for _rule, record in matched_histories)
        if auto_suppressed and confidence < 0.5:
            rejected.append({**item, "rejected_reasons": ["rule_auto_suppressed_low_confidence"]})
            continue
        if total >= min_samples:
            precision = total_accepted / total if total else 0.5
            calibrated_confidence = confidence * 0.7 + precision * 0.3
            if auto_suppressed:
                calibrated_confidence *= 0.5
            item["confidence"] = round(max(0.0, min(0.99, calibrated_confidence)), 4)
            item["judge_adjustment"] = "history_auto_suppress_downgraded" if auto_suppressed else "history_confidence_calibrated"
            item["calibration"] = {
                "precision": round(precision, 4),
                "samples": total,
                "accepted_count": total_accepted,
                "rejected_count": total_rejected,
                "window": "recent" if use_recent else "lifetime",
                "auto_suppress": auto_suppressed,
            }
        calibrated.append(item)
    return calibrated, rejected
