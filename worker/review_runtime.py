#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import uuid4

from config import db_path, effective_project_config, load_config
from file_logger import write_review_run_log, write_worker_log
from agents.registry import load_expert_profiles
from context.repo_index import build_repo_index
from context.snapshot import build_code_context_snapshot
from context.symbol_resolver import resolve_diff_symbols
from diff.slicer import build_diff_slices, diff_hunks_by_file, extract_added_lines, source_snippet_loader_for_files
from llm.client import call_llm, chat_completions_url, http_json, normalize_confidence, normalize_line_number, parse_llm_findings, summarize_pr_with_llm
from llm_router import candidate_providers
from orchestration.graph import invoke_review_graph
from orchestration.nodes.build_context import make_build_context_node
from orchestration.nodes.choose_effort import make_choose_effort_node
from orchestration.nodes.detect_conflicts import detect_conflicts, make_detect_conflicts_node
from orchestration.nodes.fetch_mr import make_fetch_mr_node
from orchestration.nodes.finalize import make_finalize_node
from orchestration.nodes.judge_findings import judge_candidate_findings, make_judge_findings_node
from orchestration.nodes.prescan import make_prescan_node
from orchestration.nodes.route_agents import make_route_agents_node
from orchestration.nodes.run_experts import make_run_experts_node
from orchestration.nodes.run_targeted_debate import run_targeted_debate, make_run_targeted_debate_node
from orchestration.nodes.summarize_pr import make_summarize_pr_node
from orchestration.nodes.verify_findings import rejected_reason_counts, verify_candidate_findings, make_verify_findings_node
from orchestration.state import EXECUTED_GRAPH_NODE_KEYS as GRAPH_NODE_KEYS
from review_queue.job_consumer import MAX_ATTEMPTS, RECLAIM_AFTER_SECONDS, start_heartbeat
from prompts.builder import build_prompt, redact_untrusted
from rules.rule_loader import load_bound_rules
from static.heuristics import static_findings
from tools.gateway import ToolGateway
from tools.java_report_tool import parse_external_report_payload
from tools.java_web_static_tool import scan_java_web_files
from tools.registry import findings_to_observations, load_tool_observations, save_tool_observations
from tools.tree_sitter_tool import build_graph as build_tree_sitter_graph
from tools.tool_normalizer import CATEGORY_PRIMARY_RULE, RULE_CATEGORY_MAP, canonical_rule_id, dedupe_tool_findings, line_bucket, normalize_tool_finding, normalized_rule_category

ROOT = Path(__file__).resolve().parents[1]
STATIC_RULES_DIR = ROOT / "config" / "static-rules"
BUILTIN_SEMGREP_REGISTRY_CONFIGS = ["p/java", "p/security-audit", "p/secrets", "p/owasp-top-ten"]
BUILTIN_PMD_RULESETS = [
    "category/java/bestpractices.xml",
    "category/java/errorprone.xml",
    "category/java/security.xml",
    "category/java/performance.xml",
]


def connect(config: dict[str, Any]) -> sqlite3.Connection:
    path = db_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    ensure_worker_schema(conn)
    return conn


