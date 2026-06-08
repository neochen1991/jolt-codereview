from __future__ import annotations

import sqlite3
from typing import Any


def load_rule_precision_history(conn: sqlite3.Connection, project_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT agent_id, rule_id, accepted_count, rejected_count, auto_suppress
        FROM rule_precision_history
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchall()
    return {
        (str(row["agent_id"]), str(row["rule_id"])): {
            "accepted_count": int(row["accepted_count"] or 0),
            "rejected_count": int(row["rejected_count"] or 0),
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
        if any(record.get("auto_suppress") for _rule, record in matched_histories):
            rejected.append({**item, "rejected_reasons": ["rule_auto_suppressed"]})
            continue
        total_accepted = sum(int(record["accepted_count"]) for _rule, record in matched_histories)
        total_rejected = sum(int(record["rejected_count"]) for _rule, record in matched_histories)
        total = total_accepted + total_rejected
        if total >= min_samples:
            precision = total_accepted / total if total else 0.5
            confidence = float(item.get("confidence") or 0)
            calibrated_confidence = confidence * 0.7 + precision * 0.3
            item["confidence"] = round(max(0.0, min(0.99, calibrated_confidence)), 4)
            item["judge_adjustment"] = "history_confidence_calibrated"
            item["calibration"] = {
                "precision": round(precision, 4),
                "samples": total,
                "accepted_count": total_accepted,
                "rejected_count": total_rejected,
            }
        calibrated.append(item)
    return calibrated, rejected
