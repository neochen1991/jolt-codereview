from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from skill_debug import is_shadow_job, shadow_context_engine


def _canonical_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in artifact.items() if key != "input_artifact_sha256"}


def canonical_artifact_json(artifact: dict[str, Any]) -> str:
    return json.dumps(_canonical_artifact(artifact), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def artifact_sha256(artifact: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_artifact_json(artifact).encode("utf-8")).hexdigest()


def validate_frozen_input_artifact(
    artifact: dict[str, Any],
    expected_sha256: str,
    expected_head_sha: str,
) -> dict[str, Any]:
    if str(artifact.get("version") or "") != "review_input_v1":
        raise ValueError("unsupported Shadow input artifact version")
    if str(artifact.get("head_sha") or "") != str(expected_head_sha):
        raise ValueError("Shadow input head_sha mismatch")
    actual_sha256 = artifact_sha256(artifact)
    if not expected_sha256 or actual_sha256 != str(expected_sha256):
        raise ValueError("Shadow input artifact sha256 mismatch")
    if not isinstance(artifact.get("files"), list) or not isinstance(artifact.get("source_file_contents"), dict):
        raise ValueError("Shadow input artifact is incomplete")
    return _canonical_artifact(artifact)


def apply_shadow_execution_controls(current: dict[str, Any], job: dict[str, Any] | Any) -> dict[str, Any]:
    engine = shadow_context_engine(job)
    if engine is None:
        return copy.deepcopy(current)
    result = copy.deepcopy(current)
    review_quality = dict(result.get("review_quality") or {})
    review_quality["context_engine"] = engine
    result["review_quality"] = review_quality
    result["_execution_controls"] = {
        "execution_kind": str(job.get("execution_kind") or ""),
        "snapshot_mode": "frozen",
        "publish_allowed": False,
    }
    return result


def should_capture_review_input(project_config: dict[str, Any], job: dict[str, Any] | Any) -> bool:
    kind = str((job.get("execution_kind") if hasattr(job, "get") else "") or "production_review")
    review_quality = project_config.get("review_quality") if isinstance(project_config.get("review_quality"), dict) else {}
    return kind == "production_review" and bool(review_quality.get("quality_shadow_mode", False))


def _as_utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_shadow_input_artifact(conn: Any, job: dict[str, Any] | Any) -> dict[str, Any] | None:
    if not is_shadow_job(job):
        return None
    try:
        context_value = job.get("debug_context_json") if hasattr(job, "get") else "{}"
        context = json.loads(str(context_value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Shadow job context") from exc
    snapshot_id = str(context.get("input_snapshot_id") or "")
    expected_sha256 = str(context.get("input_artifact_sha256") or "")
    if not snapshot_id or not expected_sha256:
        raise ValueError("Shadow job is missing frozen input reference")
    row = conn.execute(
        """
        SELECT merge_request_id, head_sha, artifact_json, artifact_sha256, expires_at
        FROM review_input_snapshots
        WHERE id = %s
        """,
        (snapshot_id,),
    ).fetchone()
    if not row:
        raise ValueError("Shadow input snapshot not found")
    if str(row["merge_request_id"]) != str(job.get("merge_request_id") or ""):
        raise ValueError("Shadow input merge_request_id mismatch")
    if str(row["head_sha"]) != str(job.get("head_sha") or ""):
        raise ValueError("Shadow input head_sha mismatch")
    expires_at = _as_utc(row["expires_at"])
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        raise ValueError("Shadow input snapshot expired")
    row_sha256 = str(row["artifact_sha256"] or "")
    if row_sha256 != expected_sha256:
        raise ValueError("Shadow input reference sha256 mismatch")
    try:
        artifact = json.loads(str(row["artifact_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Shadow input artifact JSON is invalid") from exc
    validated = validate_frozen_input_artifact(artifact, row_sha256, str(job.get("head_sha") or ""))
    return {**validated, "input_artifact_sha256": row_sha256, "input_snapshot_id": snapshot_id}


def save_review_input_snapshot(
    conn: Any,
    *,
    snapshot_id: str,
    source_review_job_id: str,
    source_review_run_id: str,
    merge_request_id: str,
    head_sha: str,
    artifact: dict[str, Any],
    retention_hours: int = 72,
) -> dict[str, Any]:
    normalized = {**_canonical_artifact(artifact), "version": "review_input_v1", "head_sha": str(head_sha)}
    canonical = canonical_artifact_json(normalized)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=max(1, min(int(retention_hours), 168)))
    conn.execute(
        """
        INSERT INTO review_input_snapshots (
          id, source_review_job_id, source_review_run_id, merge_request_id,
          head_sha, artifact_json, artifact_sha256, expires_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_review_run_id) DO NOTHING
        """,
        (
            snapshot_id,
            source_review_job_id,
            source_review_run_id,
            merge_request_id,
            str(head_sha),
            canonical,
            digest,
            expires_at,
        ),
    )
    conn.commit()
    return {
        **normalized,
        "input_snapshot_id": snapshot_id,
        "input_artifact_sha256": digest,
        "expires_at": expires_at.isoformat(),
    }