def ensure_worker_schema(conn: sqlite3.Connection) -> None:
    def add_column_if_missing(table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            return
        if any(row["name"] == column for row in rows):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    add_column_if_missing("review_findings", "covered_rules_json", "TEXT NOT NULL DEFAULT '[]'")
    add_column_if_missing("review_findings", "skipped_rules_json", "TEXT NOT NULL DEFAULT '[]'")
    add_column_if_missing("review_findings", "suggested_code", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing("review_findings", "tool_provenance_json", "TEXT NOT NULL DEFAULT '[]'")
    add_column_if_missing("review_findings", "source_observations_json", "TEXT NOT NULL DEFAULT '[]'")
    add_column_if_missing("review_findings", "quality_trace_json", "TEXT NOT NULL DEFAULT '{}'")
    add_column_if_missing("review_jobs", "pr_summary", "TEXT NOT NULL DEFAULT '{}'")
    add_column_if_missing("review_runs", "coverage_json", "TEXT NOT NULL DEFAULT '{}'")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mr_finding_history (
          id TEXT PRIMARY KEY,
          merge_request_id TEXT NOT NULL REFERENCES merge_requests(id),
          dedupe_hash TEXT NOT NULL,
          finding_id TEXT,
          first_seen_head_sha TEXT NOT NULL,
          last_seen_head_sha TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          resolved_in_commit TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(merge_request_id, dedupe_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_mr_finding_history_mr_status
          ON mr_finding_history(merge_request_id, status);
        CREATE TABLE IF NOT EXISTS rule_precision_history (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL REFERENCES projects(id),
          agent_id TEXT NOT NULL,
          rule_id TEXT NOT NULL,
          accepted_count INTEGER NOT NULL DEFAULT 0,
          rejected_count INTEGER NOT NULL DEFAULT 0,
          auto_suppress INTEGER NOT NULL DEFAULT 0,
          last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(project_id, agent_id, rule_id)
        );
        CREATE INDEX IF NOT EXISTS idx_rule_precision_project_agent
          ON rule_precision_history(project_id, agent_id);
        CREATE TABLE IF NOT EXISTS custom_skills (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          skill_key TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL,
          version TEXT NOT NULL DEFAULT 'v1',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(project_id, skill_key)
        );
        CREATE TABLE IF NOT EXISTS custom_skill_assets (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          skill_key TEXT NOT NULL,
          asset_path TEXT NOT NULL,
          asset_type TEXT NOT NULL DEFAULT 'reference',
          content TEXT NOT NULL,
          executable INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(project_id, skill_key, asset_path)
        );
        CREATE TABLE IF NOT EXISTS expert_skill_bindings (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          agent_key TEXT NOT NULL,
          skill_key TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 100,
          enabled INTEGER NOT NULL DEFAULT 1,
          UNIQUE(project_id, agent_key, skill_key)
        );
        """
    )
    conn.commit()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class ChangedFile:
    filename: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str

    def to_record(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "changes": self.changes,
            "patch": self.patch,
        }


class Recorder:
    def __init__(self, conn: sqlite3.Connection, run_id: str, max_batch: int = 200, config: dict[str, Any] | None = None):
        self.conn = conn
        self.run_id = run_id
        self.max_batch = max_batch
        self.config = config
        self.pending_writes = 0
        self.flush_count = 0

    def _file_log(self, event: str, fields: dict[str, Any] | None = None, level: str = "info") -> None:
        if not self.config:
            return
        payload = {"review_run_id": self.run_id, **(fields or {})}
        try:
            write_worker_log(self.config, event, payload, level)
            write_review_run_log(self.config, self.run_id, event, fields or {}, level)
        except OSError:
            pass

    def _mark_write(self, force: bool = False) -> None:
        self.pending_writes += 1
        if force or self.pending_writes >= self.max_batch:
            self.flush()

    def flush(self) -> None:
        if self.pending_writes:
            self.conn.commit()
            self.pending_writes = 0
            self.flush_count += 1

    def span(self, key: str, agent_id: str | None = None) -> str:
        span_id = new_id("span")
        self.conn.execute(
            """
            INSERT INTO agent_trace_spans (id, review_run_id, span_key, agent_id, status)
            VALUES (?, ?, ?, ?, 'running')
            """,
            (span_id, self.run_id, key, agent_id),
        )
        self._mark_write(force=True)
        self._file_log("trace_span_started", {"span_id": span_id, "span_key": key, "agent_id": agent_id})
        return span_id

    def event(self, span_id: str, event_type: str, summary: str, payload: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO agent_trace_events (id, span_id, event_type, summary, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_id("event"), span_id, event_type, summary, json.dumps(payload or {}, ensure_ascii=False)),
        )
        self._mark_write(force=True)
        self._file_log("trace_event", {"span_id": span_id, "event_type": event_type, "summary": summary, "payload": payload or {}})

    def message(
        self,
        span_id: str,
        from_agent: str,
        to_agent: str,
        role: str,
        content_summary: str,
        artifact_id: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO agent_messages (id, span_id, from_agent, to_agent, role, content_summary, artifact_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id("msg"), span_id, from_agent, to_agent, role, content_summary[:1000], artifact_id),
        )
        self._mark_write(force=True)
        self._file_log(
            "agent_message",
            {
                "span_id": span_id,
                "from_agent": from_agent,
                "to_agent": to_agent,
                "role": role,
                "content_summary": content_summary[:1000],
                "artifact_id": artifact_id,
            },
        )

    def finish(self, span_id: str, status: str = "completed") -> None:
        self.conn.execute(
            "UPDATE agent_trace_spans SET status = ?, ended_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, span_id),
        )
        self._mark_write(force=True)
        self._file_log("trace_span_finished", {"span_id": span_id, "status": status})

    def llm_call(
        self,
        span_id: str,
        provider: str,
        model: str,
        prompt: str,
        status: str,
        duration_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        request_id: str | None = None,
        request_messages: list[dict[str, Any]] | None = None,
        response_text: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO llm_call_records (
              id, span_id, provider, model, request_id, prompt_hash,
              input_tokens, output_tokens, duration_ms, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("llm"),
                span_id,
                provider,
                model,
                request_id,
                sha1(prompt),
                input_tokens,
                output_tokens,
                duration_ms,
                status,
            ),
        )
        self._mark_write(force=True)
        self._file_log(
            "llm_call",
            {
                "span_id": span_id,
                "provider": provider,
                "model": model,
                "request_id": request_id,
                "prompt_hash": sha1(prompt),
                "prompt": prompt,
                "request_messages": request_messages or [],
                "response_text": response_text or "",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
                "status": status,
            },
            "error" if status.startswith("failed") else "info",
        )

    def tool_call(
        self,
        span_id: str,
        tool_name: str,
        status: str,
        duration_ms: int,
        args_summary: str = "",
        output_summary: str = "",
        input_ref: dict[str, Any] | None = None,
        output_ref: dict[str, Any] | None = None,
        tool_version: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO tool_call_records (
              id, span_id, tool_name, tool_version, args_summary, input_ref_json,
              output_summary, output_ref_json, duration_ms, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("tool"),
                span_id,
                tool_name,
                tool_version,
                args_summary,
                json.dumps(input_ref or {}, ensure_ascii=False),
                output_summary,
                json.dumps(output_ref or {}, ensure_ascii=False),
                duration_ms,
                status,
            ),
        )
        self._mark_write(force=True)
        self._file_log(
            "tool_call",
            {
                "span_id": span_id,
                "tool_name": tool_name,
                "tool_version": tool_version,
                "args_summary": args_summary,
                "input_ref": input_ref or {},
                "output_summary": output_summary,
                "output_ref": output_ref or {},
                "duration_ms": duration_ms,
                "status": status,
            },
            "error" if status == "failed" or str(status).startswith("failed") else "info",
        )

    def artifact(self, artifact_type: str, name: str, path: Path, metadata: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO review_artifacts (
              id, review_run_id, artifact_type, name, storage_uri, sha256, size_bytes, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("artifact"),
                self.run_id,
                artifact_type,
                name,
                str(path),
                sha256_file(path),
                path.stat().st_size,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self._mark_write(force=True)
        self._file_log(
            "review_artifact",
            {
                "artifact_type": artifact_type,
                "name": name,
                "storage_uri": str(path),
                "size_bytes": path.stat().st_size,
                "metadata": metadata or {},
            },
        )


def path_template(value: str, repo_config: dict[str, Any], mr: sqlite3.Row) -> str:
    replacements = {
        "project_key": str(repo_config.get("project_key") or ""),
        "repo": str(repo_config.get("repo") or ""),
        "repo_id": str(repo_config.get("repo_id") or repo_config.get("repo") or ""),
        "external_repo_id": str(repo_config.get("repo_id") or repo_config.get("repo") or ""),
        "mr_number": str(mr["number"]),
        "mr_id": str(mr["external_mr_id"]),
        "head_sha": str(mr["latest_head_sha"]),
    }
    result = value
    for key, replacement in replacements.items():
        result = result.replace("{" + key + "}", urllib.parse.quote(replacement, safe=""))
    return result


def http_json(url: str, headers: dict[str, str], method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = None
    request_headers = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str, headers: dict[str, str]) -> str:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def backend_api_base_url(config: dict[str, Any]) -> str:
    worker_config = config.get("worker") or {}
    explicit = worker_config.get("vcs_proxy_base_url") or config.get("server", {}).get("api_base_url")
    if explicit:
        return str(explicit).rstrip("/")
    host = str(config.get("server", {}).get("host") or "127.0.0.1")
    port = int(config.get("server", {}).get("port") or 8011)
    return f"http://{host}:{port}/api"


def write_json_artifact(
    recorder: Recorder,
    sandbox_dir: Path,
    artifact_type: str,
    name: str,
    payload: dict[str, Any] | list[Any],
    metadata: dict[str, Any] | None = None,
) -> Path:
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    path = sandbox_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    recorder.artifact(artifact_type, name, path, metadata)
    return path


def safe_relative_path(value: str) -> Path:
    cleaned = Path(value.replace("\\", "/"))
    parts = [part for part in cleaned.parts if part not in {"", ".", ".."}]
    return Path(*parts) if parts else Path("unknown.txt")


def materialize_changed_files(
    sandbox_dir: Path,
    files: list[ChangedFile],
    source_file_contents: dict[str, str] | None = None,
) -> Path:
    worktree = sandbox_dir / "prescan" / "working-tree"
    worktree.mkdir(parents=True, exist_ok=True)
    source_file_contents = {str(key).replace("\\", "/"): value for key, value in (source_file_contents or {}).items()}
    for changed in files:
        target = worktree / safe_relative_path(changed.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        full_source = source_file_contents.get(changed.filename.replace("\\", "/"))
        if full_source:
            target.write_text(full_source if full_source.endswith("\n") else f"{full_source}\n", "utf-8")
            continue
        lines: list[str] = []
        for raw in changed.patch.splitlines():
            if raw.startswith("+") and not raw.startswith("+++"):
                lines.append(raw[1:])
            elif raw.startswith(" ") and not raw.startswith(("diff --git", "index ")):
                lines.append(raw[1:])
        target.write_text("\n".join(lines) + ("\n" if lines else ""), "utf-8")
    return worktree


def source_content_candidate_count(files: list[ChangedFile]) -> int:
    return len(
        [
            changed
            for changed in files
            if changed.status != "removed" and changed.filename.lower().endswith(SOURCE_CONTENT_SUFFIXES)
        ]
    )


def source_worktree_mode(
    *,
    configured_worktree: Path | None,
    source_file_contents: dict[str, str] | None,
    files: list[ChangedFile],
) -> str:
    if configured_worktree:
        return "configured_full_repo"
    fetched_count = len(source_file_contents or {})
    expected_count = source_content_candidate_count(files)
    if expected_count == 0:
        return "materialized_diff"
    if fetched_count >= expected_count:
        return "fetched_source_files"
    if fetched_count > 0:
        return "partial_fetched_source_files"
    return "materialized_diff"


def fetch_changed_files(config: dict[str, Any], repo: sqlite3.Row, mr: sqlite3.Row) -> list[ChangedFile]:
    repo_config = json.loads(repo["provider_config_json"] or "{}")
    fixture_path = repo_config.get("fixture_changed_files")
    if fixture_path:
        return load_fixture_changed_files(fixture_path)
    return fetch_changed_files_via_backend(config, repo, mr)


SOURCE_CONTENT_SUFFIXES = (
    ".java",
    ".kt",
    ".groovy",
    ".xml",
    ".yml",
    ".yaml",
    ".properties",
    ".sql",
    ".json",
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
)


def _repo_provider_config(repo: sqlite3.Row) -> dict[str, Any]:
    try:
        return json.loads(str(repo["provider_config_json"] or "{}"))
    except Exception:
        return {}


def _git_cache_dir(git_url: str) -> Path:
    digest = hashlib.sha256(git_url.encode("utf-8")).hexdigest()[:16]
    return ROOT / "data" / "repo-cache" / digest


def _run_git(args: list[str], *, cwd: Path | None = None, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _ensure_git_cache(git_url: str) -> tuple[Path | None, str | None]:
    cache_dir = _git_cache_dir(git_url)
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    if not (cache_dir / ".git").exists():
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        clone = _run_git(["clone", "--filter=blob:none", "--no-checkout", git_url, str(cache_dir)], timeout=180)
        if clone.returncode != 0:
            return None, clone.stderr.strip()[:500] or clone.stdout.strip()[:500] or "git clone failed"
    else:
        remote = _run_git(["remote", "set-url", "origin", git_url], cwd=cache_dir)
        if remote.returncode != 0:
            return None, remote.stderr.strip()[:500] or "git remote set-url failed"
    return cache_dir, None


def _fetch_git_file_contents(
    repo: sqlite3.Row,
    mr: sqlite3.Row,
    files: list[ChangedFile],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    provider_config = _repo_provider_config(repo)
    git_url = str(provider_config.get("git_url") or "").strip()
    head_sha = str(mr["latest_head_sha"] or "").strip()
    if not git_url or not head_sha:
        return {}, []

    candidates = [
        changed
        for changed in files
        if changed.status != "removed" and changed.filename.lower().endswith(SOURCE_CONTENT_SUFFIXES)
    ][:80]
    if not candidates:
        return {}, []

    cache_dir, cache_error = _ensure_git_cache(git_url)
    if cache_error or cache_dir is None:
        return {}, [{"filename": "*", "source": "git", "error": cache_error or "git cache unavailable"}]

    fetch = _run_git(["fetch", "--depth=1", "origin", head_sha], cwd=cache_dir, timeout=180)
    if fetch.returncode != 0:
        fetch = _run_git(["fetch", "origin", head_sha], cwd=cache_dir, timeout=180)
    if fetch.returncode != 0:
        return {}, [{"filename": "*", "source": "git", "error": fetch.stderr.strip()[:500] or "git fetch failed"}]

    contents: dict[str, str] = {}
    errors: list[dict[str, Any]] = []
    for changed in candidates:
        filename = changed.filename.replace("\\", "/")
        show = _run_git(["show", f"{head_sha}:{filename}"], cwd=cache_dir, timeout=60)
        if show.returncode == 0:
            contents[filename] = show.stdout
        else:
            errors.append({"filename": filename, "source": "git", "error": show.stderr.strip()[:500] or "git show failed"})
    return contents, errors


def _mr_metadata(mr: sqlite3.Row) -> dict[str, Any]:
    try:
        return json.loads(str(mr["metadata_json"] or "{}"))
    except Exception:
        return {}


def _fetch_git_changed_files(repo: sqlite3.Row, mr: sqlite3.Row) -> tuple[list[ChangedFile], list[dict[str, Any]]]:
    provider_config = _repo_provider_config(repo)
    git_url = str(provider_config.get("git_url") or "").strip()
    head_sha = str(mr["latest_head_sha"] or "").strip()
    metadata = _mr_metadata(mr)
    base_ref = str(metadata.get("base_sha") or mr["target_branch"] or "").strip()
    if not git_url or not head_sha or not base_ref:
        return [], []

    cache_dir, cache_error = _ensure_git_cache(git_url)
    if cache_error or cache_dir is None:
        return [], [{"source": "git", "error": cache_error or "git cache unavailable"}]

    errors: list[dict[str, Any]] = []
    for ref_name in (base_ref, head_sha):
        fetch = _run_git(["fetch", "--depth=1", "origin", ref_name], cwd=cache_dir, timeout=180)
        if fetch.returncode != 0:
            fetch = _run_git(["fetch", "origin", ref_name], cwd=cache_dir, timeout=180)
        if fetch.returncode != 0:
            errors.append({"source": "git", "ref": ref_name, "error": fetch.stderr.strip()[:500] or "git fetch failed"})
    if errors:
        return [], errors

    diff = _run_git(["diff", "--find-renames", "--find-copies", "--unified=80", f"{base_ref}..{head_sha}"], cwd=cache_dir, timeout=120)
    if diff.returncode != 0:
        return [], [{"source": "git", "error": diff.stderr.strip()[:500] or "git diff failed"}]
    return parse_git_patch(diff.stdout), []


def fetch_changed_file_contents(
    config: dict[str, Any],
    repo: sqlite3.Row,
    mr: sqlite3.Row,
    files: list[ChangedFile],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    project_id = str(repo["project_id"])
    mr_id = urllib.parse.quote(str(mr["id"]), safe="")
    base_url = backend_api_base_url(config)
    head_sha = str(mr["latest_head_sha"] or "")
    contents, errors = _fetch_git_file_contents(repo, mr, files)
    candidates = [
        changed
        for changed in files
        if changed.status != "removed" and changed.filename.lower().endswith(SOURCE_CONTENT_SUFFIXES)
    ][:80]
    for changed in candidates:
        filename = changed.filename.replace("\\", "/")
        if filename in contents:
            continue
        query = urllib.parse.urlencode({"path": filename, "sha": head_sha})
        url = f"{base_url}/vcs/{urllib.parse.quote(project_id, safe='')}/merge-requests/{mr_id}/file?{query}"
        try:
            payload = http_json(url, {"Accept": "application/json", "User-Agent": "jolt-codereview-worker"})
            content = str(payload.get("content") or "") if isinstance(payload, dict) else ""
            if content:
                contents[filename] = content
        except Exception as exc:
            errors.append({"filename": filename, "source": "vcs_api", "error": str(exc)[:500]})
    return contents, errors


def load_fixture_changed_files(fixture_path: str) -> list[ChangedFile]:
    fixture = Path(fixture_path)
    if not fixture.is_absolute():
        fixture = ROOT / fixture
    rows = json.loads(fixture.read_text("utf-8"))
    return [
        ChangedFile(
            filename=str(row.get("filename", "")),
            status=str(row.get("status", "modified")),
            additions=int(row.get("additions", 0)),
            deletions=int(row.get("deletions", 0)),
            changes=int(row.get("changes", row.get("additions", 0))),
            patch=str(row.get("patch", "")),
        )
        for row in rows
    ]


def fetch_changed_files_via_backend(config: dict[str, Any], repo: sqlite3.Row, mr: sqlite3.Row) -> list[ChangedFile]:
    git_files, git_errors = _fetch_git_changed_files(repo, mr)
    if git_files:
        return git_files
    project_id = str(repo["project_id"])
    mr_id = urllib.parse.quote(str(mr["id"]), safe="")
    base_url = backend_api_base_url(config)
    url = f"{base_url}/vcs/{urllib.parse.quote(project_id, safe='')}/merge-requests/{mr_id}/files"
    try:
        payload = http_json(url, {"Accept": "application/json", "User-Agent": "jolt-codereview-worker"})
    except Exception as exc:
        if git_errors:
            raise RuntimeError(f"{exc}; git fallback failed: {git_errors[:3]}") from exc
        raise
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"VCS proxy returned unexpected files payload for MR {mr['id']}")
    return [changed_file_from_vcs_row(row) for row in rows if isinstance(row, dict)]


def changed_file_from_vcs_row(row: dict[str, Any]) -> ChangedFile:
    filename = row.get("filename") or row.get("path") or row.get("new_path") or row.get("file_path") or ""
    additions = int(row.get("additions") or row.get("added_lines") or 0)
    deletions = int(row.get("deletions") or row.get("deleted_lines") or 0)
    return ChangedFile(
        filename=str(filename),
        status=str(row.get("status") or row.get("change_type") or "modified"),
        additions=additions,
        deletions=deletions,
        changes=int(row.get("changes") or additions + deletions),
        patch=str(row.get("patch") or row.get("diff") or ""),
    )


def parse_git_patch(patch_text: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    current_name = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_name, current_lines
        if not current_name:
            return
        patch = "\n".join(current_lines)
        additions = 0
        deletions = 0
        for line in current_lines:
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
        files.append(
            ChangedFile(
                filename=current_name,
                status="modified",
                additions=additions,
                deletions=deletions,
                changes=additions + deletions,
                patch=patch,
            )
        )
        current_name = ""
        current_lines = []

    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            flush()
            parts = line.split(" ")
            if len(parts) >= 4:
                current_name = parts[3][2:] if parts[3].startswith("b/") else parts[3]
            current_lines = []
            continue
        if line.startswith("+++ b/"):
            current_name = line[len("+++ b/") :]
        if current_name:
            current_lines.append(line)
    flush()
    return files


def known_rule_registry(agent_config_by_id: dict[str, dict[str, Any]]) -> set[str]:
    rules = set(RULE_CATEGORY_MAP.keys()) | set(RULE_CATEGORY_MAP.values()) | set(CATEGORY_PRIMARY_RULE.values())
    for config in agent_config_by_id.values():
        for key in ("rules", "covered_rules", "rule_ids"):
            values = config.get(key) if isinstance(config, dict) else None
            if isinstance(values, list):
                rules.update(str(item) for item in values if str(item))
    return rules


def language_for_file(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".py"):
        return "python"
    if lowered.endswith((".ts", ".tsx")):
        return "typescript"
    if lowered.endswith((".js", ".jsx")):
        return "javascript"
    if lowered.endswith(".java"):
        return "java"
    if lowered.endswith(".go"):
        return "go"
    if lowered.endswith((".kt", ".kts")):
        return "kotlin"
    if lowered.endswith(".vue"):
        return "javascript"
    if lowered.endswith((".css", ".scss", ".less", ".html")):
        return "frontend"
    return "unknown"


def file_matches_patterns(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def normalize_data_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    policy = dict(raw or {})
    policy.setdefault("llm_providers_allowed", ["internal-minimax-2.7"])
    policy.setdefault("default_llm_provider", "internal-minimax-2.7")
    policy.setdefault("prompt_retention", "hash_only")
    policy.setdefault("diff_max_lines_to_llm", 4000)
    policy.setdefault("sensitive_paths", ["infra/secrets/**", "config/prod/**", "**/*.pem", "**/*.p12"])
    policy.setdefault("data_residency", "cn-north-1")
    policy.setdefault("fallback_on_violation", "skip_file")
    policy.setdefault("redactor_rules", [])
    return policy


def aireviewignore_patterns(files: list[ChangedFile]) -> list[str]:
    patterns: list[str] = []
    for changed in files:
        if Path(changed.filename).name != ".aireviewignore":
            continue
        for _, text in extract_added_lines(changed.patch):
            item = text.strip()
            if item and not item.startswith("#"):
                patterns.append(item)
    return patterns


def sensitive_path(path: str, policy: dict[str, Any], extra_patterns: list[str] | None = None) -> bool:
    patterns = [str(item) for item in policy.get("sensitive_paths") or []]
    patterns.extend(extra_patterns or [])
    return file_matches_patterns(path, patterns)


def apply_data_policy_to_files(
    recorder: Recorder,
    span_id: str,
    sandbox_dir: Path,
    files: list[ChangedFile],
    policy: dict[str, Any],
) -> tuple[list[ChangedFile], list[dict[str, Any]]]:
    ignore_patterns = aireviewignore_patterns(files)
    allowed: list[ChangedFile] = []
    decisions: list[dict[str, Any]] = []
    max_lines = int(policy.get("diff_max_lines_to_llm") or 4000)
    used_lines = 0
    for changed in files:
        added_line_count = len(extract_added_lines(changed.patch))
        if sensitive_path(changed.filename, policy, ignore_patterns):
            decisions.append(
                {
                    "file_path": changed.filename,
                    "decision": "excluded_from_llm",
                    "reason": "sensitive_path_or_aireviewignore",
                    "static_scan_allowed": True,
                }
            )
            continue
        if used_lines + added_line_count > max_lines:
            decisions.append(
                {
                    "file_path": changed.filename,
                    "decision": "excluded_from_llm",
                    "reason": "diff_max_lines_to_llm_exceeded",
                    "static_scan_allowed": True,
                }
            )
            continue
        allowed.append(changed)
        used_lines += added_line_count
        decisions.append({"file_path": changed.filename, "decision": "allowed_to_llm", "added_lines": added_line_count})
    artifact = write_json_artifact(
        recorder,
        sandbox_dir,
        "policy",
        "data_policy_decisions.json",
        {
            "policy": policy,
            "aireviewignore_patterns": ignore_patterns,
            "allowed_file_count": len(allowed),
            "decisions": decisions,
        },
        {"prompt_retention": policy.get("prompt_retention"), "diff_max_lines_to_llm": max_lines},
    )
    recorder.event(
        span_id,
        "data_policy_applied",
        f"数据策略允许 {len(allowed)} 个文件进入 LLM，排除 {len(files) - len(allowed)} 个文件",
        {"artifact": str(artifact), "allowed_file_count": len(allowed), "excluded_file_count": len(files) - len(allowed)},
    )
    return allowed, decisions


def sanitize_findings_for_policy(findings: list[dict[str, Any]], policy: dict[str, Any], files: list[ChangedFile]) -> list[dict[str, Any]]:
    ignore_patterns = aireviewignore_patterns(files)
    sanitized: list[dict[str, Any]] = []
    for finding in findings:
        file_path = str(finding.get("file_path") or "")
        if sensitive_path(file_path, policy, ignore_patterns):
            item = dict(finding)
            item["line_start"] = None
            item["line_end"] = None
            item["evidence"] = "敏感路径内容已按项目数据策略隐藏，仅保留文件级静态扫描摘要。"
            item["problem_description"] = str(item.get("problem_description") or item.get("title") or "敏感路径命中")[:240]
            item["recommendation"] = str(item.get("recommendation") or "请由项目管理员在受控环境中查看该敏感路径命中。")
            item["dedupe_hash"] = sha1("|".join([str(item.get("agent_id")), str(item.get("title")), file_path, "sensitive-policy-summary"]))
            sanitized.append(item)
        else:
            sanitized.append(finding)
    return sanitized


def added_text(files: list[ChangedFile]) -> str:
    snippets: list[str] = []
    for changed in files:
        snippets.append(changed.filename)
        snippets.extend(text for _, text in extract_added_lines(changed.patch))
    return "\n".join(snippets).lower()


def semgrep_rules_path(sandbox_dir: Path) -> Path:
    rules_path = sandbox_dir / "prescan" / "semgrep-local-rules.yml"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        """
rules:
  - id: jolt.dynamic-eval
    message: Avoid dynamic eval/exec on MR input.
    severity: ERROR
    languages: [python, javascript, typescript]
    patterns:
      - pattern-either:
          - pattern: eval(...)
          - pattern: exec(...)
  - id: jolt.hardcoded-password
    message: Hardcoded password-like value added in code.
    severity: WARNING
    languages: [generic]
    patterns:
      - pattern-regex: (?i)(password|secret|token)\\s*[:=]\\s*['\"][^'\"]{6,}['\"]
  - id: jolt.java.spring.missing-valid-request-body
    message: Spring Controller @RequestBody should be validated with @Valid or @Validated.
    severity: WARNING
    languages: [java]
    patterns:
      - pattern-either:
          - pattern: |
              $RET $METHOD(..., @RequestBody $TYPE $ARG, ...) {
                ...
              }
          - pattern: |
              $RET $METHOD(@RequestBody $TYPE $ARG, ...) {
                ...
              }
      - pattern-not: |
          $RET $METHOD(..., @Valid @RequestBody $TYPE $ARG, ...) {
            ...
          }
      - pattern-not: |
          $RET $METHOD(..., @Validated @RequestBody $TYPE $ARG, ...) {
            ...
          }
      - pattern-not: |
          $RET $METHOD(..., @RequestBody @Valid $TYPE $ARG, ...) {
            ...
          }
      - pattern-not: |
          $RET $METHOD(..., @RequestBody @Validated $TYPE $ARG, ...) {
            ...
          }
  - id: jolt.java.map-payload-string-valueof
    message: Map payload field is converted with String.valueOf; missing fields become literal "null". Use DTO validation or explicit required text checks.
    severity: WARNING
    languages: [java]
    pattern-regex: 'String\\.valueOf\\s*\\(\\s*[A-Za-z_][A-Za-z0-9_]*\\.get\\s*\\('
  - id: jolt.java.jdbc.sql-concat
    message: JDBC SQL is concatenated before execution; use PreparedStatement and parameter binding.
    severity: ERROR
    languages: [java]
    patterns:
      - pattern-either:
          - pattern: $STMT.executeQuery($SQL + $X)
          - pattern: $STMT.executeUpdate($SQL + $X)
          - pattern: $CONN.createStatement().executeQuery($SQL + $X)
          - pattern: $CONN.createStatement().executeUpdate($SQL + $X)
          - pattern: $STMT.execute($SQL + $X)
  - id: jolt.java.jdbc.sql-string-concat-assignment
    message: SQL string is built through concatenation; use PreparedStatement and parameter binding before executing it.
    severity: WARNING
    languages: [java]
    patterns:
      - pattern: String $SQL = $A + $B;
      - metavariable-regex:
          metavariable: $SQL
          regex: (?i).*(sql|query|statement).*
  - id: jolt.java.sql-query-without-limit
    message: SQL query returns an unbounded result set; add pagination, LIMIT, or a cursor boundary.
    severity: WARNING
    languages: [java]
    pattern-regex: '(?i)select\\s+[^;\\n]*\\s+from\\s+[^;\\n]*(order\\s+by\\s+[^;\\n]*)?'
    paths:
      include:
        - "*.java"
    metadata:
      jolt_primary_rule: PERF-QUERY-001
  - id: jolt.java.sql-leading-wildcard-like
    message: SQL LIKE uses a leading wildcard such as '%xxx%'; B-tree indexes on merchant_id/search columns cannot be used, causing full scans.
    severity: WARNING
    languages: [java]
    pattern-regex: '(?i)like\\s+[''"]%[^;\\n]*\\+|like\\s+[''"]%[''"]\\s*\\+'
    paths:
      include:
        - "*.java"
  - id: jolt.java.sensitive-payment-field
    message: Payment credential-like field is present in Java source; tokenize or encrypt sensitive payment data and avoid exposing it through entities, DTOs, logs, or callbacks.
    severity: ERROR
    languages: [java]
    pattern-regex: '\\b(cardNumber|cvv|securityCode|cardCvv|pan)\\b'
    paths:
      include:
        - "*.java"
  - id: jolt.java.sensitive-response-field
    message: API response DTO appears to expose payment credential-like fields.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)record\\s+\\w*Response\\s*\\([^)]*\\b(cardNumber|cvv|securityCode|cardCvv|pan)\\b'
    paths:
      include:
        - "*.java"
  - id: jolt.java.sensitive-data-logging
    message: Logger call includes sensitive payment, signature, callback, or raw payload fields.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)log\\.(info|debug|warn|error)\\s*\\([^;]*(cardNumber|cvv|securityCode|callbackUrl|rawPayload|signature|token|password)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.sensitive-audit-write
    message: Audit/write log call includes sensitive signature, raw payload, callback, token, password, or payment credential fields.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)\\b\\w*(audit|audits|logger|log)\\w*\\.write\\s*\\([^;]*(cardNumber|cvv|securityCode|callbackUrl|rawPayload|signature|token|password|payload)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.admin-mutation-endpoint
    message: Admin mutation endpoint should have explicit authentication, authorization, audit, and idempotency controls.
    severity: ERROR
    languages: [java]
    pattern-regex: '@PostMapping\\s*\\(\\s*"[^"]*admin[^"]*"\\s*\\)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.arbitrary-balance-adjustment
    message: Balance adjustment adds request amount directly; enforce amount bounds, currency compatibility, operator identity, approval, and audit.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)adjustBalance\\s*\\([^)]*BigDecimal\\s+amount[^)]*\\)[\\s\\S]{0,500}\\.add\\s*\\(\\s*amount\\s*\\)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.client-controlled-risk-bypass
    message: Client-controlled request data or loopback IP is used to bypass risk control.
    severity: ERROR
    languages: [java]
    pattern-regex: '(skipRiskCheck\\s*\\(\\)|"127\\.0\\.0\\.1"\\s*\\.equals\\s*\\([^)]*clientIp|clientIp\\s*\\(\\)\\s*\\.equals\\s*\\(\\s*"127\\.0\\.0\\.1")'
    paths:
      include:
        - "*.java"
  - id: jolt.java.force-capture-state-bypass
    message: Client-controlled forceCapture/force flag bypasses payment state checks; enforce server-side state-machine transitions before debit/capture.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)force\\w*\\s*\\(\\)[\\s\\S]{0,240}(PaymentStatus|markPaid|debit|capture|paid)|PaymentStatus\\.[A-Z_]+[\\s\\S]{0,180}force\\w*\\s*\\(\\)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.weak-webhook-signature-match
    message: Webhook signature trust uses string prefix/substring matching; use cryptographic verification such as HMAC with replay protection.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)signature[^;\\n]*(startsWith|contains)\\s*\\(\\s*"test"\\s*\\)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.webhook-dedupe-key-composite-change
    message: Webhook dedupe key is built from multiple mutable provider fields; changing eventId/providerTransactionId compatibility can break idempotency.
    severity: WARNING
    languages: [java]
    pattern-regex: '(?s)(dedupe|idempot).*=[^;]*(eventId\\s*\\(\\)|providerTransactionId\\s*\\(\\))[^;]*\\+[^;]*(eventId\\s*\\(\\)|providerTransactionId\\s*\\(\\))'
    paths:
      include:
        - "*.java"
  - id: jolt.java.loose-webhook-event-match
    message: Webhook event type uses substring matching; validate exact provider event names and schema.
    severity: ERROR
    languages: [java]
    pattern-regex: 'eventType\\s*\\(\\)\\s*\\.contains\\s*\\(\\s*"PAYMENT_SUCCEEDED"\\s*\\)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.untrusted-callback-url-invocation
    message: User-controlled callback URL is invoked by RestTemplate; validate scheme, host allowlist, DNS/IP ranges, redirects, and payload minimization.
    severity: ERROR
    languages: [java]
    pattern-regex: '(postForEntity|getForObject|exchange)\\s*\\(\\s*[^,;]*(getCallbackUrl\\s*\\(\\s*\\)|callbackUrl)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.debug-controller-endpoint
    message: Debug endpoint is exposed through Spring MVC; require strong auth or remove it from production code.
    severity: ERROR
    languages: [java]
    pattern-regex: '@RequestMapping\\s*\\(\\s*"[^"]*/api/debug[^"]*"\\s*\\)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.stacktrace-response
    message: Stack traces or raw exceptions are returned to clients; return sanitized errors and log server-side details only.
    severity: ERROR
    languages: [java]
    pattern-regex: '(printStackTrace|StringWriter\\s+\\w+\\s*=\\s*new\\s+StringWriter|ResponseEntity\\.internalServerError\\s*\\(\\s*\\)\\.body)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.refund-allows-refunded-state
    message: Refund logic allows already-refunded payments; enforce refund state machine and cumulative amount checks.
    severity: ERROR
    languages: [java]
    pattern-regex: 'PaymentStatus\\.REFUNDED'
    paths:
      include:
        - "*.java"
  - id: jolt.java.refund-reason-manual-override-bypass
    message: Refund reason MANUAL_OVERRIDE is user-controlled and bypasses paid-state validation; do not use reason text as an authorization/state-machine override.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)reason\\s*\\(\\)\\s*\\.startsWith\\s*\\(\\s*"MANUAL_OVERRIDE"\\s*\\)[\\s\\S]{0,260}(PaymentStatus|refund|creditRefund|markRefunded)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.refund-reason-startswith-null
    message: Refund reason is dereferenced with startsWith before null/blank validation; invalid requests can throw NPE before business validation.
    severity: WARNING
    languages: [java]
    pattern-regex: 'reason\\s*\\(\\)\\s*\\.startsWith\\s*\\('
    paths:
      include:
        - "*.java"
  - id: jolt.java.payment-status-valueof-unvalidated
    message: PaymentStatus.valueOf(status) uses user-controlled status without null/illegal enum validation; handle IllegalArgumentException and whitelist transitions.
    severity: ERROR
    languages: [java]
    pattern-regex: 'PaymentStatus\\.valueOf\\s*\\(\\s*status\\s*\\)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.override-status-bypass
    message: Public overrideStatus/force status method bypasses the domain state machine; expose explicit transition methods with allowed from/to states.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)(overrideStatus|forceTransition)\\s*\\([^)]*status[^)]*\\)[\\s\\S]{0,260}(PaymentStatus\\.valueOf|this\\.status\\s*=|order\\.overrideStatus)'
    paths:
      include:
        - "*.java"
  - id: jolt.java.reassign-merchant-ownership
    message: Public reassignMerchant/merchantId rewrite changes aggregate ownership; require ownership authorization and domain invariant checks.
    severity: ERROR
    languages: [java]
    pattern-regex: '(?s)(reassignMerchant|merchantId)[\\s\\S]{0,220}(this\\.merchantId\\s*=|order\\.reassignMerchant)'
    paths:
      include:
        - "*.java"
  - id: jolt.config.jpa-show-sql-enabled
    message: spring.jpa.show-sql is enabled; disable SQL logging in application config unless explicitly safe and scoped.
    severity: ERROR
    languages: [generic]
    pattern-regex: '(?i)show-sql\\s*:\\s*true'
    paths:
      include:
        - "*.yml"
        - "*.yaml"
        - "*.properties"
  - id: jolt.config.stacktrace-enabled
    message: Server error config includes stack traces; disable stack traces in client responses.
    severity: ERROR
    languages: [generic]
    pattern-regex: '(?i)include-stacktrace\\s*:\\s*(always|on_param)'
    paths:
      include:
        - "*.yml"
        - "*.yaml"
        - "*.properties"
  - id: jolt.test.skip-high-risk-path-tests
    message: Test configuration skips high-risk path tests; do not mask callback, auth, debug, or external integration safety coverage.
    severity: WARNING
    languages: [generic]
    pattern-regex: '(?i)skip[-_.]?(external|callback|auth|debug|security).*:\\s*true'
    paths:
      include:
        - "*.yml"
        - "*.yaml"
        - "*.properties"
  - id: jolt.java.domain-map-string-object
    message: Domain model or aggregate uses Map<String,Object>; model explicit value objects and typed fields instead.
    severity: WARNING
    languages: [java]
    pattern-regex: 'Map\\s*<\\s*String\\s*,\\s*Object\\s*>'
    paths:
      include:
        - "*/domain/*.java"
        - "*/domain/**/*.java"
  - id: jolt.java.redis.keys
    message: Redis KEYS is dangerous in production paths; use SCAN or an indexed key set.
    severity: ERROR
    languages: [java]
    patterns:
      - pattern-either:
          - pattern: $REDIS.keys(...)
          - pattern: $CONN.keys(...)
  - id: jolt.java.redis.set-without-ttl
    message: Redis cache writes should set an explicit TTL unless the key is intentionally permanent.
    severity: WARNING
    languages: [java]
    patterns:
      - pattern: $REDIS.opsForValue().set($KEY, $VALUE)
  - id: jolt.db.drop-column
    message: Database migration drops a column directly; use a staged compatible migration.
    severity: ERROR
    languages: [generic]
    pattern-regex: '(?i)\\bALTER\\s+TABLE\\s+\\S+\\s+DROP\\s+COLUMN\\b'
  - id: jolt.java.exception-message-response
    message: Do not return raw exception messages to API clients.
    severity: WARNING
    languages: [java]
    patterns:
      - pattern: $RESP.put($KEY, $E.getMessage())
  - id: jolt.spring.actuator.expose-all
    message: Spring Actuator exposure include=* exposes dangerous operational endpoints.
    severity: ERROR
    languages: [generic]
    patterns:
      - pattern-regex: (?i)management\\s*:[\\s\\S]{0,300}endpoints\\s*:[\\s\\S]{0,300}exposure\\s*:[\\s\\S]{0,120}include\\s*:\\s*['\"]?\\*
  - id: jolt.config.hardcoded-password
    message: Configuration contains a hardcoded password-like value; move it to a secret manager or environment variable.
    severity: ERROR
    languages: [generic]
    paths:
      include:
        - "*.yml"
        - "*.yaml"
        - "*.properties"
    pattern-regex: '(?i)(password|passwd|pwd)\\s*[:=]\\s*["'']?[A-Za-z0-9_@#%+\\-/]{6,}["'']?'
""".strip()
        + "\n",
        "utf-8",
    )
    return rules_path


def semgrep_config_args(project_config: dict[str, Any] | None, sandbox_dir: Path) -> list[str]:
    values = semgrep_config_values(project_config, sandbox_dir)
    args: list[str] = []
    for value in values:
        args.extend(["--config", value])
    return args


def semgrep_config_values(project_config: dict[str, Any] | None, sandbox_dir: Path) -> list[str]:
    policy = tool_policy_config(project_config)
    runner_cfg = static_runner_config(project_config, "semgrep")
    configured = (
        runner_cfg.get("custom_config_paths")
        or runner_cfg.get("additional_config_paths")
        or runner_cfg.get("config_paths")
        or runner_cfg.get("configs")
        or runner_cfg.get("config")
    )
    custom_values = [resolve_rule_value(value) for value in configured_path_values(configured)]
    jolt_rules = [str(semgrep_rules_path(sandbox_dir))]
    values = custom_values if runner_cfg.get("replace_builtin_rules") else [*jolt_rules, *builtin_semgrep_configs(), *custom_values]
    if values:
        return values
    if runner_cfg.get("use_builtin_jolt_rules") or policy.get("use_builtin_semgrep_rules"):
        return [str(semgrep_rules_path(sandbox_dir))]
    return [str(runner_cfg.get("registry_config") or policy.get("semgrep_registry_config") or "auto")]


def gitleaks_config_path(sandbox_dir: Path) -> Path:
    config_path = sandbox_dir / "prescan" / "gitleaks-jolt.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    chinese_secret_regex = r'''(?i)(密码|口令|密钥|私钥|令牌|凭证|access[_-]?key|secret[_-]?key|api[_-]?key|ak|sk)\s*[:=：]\s*["']?[A-Za-z0-9_/\-+=]{8,}["']?'''
    cloud_access_key_regex = r'''(?i)(LTAI[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|AKLT[a-zA-Z0-9_-]{8,})'''
    spring_config_password_regex = r'''(?i)(spring\.)?(datasource|redis|mq|kafka|rabbitmq).{0,80}(password|secret|token)\s*[:=]\s*["']?[^"'\s]{6,}["']?'''
    config_path.write_text(
        f'''
title = "Jolt Java Web gitleaks rules"

[[rules]]
id = "jolt-chinese-secret-keywords"
description = "Chinese secret and credential keywords"
regex = {json.dumps(chinese_secret_regex, ensure_ascii=False)}
keywords = ["密码", "密钥", "secret", "access_key", "api_key"]

[[rules]]
id = "jolt-cloud-access-key"
description = "Cloud provider access key style token"
regex = {json.dumps(cloud_access_key_regex, ensure_ascii=False)}
keywords = ["LTAI", "AKIA", "ASIA", "AKLT"]

[[rules]]
id = "jolt-spring-config-password"
description = "Spring configuration password-like value"
regex = {json.dumps(spring_config_password_regex, ensure_ascii=False)}
keywords = ["password", "datasource", "redis", "rabbitmq"]
'''.strip() + "\n",
        "utf-8",
    )
    return config_path


def gitleaks_runtime_config_path(sandbox_dir: Path, project_config: dict[str, Any] | None) -> Path:
    policy = tool_policy_config(project_config)
    runner_cfg = static_runner_config(project_config, "gitleaks")
    configured = str(
        runner_cfg.get("extend_config_path")
        or runner_cfg.get("custom_config_path")
        or runner_cfg.get("config_path")
        or policy.get("gitleaks_config_path")
        or ""
    ).strip()
    config_path = sandbox_dir / "prescan" / "gitleaks-composite.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'title = "Jolt CodeReview gitleaks composite config"',
        "",
        "[extend]",
        "useDefault = true",
    ]
    if configured:
        lines.append(f"path = {json.dumps(str(resolve_configured_path(configured)), ensure_ascii=False)}")
    if runner_cfg.get("include_jolt_secret_rules") or policy.get("use_builtin_gitleaks_rules"):
        lines.extend(["", gitleaks_config_path(sandbox_dir).read_text("utf-8")])
    config_path.write_text("\n".join(lines).strip() + "\n", "utf-8")
    return config_path


def gitleaks_config_args(project_config: dict[str, Any] | None, sandbox_dir: Path) -> list[str]:
    return ["--config", str(gitleaks_runtime_config_path(sandbox_dir, project_config))]


def checkstyle_config_path(sandbox_dir: Path, project_config: dict[str, Any] | None) -> Path:
    policy = tool_policy_config(project_config)
    runner_cfg = {}
    static_runners = policy.get("static_runners") if isinstance(policy.get("static_runners"), dict) else {}
    if isinstance(static_runners.get("checkstyle"), dict):
        runner_cfg = static_runners["checkstyle"]
    configured = str(runner_cfg.get("config_path") or policy.get("checkstyle_config_path") or "")
    if configured:
        configured_path = Path(configured)
        return configured_path if configured_path.is_absolute() else (ROOT / configured_path).resolve()
    for candidate in [
        STATIC_RULES_DIR / "checkstyle" / "google_checks.xml",
        STATIC_RULES_DIR / "checkstyle" / "sun_checks.xml",
    ]:
        if candidate.exists():
            return candidate
    if runner_cfg.get("builtin_style") == "sun":
        return Path("/sun_checks.xml")
    return Path("/google_checks.xml")


def pmd_rulesets(project_config: dict[str, Any] | None) -> str:
    runner_cfg = static_runner_config(project_config, "pmd")
    configured = (
        runner_cfg.get("custom_rulesets")
        or runner_cfg.get("additional_rulesets")
        or runner_cfg.get("rulesets")
        or runner_cfg.get("ruleset")
        or tool_policy_config(project_config).get("pmd_rulesets")
    )
    custom_values = [resolve_rule_value(value) for value in configured_path_values(configured)]
    values = custom_values if runner_cfg.get("replace_builtin_rules") else [*builtin_pmd_rulesets(), *custom_values]
    return ",".join(values)


def builtin_java_heuristics_enabled(project_config: dict[str, Any] | None) -> bool:
    policy = tool_policy_config(project_config)
    runner_cfg = static_runner_config(project_config, "java_web_static")
    return bool(
        policy.get("enable_builtin_java_heuristics")
        or policy.get("enable_jolt_builtin_rules")
        or runner_cfg.get("enabled") is True
    )


def command_version(command: str, args: list[str]) -> tuple[str | None, int]:
    executable = shutil.which(command)
    if not executable:
        return None, 0
    started = time.time()
    try:
        completed = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = (completed.stdout or completed.stderr or "").strip().splitlines()
        version = output[0][:120] if output else "available"
        return version, int((time.time() - started) * 1000)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"version_failed:{type(exc).__name__}", int((time.time() - started) * 1000)


def run_static_command(
    recorder: Recorder,
    span_id: str,
    command: str,
    args: list[str],
    output_path: Path | None = None,
    ok_returncodes: set[int] | None = None,
    timeout_seconds: int = 40,
) -> dict[str, Any]:
    ok_codes = ok_returncodes or {0}
    version_args = {
        "semgrep": ["--version"],
        "gitleaks": ["version"],
        "ruff": ["--version"],
        "eslint": ["--version"],
        "bandit": ["--version"],
        "spotbugs": ["-version"],
        "pmd": ["--version"],
        "checkstyle": ["--version"],
        "dependency-check": ["--version"],
        "osv-scanner": ["--version"],
        "kics": ["version"],
        "trivy": ["--version"],
        "openapi-diff": ["--version"],
    }.get(command, ["--version"])
    version, version_ms = command_version(command, version_args)
    if version is None:
        recorder.tool_call(
            span_id,
            f"static.{command}",
            "missing",
            version_ms,
            args_summary=" ".join(args),
            output_summary=f"{command} is not installed",
        )
        return {"tool": command, "available": False, "status": "missing", "version": None, "findings": []}

    executable = shutil.which(command)
    started = time.time()
    stdout = ""
    stderr = ""
    returncode = -1
    status = "failed"
    try:
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [executable or command, *args],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        returncode = completed.returncode
        status = "completed" if returncode in ok_codes else "failed"
        if command == "semgrep" and status == "failed":
            try:
                payload = json.loads(stdout or "{}")
                if isinstance(payload, dict) and isinstance(payload.get("results"), list):
                    status = "completed"
            except json.JSONDecodeError:
                pass
        combined_output = f"{stdout}\n{stderr}".lower()
        if command == "dependency-check" and status == "failed" and "database does not exist" in combined_output:
            status = "skipped"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = "timeout"
        status = "timeout"
    except OSError as exc:
        stderr = str(exc)
        status = "failed"

    if output_path and stdout:
        output_path.write_text(stdout, "utf-8")

    duration_ms = int((time.time() - started) * 1000)
    if output_path and status == "completed" and not output_path.exists():
        status = "output_missing"
    output_summary = (stdout or stderr or f"returncode={returncode}")[:500]
    recorder.tool_call(
        span_id,
        f"static.{command}",
        status,
        duration_ms,
        args_summary=" ".join(args),
        output_summary=output_summary,
        output_ref={"path": str(output_path)} if output_path else None,
        tool_version=version,
    )
    return {
        "tool": command,
        "available": True,
        "status": status,
        "version": version,
        "returncode": returncode,
        "timeout_seconds": timeout_seconds,
        "stdout_path": str(output_path) if output_path else None,
        "stdout_preview": stdout[:1000],
        "stderr_preview": stderr[:1000],
        "findings": [],
    }


def skipped_static_tool(recorder: Recorder, span_id: str, command: str, reason: str) -> dict[str, Any]:
    version_args = {
        "semgrep": ["--version"],
        "gitleaks": ["version"],
        "ruff": ["--version"],
        "eslint": ["--version"],
        "bandit": ["--version"],
        "spotbugs": ["-version"],
        "pmd": ["--version"],
        "checkstyle": ["--version"],
        "dependency-check": ["--version"],
        "osv-scanner": ["--version"],
        "kics": ["version"],
        "trivy": ["--version"],
        "openapi-diff": ["--version"],
    }.get(command, ["--version"])
    version, version_ms = command_version(command, version_args)
    status = "missing" if version is None else reason
    recorder.tool_call(
        span_id,
        f"static.{command}",
        status,
        version_ms,
        args_summary=reason,
        output_summary=f"{command}: {status}",
        tool_version=version,
    )
    return {"tool": command, "available": version is not None, "status": status, "version": version, "findings": []}


def disabled_static_tool(recorder: Recorder, span_id: str, command: str, reason: str = "project_tool_policy_disabled") -> dict[str, Any]:
    recorder.tool_call(
        span_id,
        f"static.{command}",
        "disabled",
        0,
        args_summary=reason,
        output_summary=f"{command}: {reason}",
    )
    return {"tool": command, "available": False, "status": "disabled", "version": None, "findings": []}


def tool_policy_config(project_config: dict[str, Any] | None) -> dict[str, Any]:
    if not project_config:
        return {}
    policy = project_config.get("tool_policy")
    return policy if isinstance(policy, dict) else {}


def static_runner_config(project_config: dict[str, Any] | None, tool_name: str) -> dict[str, Any]:
    policy = tool_policy_config(project_config)
    static_runners = policy.get("static_runners") if isinstance(policy.get("static_runners"), dict) else {}
    runner_cfg = static_runners.get(tool_name) if isinstance(static_runners, dict) else None
    return runner_cfg if isinstance(runner_cfg, dict) else {}


def static_tool_enabled(project_config: dict[str, Any] | None, tool_name: str) -> bool:
    policy = tool_policy_config(project_config)
    disabled = {str(item) for item in policy.get("disabled_tools") or []}
    if tool_name in disabled:
        return False
    enabled = policy.get("enabled_tools")
    if isinstance(enabled, list) and enabled:
        return tool_name in {str(item) for item in enabled}
    runner_cfg = static_runner_config(project_config, tool_name)
    if isinstance(runner_cfg, dict) and runner_cfg.get("enabled") is False:
        return False
    return True


def static_tool_timeout_seconds(project_config: dict[str, Any] | None, tool_name: str) -> int:
    runner_cfg = static_runner_config(project_config, tool_name)
    configured = runner_cfg.get("timeout_seconds")
    if configured is None:
        configured = runner_cfg.get("timeout_ms")
        if configured is not None:
            try:
                return max(1, int(configured) // 1000)
            except (TypeError, ValueError):
                return 180 if tool_name in {"dependency-check", "osv-scanner", "trivy"} else 40
    try:
        if configured is not None:
            return max(1, int(configured))
        return 180 if tool_name in {"dependency-check", "osv-scanner", "trivy"} else 40
    except (TypeError, ValueError):
        return 180 if tool_name in {"dependency-check", "osv-scanner", "trivy"} else 40


def runner_extra_args(project_config: dict[str, Any] | None, tool_name: str) -> list[str]:
    runner_cfg = static_runner_config(project_config, tool_name)
    extra_args = runner_cfg.get("extra_args")
    if not isinstance(extra_args, list):
        return []
    return [str(item) for item in extra_args if str(item)]


def resolve_configured_path(value: str, base_dir: Path = ROOT) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def configured_path_values(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def existing_rule_paths(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths if path.exists()]


def resolve_rule_value(value: str) -> str:
    if not value:
        return value
    if value.startswith(("p/", "r/", "https://", "http://")):
        return value
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str((ROOT / path).resolve())


def builtin_semgrep_configs() -> list[str]:
    downloaded_root = STATIC_RULES_DIR / "semgrep"
    downloaded_dirs = existing_rule_paths(
        [
            downloaded_root / "java",
            downloaded_root / "generic",
            downloaded_root / "yaml",
            downloaded_root / "secrets",
        ]
    )
    local_configs = existing_rule_paths(
        [
            STATIC_RULES_DIR / "semgrep" / "jolt-java-web.yml",
            STATIC_RULES_DIR / "semgrep" / "semgrep-rules.yml",
        ]
    )
    return downloaded_dirs + local_configs or BUILTIN_SEMGREP_REGISTRY_CONFIGS


def builtin_pmd_rulesets() -> list[str]:
    # PMD category XML downloaded from GitHub may contain documentation properties
    # such as ${pmd.website.baseurl}. The installed PMD distribution resolves the
    # same open-source rules reliably through category/java/... identifiers.
    return BUILTIN_PMD_RULESETS


def dependency_check_args(project_config: dict[str, Any] | None, worktree: Path, output_dir: Path) -> list[str]:
    runner_cfg = static_runner_config(project_config, "dependency-check")
    args = [
        "--project",
        str(runner_cfg.get("project_name") or "jolt-mr"),
        "--scan",
        str(worktree),
        "--format",
        "JSON",
        "--out",
        str(output_dir),
    ]
    if runner_cfg.get("disable_version_check", True):
        args.append("--disableVersionCheck")
    allow_update = runner_cfg.get("allow_update") is True
    if runner_cfg.get("noupdate") is True or runner_cfg.get("offline") or not allow_update:
        args.append("--noupdate")

    nvd_api_key = str(runner_cfg.get("nvd_api_key") or "")
    nvd_api_key_env = str(runner_cfg.get("nvd_api_key_env") or "")
    if not nvd_api_key and nvd_api_key_env:
        nvd_api_key = os.environ.get(nvd_api_key_env, "")
    if nvd_api_key:
        args.extend(["--nvdApiKey", nvd_api_key])
    data_directory = str(runner_cfg.get("data_directory") or "data/cache/dependency-check")
    if data_directory:
        resolved_data_directory = Path(resolve_configured_path(data_directory))
        resolved_data_directory.mkdir(parents=True, exist_ok=True)
        args.extend(["-d", str(resolved_data_directory)])
    if runner_cfg.get("nvd_api_delay_ms"):
        args.extend(["--nvdApiDelay", str(runner_cfg["nvd_api_delay_ms"])])
    if runner_cfg.get("nvd_api_results_per_page"):
        args.extend(["--nvdApiResultsPerPage", str(runner_cfg["nvd_api_results_per_page"])])
    if runner_cfg.get("nvd_api_endpoint"):
        args.extend(["--nvdApiEndpoint", str(runner_cfg["nvd_api_endpoint"])])
    if runner_cfg.get("proxy_server"):
        args.extend(["--proxyserver", str(runner_cfg["proxy_server"])])
    if runner_cfg.get("proxy_port"):
        args.extend(["--proxyport", str(runner_cfg["proxy_port"])])
    if runner_cfg.get("proxy_user"):
        args.extend(["--proxyuser", str(runner_cfg["proxy_user"])])
    proxy_pass = str(runner_cfg.get("proxy_pass") or "")
    proxy_pass_env = str(runner_cfg.get("proxy_pass_env") or "")
    if not proxy_pass and proxy_pass_env:
        proxy_pass = os.environ.get(proxy_pass_env, "")
    if proxy_pass:
        args.extend(["--proxypass", proxy_pass])

    for suppression in configured_path_values(runner_cfg.get("suppression_files") or runner_cfg.get("suppression_file")):
        args.extend(["--suppression", str(resolve_configured_path(suppression))])
    for pattern in configured_path_values(runner_cfg.get("exclude_patterns") or runner_cfg.get("exclude")):
        args.extend(["--exclude", pattern])
    args.extend(runner_extra_args(project_config, "dependency-check"))
    return args


def osv_scanner_args(project_config: dict[str, Any] | None, worktree: Path, output_path: Path) -> list[str]:
    runner_cfg = static_runner_config(project_config, "osv-scanner")
    recursive = runner_cfg.get("recursive", True) is not False
    args = ["scan", "source"]
    if recursive:
        args.append("--recursive")
    if runner_cfg.get("no_ignore", True) is not False:
        args.append("--no-ignore")
    args.extend(["--format", "json", "--output-file", str(output_path)])
    if runner_cfg.get("offline"):
        args.append("--offline")
    if runner_cfg.get("offline_vulnerabilities"):
        args.append("--offline-vulnerabilities")
    if runner_cfg.get("download_offline_databases"):
        args.append("--download-offline-databases")
    if runner_cfg.get("allow_no_lockfiles"):
        args.append("--allow-no-lockfiles")
    if runner_cfg.get("all_packages"):
        args.append("--all-packages")
    if runner_cfg.get("no_resolve"):
        args.append("--no-resolve")
    if runner_cfg.get("data_source"):
        args.extend(["--data-source", str(runner_cfg["data_source"])])
    if runner_cfg.get("maven_registry"):
        args.extend(["--maven-registry", str(runner_cfg["maven_registry"])])
    args.extend(runner_extra_args(project_config, "osv-scanner"))
    args.append(str(worktree))
    return args


def trivy_args(project_config: dict[str, Any] | None, worktree: Path, output_path: Path) -> list[str]:
    runner_cfg = static_runner_config(project_config, "trivy")
    args = ["fs", "--format", "json", "--output", str(output_path), "--no-progress"]
    if runner_cfg.get("skip_db_update"):
        args.append("--skip-db-update")
    if runner_cfg.get("skip_java_db_update"):
        args.append("--skip-java-db-update")
    if runner_cfg.get("offline_scan"):
        args.append("--offline-scan")
    if runner_cfg.get("cache_dir"):
        args.extend(["--cache-dir", str(resolve_configured_path(str(runner_cfg["cache_dir"])))])
    if runner_cfg.get("scanners"):
        scanners = runner_cfg["scanners"]
        args.extend(["--scanners", ",".join(str(item) for item in scanners) if isinstance(scanners, list) else str(scanners)])
    args.extend(runner_extra_args(project_config, "trivy"))
    args.append(str(worktree))
    return args


def run_static_tool_with_policy(
    recorder: Recorder,
    span_id: str,
    project_config: dict[str, Any] | None,
    command: str,
    args: list[str],
    output_path: Path | None = None,
    ok_returncodes: set[int] | None = None,
) -> dict[str, Any]:
    if not static_tool_enabled(project_config, command):
        return disabled_static_tool(recorder, span_id, command)
    return run_static_command(
        recorder,
        span_id,
        command,
        args,
        output_path,
        ok_returncodes,
        static_tool_timeout_seconds(project_config, command),
    )


def run_semgrep_prescan(
    recorder: Recorder,
    span_id: str,
    project_config: dict[str, Any] | None,
    sandbox_dir: Path,
    output_path: Path,
    target_paths: list[str],
    worktree: Path,
) -> dict[str, Any]:
    if not static_tool_enabled(project_config, "semgrep"):
        return disabled_static_tool(recorder, span_id, "semgrep")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    configs = semgrep_config_values(project_config, sandbox_dir)
    scan_targets = target_paths or [str(worktree)]
    child_results: list[dict[str, Any]] = []
    merged_results: list[Any] = []
    merged_errors: list[Any] = []
    merged_paths: dict[str, Any] = {}
    timeout_seconds = static_tool_timeout_seconds(project_config, "semgrep")
    for index, config_value in enumerate(configs):
        child_output = output_path.with_name(f"{output_path.stem}-{index + 1}.json")
        result = run_static_command(
            recorder,
            span_id,
            "semgrep",
            ["--config", config_value, "--json", "--quiet", "--no-git-ignore", *scan_targets],
            child_output,
            {0, 1},
            timeout_seconds,
        )
        result["config"] = config_value
        child_results.append(result)
        if not child_output.exists():
            continue
        try:
            payload = json.loads(child_output.read_text("utf-8") or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            if isinstance(payload.get("results"), list):
                merged_results.extend(payload["results"])
            if isinstance(payload.get("errors"), list):
                merged_errors.extend(payload["errors"])
            if isinstance(payload.get("paths"), dict):
                merged_paths.update(payload["paths"])
    combined = {"results": merged_results, "errors": merged_errors, "paths": merged_paths}
    output_path.write_text(json.dumps(combined, ensure_ascii=False), "utf-8")
    completed_children = [item for item in child_results if item.get("status") == "completed"]
    available_children = [item for item in child_results if item.get("available")]
    if completed_children:
        status = "completed"
    elif any(item.get("status") == "timeout" for item in child_results):
        status = "timeout"
    elif any(item.get("status") == "missing" for item in child_results):
        status = "missing"
    else:
        status = "failed"
    recorder.tool_call(
        span_id,
        "static.semgrep.aggregate",
        status,
        0,
        args_summary=f"configs={len(configs)} targets={len(scan_targets)}",
        output_summary=f"merged_results={len(merged_results)} child_statuses={[item.get('status') for item in child_results]}",
        output_ref={"path": str(output_path)},
        tool_version=(available_children[0].get("version") if available_children else None),
    )
    return {
        "tool": "semgrep",
        "available": bool(available_children),
        "status": status,
        "version": available_children[0].get("version") if available_children else None,
        "returncode": None,
        "stdout_path": str(output_path),
        "stdout_preview": json.dumps(combined, ensure_ascii=False)[:1000],
        "stderr_preview": "",
        "findings": [],
        "child_reports": [
            {
                "config": item.get("config"),
                "status": item.get("status"),
                "returncode": item.get("returncode"),
                "stdout_path": item.get("stdout_path"),
                "version": item.get("version"),
            }
            for item in child_results
        ],
    }


def skipped_static_tool_with_policy(
    recorder: Recorder,
    span_id: str,
    project_config: dict[str, Any] | None,
    command: str,
    reason: str,
) -> dict[str, Any]:
    if not static_tool_enabled(project_config, command):
        return disabled_static_tool(recorder, span_id, command)
    return skipped_static_tool(recorder, span_id, command, reason)


def path_to_changed(path_value: str, worktree: Path, files_by_name: dict[str, ChangedFile]) -> ChangedFile | None:
    raw = Path(path_value)
    try:
        rel = raw.resolve().relative_to(worktree.resolve())
        key = rel.as_posix()
    except (ValueError, OSError):
        key = path_value.replace("\\", "/")
    return files_by_name.get(key)


def invalid_tool_evidence(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    return lowered in {"requires login", "login required", "none", "null"} or lowered.startswith("requires login")


def source_line_evidence(path_value: str, worktree: Path, line_no: int | None, *, window: int = 1) -> str:
    if not line_no or line_no <= 0:
        return ""
    raw = Path(path_value)
    source_path = raw
    if not source_path.is_absolute():
        source_path = worktree / safe_relative_path(path_value)
    try:
        source_path = source_path.resolve()
    except OSError:
        pass
    try:
        if not source_path.exists():
            return ""
        lines = source_path.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = max(1, int(line_no) - window)
    end = min(len(lines), int(line_no) + window)
    return "\n".join(f"{index}: {lines[index - 1]}" for index in range(start, end + 1))


def tool_finding(
    agent_id: str,
    severity: str,
    changed: ChangedFile,
    line_no: int | None,
    title: str,
    description: str,
    recommendation: str,
    evidence: str,
    head_sha: str,
    tool_name: str,
) -> dict[str, Any]:
    finding = make_finding(agent_id, severity, changed, line_no, title, description, recommendation, evidence, head_sha)
    finding["dedupe_hash"] = sha1("|".join([tool_name, agent_id, title, changed.filename, str(line_no), evidence[:120]]))
    finding["confidence"] = max(float(finding["confidence"]), 0.82 if severity in {"critical", "high"} else 0.76)
    finding["tool_name"] = tool_name
    finding["tool_rule_id"] = title
    return finding


def agent_for_static_rule(rule_id: str, message: str = "") -> str:
    category = normalized_rule_category(rule_id, message)
    if category in {
        "SQL_INJECTION",
        "SECRET_LEAK",
        "ERROR_INFORMATION_LEAK",
        "SPRING_ACTUATOR_EXPOSED",
        "AUTHORIZATION_BYPASS",
        "RISK_CONTROL_BYPASS",
        "WEAK_WEBHOOK_TRUST",
        "SSRF_CALLBACK",
    }:
        return "security_agent"
    if category in {"UNBOUNDED_QUERY", "UNBOUNDED_RESULT_MEMORY", "REQUEST_THREAD_BLOCKING"}:
        return "performance_agent"
    if category in {"REDIS_DANGEROUS_COMMAND", "REDIS_MISSING_TTL"}:
        return "redis_agent"
    if category in {"DDD_WEAK_DOMAIN_MODEL", "LAYER_VIOLATION"}:
        return "ddd_agent"
    if category in {"DB_BREAKING_CHANGE", "DB_NOT_NULL_NO_DEFAULT", "DB_MAP_RESULT_TYPE", "IBATIS_MEMORY_PAGINATION"}:
        return "database_agent"
    if category in {"DEPENDENCY_CVE", "DEPENDENCY_SCOPE"}:
        return "dependency_agent"
    if category in {"SPRING_VALIDATION", "IDEMPOTENCY_GUARD", "SPRING_TRANSACTION"}:
        return "backend_agent"
    if category in {"STATE_MACHINE_INTEGRITY"}:
        return "coding_agent"
    return "coding_agent"


def parse_semgrep_findings(path: Path, worktree: Path, files_by_name: dict[str, ChangedFile], head_sha: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text("utf-8") or "{}")
    except json.JSONDecodeError:
        return []
    findings: list[dict[str, Any]] = []
    for result in payload.get("results", []) if isinstance(payload, dict) else []:
        if not isinstance(result, dict):
            continue
        changed = path_to_changed(str(result.get("path") or ""), worktree, files_by_name)
        if not changed:
            continue
        extra = result.get("extra") if isinstance(result.get("extra"), dict) else {}
        check_id = canonical_rule_id(str(result.get("check_id") or "semgrep"))
        line_no = (result.get("start") or {}).get("line") if isinstance(result.get("start"), dict) else None
        parsed_line = int(line_no) if line_no else None
        severity = "high" if str(extra.get("severity", "")).upper() == "ERROR" else "medium"
        message = str(extra.get("message") or "Semgrep 静态规则命中，需要人工确认风险。")
        evidence = str(extra.get("lines") or "")
        source_evidence = source_line_evidence(str(result.get("path") or ""), worktree, parsed_line)
        if invalid_tool_evidence(evidence):
            evidence = source_evidence or check_id
        elif source_evidence and source_evidence not in evidence:
            evidence = f"{evidence}\nSource:\n{source_evidence}"
        item = tool_finding(
            agent_for_static_rule(check_id, message),
            severity,
            changed,
            parsed_line,
            f"Semgrep 命中：{check_id}",
            message,
            "结合规则命中位置修复代码，并保留必要测试。",
            evidence,
            head_sha,
            "semgrep",
        )
        item["tool_rule_id"] = check_id
        findings.append(item)
    return findings


def parse_gitleaks_findings(path: Path, worktree: Path, files_by_name: dict[str, ChangedFile], head_sha: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text("utf-8") or "[]")
    except json.JSONDecodeError:
        return []
    findings: list[dict[str, Any]] = []
    rows = payload if isinstance(payload, list) else payload.get("findings", []) if isinstance(payload, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        changed = path_to_changed(str(row.get("File") or row.get("file") or ""), worktree, files_by_name)
        if not changed:
            continue
        line_no = row.get("StartLine") or row.get("startLine")
        rule = str(row.get("RuleID") or row.get("rule") or "secret")
        findings.append(
            tool_finding(
                "security_agent",
                "high",
                changed,
                int(line_no) if line_no else None,
                f"Gitleaks 疑似密钥：{rule}",
                "静态密钥扫描发现疑似敏感信息进入 MR。",
                "移除敏感值，改用 secret store 或环境变量，并轮换已暴露凭据。",
                str(row.get("Description") or row.get("Match") or rule),
                head_sha,
                "gitleaks",
            )
        )
    return findings


def parse_ruff_findings(path: Path, worktree: Path, files_by_name: dict[str, ChangedFile], head_sha: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text("utf-8") or "[]")
    except json.JSONDecodeError:
        return []
    findings: list[dict[str, Any]] = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict):
            continue
        changed = path_to_changed(str(row.get("filename") or ""), worktree, files_by_name)
        if not changed:
            continue
        location = row.get("location") if isinstance(row.get("location"), dict) else {}
        code = str(row.get("code") or "ruff")
        findings.append(
            tool_finding(
                "backend_agent",
                "low",
                changed,
                int(location.get("row")) if location.get("row") else None,
                f"Ruff 命中：{code}",
                str(row.get("message") or "Python 静态检查命中。"),
                "按 Ruff 提示修复，并确认不影响业务行为。",
                code,
                head_sha,
                "ruff",
            )
        )
    return findings


def parse_eslint_findings(path: Path, worktree: Path, files_by_name: dict[str, ChangedFile], head_sha: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text("utf-8") or "[]")
    except json.JSONDecodeError:
        return []
    findings: list[dict[str, Any]] = []
    for file_result in payload if isinstance(payload, list) else []:
        if not isinstance(file_result, dict):
            continue
        changed = path_to_changed(str(file_result.get("filePath") or ""), worktree, files_by_name)
        if not changed:
            continue
        for message in file_result.get("messages", []):
            if not isinstance(message, dict):
                continue
            rule = str(message.get("ruleId") or "eslint")
            severity = "medium" if int(message.get("severity") or 0) >= 2 else "low"
            findings.append(
                tool_finding(
                    "backend_agent",
                    severity,
                    changed,
                    int(message.get("line")) if message.get("line") else None,
                    f"ESLint 命中：{rule}",
                    str(message.get("message") or "JavaScript/TypeScript 静态检查命中。"),
                    "按 ESLint 提示修复，并确认不影响交互和接口行为。",
                    rule,
                    head_sha,
                    "eslint",
                )
            )
    return findings


def match_external_report_path(path_value: str, files_by_name: dict[str, ChangedFile]) -> ChangedFile | None:
    normalized = (path_value or "").replace("\\", "/").lstrip("./")
    if normalized in files_by_name:
        return files_by_name[normalized]
    for name, changed in files_by_name.items():
        if normalized.endswith(name) or name.endswith(normalized):
            return changed
    return None


def external_report_findings(
    conn: sqlite3.Connection,
    mr_id: str,
    head_sha: str,
    files_by_name: dict[str, ChangedFile],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'external_review_reports'"
    ).fetchone()
    if not table:
        return [], []
    rows = conn.execute(
        """
        SELECT *
        FROM external_review_reports
        WHERE merge_request_id = ?
          AND (commit_sha = ? OR commit_sha = '')
          AND status IN ('received', 'completed')
        ORDER BY created_at
        """,
        (mr_id, head_sha),
    ).fetchall()
    findings: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        parsed = parse_external_report_payload(row["report_type"], row["report_format"], payload)
        reports.append(
            {
                "id": row["id"],
                "tool": parsed.get("tool") or row["report_type"],
                "status": parsed.get("status"),
                "finding_count": parsed.get("finding_count") or len(parsed.get("findings") or []),
                "format": row["report_format"],
            }
        )
        for raw in parsed.get("findings") or []:
            if not isinstance(raw, dict):
                continue
            changed = match_external_report_path(str(raw.get("file_path") or ""), files_by_name)
            if not changed:
                continue
            item = dict(raw)
            item["head_sha"] = head_sha
            item["file_path"] = changed.filename
            item["line_start"] = int(item["line_start"]) if item.get("line_start") else None
            item["line_end"] = int(item["line_end"]) if item.get("line_end") else item["line_start"]
            item["dedupe_hash"] = sha1(
                "|".join(
                    [
                        str(item.get("tool_name") or row["report_type"]),
                        str(item.get("agent_id") or "coding_agent"),
                        str(item.get("tool_rule_id") or item.get("title") or ""),
                        changed.filename,
                        str(item.get("line_start") or ""),
                        str(item.get("evidence") or "")[:120],
                    ]
                )
            )
            findings.append(item)
    return findings, reports


def parse_tool_report_file(
    report_type: str,
    report_format: str,
    report_path: Path,
    files_by_name: dict[str, ChangedFile],
    head_sha: str,
) -> list[dict[str, Any]]:
    if not report_path.exists():
        return []
    try:
        content = report_path.read_text("utf-8", errors="replace")
    except OSError:
        return []
    parsed = parse_external_report_payload(report_type, report_format, {"content": content})
    findings: list[dict[str, Any]] = []
    for raw in parsed.get("findings") or []:
        if not isinstance(raw, dict):
            continue
        if not should_keep_tool_finding(report_type, raw):
            continue
        changed = match_external_report_path(str(raw.get("file_path") or ""), files_by_name)
        if not changed:
            continue
        item = dict(raw)
        item["head_sha"] = head_sha
        item["file_path"] = changed.filename
        item["line_start"] = int(item["line_start"]) if item.get("line_start") else None
        item["line_end"] = int(item["line_end"]) if item.get("line_end") else item["line_start"]
        item["dedupe_hash"] = sha1(
            "|".join(
                [
                    str(item.get("tool_name") or report_type),
                    str(item.get("agent_id") or "coding_agent"),
                    str(item.get("tool_rule_id") or item.get("title") or ""),
                    changed.filename,
                    str(item.get("line_start") or ""),
                    str(item.get("evidence") or "")[:120],
                ]
            )
        )
        findings.append(item)
    return findings


CHECKSTYLE_STYLE_NOISE_RULES = (
    "AbbreviationAsWordInName",
    "AvoidStarImport",
    "CustomImportOrder",
    "EmptyLineSeparator",
    "FinalParameters",
    "Indentation",
    "Javadoc",
    "LineLength",
    "MissingJavadoc",
    "NeedBraces",
    "NoWhitespace",
    "OneStatementPerLine",
    "OperatorWrap",
    "OuterTypeFilename",
    "ParameterName",
    "RegexpSingleline",
    "SeparatorWrap",
    "SummaryJavadoc",
    "TodoComment",
    "VariableDeclarationUsageDistance",
    "Whitespace",
)

CHECKSTYLE_ACTIONABLE_RULE_HINTS = (
    "ArrayTrailingComma",
    "AvoidHidingCauseException",
    "CovariantEquals",
    "DeclarationOrder",
    "EqualsHashCode",
    "FallThrough",
    "Finalizer",
    "HiddenField",
    "IllegalCatch",
    "IllegalInstantiation",
    "IllegalThrows",
    "InnerAssignment",
    "MissingCtor",
    "ModifiedControlVariable",
    "MutableException",
    "NestedForDepth",
    "NestedIfDepth",
    "NestedTryDepth",
    "OneTopLevelClass",
    "OverloadMethodsDeclarationOrder",
    "ReturnCount",
    "SimplifyBooleanExpression",
    "StringLiteralEquality",
    "SuperClone",
    "SuperFinalize",
    "UnnecessaryParentheses",
)


def should_keep_tool_finding(report_type: str, raw: dict[str, Any]) -> bool:
    tool = str(raw.get("tool_name") or report_type or "").lower()
    if tool != "checkstyle":
        return True
    rule_id = str(raw.get("tool_rule_id") or raw.get("rule_id") or raw.get("title") or "")
    message = str(raw.get("problem_description") or raw.get("message") or raw.get("evidence") or "")
    combined = f"{rule_id} {message}"
    if any(hint in combined for hint in CHECKSTYLE_ACTIONABLE_RULE_HINTS):
        return True
    if any(hint in combined for hint in CHECKSTYLE_STYLE_NOISE_RULES):
        return False
    return False


def changed_files_with_suffix(files: list[ChangedFile], suffixes: tuple[str, ...]) -> list[ChangedFile]:
    return [item for item in files if item.filename.replace("\\", "/").endswith(suffixes)]


def changed_file_paths(worktree: Path, files: list[ChangedFile]) -> list[str]:
    paths: list[str] = []
    for item in files:
        path = worktree / safe_relative_path(item.filename)
        if path.exists():
            paths.append(str(path))
    return paths


def dependency_manifest_files(files: list[ChangedFile]) -> list[ChangedFile]:
    manifest_names = (
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "gradle.lockfile",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "requirements.txt",
        "poetry.lock",
        "Pipfile.lock",
        "go.mod",
        "go.sum",
        "Cargo.lock",
    )
    return [
        item
        for item in files
        if item.filename.replace("\\", "/").endswith(manifest_names)
    ]


def iac_or_container_files(files: list[ChangedFile]) -> list[ChangedFile]:
    suffixes = (".tf", ".yaml", ".yml", ".json", "Dockerfile", ".dockerfile", "docker-compose.yml", "docker-compose.yaml")
    return [item for item in files if item.filename.replace("\\", "/").endswith(suffixes)]


def openapi_files(files: list[ChangedFile]) -> list[ChangedFile]:
    candidates: list[ChangedFile] = []
    for item in files:
        name = item.filename.replace("\\", "/").lower()
        if not name.endswith((".yaml", ".yml", ".json")):
            continue
        if "openapi" in name or "swagger" in name or "/api/" in name:
            candidates.append(item)
    return candidates


def find_compiled_class_dirs(worktree: Path) -> list[Path]:
    candidates = [
        worktree / "target" / "classes",
        worktree / "build" / "classes" / "java" / "main",
        worktree / "build" / "classes",
    ]
    return [path for path in candidates if path.exists()]


def spotbugs_class_dirs(project_config: dict[str, Any] | None, worktree: Path) -> list[Path]:
    runner_cfg = static_runner_config(project_config, "spotbugs")
    configured = (
        configured_path_values(runner_cfg.get("class_dirs"))
        + configured_path_values(runner_cfg.get("class_dir"))
        + configured_path_values(runner_cfg.get("compiled_classes_path"))
    )
    dirs: list[Path] = []
    for value in configured:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (worktree / path).resolve()
        if path.exists() and path.is_dir():
            dirs.append(path)
    return dirs or find_compiled_class_dirs(worktree)


def configured_analysis_worktree(project_config: dict[str, Any] | None) -> Path | None:
    policy = tool_policy_config(project_config)
    path_value = (
        policy.get("analysis_worktree_path")
        or policy.get("full_repo_worktree_path")
        or policy.get("workspace_path")
    )
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path if path.exists() and path.is_dir() else None


def build_repo_related_context(
    *,
    project_config: dict[str, Any],
    sandbox_dir: Path,
    repository_id: str,
    head_sha: str,
    files: list[ChangedFile],
    source_file_contents: dict[str, str] | None = None,
) -> dict[str, Any]:
    diff_worktree = materialize_changed_files(sandbox_dir, files, source_file_contents)
    configured_worktree = configured_analysis_worktree(project_config)
    worktree = configured_worktree or diff_worktree
    worktree_mode = source_worktree_mode(
        configured_worktree=configured_worktree,
        source_file_contents=source_file_contents,
        files=files,
    )
    index_sha = f"{head_sha}-{worktree_mode}"
    index_info = build_repo_index(worktree, repository_id, index_sha, ROOT / "data" / "repo_index")
    related = resolve_diff_symbols(index_info, worktree, files)
    return {
        **index_info,
        **related,
        "worktree": str(worktree),
        "worktree_mode": worktree_mode,
    }


def kics_queries_args(project_config: dict[str, Any] | None) -> list[str]:
    runner_cfg = static_runner_config(project_config, "kics")
    candidates = [
        str(runner_cfg.get("queries_path") or ""),
        str(runner_cfg.get("custom_queries_path") or ""),
        os.environ.get("KICS_QUERIES_PATH", ""),
        str(STATIC_RULES_DIR / "kics" / "queries"),
        "/opt/homebrew/opt/kics/share/kics/assets/queries",
        "/usr/local/opt/kics/share/kics/assets/queries",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists() and path.is_dir():
            return ["--queries-path", str(path)]
    return []


def java_static_tool_results(
    recorder: Recorder,
    span_id: str,
    project_config: dict[str, Any] | None,
    worktree: Path,
    outputs_dir: Path,
    files: list[ChangedFile],
    files_by_name: dict[str, ChangedFile],
    head_sha: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    java_files = changed_files_with_suffix(files, (".java",))
    java_targets = changed_file_paths(worktree, java_files)

    pmd_output = outputs_dir / "pmd.xml"
    if java_targets:
        results.append(
            run_static_tool_with_policy(
                recorder,
                span_id,
                project_config,
                    "pmd",
                    [
                        "check",
                        "-d",
                        str(worktree),
                        "-R",
                        pmd_rulesets(project_config),
                        "-f",
                        "xml",
                        "-r",
                        str(pmd_output),
                    ],
                    pmd_output,
                    {0, 4},
                )
            )
        findings.extend(parse_tool_report_file("pmd", "xml", pmd_output, files_by_name, head_sha))
    else:
        results.append(skipped_static_tool_with_policy(recorder, span_id, project_config, "pmd", "skipped_no_java_targets"))

    checkstyle_output = outputs_dir / "checkstyle.xml"
    if java_targets:
        results.append(
            run_static_tool_with_policy(
                recorder,
                span_id,
                project_config,
                "checkstyle",
                ["-c", str(checkstyle_config_path(outputs_dir.parent.parent, project_config)), "-f", "xml", "-o", str(checkstyle_output), *java_targets],
                checkstyle_output,
                {0, 1},
            )
        )
        findings.extend(parse_tool_report_file("checkstyle", "xml", checkstyle_output, files_by_name, head_sha))
    else:
        results.append(skipped_static_tool_with_policy(recorder, span_id, project_config, "checkstyle", "skipped_no_java_targets"))

    spotbugs_output = outputs_dir / "spotbugs.xml"
    class_dirs = spotbugs_class_dirs(project_config, worktree)
    if class_dirs:
        results.append(
            run_static_tool_with_policy(
                recorder,
                span_id,
                project_config,
                "spotbugs",
                ["-textui", "-xml:withMessages", "-output", str(spotbugs_output), *[str(path) for path in class_dirs]],
                spotbugs_output,
                {0, 1},
            )
        )
        findings.extend(parse_tool_report_file("spotbugs", "xml", spotbugs_output, files_by_name, head_sha))
    else:
        results.append(skipped_static_tool_with_policy(recorder, span_id, project_config, "spotbugs", "skipped_no_compiled_classes"))

    return results, findings


def security_dependency_tool_results(
    recorder: Recorder,
    span_id: str,
    project_config: dict[str, Any] | None,
    worktree: Path,
    outputs_dir: Path,
    files: list[ChangedFile],
    files_by_name: dict[str, ChangedFile],
    head_sha: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    manifests = dependency_manifest_files(files)

    dependency_check_output_dir = outputs_dir / "dependency-check"
    dependency_check_output = dependency_check_output_dir / "dependency-check-report.json"
    if manifests:
        results.append(
            run_static_tool_with_policy(
                recorder,
                span_id,
                project_config,
                "dependency-check",
                dependency_check_args(project_config, worktree, dependency_check_output_dir),
                dependency_check_output,
                {0, 1},
            )
        )
        findings.extend(parse_tool_report_file("dependency-check", "json", dependency_check_output, files_by_name, head_sha))
    else:
        results.append(
            skipped_static_tool_with_policy(recorder, span_id, project_config, "dependency-check", "skipped_no_dependency_manifests")
        )

    osv_output = outputs_dir / "osv-scanner.json"
    if manifests:
        results.append(
            run_static_tool_with_policy(
                recorder,
                span_id,
                project_config,
                "osv-scanner",
                osv_scanner_args(project_config, worktree, osv_output),
                osv_output,
                {0, 1},
            )
        )
        findings.extend(parse_tool_report_file("osv", "json", osv_output, files_by_name, head_sha))
    else:
        results.append(skipped_static_tool_with_policy(recorder, span_id, project_config, "osv-scanner", "skipped_no_dependency_manifests"))

    trivy_output = outputs_dir / "trivy.json"
    scan_targets = manifests or iac_or_container_files(files)
    if scan_targets:
        results.append(
            run_static_tool_with_policy(
                recorder,
                span_id,
                project_config,
                "trivy",
                trivy_args(project_config, worktree, trivy_output),
                trivy_output,
                {0, 1},
            )
        )
        findings.extend(parse_tool_report_file("trivy", "json", trivy_output, files_by_name, head_sha))
    else:
        results.append(skipped_static_tool_with_policy(recorder, span_id, project_config, "trivy", "skipped_no_dependency_or_iac_targets"))

    return results, findings


def iac_and_api_tool_results(
    recorder: Recorder,
    span_id: str,
    project_config: dict[str, Any] | None,
    worktree: Path,
    outputs_dir: Path,
    files: list[ChangedFile],
    files_by_name: dict[str, ChangedFile],
    head_sha: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    iac_targets = iac_or_container_files(files)

    kics_output_dir = outputs_dir / "kics"
    kics_output = kics_output_dir / "kics.json"
    if iac_targets:
        results.append(
            run_static_tool_with_policy(
                recorder,
                span_id,
                project_config,
                "kics",
                [
                    "scan",
                    "-p",
                    str(worktree),
                    "-o",
                    str(kics_output_dir),
                    "--report-formats",
                    "json",
                    "--output-name",
                    "kics",
                    *kics_queries_args(project_config),
                ],
                kics_output,
                {0, 20, 30, 40, 50},
            )
        )
        findings.extend(parse_tool_report_file("kics", "json", kics_output, files_by_name, head_sha))
    else:
        results.append(skipped_static_tool_with_policy(recorder, span_id, project_config, "kics", "skipped_no_iac_targets"))

    api_files = openapi_files(files)
    policy = tool_policy_config(project_config)
    openapi_policy = policy.get("openapi_diff") if isinstance(policy.get("openapi_diff"), dict) else {}
    base_spec = str(openapi_policy.get("base_spec_path") or "")
    if api_files and base_spec:
        head_spec = worktree / safe_relative_path(api_files[0].filename)
        base_path = Path(base_spec)
        if not base_path.is_absolute():
            base_path = (ROOT / base_path).resolve()
        openapi_output = outputs_dir / "openapi-diff.json"
        if base_path.exists():
            results.append(
                run_static_tool_with_policy(
                    recorder,
                    span_id,
                    project_config,
                    "openapi-diff",
                    [str(base_path), str(head_spec), "--json"],
                    openapi_output,
                    {0, 1},
                )
            )
            findings.extend(parse_tool_report_file("openapi-diff", "json", openapi_output, files_by_name, head_sha))
        else:
            results.append(
                skipped_static_tool_with_policy(recorder, span_id, project_config, "openapi-diff", "skipped_base_spec_missing")
            )
    elif api_files:
        results.append(
            skipped_static_tool_with_policy(recorder, span_id, project_config, "openapi-diff", "skipped_requires_baseline_spec")
        )
    else:
        results.append(skipped_static_tool_with_policy(recorder, span_id, project_config, "openapi-diff", "skipped_no_openapi_targets"))

    return results, findings


def project_id_for_merge_request(conn: sqlite3.Connection | None, mr_id: str | None) -> str | None:
    if conn is None or not mr_id:
        return None
    try:
        row = conn.execute(
            """
            SELECT r.project_id
            FROM merge_requests mr
            JOIN repositories r ON r.id = mr.repository_id
            WHERE mr.id = ?
            """,
            (mr_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    return str(row["project_id"]) if row else None


def load_baseline_fingerprints(conn: sqlite3.Connection, project_id: str) -> set[str]:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'review_baseline_suppressions'"
    ).fetchone()
    if not table:
        return set()
    rows = conn.execute(
        """
        SELECT fingerprint
        FROM review_baseline_suppressions
        WHERE project_id = ?
          AND (expires_at IS NULL OR expires_at = '' OR expires_at > CURRENT_TIMESTAMP)
        """,
        (project_id,),
    ).fetchall()
    return {str(row["fingerprint"]) for row in rows}


def apply_baseline_suppression(
    conn: sqlite3.Connection | None,
    project_id: str | None,
    project_config: dict[str, Any] | None,
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    baseline_policy = tool_policy_config(project_config).get("baseline")
    if isinstance(baseline_policy, dict) and baseline_policy.get("enabled") is False:
        return findings, 0
    if conn is None or not project_id:
        return findings, 0
    fingerprints = load_baseline_fingerprints(conn, project_id)
    if not fingerprints:
        return findings, 0
    kept: list[dict[str, Any]] = []
    suppressed = 0
    for finding in findings:
        normalized = normalize_tool_finding(finding)
        if str(normalized.get("dedupe_hash")) in fingerprints:
            suppressed += 1
            continue
        kept.append(normalized)
    return kept, suppressed


def apply_project_rule_policy(
    project_config: dict[str, Any] | None,
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    policy = tool_policy_config(project_config)
    rules = policy.get("rule_overrides") if isinstance(policy.get("rule_overrides"), dict) else {}
    if not rules:
        return findings, 0, []
    kept: list[dict[str, Any]] = []
    suppressed = 0
    applied: list[dict[str, Any]] = []
    for finding in findings:
        item = normalize_tool_finding(finding)
        keys = [
            str(item.get("tool_rule_id") or ""),
            str(item.get("normalized_rule_category") or ""),
            str(item.get("title") or ""),
        ]
        override = next((rules.get(key) for key in keys if isinstance(rules.get(key), dict)), None)
        if override and override.get("enabled") is False:
            suppressed += 1
            applied.append({"rule": keys[0], "category": keys[1], "action": "disabled"})
            continue
        if override:
            if override.get("severity"):
                item["severity"] = str(override["severity"])
            if override.get("confidence"):
                item["confidence"] = float(override["confidence"])
            applied.append({"rule": keys[0], "category": keys[1], "action": "override"})
        kept.append(item)
    return kept, suppressed, applied


def run_external_static_prescan(
    recorder: Recorder,
    span_id: str,
    sandbox_dir: Path,
    files: list[ChangedFile],
    head_sha: str,
    conn: sqlite3.Connection | None = None,
    mr_id: str | None = None,
    project_config: dict[str, Any] | None = None,
    source_file_contents: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    diff_worktree = materialize_changed_files(sandbox_dir, files, source_file_contents)
    configured_worktree = configured_analysis_worktree(project_config)
    worktree = configured_worktree or diff_worktree
    worktree_mode = source_worktree_mode(
        configured_worktree=configured_worktree,
        source_file_contents=source_file_contents,
        files=files,
    )
    expected_source_count = source_content_candidate_count(files)
    fetched_source_count = len(source_file_contents or {})
    outputs_dir = sandbox_dir / "prescan" / "tool-outputs"
    files_by_name = {changed.filename.replace("\\", "/"): changed for changed in files}
    target_paths = [str(worktree / safe_relative_path(changed.filename)) for changed in files]
    python_targets = [
        str(worktree / safe_relative_path(changed.filename))
        for changed in files
        if changed.filename.endswith(".py")
    ]
    eslint_targets = [
        str(worktree / safe_relative_path(changed.filename))
        for changed in files
        if changed.filename.endswith((".js", ".jsx", ".ts", ".tsx"))
    ]

    semgrep_output = outputs_dir / "semgrep.json"
    gitleaks_output = outputs_dir / "gitleaks.json"
    ruff_output = outputs_dir / "ruff.json"
    eslint_output = outputs_dir / "eslint.json"
    bandit_output = outputs_dir / "bandit.json"

    outputs_dir.mkdir(parents=True, exist_ok=True)
    tree_started = time.time()
    tree_graph = build_tree_sitter_graph(worktree)
    tree_graph_output = outputs_dir / "tree-sitter-code-graph.json"
    tree_graph_output.write_text(json.dumps(tree_graph, ensure_ascii=False, indent=2), "utf-8")
    tree_status = "completed" if tree_graph.get("status") == "indexed" else str(tree_graph.get("status") or "failed")
    recorder.tool_call(
        span_id,
        "static.tree_sitter_code_graph",
        tree_status,
        int((time.time() - tree_started) * 1000),
        args_summary=f"worktree={worktree}; mode={worktree_mode}; source_files={fetched_source_count}/{expected_source_count}",
        output_summary=(
            f"files={tree_graph.get('parsed_file_count', 0)}/{tree_graph.get('file_count', 0)}, "
            f"classes={len(tree_graph.get('classes') or [])}, "
            f"functions={len(tree_graph.get('functions') or [])}, "
            f"calls={len(tree_graph.get('callers') or [])}"
        ),
        output_ref={"path": str(tree_graph_output)},
        tool_version="python-tree-sitter",
    )

    results = [
        {
            "tool": "tree_sitter_code_graph",
            "available": tree_graph.get("status") == "indexed",
            "status": tree_status,
            "version": "python-tree-sitter",
            "stdout_path": str(tree_graph_output),
            "returncode": 0 if tree_graph.get("status") == "indexed" else 1,
            "findings": [],
            "metrics": {
                "worktree_mode": worktree_mode,
                "source_file_count": fetched_source_count,
                "expected_source_file_count": expected_source_count,
                "file_count": tree_graph.get("file_count", 0),
                "parsed_file_count": tree_graph.get("parsed_file_count", 0),
                "class_count": len(tree_graph.get("classes") or []),
                "function_count": len(tree_graph.get("functions") or []),
                "call_count": len(tree_graph.get("callers") or []),
                "impact_symbol_count": len(tree_graph.get("impact_symbols") or []),
            },
        },
        run_semgrep_prescan(
            recorder,
            span_id,
            project_config,
            sandbox_dir,
            semgrep_output,
            target_paths,
            worktree,
        ),
        run_static_tool_with_policy(
            recorder,
            span_id,
            project_config,
            "gitleaks",
            [
                "detect",
                "--no-git",
                "--source",
                str(worktree),
                *gitleaks_config_args(project_config, sandbox_dir),
                "--report-format",
                "json",
                "--report-path",
                str(gitleaks_output),
            ],
            gitleaks_output,
            {0, 1},
        ),
        run_static_tool_with_policy(
            recorder,
            span_id,
            project_config,
            "ruff",
            ["check", "--output-format", "json", *python_targets],
            ruff_output,
            {0, 1},
        ) if python_targets else skipped_static_tool_with_policy(recorder, span_id, project_config, "ruff", "skipped_no_targets"),
        run_static_tool_with_policy(
            recorder,
            span_id,
            project_config,
            "bandit",
            ["-f", "json", "-o", str(bandit_output), *python_targets],
            bandit_output,
            {0, 1},
        ) if python_targets else skipped_static_tool_with_policy(recorder, span_id, project_config, "bandit", "skipped_no_targets"),
        run_static_tool_with_policy(
            recorder,
            span_id,
            project_config,
            "eslint",
            ["--format", "json", *eslint_targets],
            eslint_output,
            {0, 1},
        ) if eslint_targets else skipped_static_tool_with_policy(recorder, span_id, project_config, "eslint", "skipped_no_targets"),
    ]
    java_results, java_tool_findings = java_static_tool_results(
        recorder,
        span_id,
        project_config,
        worktree,
        outputs_dir,
        files,
        files_by_name,
        head_sha,
    )
    security_results, security_tool_findings = security_dependency_tool_results(
        recorder,
        span_id,
        project_config,
        worktree,
        outputs_dir,
        files,
        files_by_name,
        head_sha,
    )
    iac_results, iac_tool_findings = iac_and_api_tool_results(
        recorder,
        span_id,
        project_config,
        worktree,
        outputs_dir,
        files,
        files_by_name,
        head_sha,
    )
    results.extend(java_results + security_results + iac_results)

    java_web_findings: list[dict[str, Any]] = []
    if builtin_java_heuristics_enabled(project_config):
        java_web_findings = scan_java_web_files(files, head_sha)
        recorder.tool_call(
            span_id,
            "static.java_web_static",
            "completed",
            0,
            args_summary="enable_builtin_java_heuristics=true",
            output_summary=f"builtin heuristic findings={len(java_web_findings)}",
            tool_version="jolt-builtin-static-analysis-v1",
        )
        results.append(
            {
                "tool": "java_web_static",
                "available": True,
                "status": "completed",
                "version": "jolt-builtin-static-analysis-v1",
                "findings": java_web_findings,
                "builtin": True,
            }
        )
    else:
        results.append(disabled_static_tool(recorder, span_id, "java_web_static", "disabled_by_default_use_open_source_tools"))
    external_findings: list[dict[str, Any]] = []
    external_reports: list[dict[str, Any]] = []
    if conn is not None and mr_id:
        external_findings, external_reports = external_report_findings(conn, mr_id, head_sha, files_by_name)
    findings = dedupe_tool_findings(
        parse_semgrep_findings(semgrep_output, worktree, files_by_name, head_sha)
        + parse_gitleaks_findings(gitleaks_output, worktree, files_by_name, head_sha)
        + parse_ruff_findings(ruff_output, worktree, files_by_name, head_sha)
        + parse_eslint_findings(eslint_output, worktree, files_by_name, head_sha)
        + java_tool_findings
        + security_tool_findings
        + iac_tool_findings
        + external_findings
        + java_web_findings
    )
    findings, rule_policy_suppressed, rule_policy_applied = apply_project_rule_policy(project_config, findings)
    project_id = project_id_for_merge_request(conn, mr_id)
    findings, baseline_suppressed = apply_baseline_suppression(conn, project_id, project_config, findings)
    summary = {
        "worktree": str(worktree),
        "diff_worktree": str(diff_worktree),
        "worktree_mode": worktree_mode,
        "source_file_count": fetched_source_count,
        "expected_source_file_count": expected_source_count,
        "tools": results,
        "tool_finding_count": len(findings),
        "baseline_suppressed": baseline_suppressed,
        "rule_policy_suppressed": rule_policy_suppressed,
        "rule_policy_applied": rule_policy_applied[:50],
        "external_reports": external_reports,
        "raw_reports": [
            {
                "tool": item.get("tool"),
                "status": item.get("status"),
                "version": item.get("version"),
                "returncode": item.get("returncode"),
                "path": item.get("stdout_path"),
                "exists": Path(str(item.get("stdout_path"))).exists() if item.get("stdout_path") else False,
            }
            for item in results
            if item.get("stdout_path")
        ],
        "scan_policy": {
            "mode": "open_source_tools_first",
            "builtin_java_heuristics_enabled": builtin_java_heuristics_enabled(project_config),
            "semgrep_config": semgrep_config_args(project_config, sandbox_dir),
            "gitleaks_config": gitleaks_config_args(project_config, sandbox_dir),
        },
        "available_tools": [item["tool"] for item in results if item.get("available")],
        "unavailable_tools": [item["tool"] for item in results if not item.get("available")],
        "disabled_tools": [item["tool"] for item in results if item.get("status") == "disabled"],
    }
    return summary, findings


def make_finding(
    agent_id: str,
    severity: str,
    changed: ChangedFile,
    line_no: int | None,
    title: str,
    description: str,
    recommendation: str,
    evidence: str,
    head_sha: str,
    suggested_code: str | None = None,
) -> dict[str, Any]:
    confidence = {"high": 0.86, "medium": 0.78, "low": 0.68}.get(severity, 0.7)
    default_suggested_code = (
        f"// 建议修改示例：请在 {changed.filename}"
        f"{f':{line_no}' if line_no else ''} 按以下方向调整\n"
        f"// {recommendation}"
    )
    return {
        "severity": severity,
        "confidence": confidence,
        "agent_id": agent_id,
        "head_sha": head_sha,
        "dedupe_hash": sha1("|".join([agent_id, title, changed.filename, evidence.strip()[:120]])),
        "file_path": changed.filename,
        "line_start": line_no,
        "line_end": line_no,
        "title": title,
        "problem_description": description,
        "recommendation": recommendation,
        "suggested_code": (suggested_code or default_suggested_code).strip()[:4000],
        "evidence": evidence.strip()[:500],
    }


def load_agent_configs(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM agent_configs WHERE project_id = ? ORDER BY agent_id",
        (project_id,),
    ).fetchall()
    config_by_agent: dict[str, sqlite3.Row] = {row["agent_id"]: row for row in rows}
    profiles = load_expert_profiles(conn, project_id)
    result: list[dict[str, Any]] = []
    for profile in profiles:
        config_row = config_by_agent.get(profile.agent_key)
        if config_row and int(config_row["enabled"]) != 1:
            continue
        agent = profile.to_agent_config()
        if config_row:
            applies_to = json.loads(config_row["applies_to_json"] or "{}")
            agent.update(
                {
                    "display_name": config_row["display_name"],
                    "applies_to": {
                        **agent["applies_to"],
                        **applies_to,
                        "persona": profile.role_profile,
                        "review_scope": profile.responsibility_scope,
                        "excluded_scope": profile.excluded_scope,
                    },
                    "tools": json.loads(config_row["tools_json"] or "[]"),
                    "skills": json.loads(config_row["skills_json"] or "[]"),
                    "rule_sets": json.loads(config_row["rule_sets_json"] or "[]"),
                    "requires_deepagents": bool(config_row["requires_deepagents"]) if "requires_deepagents" in config_row.keys() else False,
                    "min_confidence": max(float(config_row["min_confidence"]), profile.min_confidence),
                    "max_findings_per_mr": max(1, min(int(config_row["max_findings_per_mr"]), 10)),
                    "max_tool_calls": profile.max_tool_calls,
                }
            )
        custom_skills = load_bound_custom_skill_keys(conn, project_id, profile.agent_key)
        agent["skills"] = dedupe_strings([*(agent.get("skills") or []), *custom_skills])
        agent["custom_skills"] = custom_skills
        agent["skill_assets"] = load_bound_custom_skill_assets(conn, project_id, custom_skills)
        if custom_skills or agent["skill_assets"]:
            agent["requires_deepagents"] = True
            agent["max_tool_calls"] = max(int(agent.get("max_tool_calls") or 0), 6)
        agent["bound_rules"] = load_bound_rules(conn, project_id, profile.agent_key)
        result.append(agent)
    if result:
        return result

    result = []
    for row in [item for item in rows if int(item["enabled"]) == 1]:
        result.append(
            {
                "agent_id": row["agent_id"],
                "display_name": row["display_name"],
                "applies_to": json.loads(row["applies_to_json"] or "{}"),
                "tools": json.loads(row["tools_json"] or "[]"),
                "skills": json.loads(row["skills_json"] or "[]"),
                "rule_sets": json.loads(row["rule_sets_json"] or "[]"),
                "requires_deepagents": bool(row["requires_deepagents"]) if "requires_deepagents" in row.keys() else False,
                "min_confidence": float(row["min_confidence"]),
                "max_findings_per_mr": int(row["max_findings_per_mr"]),
            }
        )
    if result:
        return result
    return [
        {
            "agent_id": "security_agent",
            "display_name": "Security Agent",
            "applies_to": {"exclusive_scope": "security", "persona": "安全专家", "review_scope": "安全问题"},
            "tools": [],
            "min_confidence": 0.72,
            "max_findings_per_mr": 5,
            "skills": ["security-review"],
        },
        {
            "agent_id": "coding_agent",
            "display_name": "General Coding Agent",
            "applies_to": {"exclusive_scope": "general_coding", "persona": "通用编码专家", "review_scope": "通用实现问题"},
            "tools": [],
            "min_confidence": 0.74,
            "max_findings_per_mr": 5,
            "skills": ["coding-review"],
        },
        {
            "agent_id": "test_agent",
            "display_name": "Test Agent",
            "applies_to": {"exclusive_scope": "test_coverage", "persona": "测试专家", "review_scope": "测试覆盖问题"},
            "tools": [],
            "min_confidence": 0.7,
            "max_findings_per_mr": 5,
            "skills": ["test-review"],
        },
    ]


def dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def load_bound_custom_skill_keys(conn: sqlite3.Connection, project_id: str, agent_key: str) -> list[str]:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'expert_skill_bindings'"
    ).fetchone()
    if not table:
        return []
    rows = conn.execute(
        """
        SELECT esb.skill_key
        FROM expert_skill_bindings esb
        JOIN custom_skills cs
          ON cs.project_id = esb.project_id
         AND cs.skill_key = esb.skill_key
        WHERE esb.project_id = ?
          AND esb.agent_key = ?
          AND esb.enabled = 1
          AND cs.status = 'active'
        ORDER BY esb.priority, esb.skill_key
        """,
        (project_id, agent_key),
    ).fetchall()
    return [str(row["skill_key"]) for row in rows]


def merge_custom_agents(agent_configs: list[dict[str, Any]], project_config: dict[str, Any]) -> list[dict[str, Any]]:
    custom_agents = project_config.get("routing", {}).get("custom_agents")
    if not isinstance(custom_agents, list):
        return agent_configs
    by_id = {str(agent.get("agent_id")): dict(agent) for agent in agent_configs}
    for raw in custom_agents:
        if not isinstance(raw, dict):
            continue
        agent_id = str(raw.get("id") or raw.get("agent_id") or "").strip()
        if not agent_id:
            continue
        by_id[agent_id] = {
            "agent_id": agent_id,
            "display_name": str(raw.get("display_name") or raw.get("name") or agent_id),
            "applies_to": {
                "persona": str(raw.get("description") or raw.get("persona") or "自定义专家"),
                "exclusive_scope": str(raw.get("exclusive_scope") or raw.get("scope") or agent_id),
                "review_scope": str(raw.get("review_scope") or raw.get("description") or ""),
                "excluded_scope": str(raw.get("excluded_scope") or ""),
                "languages": raw.get("languages") if isinstance(raw.get("languages"), list) else [],
                "paths": raw.get("file_patterns") if isinstance(raw.get("file_patterns"), list) else raw.get("paths") if isinstance(raw.get("paths"), list) else [],
                "triggers": raw.get("triggers") if isinstance(raw.get("triggers"), list) else [],
            },
            "tools": raw.get("tools") if isinstance(raw.get("tools"), list) else [],
            "skills": raw.get("skills") if isinstance(raw.get("skills"), list) else [],
            "rule_sets": raw.get("rule_sets") if isinstance(raw.get("rule_sets"), list) else [],
            "min_confidence": float(raw.get("min_confidence") or 0.75),
            "max_findings_per_mr": int(raw.get("max_findings_per_mr") or 5),
            "max_tool_calls": int(raw.get("max_tool_calls") or 4),
            "bound_rules": raw.get("bound_rules") if isinstance(raw.get("bound_rules"), list) else [],
        }
    return list(by_id.values())


def load_custom_skill_summary(
    conn: sqlite3.Connection | None,
    project_id: str | None,
    skill_name: str,
) -> str:
    if conn is None or not project_id:
        return ""
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'custom_skills'"
    ).fetchone()
    if not table:
        return ""
    row = conn.execute(
        """
        SELECT skill_key, name, description, content, version
        FROM custom_skills
        WHERE project_id = ?
          AND skill_key = ?
          AND status = 'active'
        """,
        (project_id, skill_name),
    ).fetchone()
    if not row:
        return ""
    return (
        f"# 自定义检视 Skill：{row['name']}\n\n"
        f"- skill_key: {row['skill_key']}\n"
        f"- version: {row['version']}\n"
        f"- description: {row['description']}\n\n"
        f"{row['content']}\n\n"
        f"{custom_skill_asset_manifest(conn, project_id, skill_name)}"
    )


def load_bound_custom_skill_assets(
    conn: sqlite3.Connection,
    project_id: str,
    skill_keys: list[str],
) -> list[dict[str, Any]]:
    if not skill_keys:
        return []
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'custom_skill_assets'"
    ).fetchone()
    if not table:
        return []
    placeholders = ",".join("?" for _ in skill_keys)
    rows = conn.execute(
        f"""
        SELECT skill_key, asset_path, asset_type, content, executable
        FROM custom_skill_assets
        WHERE project_id = ?
          AND skill_key IN ({placeholders})
        ORDER BY skill_key, asset_path
        """,
        (project_id, *skill_keys),
    ).fetchall()
    return [
        {
            "skill_key": row["skill_key"],
            "asset_path": row["asset_path"],
            "asset_type": row["asset_type"],
            "content": row["content"],
            "executable": bool(row["executable"]),
        }
        for row in rows
    ]


def custom_skill_asset_manifest(conn: sqlite3.Connection | None, project_id: str | None, skill_name: str) -> str:
    if conn is None or not project_id:
        return ""
    assets = load_bound_custom_skill_assets(conn, project_id, [skill_name])
    if not assets:
        return "## Skill Bundle Assets\n\n无 references/scripts/assets 目录资源。"
    lines = ["## Skill Bundle Assets", ""]
    for asset in assets:
        lines.append(
            f"- {asset['asset_path']} ({asset['asset_type']}, executable={str(asset['executable']).lower()})"
        )
    reference_chunks = [
        asset
        for asset in assets
        if str(asset["asset_type"]) in {"skill", "reference"} and str(asset["asset_path"]).endswith((".md", ".txt"))
    ]
    if reference_chunks:
        lines.append("")
        lines.append("## 预加载参考资料")
        for asset in reference_chunks[:5]:
            lines.append(f"\n### {asset['asset_path']}\n")
            lines.append(str(asset["content"])[:3000])
    if any(str(asset["asset_type"]) == "script" for asset in assets):
        lines.append("")
        lines.append("## Scripts 调用策略")
        lines.append("脚本作为标准 Skill 资源注册给 DeepAgents；默认只允许读取脚本内容和调用受控平台工具，不直接执行未沙箱化脚本。")
    return "\n".join(lines)


def load_skill_summary(
    skill_name: str,
    files: list[ChangedFile] | None = None,
    conn: sqlite3.Connection | None = None,
    project_id: str | None = None,
) -> str:
    custom_text = load_custom_skill_summary(conn, project_id, skill_name)
    skill_path = ROOT / "agent-skills" / skill_name / "SKILL.md"
    if not skill_path.exists():
        return custom_text[:12000] if custom_text else f"skill {skill_name} is not available"
    text = skill_path.read_text("utf-8")
    if custom_text:
        text = f"{text}\n\n# 项目自定义 Skill 覆写/补充\n\n{custom_text}"
    loaded_standards: set[Path] = set()

    def append_standard(path: Path, title: str) -> None:
        nonlocal text
        if path.exists() and path not in loaded_standards:
            loaded_standards.add(path)
            text = text + f"\n\n# {title}\n\n" + path.read_text("utf-8")

    append_standard(skill_path.parent / "CORE_STANDARD.md", "绑定通用结构化规范文档")
    languages = sorted({language_for_file(item.filename) for item in (files or []) if language_for_file(item.filename) != "unknown"})
    lang_map = {"javascript": "typescript", "frontend": "typescript"}
    for language in languages:
        normalized = lang_map.get(language, language)
        append_standard(skill_path.parent / f"LANG_{normalized}.md", f"绑定 {normalized} 语言规范文档")
    standard_match = re.search(r"^bound_standard:\s*(\S+)\s*$", text, re.MULTILINE)
    if standard_match and (not files or "java" in languages):
        standard_path = skill_path.parent / standard_match.group(1)
        append_standard(standard_path, "绑定兼容结构化规范文档")
    return text[:12000]


def choose_effort(requested: str, files: list[ChangedFile], risk_score: int, fetch_degraded: bool = False) -> str:
    if requested in {"trivial", "fast", "standard", "deep"} and requested != "standard":
        return requested
    if fetch_degraded:
        return requested if requested in {"fast", "standard", "deep"} else "standard"
    file_count = len(files)
    churn = sum(item.additions + item.deletions for item in files)
    if file_count == 0 or all(is_short_circuit_file(item.filename) for item in files):
        return "trivial"
    if risk_score < 25 and churn < 80 and file_count <= 3:
        return "fast"
    return "standard"


def is_short_circuit_file(path: str) -> bool:
    lowered = path.lower()
    suffixes = (
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "go.sum",
        "cargo.lock",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".woff",
        ".woff2",
        ".pdf",
    )
    return lowered.endswith(suffixes) or lowered.startswith(("dist/", "build/"))


def agent_matches_files(agent: dict[str, Any], files: list[ChangedFile], change_text: str) -> bool:
    applies_to = agent.get("applies_to") or {}
    languages = set(applies_to.get("languages") or [])
    paths = list(applies_to.get("paths") or [])
    triggers = [str(item).lower() for item in applies_to.get("triggers") or []]
    agent_id = str(agent.get("agent_id") or "")
    if any(trigger in change_text for trigger in triggers):
        return True
    if agent_id == "frontend_agent":
        return any(
            file_matches_patterns(changed.filename, paths)
            or changed.filename.lower().endswith((".tsx", ".jsx", ".vue", ".css", ".scss", ".html"))
            for changed in files
        )
    if agent_id == "redis_agent":
        return any(token in change_text for token in ["redis", "cache", "ttl", "expire", "pipeline", "lua", "keys("])
    if agent_id == "ddd_agent":
        return any(
            file_matches_patterns(changed.filename, ["domain/**", "**/domain/**", "**/aggregate/**", "**/entity/**"])
            for changed in files
        ) or any(token in change_text for token in ["aggregate", "entity", "valueobject", "value_object", "repository", "domain event"])
    if agent_id == "performance_agent":
        return any(token in change_text for token in ["fetchall", "select *", "query(", "timeout", "sleep(", "batch", "n+1", "large_payload"])
    if agent_id == "dependency_agent":
        return any(changed.filename.lower().endswith(("pom.xml", "build.gradle", "build.gradle.kts")) for changed in files)
    if agent_id == "database_agent":
        return any(
            "/db/migration/" in changed.filename.lower()
            or "/changelog/" in changed.filename.lower()
            or "/repository/" in changed.filename.lower()
            or "/mapper/" in changed.filename.lower()
            or changed.filename.lower().endswith("mapper.xml")
            or changed.filename.lower().endswith(".sql")
            for changed in files
        ) or any(
            token in change_text
            for token in [
                "select ",
                "insert ",
                "update ",
                "delete ",
                " join ",
                "order by",
                "group by",
                "jdbc",
                "jdbctemplate",
                "repository",
                "mapper",
                "mybatis",
                "hibernate",
                "entitymanager",
                "@transactional",
                "resultset",
                "preparedstatement",
            ]
        )
    for changed in files:
        language = language_for_file(changed.filename)
        if languages and language not in languages and language != "frontend":
            continue
        if file_matches_patterns(changed.filename, paths):
            return True
    if agent_id in {"security_agent", "coding_agent", "test_agent", "backend_agent"}:
        return any(language_for_file(item.filename) in {"python", "typescript", "javascript", "java"} for item in files)
    return False


def route_agents_with_llm(
    project_config: dict[str, Any],
    recorder: Recorder,
    span_id: str,
    agent_configs: list[dict[str, Any]],
    files: list[ChangedFile],
    budget_tracker: Any | None,
) -> list[str]:
    llm = project_config.get("llm", {})
    prompt = json.dumps(
        {
            "task": "请根据变更文件和专家职责选择最相关的 agent_id，只输出 JSON 数组，例如 [\"security_agent\"]。",
            "files": [
                {
                    "filename": item.filename,
                    "status": item.status,
                    "additions": item.additions,
                    "deletions": item.deletions,
                    "patch_head": item.patch[:800],
                }
                for item in files[:30]
            ],
            "agents": [
                {
                    "agent_id": agent.get("agent_id"),
                    "display_name": agent.get("display_name"),
                    "applies_to": agent.get("applies_to"),
                }
                for agent in agent_configs
            ],
            "policy": "最多选择 10 个；优先让 LLM 根据文件、patch 和专家唯一职责选择；Java/Spring MR 应覆盖安全、性能、通用编码、DDD、Redis、依赖、Database、后端接口等明显相关专家。",
        },
        ensure_ascii=False,
    )
    providers = candidate_providers(llm, required_context=max(1, len(prompt) // 4))
    provider = str((providers[0] if providers else {}).get("provider") or llm.get("default_provider") or "dashscope-openai-compatible")
    model = str((providers[0] if providers else {}).get("model") or llm.get("default_model") or "MiniMax-M2.7")
    if budget_tracker and budget_tracker.should_stop():
        recorder.llm_call(span_id, provider, model, prompt, f"skipped_by_budget:{budget_tracker.truncated_reason}", 0, len(prompt) // 4, 0)
        return []
    if not providers:
        recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, len(prompt) // 4, 0)
        return []
    valid_ids = {str(agent.get("agent_id")) for agent in agent_configs}
    for index, candidate in enumerate(providers):
        provider = str(candidate.get("provider"))
        model = str(candidate.get("model"))
        base_url = str(candidate.get("base_url") or "").rstrip("/")
        api_key = candidate.get("api_key")
        if not base_url or not api_key:
            recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, len(prompt) // 4, 0)
            continue
        started = time.time()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是代码检视路由器，只输出 JSON 数组。"
                    "除 agent_id、文件路径、类名、方法名和技术专有名词外，自然语言必须使用中文。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        try:
            response = http_json(
                chat_completions_url(base_url),
                {"Authorization": f"Bearer {api_key}"},
                method="POST",
                body={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.0,
                },
            )
            duration_ms = int((time.time() - started) * 1000)
            usage = response.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", len(prompt) // 4))
            output_tokens = int(usage.get("completion_tokens", 0))
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "[]")
            recorder.llm_call(span_id, provider, model, prompt, "completed", duration_ms, input_tokens, output_tokens, str(response.get("id") or ""), messages, str(content))
            if budget_tracker:
                budget_tracker.charge_llm(model, input_tokens, output_tokens)
            start = content.find("[")
            end = content.rfind("]")
            parsed = json.loads(content[start : end + 1] if start >= 0 and end >= start else content)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item) in valid_ids][:10]
            return []
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            recorder.llm_call(span_id, provider, model, prompt, f"failed:{type(exc).__name__}", int((time.time() - started) * 1000), len(prompt) // 4, 0, None, messages, str(exc))
            if index < len(providers) - 1:
                recorder.event(span_id, "router_llm_failover", f"{provider} 路由失败，尝试下一个 provider", {"error": str(exc)[:300]})
            else:
                recorder.event(span_id, "router_llm_error", f"路由 LLM 失败，回退规则路由：{exc}")
    return []


def required_java_agent_ids(files: list[ChangedFile], text: str) -> list[str]:
    filenames = [changed.filename.lower() for changed in files]
    is_java_mr = any(name.endswith((".java", "pom.xml", ".gradle", ".sql", ".yml", ".yaml", ".properties")) for name in filenames)
    if not is_java_mr:
        return []
    required = ["security_agent", "coding_agent", "backend_agent"]
    if any(token in text for token in ["select ", "limit", "resultset", "pageable", "order by", "query"]):
        required.append("performance_agent")
    if any(token in text for token in ["redis", "redistemplate", ".keys(", "opsforvalue"]):
        required.append("redis_agent")
    if any("/domain/" in name or token in text for name in filenames for token in ["aggregate", "valueobject", "entity", "domain event", "map<string, object>"]):
        required.append("ddd_agent")
    if any(name.endswith("pom.xml") or name.endswith("build.gradle") or name.endswith("build.gradle.kts") for name in filenames):
        required.append("dependency_agent")
    if any(
        "/db/migration/" in name
        or "/repository/" in name
        or "/mapper/" in name
        or name.endswith("mapper.xml")
        or name.endswith(".sql")
        for name in filenames
    ) or any(
        token in text
        for token in [
            "select ",
            "insert ",
            "update ",
            "delete ",
            " join ",
            "order by",
            "group by",
            "jdbc",
            "jdbctemplate",
            "repository",
            "mapper",
            "mybatis",
            "hibernate",
            "@transactional",
            "resultset",
            "preparedstatement",
        ]
    ):
        required.append("database_agent")
    if any(name.endswith(".java") for name in filenames):
        required.append("test_agent")
    return dedupe_strings(required)


def route_agents(
    agent_configs: list[dict[str, Any]],
    files: list[ChangedFile],
    effort: str,
    project_config: dict[str, Any] | None = None,
    recorder: Recorder | None = None,
    span_id: str | None = None,
    budget_tracker: Any | None = None,
) -> list[dict[str, Any]]:
    if effort == "trivial":
        return []
    text = added_text(files)
    matched = [agent for agent in agent_configs if agent_matches_files(agent, files, text)]
    should_llm_route = effort != "fast" and (not matched or len(matched) >= 5)
    routed_by_llm = False
    if should_llm_route and project_config and recorder and span_id:
        routed_ids = route_agents_with_llm(project_config, recorder, span_id, agent_configs, files, budget_tracker)
        if routed_ids:
            by_id = {agent["agent_id"]: agent for agent in agent_configs}
            matched = [by_id[agent_id] for agent_id in routed_ids if agent_id in by_id]
            routed_by_llm = True
            recorder.event(span_id, "router_llm_selected", f"LLM Router 选择 {len(matched)} 个 Agent", {"agents": routed_ids})
    if not matched:
        matched = [agent for agent in agent_configs if agent["agent_id"] in {"coding_agent", "security_agent", "test_agent"}]
    if effort == "fast":
        priority = {"security_agent", "coding_agent", "test_agent", "frontend_agent", "redis_agent"}
        return [agent for agent in matched if agent["agent_id"] in priority][:3]
    if effort == "standard":
        preferred_order = [
            "security_agent",
            "dependency_agent",
            "database_agent",
            "performance_agent",
            "coding_agent",
            "ddd_agent",
            "backend_agent",
            "frontend_agent",
            "redis_agent",
            "test_agent",
        ]
        by_id = {agent["agent_id"]: agent for agent in matched}
        ordered = [by_id[agent_id] for agent_id in preferred_order if agent_id in by_id]
        ordered.extend(agent for agent in matched if agent.get("agent_id") not in set(preferred_order))
        if routed_by_llm:
            all_agents_by_id = {agent["agent_id"]: agent for agent in agent_configs}
            selected_ids = {agent["agent_id"] for agent in ordered}
            appended: list[str] = []
            for agent_id in required_java_agent_ids(files, text):
                if agent_id in selected_ids or agent_id not in all_agents_by_id:
                    continue
                ordered.append(all_agents_by_id[agent_id])
                selected_ids.add(agent_id)
                appended.append(agent_id)
            if appended and recorder and span_id:
                recorder.event(
                    span_id,
                    "router_java_required_experts_appended",
                    f"追加 {len(appended)} 个 Java 必要专家兜底",
                    {"agents": appended, "reason": "llm_router_primary_with_java_domain_coverage_guard"},
                )
        return ordered[:10]
    return matched


def load_feedback_suppressions(conn: sqlite3.Connection, project_id: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT uf.dedupe_hash
        FROM user_feedback uf
        JOIN review_findings rf ON rf.id = uf.finding_id
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = ?
          AND uf.feedback_type IN ('false_positive', 'suppress_rule')
          AND uf.created_at >= datetime('now', '-90 days')
        """,
        (project_id,),
    ).fetchall()
    return {row["dedupe_hash"] for row in rows}


