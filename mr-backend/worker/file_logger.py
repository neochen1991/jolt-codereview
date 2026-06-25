from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BEIJING_TZ = timezone(timedelta(hours=8))


def _logging_config(config: dict[str, Any] | None) -> dict[str, Any]:
    logging = (config or {}).get("logging") or {}
    return {
        "enabled": logging.get("enabled", True),
        "dir": logging.get("dir") or "logs",
        "worker_file": logging.get("worker_file") or "jolt-worker.log",
        "review_run_dir": logging.get("review_run_dir") or "review-runs",
    }


def _resolve_dir(config: dict[str, Any] | None) -> Path:
    logging = _logging_config(config)
    configured = Path(str(logging["dir"]))
    return configured if configured.is_absolute() else ROOT / configured


def beijing_iso_timestamp() -> str:
    return datetime.now(BEIJING_TZ).isoformat()


def clear_worker_logs(config: dict[str, Any] | None) -> None:
    logging = _logging_config(config)
    if not logging["enabled"]:
        return
    log_dir = _resolve_dir(config)
    for target in [
        log_dir / str(logging["worker_file"]),
        log_dir / str(logging["review_run_dir"]),
    ]:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)


def _redact(key: str, value: Any) -> Any:
    if value is None:
        return value
    normalized = key.lower()
    sensitive_keys = {"token", "access_token", "refresh_token", "api_key", "apikey", "secret", "authorization", "password"}
    if normalized in sensitive_keys or re.search(r"(^|_)(api[_-]?key|secret|authorization|password)$", normalized):
        return "<redacted>"
    return value


def _sanitize(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact(key, value) for key, value in fields.items()}


def write_worker_log(config: dict[str, Any] | None, event: str, fields: dict[str, Any] | None = None, level: str = "info") -> None:
    logging = _logging_config(config)
    if not logging["enabled"]:
        return
    log_dir = _resolve_dir(config)
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": beijing_iso_timestamp(),
        "service": "jolt-worker",
        "level": level,
        "event": event,
        **_sanitize(fields or {}),
    }
    with (log_dir / str(logging["worker_file"])).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def write_review_run_log(config: dict[str, Any] | None, run_id: str, event: str, fields: dict[str, Any] | None = None, level: str = "info") -> None:
    logging = _logging_config(config)
    if not logging["enabled"]:
        return
    run_dir = _resolve_dir(config) / str(logging["review_run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": beijing_iso_timestamp(),
        "service": "jolt-worker",
        "level": level,
        "event": event,
        "review_run_id": run_id,
        **_sanitize(fields or {}),
    }
    with (run_dir / f"{run_id}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
