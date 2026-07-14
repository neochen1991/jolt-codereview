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


def shadow_pair_id(project_id: str, merge_request_id: str, head_sha: str, artifact_digest: str) -> str:
    identity = "|".join([str(project_id), str(merge_request_id), str(head_sha), str(artifact_digest)])
    return f"qpair_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"


def shadow_baseline_job_id(pair_id: str) -> str:
    return f"qshadow_v1_{hashlib.sha256(str(pair_id).encode('utf-8')).hexdigest()[:28]}"


def should_auto_enqueue_baseline(
    project_config: dict[str, Any],
    job: dict[str, Any] | Any,
    status: str,
) -> bool:
    kind = str((job.get("execution_kind") if hasattr(job, "get") else "") or "production_review")
    quality = project_config.get("review_quality") if isinstance(project_config.get("review_quality"), dict) else {}
    return (
        kind == "production_review"
        and str(quality.get("context_engine") or "v2") == "v2"
        and bool(quality.get("quality_shadow_mode", True))
        and bool(quality.get("auto_shadow_baseline", True))
        and str(status) in {"waiting_confirmation", "no_issue"}
    )


def _job_context(job: dict[str, Any] | Any) -> dict[str, Any]:
    try:
        value = job.get("debug_context_json") if hasattr(job, "get") else "{}"
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def enqueue_v1_shadow_pair(
    conn: Any,
    *,
    project_config: dict[str, Any],
    project_id: str,
    job: dict[str, Any] | Any,
    run_id: str,
    status: str,
    commit: bool = True,
) -> dict[str, Any]:
    if not should_auto_enqueue_baseline(project_config, job, status):
        return {"status": "not_eligible"}
    snapshot = conn.execute(
        """
        SELECT id, artifact_sha256
        FROM review_input_snapshots
        WHERE source_review_run_id = %s
        """,
        (run_id,),
    ).fetchone()
    merge_request_id = str(job.get("merge_request_id") or "")
    head_sha = str(job.get("head_sha") or "")
    if not snapshot:
        pair_id = shadow_pair_id(project_id, merge_request_id, head_sha, run_id)
        conn.execute(
            """
            INSERT INTO review_quality_shadow_pairs (
              id, project_id, merge_request_id, head_sha,
              production_job_id, production_run_id, status, failure_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, 'validation_input_missing', 'snapshot_not_found')
            ON CONFLICT (production_run_id) DO NOTHING
            """,
            (pair_id, project_id, merge_request_id, head_sha, str(job.get("id") or ""), run_id),
        )
        if commit:
            conn.commit()
        return {"status": "validation_input_missing", "pair_id": pair_id}

    snapshot_id = str(snapshot["id"])
    artifact_digest = str(snapshot["artifact_sha256"])
    pair_id = shadow_pair_id(project_id, merge_request_id, head_sha, artifact_digest)
    baseline_job_id = shadow_baseline_job_id(pair_id)
    context = json.dumps(
        {
            "kind": "review_quality_auto_shadow",
            "quality_shadow_pair_id": pair_id,
            "input_snapshot_id": snapshot_id,
            "input_artifact_sha256": artifact_digest,
            "publish_allowed": False,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    conn.execute(
        """
        INSERT INTO review_quality_shadow_pairs (
          id, project_id, merge_request_id, head_sha, input_snapshot_id,
          input_artifact_sha256, production_job_id, production_run_id,
          baseline_job_id, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'baseline_queued')
        ON CONFLICT (production_run_id) DO NOTHING
        """,
        (
            pair_id,
            project_id,
            merge_request_id,
            head_sha,
            snapshot_id,
            artifact_digest,
            str(job.get("id") or ""),
            run_id,
            baseline_job_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO review_jobs (
          id, merge_request_id, head_sha, status, priority,
          requested_effort_level, requested_by, debug_context_json, execution_kind
        ) VALUES (%s, %s, %s, 'queued', -100, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            baseline_job_id,
            merge_request_id,
            head_sha,
            str(job.get("requested_effort_level") or "standard"),
            str(job.get("requested_by") or "review-quality-auto-shadow"),
            context,
            "quality_shadow_v1",
        ),
    )
    if commit:
        conn.commit()
    return {
        "status": "baseline_queued",
        "pair_id": pair_id,
        "baseline_job_id": baseline_job_id,
        "input_snapshot_id": snapshot_id,
        "input_artifact_sha256": artifact_digest,
    }


def complete_shadow_pair(
    conn: Any,
    *,
    job: dict[str, Any] | Any,
    run_id: str,
    status: str,
    commit: bool = True,
) -> bool:
    if not is_shadow_job(job):
        return False
    pair_id = str(_job_context(job).get("quality_shadow_pair_id") or "")
    if not pair_id:
        return False
    pair_status = "completed" if str(status) in {"waiting_confirmation", "no_issue"} else "failed"
    conn.execute(
        """
        UPDATE review_quality_shadow_pairs
        SET baseline_run_id = %s, status = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (run_id, pair_status, pair_id),
    )
    if commit:
        conn.commit()
    return True


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
