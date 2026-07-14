from __future__ import annotations

import copy
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG: dict[str, Any] = {
    "github": {
        "default_token_env": "GITHUB_TOKEN",
        "default_endpoint": "https://api.github.com",
    },
    "codehub": {
        "default_token_env": "CODEHUB_TOKEN",
        "default_endpoint": "",
    },
    "server": {
        "database_driver": "postgres",
        "postgres_url": "",
        "postgres_user": "",
        "postgres_password": "",
        "postgres_query_timeout_seconds": 120,
    },
    "logging": {
        "enabled": True,
        "dir": "logs",
        "api_file": "jolt-api.log",
        "worker_file": "jolt-worker.log",
        "review_run_dir": "review-runs",
    },
    "budget_policy": {
        "efforts": {
            "standard": {
                "max_llm_calls": 80,
                "max_wall_seconds": 1800,
                "max_output_tokens": 16000,
                "max_findings": 80,
            },
            "deep": {
                "max_llm_calls": 120,
                "max_wall_seconds": 2400,
                "max_output_tokens": 24000,
                "max_findings": 120,
            },
        },
    },
    "review_policy": {
        "max_added_lines_per_mr": 2000,
    },
    "review_quality": {
        "context_engine": "v2",
        "semantic_index": "tree_sitter",
        "llm_replay": "record",
        "quality_shadow_mode": True,
        "auto_shadow_baseline": True,
        "auto_rollback_enabled": True,
        "minimum_distinct_mrs": 30,
        "gold_dataset_path": "evaluation/production_review_quality_gold.jsonl",
    },
    "agent_policy": {
        "deepagents": {
            "enabled": False,
            "enable_for_deep_effort": True,
            "enable_for_required_agents": True,
            "enable_for_skill_bundle": True,
        },
    },
    "queue_policy": {
        "poll_interval_seconds": 300,
        "max_concurrency": 1,
        "max_attempts": 3,
        "heartbeat_timeout_seconds": 600,
    },
    "token_usage": {
        "enabled": False,
        "endpoint": "",
        "method": "POST",
        "timeout_seconds": 10,
        "auth_header": "Authorization",
        "auth_token_env": None,
        "auth_token": None,
        "employee_no_env": "JOLT_REPORTER_EMPLOYEE_NO",
        "default_employee_no": "system",
        "service_name": "jolt-codereview",
    },
}

SETTINGS_TO_CONFIG = {
    "llm_policy": "llm",
    "review_policy": "review_policy",
    "budget_policy": "budget_policy",
    "agent_policy": "agent_policy",
    "tool_policy": "tool_policy",
    "queue_policy": "queue_policy",
    "publish_policy": "publish_policy",
    "data_policy": "data_policy",
    "token_usage": "token_usage",
    "review_quality": "review_quality",
}

VCS_POLICY_KEY = "vcs_policy"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config() -> dict[str, Any]:
    explicit = os.environ.get("CONFIG_PATH")
    config_path = Path(explicit) if explicit else ROOT / "config.json"
    config = copy.deepcopy(DEFAULT_CONFIG)
    if config_path.exists():
        user_config = json.loads(config_path.read_text("utf-8"))
        config = deep_merge(config, user_config)
    return config


def normalize_review_quality_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("review_quality") if isinstance(config.get("review_quality"), dict) else {}
    result = {
        "context_engine": str(raw.get("context_engine") or "v2"),
        "semantic_index": str(raw.get("semantic_index") or "tree_sitter"),
        "llm_replay": str(raw.get("llm_replay") or "record"),
        "quality_shadow_mode": bool(raw.get("quality_shadow_mode", True)),
        "auto_shadow_baseline": bool(raw.get("auto_shadow_baseline", True)),
        "auto_rollback_enabled": bool(raw.get("auto_rollback_enabled", True)),
        "minimum_distinct_mrs": max(30, int(raw.get("minimum_distinct_mrs") or 30)),
        "gold_dataset_path": str(raw.get("gold_dataset_path") or "evaluation/production_review_quality_gold.jsonl"),
    }
    allowed = {
        "context_engine": {"v1", "v2"},
        "semantic_index": {"regex", "tree_sitter", "typed"},
        "llm_replay": {"off", "record", "replay", "live_repeat"},
    }
    for key, values in allowed.items():
        if result[key] not in values:
            raise ValueError(f"unsupported review_quality.{key}: {result[key]}")
    return result


