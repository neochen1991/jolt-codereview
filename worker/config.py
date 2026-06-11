from __future__ import annotations

import copy
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG: dict[str, Any] = {
    "llm": {
        "default_provider": "dashscope-openai-compatible",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "default_model": "MiniMax-M2.7",
        "default_api_key_env": None,
        "default_api_key": None,
        "request_timeout_seconds": 120,
        "max_output_tokens": 8192,
        "enable_stream": True,
    },
    "github": {
        "default_token_env": "GITHUB_TOKEN",
        "default_endpoint": "https://api.github.com",
    },
    "codehub": {
        "default_token_env": "CODEHUB_TOKEN",
        "default_endpoint": "",
    },
    "server": {
        "database_path": "data/jolt-codereview.sqlite",
        "database_driver": "sqlite",
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


def db_path(config: dict[str, Any]) -> Path:
    configured = config.get("server", {}).get("database_path", "data/jolt-codereview.sqlite")
    path = Path(configured)
    return path if path.is_absolute() else ROOT / path


def load_project_settings(conn: sqlite3.Connection, project_id: str) -> dict[str, dict[str, Any]]:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'project_settings'"
    ).fetchone()
    if not table:
        return {}
    rows = conn.execute(
        "SELECT settings_key, settings_json FROM project_settings WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    settings: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            settings[str(row["settings_key"])] = json.loads(row["settings_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            settings[str(row["settings_key"])] = {}
    return settings


def load_user_settings(conn: sqlite3.Connection, user_id: str | None) -> dict[str, dict[str, Any]]:
    if not user_id:
        return {}
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'user_settings'"
    ).fetchone()
    if not table:
        return {}
    rows = conn.execute(
        "SELECT settings_key, settings_json FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    settings: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            settings[str(row["settings_key"])] = json.loads(row["settings_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            settings[str(row["settings_key"])] = {}
    return settings


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


def effective_project_config(base_config: dict[str, Any], conn: sqlite3.Connection, project_id: str, user_id: str | None = None) -> dict[str, Any]:
    effective = copy.deepcopy(base_config)
    settings = load_project_settings(conn, project_id)
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
