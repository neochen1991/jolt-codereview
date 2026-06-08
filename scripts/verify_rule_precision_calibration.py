from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from calibration.precision_history import calibrate_findings_with_history, load_rule_precision_history


def main() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE rule_precision_history (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          rule_id TEXT NOT NULL,
          accepted_count INTEGER NOT NULL DEFAULT 0,
          rejected_count INTEGER NOT NULL DEFAULT 0,
          auto_suppress INTEGER NOT NULL DEFAULT 0,
          last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(project_id, agent_id, rule_id)
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO rule_precision_history (
          id, project_id, agent_id, rule_id, accepted_count, rejected_count, auto_suppress
        )
        VALUES (?, 'project_default', ?, ?, ?, ?, ?)
        """,
        [
            ("rph_good", "security_agent", "SEC-INJECT-003", 9, 1, 0),
            ("rph_weak", "performance_agent", "PERF-MEM-004", 1, 9, 0),
            ("rph_suppress", "coding_agent", "CODE-NOISE-001", 1, 12, 1),
        ],
    )
    history = load_rule_precision_history(conn, "project_default")
    calibrated, rejected = calibrate_findings_with_history(
        [
            {"agent_id": "security_agent", "covered_rules": ["SEC-INJECT-003"], "confidence": 0.8, "dedupe_hash": "good"},
            {"agent_id": "performance_agent", "covered_rules": ["PERF-MEM-004"], "confidence": 0.9, "dedupe_hash": "weak"},
            {"agent_id": "coding_agent", "covered_rules": ["CODE-NOISE-001"], "confidence": 0.95, "dedupe_hash": "suppress"},
        ],
        history,
    )
    by_hash = {item["dedupe_hash"]: item for item in calibrated}
    assert by_hash["good"]["confidence"] > 0.8, by_hash
    assert by_hash["weak"]["confidence"] < 0.9, by_hash
    assert rejected and rejected[0]["rejected_reasons"] == ["rule_auto_suppressed"], rejected
    print(json.dumps({"calibrated": calibrated, "rejected": rejected}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
