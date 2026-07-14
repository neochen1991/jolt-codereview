from __future__ import annotations

import fnmatch
import re
from typing import Any


def _file_value(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def changed_file_paths(files: list[Any]) -> list[str]:
    result: list[str] = []
    for item in files or []:
        value = str(_file_value(item, "path") or _file_value(item, "file_path") or _file_value(item, "filename") or "").replace("\\", "/").lstrip("/")
        if value and value not in result:
            result.append(value)
    return result


def applies_to_patterns(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value or "**/*").strip()
    return [item.strip() for item in re.split(r"[,;\n]+", raw) if item.strip()] or ["**/*"]


def path_matches_applies_to(path: str, applies_to: Any) -> bool:
    normalized = str(path or "").replace("\\", "/").lstrip("/")
    for pattern in applies_to_patterns(applies_to):
        candidate = pattern.replace("\\", "/").lstrip("/")
        if candidate in {"*", "**", "**/*"}:
            return True
        if not any(token in candidate for token in ("/", "*", "?", "[", "]", ".")):
            # Legacy Skills often use descriptive scopes such as "Java 后端".
            # Treat them as broad applicability instead of silently dropping checkpoints.
            return True
        if fnmatch.fnmatchcase(normalized, candidate):
            return True
        if candidate.startswith("**/") and fnmatch.fnmatchcase(normalized, candidate[3:]):
            return True
    return False


def checkpoint_applies_to_files(checkpoint: dict[str, Any], files: list[Any]) -> bool:
    paths = changed_file_paths(files)
    return not paths or any(path_matches_applies_to(path, checkpoint.get("applies_to")) for path in paths)


def build_skill_routing_facts(
    agent_configs: list[dict[str, Any]],
    selected_agents: list[dict[str, Any]],
    files: list[Any],
) -> list[dict[str, Any]]:
    selected_ids = {str(agent.get("agent_id") or "") for agent in selected_agents}
    paths = changed_file_paths(files)
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for agent in agent_configs:
        agent_id = str(agent.get("agent_id") or "")
        manifests = agent.get("skill_checkpoint_manifests") if isinstance(agent.get("skill_checkpoint_manifests"), dict) else {}
        for skill_key in [str(item) for item in (agent.get("custom_skills") or []) if str(item).strip()]:
            identity = (agent_id, skill_key)
            if identity in seen:
                continue
            seen.add(identity)
            manifest = manifests.get(skill_key) if isinstance(manifests.get(skill_key), dict) else {}
            checkpoints = [item for item in (manifest.get("checkpoints") or []) if isinstance(item, dict)]
            matched_files = sorted(
                {
                    path
                    for path in paths
                    if not checkpoints or any(path_matches_applies_to(path, item.get("applies_to")) for item in checkpoints)
                }
            )
            applicable = bool(matched_files) if paths else True
            if not manifest:
                applicable = True
                matched_files = list(paths)
            facts.append(
                {
                    "skill_key": skill_key,
                    "agent_id": agent_id,
                    "applicable": applicable,
                    "applicability_mode": "compiled_manifest" if manifest else "legacy_fallback",
                    "matched_files": matched_files,
                    "routed": agent_id in selected_ids,
                    "skill_version": str(manifest.get("skill_version") or ""),
                    "bundle_sha256": str(manifest.get("bundle_sha256") or ""),
                    "manifest_source_hash": str(manifest.get("source_hash") or ""),
                    "compiler_version": str(manifest.get("compiler_version") or ""),
                }
            )
    return facts


def seal_skill_runtime_facts(
    routing_facts: list[dict[str, Any]],
    coverage: dict[str, Any],
    final_findings: list[dict[str, Any]],
    loaded_skills: set[tuple[str, str]],
    *,
    unclassified_deletions: int | dict[tuple[str, str], int] = 0,
) -> list[dict[str, Any]]:
    coverage_items = [item for item in (coverage.get("items") or []) if isinstance(item, dict) and item.get("type") == "skill_checkpoint"]
    final_rules_by_agent: dict[str, set[str]] = {}
    for finding in final_findings:
        agent_id = str(finding.get("agent_id") or "")
        final_rules_by_agent.setdefault(agent_id, set()).update(str(rule) for rule in (finding.get("covered_rules") or []) if str(rule))

    sealed: list[dict[str, Any]] = []
    for routing in routing_facts:
        skill_key = str(routing.get("skill_key") or "")
        agent_id = str(routing.get("agent_id") or "")
        items = [
            item
            for item in coverage_items
            if str(item.get("skill_key") or "") == skill_key and str(item.get("agent_id") or "") == agent_id
        ]
        checkpoint_facts: list[dict[str, Any]] = []
        for item in items:
            checkpoint_id = str(item.get("checkpoint_id") or item.get("rule_id") or "")
            checked = bool(item.get("checked"))
            finding_count = int(item.get("finding_count") or 0)
            skipped = bool(item.get("skipped"))
            rejected_count = int(item.get("rejected_count") or 0)
            if checked and finding_count > 0:
                outcome = "hit"
            elif checked and skipped:
                outcome = "not_applicable"
            elif checked and rejected_count > 0:
                outcome = "rejected"
            elif checked:
                outcome = "clean"
            else:
                outcome = "unresolved"
            judge_hit = checkpoint_id in final_rules_by_agent.get(agent_id, set())
            checkpoint_facts.append(
                {
                    "checkpoint_id": checkpoint_id,
                    "outcome": outcome,
                    "checked": checked,
                    "raw_hit": finding_count > 0,
                    "judge_hit": judge_hit,
                    "finding_count": finding_count,
                    "rejected_count": rejected_count,
                    "retry_count": int(item.get("retry_count") or 0),
                }
            )
        completed = sum(1 for item in checkpoint_facts if item["outcome"] in {"hit", "clean", "not_applicable", "rejected"})
        unresolved = sum(1 for item in checkpoint_facts if item["outcome"] in {"error", "timeout", "unresolved"})
        if isinstance(unclassified_deletions, dict):
            unclassified_count = sum(
                int(unclassified_deletions.get((agent_id, str(item.get("checkpoint_id") or "")), 0))
                for item in checkpoint_facts
            )
        else:
            unclassified_count = int(unclassified_deletions or 0)
        sealed.append(
            {
                **routing,
                "loaded": (agent_id, skill_key) in loaded_skills,
                "required_checkpoint_count": len(checkpoint_facts),
                "completed_checkpoint_count": completed,
                "unresolved_checkpoint_count": unresolved,
                "raw_hit_checkpoint_count": sum(1 for item in checkpoint_facts if item["raw_hit"]),
                "judge_hit_checkpoint_count": sum(1 for item in checkpoint_facts if item["judge_hit"]),
                "judge_unclassified_deletion_count": unclassified_count,
                "checkpoints": checkpoint_facts,
            }
        )
    return sealed
