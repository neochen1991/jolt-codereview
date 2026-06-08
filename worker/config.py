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
    },
    "logging": {
        "enabled": True,
        "dir": "logs",
        "api_file": "jolt-api.log",
        "worker_file": "jolt-worker.log",
        "review_run_dir": "review-runs",
    },
}

SETTINGS_TO_CONFIG = {
    "llm_policy": "llm",
    "review_policy": "review_policy",
    "agent_policy": "agent_policy",
    "tool_policy": "tool_policy",
    "queue_policy": "queue_policy",
    "publish_policy": "publish_policy",
    "data_policy": "data_policy",
}


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


def effective_project_config(base_config: dict[str, Any], conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
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
    effective["_project_settings"] = settings
    return effective