def load_feedback_boosts(conn: sqlite3.Connection, project_id: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT uf.dedupe_hash
        FROM user_feedback uf
        JOIN review_findings rf ON rf.id = uf.finding_id
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = ?
          AND uf.feedback_type IN ('accepted', 'published')
          AND uf.created_at >= datetime('now', '-90 days')
        """,
        (project_id,),
    ).fetchall()
    return {row["dedupe_hash"] for row in rows}


def verify_findings(
    recorder: Recorder,
    span_id: str,
    findings: list[dict[str, Any]],
    files: list[ChangedFile],
    agent_config_by_id: dict[str, dict[str, Any]],
    suppressed_hashes: set[str],
    boosted_hashes: set[str],
    tool_observations: list[dict[str, Any]] | None = None,
    source_file_contents: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    valid_files = {item.filename for item in files}
    adjusted_findings: list[dict[str, Any]] = []
    for finding in findings:
        item = dict(finding)
        if item.get("dedupe_hash") in boosted_hashes:
            original = float(item.get("confidence") or 0)
            item["confidence"] = min(0.99, original + 0.05)
            item["feedback_adjustment"] = "accepted_confidence_boost"
            recorder.event(
                span_id,
                "finding_feedback_boosted",
                f"{item.get('title', 'candidate')} 因历史采纳反馈提升置信度",
                {"dedupe_hash": item.get("dedupe_hash"), "before": original, "after": item["confidence"]},
            )
        adjusted_findings.append(item)
    diff_source_loader = source_snippet_loader_for_files(files)

    def source_loader(file_path: str, line_no: int, window: int = 5) -> str:
        source = (source_file_contents or {}).get(file_path)
        if not source:
            return diff_source_loader(file_path, line_no, window=window)
        lines = source.splitlines()
        start = max(1, int(line_no) - window)
        end = min(len(lines), int(line_no) + window)
        return "\n".join(lines[index - 1] for index in range(start, end + 1))

    accepted, rejected = verify_candidate_findings(
        adjusted_findings,
        valid_files,
        agent_config_by_id,
        suppressed_hashes,
        diff_hunks_by_file(files),
        known_rule_registry(agent_config_by_id),
        source_loader,
        tool_observations or [],
    )
    if rejected:
        recorder.event(
            span_id,
            "finding_verifier_rejected_summary",
            f"Verifier 过滤 {len(rejected)} 个候选问题",
            {"rejected_reason_counts": rejected_reason_counts(rejected)},
        )
    for finding in rejected:
        reasons = finding.get("rejected_reasons") or []
        recorder.event(
            span_id,
            "finding_dropped",
            f"{finding.get('title', 'candidate')} 被过滤：{','.join(reasons)}",
            {"dedupe_hash": finding.get("dedupe_hash"), "reasons": reasons},
        )
    return accepted


def choose_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'review_jobs'"
    ).fetchone()
    if not table:
        return None
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE review_jobs
            SET status = 'queued', locked_at = NULL, locked_by = NULL
            WHERE status IN ('fetching', 'pre_scanning', 'reviewing', 'judging')
              AND (heartbeat_at IS NULL OR heartbeat_at < datetime('now', ?))
            """,
            (f"-{RECLAIM_AFTER_SECONDS} seconds",),
        )
        job = conn.execute(
            """
            SELECT * FROM review_jobs
            WHERE status = 'queued'
              AND attempt < ?
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            """,
            (MAX_ATTEMPTS,),
        ).fetchone()
        if not job:
            conn.commit()
            return None
        changed = conn.execute(
            """
            UPDATE review_jobs
            SET status = 'fetching', locked_at = CURRENT_TIMESTAMP, locked_by = 'python-worker', heartbeat_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'queued'
            """,
            (job["id"],),
        ).rowcount
        if changed != 1:
            conn.rollback()
            return None
        conn.execute("UPDATE merge_requests SET review_status = 'fetching' WHERE id = ?", (job["merge_request_id"],))
        conn.commit()
        return job
    except sqlite3.OperationalError:
        conn.rollback()
        return None


