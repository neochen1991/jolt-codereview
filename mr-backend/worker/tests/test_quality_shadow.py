from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quality_shadow import (  # type: ignore[import-not-found]
    apply_shadow_execution_controls,
    artifact_sha256,
    complete_shadow_pair,
    enqueue_v1_shadow_pair,
    load_shadow_input_artifact,
    shadow_baseline_job_id,
    shadow_pair_id,
    should_auto_enqueue_baseline,
    should_capture_review_input,
    validate_frozen_input_artifact,
)
from config import DEFAULT_CONFIG, normalize_review_quality_config


class FakeConnection:
    def __init__(self, row: dict | None):
        self.row = row
        self.params = None

    def execute(self, _sql: str, params: tuple):
        self.params = params
        return self

    def fetchone(self):
        return self.row


class PairConnection:
    def __init__(self, snapshot: dict | None = None):
        self.snapshot = snapshot
        self.calls: list[tuple[str, tuple]] = []
        self.commits = 0
        self.rowcount = 1

    def execute(self, sql: str, params: tuple = ()):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self.snapshot

    def commit(self):
        self.commits += 1


def frozen_artifact() -> dict:
    return {
        "version": "review_input_v1",
        "head_sha": "head-123",
        "files": [{"filename": "src/A.java", "patch": "@@ -1 +1 @@\n-old\n+new"}],
        "source_file_contents": {"src/A.java": "class A {}"},
    }


def test_artifact_hash_is_canonical_and_tampering_is_rejected() -> None:
    artifact = frozen_artifact()
    reordered = {
        "source_file_contents": artifact["source_file_contents"],
        "files": artifact["files"],
        "head_sha": artifact["head_sha"],
        "version": artifact["version"],
    }
    digest = artifact_sha256(artifact)
    assert digest == artifact_sha256(reordered)
    assert validate_frozen_input_artifact(artifact, digest, "head-123") == artifact

    tampered = {**artifact, "source_file_contents": {"src/A.java": "class B {}"}}
    try:
        validate_frozen_input_artifact(tampered, digest, "head-123")
    except ValueError as exc:
        assert "sha256" in str(exc)
    else:
        raise AssertionError("tampered Shadow input must be rejected")


def test_shadow_config_only_overrides_context_engine() -> None:
    configured = {
        "llm": {"default_model": "model-a", "exchange_mode": "record"},
        "review_quality": {
            "context_engine": "v1",
            "semantic_index": "tree_sitter",
            "llm_replay": "record",
            "quality_shadow_mode": True,
        },
    }
    result = apply_shadow_execution_controls(configured, {"execution_kind": "quality_shadow_v2"})
    assert result["review_quality"] == {
        "context_engine": "v2",
        "semantic_index": "tree_sitter",
        "llm_replay": "record",
        "quality_shadow_mode": True,
    }
    assert result["llm"] == configured["llm"]
    assert result["_execution_controls"]["publish_allowed"] is False


def test_capture_requires_production_job_and_explicit_opt_in() -> None:
    enabled = {"review_quality": {"quality_shadow_mode": True}}
    disabled = {"review_quality": {"quality_shadow_mode": False}}
    assert should_capture_review_input(enabled, {"execution_kind": "production_review"}) is True
    assert should_capture_review_input(disabled, {"execution_kind": "production_review"}) is False
    assert should_capture_review_input(enabled, {"execution_kind": "quality_shadow_v1"}) is False
    assert should_capture_review_input(enabled, {"execution_kind": "skill_debug_candidate"}) is False


def test_production_defaults_switch_to_v2_with_validation_guards() -> None:
    quality = normalize_review_quality_config(DEFAULT_CONFIG)
    assert quality["context_engine"] == "v2"
    assert quality["quality_shadow_mode"] is True
    assert quality["auto_shadow_baseline"] is True
    assert quality["auto_rollback_enabled"] is True
    assert quality["minimum_distinct_mrs"] == 30


def test_shadow_pair_ids_are_deterministic_and_baseline_specific() -> None:
    pair_id = shadow_pair_id("project-1", "mr-1", "head-1", "a" * 64)
    assert pair_id == shadow_pair_id("project-1", "mr-1", "head-1", "a" * 64)
    assert pair_id != shadow_pair_id("project-1", "mr-1", "head-2", "a" * 64)
    assert pair_id.startswith("qpair_")
    assert shadow_baseline_job_id(pair_id).startswith("qshadow_v1_")


def test_only_successful_production_v2_auto_enqueues_baseline() -> None:
    config = {"review_quality": {"context_engine": "v2", "quality_shadow_mode": True, "auto_shadow_baseline": True}}
    production = {"execution_kind": "production_review"}
    assert should_auto_enqueue_baseline(config, production, "waiting_confirmation") is True
    assert should_auto_enqueue_baseline(config, production, "no_issue") is True
    assert should_auto_enqueue_baseline(config, production, "failed") is False
    assert should_auto_enqueue_baseline(config, {"execution_kind": "quality_shadow_v1"}, "no_issue") is False
    assert should_auto_enqueue_baseline({"review_quality": {**config["review_quality"], "context_engine": "v1"}}, production, "no_issue") is False


