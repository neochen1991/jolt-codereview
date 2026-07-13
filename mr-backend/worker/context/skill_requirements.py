from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_CONTEXT_QUERIES = frozenset({"callers", "callees", "implementations", "tests", "config_refs"})


@dataclass(frozen=True)
class SkillContextRequirements:
    checkpoint_ids: tuple[str, ...]
    evidence_scope: str
    context_queries: tuple[str, ...]
    max_dependency_hops: int

    def to_record(self) -> dict[str, Any]:
        return {
            "checkpoint_ids": list(self.checkpoint_ids),
            "evidence_scope": self.evidence_scope,
            "context_queries": list(self.context_queries),
            "max_dependency_hops": self.max_dependency_hops,
        }


def normalize_checkpoint_requirement(checkpoint: dict[str, Any]) -> dict[str, Any]:
    scope = str(checkpoint.get("evidence_scope") or "symbol").strip()
    if scope not in {"symbol", "cross_file"}:
        raise ValueError(f"unsupported evidence_scope: {scope}")
    queries = checkpoint.get("context_queries") or []
    if isinstance(queries, str):
        queries = [item.strip() for item in queries.replace("，", ",").split(",") if item.strip()]
    normalized_queries = tuple(dict.fromkeys(str(item).strip() for item in queries if str(item).strip()))
    unsupported = sorted(set(normalized_queries) - ALLOWED_CONTEXT_QUERIES)
    if unsupported:
        raise ValueError(f"unsupported context queries: {', '.join(unsupported)}")
    try:
        hops = int(checkpoint.get("max_dependency_hops") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_dependency_hops must be an integer") from exc
    if not 1 <= hops <= 3:
        raise ValueError("max_dependency_hops must be between 1 and 3")
    return {
        "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
        "evidence_scope": scope,
        "context_queries": normalized_queries,
        "max_dependency_hops": hops,
    }


def collect_skill_context_requirements(selected_agents: list[dict[str, Any]]) -> SkillContextRequirements:
    normalized: list[dict[str, Any]] = []
    for agent in selected_agents or []:
        manifests = agent.get("skill_checkpoint_manifests") if isinstance(agent.get("skill_checkpoint_manifests"), dict) else {}
        for manifest in manifests.values():
            if not isinstance(manifest, dict):
                continue
            for checkpoint in manifest.get("checkpoints") or []:
                if isinstance(checkpoint, dict):
                    normalized.append(normalize_checkpoint_requirement(checkpoint))
    checkpoint_ids = tuple(sorted({item["checkpoint_id"] for item in normalized if item["checkpoint_id"]}))
    cross_file = any(item["evidence_scope"] == "cross_file" for item in normalized)
    queries = tuple(sorted({query for item in normalized for query in item["context_queries"]}))
    hops = max((item["max_dependency_hops"] for item in normalized), default=1)
    return SkillContextRequirements(checkpoint_ids, "cross_file" if cross_file else "symbol", queries, hops)