def load_incremental_context(conn: sqlite3.Connection, merge_request_id: str, head_sha: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT dedupe_hash, last_seen_head_sha, status, resolved_in_commit
        FROM mr_finding_history
        WHERE merge_request_id = ?
        ORDER BY updated_at DESC
        LIMIT 100
        """,
        (merge_request_id,),
    ).fetchall()
    active = [dict(row) for row in rows if row["status"] == "active"]
    previous_heads = sorted({str(row["last_seen_head_sha"]) for row in active if row["last_seen_head_sha"] != head_sha})
    return {
        "has_history": bool(rows),
        "incremental_diff_only": bool(previous_heads),
        "previous_head_shas": previous_heads[:5],
        "active_finding_count": len(active),
        "history_count": len(rows),
        "note": "当前 VCS diff 仍由 MR 数据源提供；该上下文用于 resolved 判断和后续按 commit 缩小 diff。",
    }


def process_mr_one(conn: sqlite3.Connection, config: dict[str, Any]) -> bool:
    job = choose_job(conn)
    if not job:
        write_worker_log(config, "worker_idle", {"reason": "no_queued_review_job"})
        return False
    start_heartbeat(db_path(config), job["id"])
    write_worker_log(
        config,
        "review_job_claimed",
        {
            "review_job_id": job["id"],
            "merge_request_id": job["merge_request_id"],
            "head_sha": job["head_sha"],
            "effort_level": job["requested_effort_level"],
        },
    )

    run_id = new_id("run")
    sandbox_dir = ROOT / "data" / "sandboxes" / run_id
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(conn, run_id, config=config)
    write_worker_log(
        config,
        "review_run_started",
        {"review_run_id": run_id, "review_job_id": job["id"], "sandbox_dir": str(sandbox_dir)},
    )
    write_review_run_log(
        config,
        run_id,
        "review_run_started",
        {"review_job_id": job["id"], "merge_request_id": job["merge_request_id"], "sandbox_dir": str(sandbox_dir)},
    )
    conn.execute(
        """
        INSERT INTO review_runs (
          id, review_job_id, effort_level, risk_score, sandbox_uri, budget_json,
          toolchain_manifest, data_policy_snapshot, status
        )
        SELECT ?, j.id, j.requested_effort_level, mr.risk_score, ?, ?, ?, p.data_policy_json, 'running'
        FROM review_jobs j
        JOIN merge_requests mr ON mr.id = j.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        JOIN projects p ON p.id = r.project_id
        WHERE j.id = ?
        """,
        (
            run_id,
            str(sandbox_dir),
            json.dumps({"max_llm_calls_per_agent": 1, "max_findings": 30}),
            json.dumps({"static": "open_source_tools_first", "llm": config.get("llm", {}).get("default_model")}),
            job["id"],
        ),
    )
    mr = conn.execute("SELECT * FROM merge_requests WHERE id = ?", (job["merge_request_id"],)).fetchone()
    repo = conn.execute("SELECT * FROM repositories WHERE id = ?", (mr["repository_id"],)).fetchone()
    project_id = repo["project_id"]
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    project_config = effective_project_config(config, conn, project_id)
    tool_gateway = ToolGateway(conn, project_id, project_config)
    conn.execute(
        "UPDATE review_runs SET toolchain_manifest = ? WHERE id = ?",
        (
            json.dumps({"static": "open_source_tools_first", "llm": project_config.get("llm", {}).get("default_model")}),
            run_id,
        ),
    )
    conn.commit()

    legacy_data_policy = json.loads(project["data_policy_json"] or "{}") if project else {}
    configured_data_policy = project_config.get("data_policy") or {}
    data_policy = normalize_data_policy({**legacy_data_policy, **configured_data_policy})
    conn.execute("UPDATE review_runs SET data_policy_snapshot = ? WHERE id = ?", (json.dumps(data_policy, ensure_ascii=False), run_id))
    conn.commit()
    agent_configs = merge_custom_agents(load_agent_configs(conn, project_id), project_config)
    agent_config_by_id = {agent["agent_id"]: agent for agent in agent_configs}

    try:
        fetch_node = make_fetch_mr_node(
            recorder=recorder,
            sandbox_dir=sandbox_dir,
            project_config=project_config,
            repo=repo,
            mr=mr,
            job=job,
            data_policy=data_policy,
            fetch_changed_files=fetch_changed_files,
            fetch_changed_file_contents=fetch_changed_file_contents,
            write_json_artifact=write_json_artifact,
            apply_data_policy_to_files=apply_data_policy_to_files,
            load_incremental_context=lambda: load_incremental_context(conn, str(job["merge_request_id"]), str(job["head_sha"])),
        )
        choose_effort_node = make_choose_effort_node(
            conn=conn,
            job=job,
            mr=mr,
            run_id=run_id,
            choose_effort=choose_effort,
        )
        prescan_node = make_prescan_node(
            conn=conn,
            recorder=recorder,
            sandbox_dir=sandbox_dir,
            run_id=run_id,
            job=job,
            project_config=project_config,
            data_policy=data_policy,
            agent_configs=agent_configs,
            graph_node_keys=GRAPH_NODE_KEYS,
            new_id=new_id,
            package_version=package_version,
            build_diff_slices=build_diff_slices,
            build_code_context_snapshot=build_code_context_snapshot,
            build_repo_related_context=lambda changed_files, source_file_contents=None: build_repo_related_context(
                project_config=project_config,
                sandbox_dir=sandbox_dir,
                repository_id=str(repo["id"]),
                head_sha=str(job["head_sha"]),
                files=changed_files,
                source_file_contents=source_file_contents or {},
            ),
            run_external_static_prescan=run_external_static_prescan,
            sanitize_findings_for_policy=sanitize_findings_for_policy,
            findings_to_observations=findings_to_observations,
            save_tool_observations=save_tool_observations,
            write_json_artifact=write_json_artifact,
        )
        route_agents_node = make_route_agents_node(
            recorder=recorder,
            project_config=project_config,
            agent_configs=agent_configs,
            route_agents=route_agents,
        )
        build_context_node = make_build_context_node(recorder=recorder)
        run_experts_node = make_run_experts_node(
            conn=conn,
            recorder=recorder,
            job=job,
            run_id=run_id,
            project_config=project_config,
            data_policy=data_policy,
            tool_gateway=tool_gateway,
            package_version=package_version,
            load_skill_summary=lambda skill, files=None: load_skill_summary(skill, files, conn, project_id),
            load_tool_observations=load_tool_observations,
            static_findings=static_findings,
            sanitize_findings_for_policy=sanitize_findings_for_policy,
            call_llm=call_llm,
            dedupe=dedupe,
        )
        verify_findings_node = make_verify_findings_node(
            conn=conn,
            recorder=recorder,
            job=job,
            project_id=project_id,
            run_id=run_id,
            agent_config_by_id=agent_config_by_id,
            load_feedback_suppressions=load_feedback_suppressions,
            load_feedback_boosts=load_feedback_boosts,
            verify_findings=verify_findings,
            load_tool_observations=load_tool_observations,
        )
        detect_conflicts_node = make_detect_conflicts_node(
            conn=conn,
            recorder=recorder,
            run_id=run_id,
            load_tool_observations=load_tool_observations,
        )
        run_targeted_debate_node = make_run_targeted_debate_node(recorder=recorder, project_config=project_config)
        judge_findings_node = make_judge_findings_node(
            conn=conn,
            recorder=recorder,
            job=job,
            project_id=project_id,
            run_id=run_id,
            new_id=new_id,
            load_tool_observations=load_tool_observations,
            max_findings=30,
            selection_confidence=0.75,
        )
        summarize_pr_node = make_summarize_pr_node(
            conn=conn,
            recorder=recorder,
            job=job,
            mr=mr,
            project_config=project_config,
            summarize_pr=summarize_pr_with_llm,
        )
        finalize_node = make_finalize_node(conn=conn, job=job, mr=mr, run_id=run_id, recorder=recorder)

        invoke_review_graph(
            {"run_id": run_id, "job_id": job["id"]},
            [
                ("fetch_mr", fetch_node),
                ("choose_effort", choose_effort_node),
                ("prescan", prescan_node),
                ("build_context", build_context_node),
                ("route_agents", route_agents_node),
                ("run_experts", run_experts_node),
                ("verify_findings", verify_findings_node),
                ("detect_conflicts", detect_conflicts_node),
                ("run_targeted_debate", run_targeted_debate_node),
                ("judge_findings", judge_findings_node),
                ("summarize_pr", summarize_pr_node),
                ("finalize", finalize_node),
            ],
            recorder,
        )
        recorder.flush()
        run_status = conn.execute("SELECT status FROM review_runs WHERE id = ?", (run_id,)).fetchone()
        finding_count = conn.execute("SELECT COUNT(*) AS count FROM review_findings WHERE review_run_id = ?", (run_id,)).fetchone()
        write_worker_log(
            config,
            "review_run_completed",
            {
                "review_run_id": run_id,
                "review_job_id": job["id"],
                "merge_request_id": job["merge_request_id"],
                "status": run_status["status"] if run_status else "completed",
                "finding_count": int(finding_count["count"] or 0) if finding_count else 0,
            },
        )
        write_review_run_log(
            config,
            run_id,
            "review_run_completed",
            {
                "review_job_id": job["id"],
                "merge_request_id": job["merge_request_id"],
                "status": run_status["status"] if run_status else "completed",
                "finding_count": int(finding_count["count"] or 0) if finding_count else 0,
            },
        )
        return True
    except Exception as exc:
        fail_span = recorder.span("failure")
        recorder.event(fail_span, "worker_error", str(exc))
        recorder.finish(fail_span, "failed")
        recorder.flush()
        next_attempt = int(job["attempt"] or 0) + 1
        if next_attempt >= MAX_ATTEMPTS:
            conn.execute(
                """
                INSERT INTO review_jobs_dead_letter (id, review_job_id, failure_reason, final_attempt)
                VALUES (?, ?, ?, ?)
                """,
                (new_id("dead"), job["id"], str(exc), next_attempt),
            )
            job_status = "dead_letter"
            mr_status = "failed"
        else:
            job_status = "queued"
            mr_status = "queued"
        conn.execute("UPDATE review_runs SET status = 'failed', report_summary = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?", (str(exc), run_id))
        conn.execute(
            """
            UPDATE review_jobs
            SET status = ?, attempt = ?, locked_at = NULL, locked_by = NULL, heartbeat_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (job_status, next_attempt, job["id"]),
        )
        conn.execute("UPDATE merge_requests SET review_status = ? WHERE id = ?", (mr_status, mr["id"]))
        conn.commit()
        write_worker_log(
            config,
            "review_run_failed",
            {
                "review_run_id": run_id,
                "review_job_id": job["id"],
                "merge_request_id": job["merge_request_id"],
                "status": job_status,
                "next_attempt": next_attempt,
                "error_message": str(exc),
            },
            "error",
        )
        write_review_run_log(
            config,
            run_id,
            "review_run_failed",
            {
                "review_job_id": job["id"],
                "merge_request_id": job["merge_request_id"],
                "status": job_status,
                "next_attempt": next_attempt,
                "error_message": str(exc),
            },
            "error",
        )
        return True


