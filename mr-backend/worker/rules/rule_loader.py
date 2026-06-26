from __future__ import annotations

from typing import Any

from db_helpers import table_exists
from rules.markdown_rule_parser import parse_markdown_rules


def load_bound_rules(conn: Any, project_id: str, agent_key: str) -> list[dict[str, Any]]:
    if not table_exists(conn, "expert_rule_bindings"):
        return []
    rows = conn.execute(
        """
        SELECT rd.id, rd.name, rd.version, rd.content, erb.priority
        FROM expert_rule_bindings erb
        JOIN rule_documents rd ON rd.id = erb.rule_document_id
        WHERE erb.project_id = %s
          AND erb.agent_key = %s
          AND rd.status = 'active'
        ORDER BY erb.priority, rd.name
        """,
        (project_id, agent_key),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        for rule in parse_markdown_rules(row["content"] or ""):
            item = rule.to_prompt_item()
            item.update(
                {
                    "document_id": row["id"],
                    "document_name": row["name"],
                    "document_version": row["version"],
                    "priority": int(row["priority"]),
                }
            )
            items.append(item)
    return items
