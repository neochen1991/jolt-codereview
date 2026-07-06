from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "worker" / "rules" / "registry.json"


def _load_raw() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"defaults": {}, "rules": []}
    return json.loads(REGISTRY_PATH.read_text("utf-8"))


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    raw = _load_raw()
    rules = raw.get("rules") if isinstance(raw.get("rules"), list) else []
    by_id = {str(rule.get("id")): rule for rule in rules if isinstance(rule, dict) and rule.get("id")}
    tool_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    wildcard_index: dict[str, list[dict[str, Any]]] = {}
    for rule in by_id.values():
        for source in rule.get("tool_sources") or []:
            if not isinstance(source, dict):
                continue
            tool = str(source.get("tool") or "*")
            tool_rule_id = str(source.get("tool_rule_id") or "")
            if not tool_rule_id:
                continue
            item = {"rule": rule, "source": source}
            if tool == "*":
                wildcard_index.setdefault(tool_rule_id, []).append(item)
            else:
                tool_index.setdefault((tool, tool_rule_id), []).append(item)
    return {
        "defaults": raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {},
        "rules": rules,
        "by_id": by_id,
        "tool_index": tool_index,
        "wildcard_index": wildcard_index,
    }


def rule(rule_id: str | None) -> dict[str, Any] | None:
    if not rule_id:
        return None
    return load_registry()["by_id"].get(str(rule_id))


def rule_ids() -> set[str]:
    return set(load_registry()["by_id"])


def promotable_rule_ids() -> set[str]:
    return {
        str(item.get("id") or "")
        for item in load_registry()["by_id"].values()
        if isinstance(item, dict) and item.get("promote_from_tool")
    } - {""}


def tool_coverage_fill_rule_ids() -> set[str]:
    return promotable_rule_ids()


def external_tool_rule_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in load_registry()["by_id"].values():
        rule_id = str(item.get("id") or "")
        if not rule_id:
            continue
        for source in item.get("tool_sources") or []:
            if not isinstance(source, dict):
                continue
            tool_rule_id = str(source.get("tool_rule_id") or "")
            if tool_rule_id and tool_rule_id != rule_id:
                mapping.setdefault(tool_rule_id, rule_id)
    return mapping


def category_for_rule(rule_id: str | None) -> str:
    item = rule(rule_id)
    category = item.get("category") if isinstance(item, dict) else None
    return str(category or "")


def agent_owners_for_rule(rule_id: str | None) -> set[str]:
    item = rule(rule_id)
    owners = item.get("agent_owners") if isinstance(item, dict) else None
    return {str(owner) for owner in owners or []}


def categories_for_agent(agent_id: str | None) -> set[str]:
    if not agent_id:
        return set()
    categories: set[str] = set()
    for item in load_registry()["by_id"].values():
        owners = item.get("agent_owners") if isinstance(item, dict) else None
        if str(agent_id) in {str(owner) for owner in owners or []}:
            category = str(item.get("category") or "")
            if category:
                categories.add(category)
    return categories


def signature_keys_for(rule_id: str | None) -> list[str]:
    item = rule(rule_id)
    keys = item.get("signature_keys") if isinstance(item, dict) else None
    defaults = load_registry().get("defaults", {})
    default_keys = defaults.get("signature_keys") if isinstance(defaults, dict) else None
    values = keys if isinstance(keys, list) and keys else default_keys
    return [str(key) for key in values] if isinstance(values, list) else ["covered_rules", "file_path", "line_bucket"]


def _tool_source_candidates(observation: dict[str, Any]) -> list[dict[str, Any]]:
    registry = load_registry()
    tool = str(observation.get("tool_name") or "")
    tool_rule_id = str(observation.get("rule_id") or observation.get("tool_rule_id") or "")
    if not tool_rule_id:
        return []
    return [
        *registry["tool_index"].get((tool, tool_rule_id), []),
        *registry["wildcard_index"].get(tool_rule_id, []),
    ]


def tool_source_for_observation(observation: dict[str, Any]) -> dict[str, Any] | None:
    candidates = _tool_source_candidates(observation)
    for candidate in candidates:
        if candidate["rule"].get("promote_from_tool"):
            return candidate
    return candidates[0] if candidates else None


def rule_for_tool_observation(observation: dict[str, Any]) -> dict[str, Any] | None:
    confidence = float(observation.get("confidence") or 0)
    for candidate in _tool_source_candidates(observation):
        source = candidate["source"]
        try:
            min_confidence = float(source.get("min_confidence") or 0)
        except (TypeError, ValueError):
            min_confidence = 0.0
        if confidence >= min_confidence:
            return candidate["rule"]
    return None
