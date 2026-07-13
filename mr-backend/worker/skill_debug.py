from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any


SENSITIVE_KEYS = {"token", "access_token", "refresh_token", "api_key", "apikey", "secret", "authorization", "password"}


class SkillDebugStopped(RuntimeError):
    pass


def is_debug_job(job: dict[str, Any] | Any) -> bool:
    kind = str((job.get("execution_kind") if hasattr(job, "get") else "") or "production_review")
    return kind.startswith("skill_debug_")


def is_shadow_job(job: dict[str, Any] | Any) -> bool:
    kind = str((job.get("execution_kind") if hasattr(job, "get") else "") or "production_review")
    return kind in {"quality_shadow_v1", "quality_shadow_v2"}


def is_non_production_job(job: dict[str, Any] | Any) -> bool:
    return is_debug_job(job) or is_shadow_job(job)


def shadow_context_engine(job: dict[str, Any] | Any) -> str | None:
    if not is_shadow_job(job):
        return None
    return str(job.get("execution_kind")).removeprefix("quality_shadow_")


def debug_variant(job: dict[str, Any] | Any) -> str:
    return str((job.get("debug_variant") if hasattr(job, "get") else "") or "candidate")


def production_side_effects_allowed(job: dict[str, Any] | Any) -> bool:
    return not is_non_production_job(job)