def common_base_url(config: dict[str, Any]) -> str:
    configured = os.environ.get("COMMON_API_BASE") or os.environ.get("VITE_COMMON_API_BASE")
    if configured:
        return configured.rstrip("/")
    server = config.get("server") or {}
    host = server.get("host") or "127.0.0.1"
    port = server.get("common_port") or 9022
    return f"http://{host}:{port}"


def internal_service_token() -> str:
    return os.environ.get("JOLT_INTERNAL_SERVICE_TOKEN", "").strip()


def common_get_json(config: dict[str, Any], path: str, query: dict[str, str]) -> dict[str, Any]:
    token = internal_service_token()
    if not token:
        raise RuntimeError("JOLT_INTERNAL_SERVICE_TOKEN is required for worker/common API communication")
    encoded = urllib.parse.urlencode(query)
    url = f"{common_base_url(config)}{path}"
    if encoded:
        url = f"{url}?{encoded}"
    request = urllib.request.Request(url, headers={"x-internal-service-token": token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"common API {path} failed: {exc.code} {detail}") from exc
    return json.loads(body or "{}")


def load_user_settings(config: dict[str, Any], user_id: str | None) -> dict[str, dict[str, Any]]:
    if not user_id:
        return {}
    payload = common_get_json(config, "/internal/auth/introspect", {"user_id": user_id})
    settings = payload.get("settings") or {}
    return {
        str(key): value if isinstance(value, dict) else {}
        for key, value in settings.items()
    }


def apply_project_vcs_policy(effective: dict[str, Any], settings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    vcs_policy = settings.get(VCS_POLICY_KEY) or {}
    if not vcs_policy:
        return effective
    github_patch: dict[str, Any] = {}
    codehub_patch: dict[str, Any] = {}
    if vcs_policy.get("github_token"):
        github_patch["default_token"] = vcs_policy.get("github_token")
    if vcs_policy.get("github_token_env"):
        github_patch["default_token_env"] = vcs_policy.get("github_token_env")
    if vcs_policy.get("github_endpoint"):
        github_patch["default_endpoint"] = vcs_policy.get("github_endpoint")
    if vcs_policy.get("codehub_token"):
        codehub_patch["default_token"] = vcs_policy.get("codehub_token")
    if vcs_policy.get("codehub_token_env"):
        codehub_patch["default_token_env"] = vcs_policy.get("codehub_token_env")
    if vcs_policy.get("codehub_endpoint"):
        codehub_patch["default_endpoint"] = vcs_policy.get("codehub_endpoint")
    if github_patch:
        effective["github"] = deep_merge(effective.get("github") or {}, github_patch)
    if codehub_patch:
        effective["codehub"] = deep_merge(effective.get("codehub") or {}, codehub_patch)
    return effective


def effective_project_config(base_config: dict[str, Any], conn: Any, project_id: str, user_id: str | None = None) -> dict[str, Any]:
    effective = copy.deepcopy(base_config)
    payload = common_get_json(base_config, "/internal/models/effective-config", {"project_id": project_id})
    common_effective = payload.get("effective_config") if isinstance(payload.get("effective_config"), dict) else {}
    common_llm = common_effective.get("llm") if isinstance(common_effective.get("llm"), dict) else payload.get("llm")
    if isinstance(common_llm, dict) and common_llm:
        effective["llm"] = copy.deepcopy(common_llm)
    effective["_project_id"] = project_id
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    raw_settings = source.get("project_settings") if isinstance(source.get("project_settings"), dict) else {}
    settings = {
        str(key): value if isinstance(value, dict) else {}
        for key, value in raw_settings.items()
    }
    for settings_key, config_key in SETTINGS_TO_CONFIG.items():
        value = settings.get(settings_key) or {}
        if not value:
            continue
        if isinstance(effective.get(config_key), dict):
            effective[config_key] = deep_merge(effective[config_key], value)
        else:
            effective[config_key] = copy.deepcopy(value)
    effective = apply_project_vcs_policy(effective, settings)
    effective["_project_settings"] = settings
    return effective