def process_one(conn: sqlite3.Connection, config: dict[str, Any]) -> bool:
    return process_mr_one(conn, config)


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        item = normalize_tool_finding(item)
        key = "|".join([
            str(item.get("normalized_rule_category") or item.get("tool_rule_id") or item.get("title") or ""),
            str(item.get("file_path") or ""),
            str(line_bucket(item.get("line_start"))),
        ])
        current = seen.get(key)
        if current is None:
            seen[key] = item
            continue
        if float(item["confidence"]) > float(current["confidence"]):
            merged_sources = set(current.get("tool_sources") or [])
            merged_sources.update(item.get("tool_sources") or [])
            if current.get("tool_name"):
                merged_sources.add(str(current.get("tool_name")))
            if item.get("tool_name"):
                merged_sources.add(str(item.get("tool_name")))
            item["tool_sources"] = sorted(merged_sources)
            item["confidence"] = min(0.99, float(item["confidence"]) + 0.05 * len(merged_sources))
            seen[key] = item
        else:
            sources = set(current.get("tool_sources") or [])
            if item.get("tool_name"):
                sources.add(str(item.get("tool_name")))
            current["tool_sources"] = sorted(sources)
            current["confidence"] = min(0.99, float(current["confidence"]) + 0.03)
    return sorted(seen.values(), key=lambda x: (severity_rank(x["severity"]), float(x["confidence"])), reverse=True)


def severity_rank(value: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    config = load_config()
    conn = connect(config)
    if args.once:
        process_one(conn, config)
        return
    while True:
        did_work = process_one(conn, config)
        time.sleep(1 if did_work else 3)


if __name__ == "__main__":
    main()