def redact_snapshot(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_KEYS or any(key.lower().endswith(f"_{item}") for item in SENSITIVE_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return {item_key: redact_snapshot(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact_snapshot(item) for item in value]
    return value


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def apply_debug_snapshot(agent_configs: list[dict[str, Any]], snapshot: dict[str, Any], variant: str) -> list[dict[str, Any]]:
    agents = copy.deepcopy(agent_configs)
    skill = dict(snapshot.get("skill") or {})
    target_skill = str(skill.get("skill_key") or "").strip()
    snapshot_agent = dict(snapshot.get("agent") or {})
    target_agent = str(snapshot_agent.get("agent_key") or snapshot_agent.get("agent_id") or "").strip()
    bindings = dict(snapshot.get("bindings") or {})
    bound_skills = [
        str(item.get("skill_key") or "").strip()
        for item in (bindings.get("skills") or [])
        if isinstance(item, dict) and item.get("enabled", 1) not in (0, False)
    ]
    snapshot_custom_skills = _strings(snapshot_agent.get("custom_skills")) or _strings(bound_skills)
    snapshot_skills = _strings(snapshot_agent.get("skills")) or list(snapshot_custom_skills)
    assets = [dict(item) for item in (snapshot.get("assets") or []) if isinstance(item, dict)]
    snapshot_manifest = copy.deepcopy(skill.get("checkpoint_manifest"))
    for index, current in enumerate(agents):
        agent_id = str(current.get("agent_id") or current.get("agent_key") or "")
        if agent_id != target_agent:
            continue
        merged = {**current}
        for source, target in (
            ("display_name", "display_name"),
            ("role_profile", "persona"),
            ("responsibility_scope", "review_scope"),
            ("excluded_scope", "exclusive_scope"),
            ("min_confidence", "min_confidence"),
            ("max_findings", "max_findings"),
            ("max_llm_calls", "max_llm_calls"),
            ("max_tool_calls", "max_tool_calls"),
        ):
            if source in snapshot_agent:
                if target in {"persona", "review_scope", "exclusive_scope"}:
                    applies_to = dict(merged.get("applies_to") or {})
                    applies_to[target] = snapshot_agent[source]
                    merged["applies_to"] = applies_to
                else:
                    merged[target] = snapshot_agent[source]
        custom_skills = list(snapshot_custom_skills)
        skills = list(snapshot_skills)
        manifests = copy.deepcopy(merged.get("skill_checkpoint_manifests") or {})
        if variant == "baseline":
            custom_skills = [item for item in custom_skills if item != target_skill]
            skills = [item for item in skills if item != target_skill]
            assets = [item for item in assets if str(item.get("skill_key") or target_skill) != target_skill]
            manifests.pop(target_skill, None)
        elif target_skill:
            if target_skill not in custom_skills:
                custom_skills.append(target_skill)
            if target_skill not in skills:
                skills.append(target_skill)
            for asset in assets:
                asset.setdefault("skill_key", target_skill)
            if isinstance(snapshot_manifest, dict):
                manifests[target_skill] = {
                    **snapshot_manifest,
                    "skill_key": str(snapshot_manifest.get("skill_key") or target_skill),
                    "skill_version": str(skill.get("version") or snapshot_manifest.get("skill_version") or ""),
                    "bundle_sha256": str(skill.get("bundle_sha256") or snapshot_manifest.get("bundle_sha256") or ""),
                }
        merged["custom_skills"] = custom_skills
        merged["skills"] = skills
        merged["skill_assets"] = assets
        merged["skill_checkpoint_manifests"] = manifests
        agents[index] = merged
        break
    return agents


def apply_snapshot_config(current: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(current)
    frozen = dict(snapshot.get("config") or {})
    for section in ("llm", "data_policy", "queue_policy", "review_quality"):
        if not isinstance(frozen.get(section), dict):
            continue
        existing = dict(result.get(section) or {})
        for key, value in frozen[section].items():
            if value == "<redacted>" or key.lower() in SENSITIVE_KEYS or key.lower().endswith(("_api_key", "_token", "_password", "_secret")):
                continue
            existing[key] = copy.deepcopy(value)
        result[section] = existing
    return result


def apply_debug_execution_controls(current: dict[str, Any], debug_context: dict[str, Any]) -> dict[str, Any]:
    """Apply trace/replay controls without forking the production review graph."""
    result = copy.deepcopy(current)
    if str(debug_context.get("kind") or "") != "skill_debug":
        return result
    replay = str(debug_context.get("llm_replay") or "record").strip().lower()
    if replay not in {"off", "record", "replay", "live_repeat"}:
        raise ValueError(f"unsupported skill debug llm replay mode: {replay}")
    llm = dict(result.get("llm") or {})
    llm["exchange_mode"] = replay
    # Exact replay payload persistence is opt-in and bounded by the debug-session TTL.
    llm["allow_exact_replay_storage"] = replay in {"record", "replay"}
    result["llm"] = llm
    result["_execution_controls"] = {
        "execution_kind": "skill_debug",
        "snapshot_mode": str(debug_context.get("snapshot_mode") or "frozen"),
        "trace_level": str(debug_context.get("trace_level") or "full"),
        "llm_replay": replay,
    }
    return result


def debug_skill_summary(debug_context: dict[str, Any], skill_key: str) -> str | None:
    snapshot = dict(debug_context.get("snapshot") or {})
    skill = dict(snapshot.get("skill") or {})
    if str(skill.get("skill_key") or "") != str(skill_key):
        return None
    parts = [str(skill.get("content") or "")]
    for asset in snapshot.get("assets") or []:
        if not isinstance(asset, dict) or str(asset.get("asset_path") or "") == "SKILL.md":
            continue
        parts.append(f"\n## {asset.get('asset_path')}\n{asset.get('content') or ''}")
    return "\n".join(parts).strip()


def check_debug_cancelled_or_timed_out(conn: Any, job: dict[str, Any], debug_context: dict[str, Any]) -> str | None:
    if not is_debug_job(job):
        return None
    session_id = str(job.get("debug_session_id") or debug_context.get("session_id") or "")
    if not session_id:
        return "missing_debug_session"
    row = conn.execute("SELECT status, created_at FROM skill_debug_sessions WHERE id = %s", (session_id,)).fetchone()
    if not row:
        return "missing_debug_session"
    if str(row["status"]) == "cancelled":
        return "cancelled"
    max_seconds = max(60, int(debug_context.get("max_duration_seconds") or 1800))
    created = row["created_at"]
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if created and (datetime.now(timezone.utc) - created).total_seconds() > max_seconds:
        conn.execute("UPDATE skill_debug_sessions SET status = 'timed_out', failure_reason = 'max_duration_exceeded', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (session_id,))
        conn.execute("UPDATE review_jobs SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE debug_session_id = %s AND status NOT IN ('no_issue','waiting_confirmation','cancelled','failed','dead_letter')", (session_id,))
        conn.commit()
        return "timed_out"
    return None


def load_debug_context(job: dict[str, Any] | Any) -> dict[str, Any]:
    try:
        value = job.get("debug_context_json") if hasattr(job, "get") else "{}"
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