def test_enqueue_v1_shadow_pair_reuses_production_snapshot() -> None:
    snapshot = {"id": "snapshot-1", "artifact_sha256": "a" * 64}
    conn = PairConnection(snapshot)
    result = enqueue_v1_shadow_pair(
        conn,
        project_config={"review_quality": {"context_engine": "v2", "quality_shadow_mode": True, "auto_shadow_baseline": True}},
        project_id="project-1",
        job={"id": "job-v2", "merge_request_id": "mr-1", "head_sha": "head-1", "execution_kind": "production_review", "requested_effort_level": "standard", "requested_by": "user-1"},
        run_id="run-v2",
        status="waiting_confirmation",
    )
    assert result["status"] == "baseline_queued"
    assert result["input_snapshot_id"] == "snapshot-1"
    assert result["input_artifact_sha256"] == "a" * 64
    assert any("INSERT INTO review_quality_shadow_pairs" in sql for sql, _ in conn.calls)
    assert any("quality_shadow_v1" in params for _sql, params in conn.calls)
    assert conn.commits == 1


def test_shadow_completion_updates_pair_by_context_reference() -> None:
    conn = PairConnection()
    job = {
        "execution_kind": "quality_shadow_v1",
        "debug_context_json": json.dumps({"quality_shadow_pair_id": "qpair-1"}),
    }
    assert complete_shadow_pair(conn, job=job, run_id="run-v1", status="no_issue") is True
    sql, params = conn.calls[-1]
    assert "UPDATE review_quality_shadow_pairs" in sql
    assert params == ("run-v1", "completed", "qpair-1")
    assert conn.commits == 1


def test_load_shadow_input_validates_reference_head_hash_and_expiry() -> None:
    artifact = frozen_artifact()
    digest = artifact_sha256(artifact)
    row = {
        "artifact_json": json.dumps(artifact),
        "artifact_sha256": digest,
        "merge_request_id": "mr-1",
        "head_sha": "head-123",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    conn = FakeConnection(row)
    job = {
        "execution_kind": "quality_shadow_v1",
        "merge_request_id": "mr-1",
        "head_sha": "head-123",
        "debug_context_json": json.dumps({"input_snapshot_id": "snapshot-1", "input_artifact_sha256": digest}),
    }
    loaded = load_shadow_input_artifact(conn, job)
    assert loaded["input_artifact_sha256"] == digest
    assert conn.params == ("snapshot-1",)

    expired = {**row, "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    try:
        load_shadow_input_artifact(FakeConnection(expired), job)
    except ValueError as exc:
        assert "expired" in str(exc)
    else:
        raise AssertionError("expired Shadow input must be rejected")


def test_runtime_and_schema_wire_frozen_input_callbacks() -> None:
    root = Path(__file__).resolve().parents[3]
    runtime = (root / "mr-backend/worker/review_runtime.py").read_text("utf-8")
    finalize = (root / "mr-backend/worker/orchestration/nodes/finalize.py").read_text("utf-8")
    migrations = (root / "mr-backend/src/backend/db/migrations.ts").read_text("utf-8")
    job_repository = (root / "mr-backend/src/backend/repositories/ReviewJobRepository.ts").read_text("utf-8")
    assert "CREATE TABLE IF NOT EXISTS review_input_snapshots" in migrations
    assert "save_review_input_snapshot" in runtime
    assert "load_shadow_input_artifact" in runtime
    assert "apply_shadow_execution_controls" in runtime
    assert "recorder = Recorder(conn, run_id, config=project_config)" in runtime
    assert "shadow_input_validation_failed" in runtime
    assert "CREATE TABLE IF NOT EXISTS review_quality_shadow_pairs" in migrations
    assert "CREATE TABLE IF NOT EXISTS review_quality_shadow_pairs" in runtime
    assert "enqueue_v1_shadow_pair" in finalize
    assert "complete_shadow_pair" in finalize
    assert "complete_shadow_pair(conn, job=job, run_id=run_id, status=job_status" in runtime
    supersede_body = job_repository.split("supersedeQueued", 1)[1].split("cancelQueued", 1)[0]
    assert "execution_kind = 'production_review'" in supersede_body


if __name__ == "__main__":
    test_artifact_hash_is_canonical_and_tampering_is_rejected()
    test_shadow_config_only_overrides_context_engine()
    test_capture_requires_production_job_and_explicit_opt_in()
    test_production_defaults_switch_to_v2_with_validation_guards()
    test_shadow_pair_ids_are_deterministic_and_baseline_specific()
    test_only_successful_production_v2_auto_enqueues_baseline()
    test_enqueue_v1_shadow_pair_reuses_production_snapshot()
    test_shadow_completion_updates_pair_by_context_reference()
    test_load_shadow_input_validates_reference_head_hash_and_expiry()
    test_runtime_and_schema_wire_frozen_input_callbacks()
