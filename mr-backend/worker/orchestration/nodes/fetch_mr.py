from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable


def make_fetch_mr_node(
    *,
    recorder: Any,
    sandbox_dir: Path,
    project_config: dict[str, Any],
    repo: Any,
    mr: Any,
    job: Any,
    data_policy: dict[str, Any],
    fetch_changed_files: Callable[[dict[str, Any], Any, Any], list[Any]],
    fetch_changed_file_contents: Callable[[dict[str, Any], Any, Any, list[Any]], tuple[dict[str, str], list[dict[str, Any]]]],
    write_json_artifact: Callable[..., Path],
    apply_data_policy_to_files: Callable[..., tuple[list[Any], list[dict[str, Any]]]],
    prepare_source_worktree: Callable[[dict[str, Any], Any, Any], tuple[str | None, list[dict[str, Any]]]] | None = None,
    load_incremental_context: Callable[[], dict[str, Any]] | None = None,
    load_debug_input_artifact: Callable[[], dict[str, Any] | None] | None = None,
    save_debug_input_artifact: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    hydrate_changed_files: Callable[[list[dict[str, Any]]], list[Any]] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def fetch_mr_node(state: dict[str, Any]) -> dict[str, Any]:
        fetch_span = recorder.span("fetch_mr")
        fetch_started = time.time()
        repo_ref = f"{repo['provider']}:{repo['external_repo_id']}#{mr['number']}"
        tool_version = "github-rest-2022-11-28" if repo["provider"] == "github" else "codehub-configured-rest"
        frozen_input = load_debug_input_artifact() if load_debug_input_artifact else None
        if frozen_input and hydrate_changed_files:
            files = hydrate_changed_files(list(frozen_input.get("files") or []))
            source_file_contents = {str(key): str(value) for key, value in dict(frozen_input.get("source_file_contents") or {}).items()}
            llm_files, policy_decisions = apply_data_policy_to_files(recorder, fetch_span, sandbox_dir, files, data_policy)
            source_worktree_path: str | None = None
            worktree_errors: list[dict[str, Any]] = []
            if prepare_source_worktree:
                source_worktree_path, worktree_errors = prepare_source_worktree(project_config, repo, mr)
            incremental_context = dict(frozen_input.get("incremental_context") or {"incremental_diff_only": False})
            recorder.tool_call(fetch_span, "review.input_artifact", "completed", int((time.time() - fetch_started) * 1000), args_summary=repo_ref, output_summary=f"reused {len(files)} frozen changed files", tool_version="review-input-v1")
            recorder.event(fetch_span, "skill_debug_input_reused", "复用冻结 Review 输入工件", {"file_count": len(files), "input_artifact_sha256": frozen_input.get("input_artifact_sha256")})
            recorder.finish(fetch_span)
            return {
                **state, "files": files, "llm_files": llm_files, "policy_decisions": policy_decisions,
                "source_file_contents": source_file_contents, "source_worktree_path": source_worktree_path,
                "source_worktree_errors": worktree_errors, "fetch_degraded": False,
                "incremental_context": incremental_context, "input_artifact_reused": True,
            }
        try:
            files = fetch_changed_files(project_config, repo, mr)
            fetch_duration_ms = int((time.time() - fetch_started) * 1000)
            changed_files_artifact = write_json_artifact(
                recorder,
                sandbox_dir,
                "diff",
                "changed_files.json",
                [item.to_record() for item in files],
                {"provider": repo["provider"], "mr_number": mr["number"], "head_sha": job["head_sha"]},
            )
            recorder.tool_call(
                fetch_span,
                f"{repo['provider']}.list_changed_files",
                "completed",
                fetch_duration_ms,
                args_summary=repo_ref,
                output_summary=f"{len(files)} changed files",
                output_ref={"artifact": str(changed_files_artifact), "file_count": len(files)},
                tool_version=tool_version,
            )
            recorder.event(fetch_span, "github_files", f"拉取 {len(files)} 个变更文件", {"files": [f.filename for f in files]})
            content_started = time.time()
            source_file_contents, source_errors = fetch_changed_file_contents(project_config, repo, mr, files)
            source_artifact = write_json_artifact(
                recorder,
                sandbox_dir,
                "source",
                "changed_file_contents.json",
                {
                    "files": [
                        {"filename": filename, "size": len(content)}
                        for filename, content in sorted(source_file_contents.items())
                    ],
                    "errors": source_errors,
                },
                {"provider": repo["provider"], "mr_number": mr["number"], "head_sha": job["head_sha"]},
            )
            recorder.tool_call(
                fetch_span,
                f"{repo['provider']}.fetch_file_contents",
                "completed" if not source_errors else "completed_with_errors",
                int((time.time() - content_started) * 1000),
                args_summary=f"{len(files)} changed files",
                output_summary=f"{len(source_file_contents)} source files fetched, {len(source_errors)} errors",
                output_ref={"artifact": str(source_artifact), "file_count": len(source_file_contents), "error_count": len(source_errors)},
                tool_version=tool_version,
            )
            source_worktree_path: str | None = None
            worktree_errors: list[dict[str, Any]] = []
            if prepare_source_worktree:
                worktree_started = time.time()
                source_worktree_path, worktree_errors = prepare_source_worktree(project_config, repo, mr)
                if source_worktree_path and not worktree_errors:
                    worktree_status = "completed"
                    worktree_summary = source_worktree_path
                elif worktree_errors:
                    worktree_status = "completed_with_errors"
                    worktree_summary = f"{len(worktree_errors)} errors"
                else:
                    worktree_status = "skipped_no_git_url"
                    worktree_summary = "repository git_url not configured"
                worktree_artifact = write_json_artifact(
                    recorder,
                    sandbox_dir,
                    "source",
                    "source_worktree.json",
                    {
                        "path": source_worktree_path,
                        "errors": worktree_errors,
                    },
                    {"provider": repo["provider"], "mr_number": mr["number"], "head_sha": job["head_sha"]},
                )
                recorder.tool_call(
                    fetch_span,
                    "git.prepare_source_worktree",
                    worktree_status,
                    int((time.time() - worktree_started) * 1000),
                    args_summary=repo_ref,
                    output_summary=worktree_summary,
                    output_ref={
                        "artifact": str(worktree_artifact),
                        "path": source_worktree_path,
                        "error_count": len(worktree_errors),
                    },
                    tool_version="git-worktree-v1",
                )
            llm_files, policy_decisions = apply_data_policy_to_files(recorder, fetch_span, sandbox_dir, files, data_policy)
            incremental_context = load_incremental_context() if load_incremental_context else {"incremental_diff_only": False}
            if save_debug_input_artifact:
                saved_input = save_debug_input_artifact({
                    "version": "review_input_v1",
                    "head_sha": str(job["head_sha"]),
                    "files": [item.to_record() for item in files],
                    "source_file_contents": source_file_contents,
                    "incremental_context": incremental_context,
                })
                recorder.event(fetch_span, "review_input_frozen", "冻结 Review 输入工件供同输入复用", {"file_count": len(files), "input_artifact_sha256": saved_input.get("input_artifact_sha256")})
            recorder.event(
                fetch_span,
                "incremental_context",
                "MR 增量上下文已载入" if incremental_context.get("has_history") else "MR 暂无历史 finding，按完整 MR diff 检视",
                incremental_context,
            )
            recorder.finish(fetch_span)
            return {
                **state,
                "files": files,
                "llm_files": llm_files,
                "policy_decisions": policy_decisions,
                "source_file_contents": source_file_contents,
                "source_worktree_path": source_worktree_path,
                "source_worktree_errors": worktree_errors,
                "fetch_degraded": False,
                "incremental_context": incremental_context,
            }
        except Exception as exc:
            fetch_duration_ms = int((time.time() - fetch_started) * 1000)
            changed_files_artifact = write_json_artifact(
                recorder,
                sandbox_dir,
                "diff",
                "changed_files.json",
                {"files": [], "error": str(exc)},
                {"provider": repo["provider"], "mr_number": mr["number"], "head_sha": job["head_sha"], "degraded": True},
            )
            recorder.tool_call(
                fetch_span,
                f"{repo['provider']}.list_changed_files",
                "failed_degraded",
                fetch_duration_ms,
                args_summary=repo_ref,
                output_summary=str(exc)[:500],
                output_ref={"artifact": str(changed_files_artifact), "file_count": 0},
                tool_version=tool_version,
            )
            recorder.event(
                fetch_span,
                "github_fetch_error",
                f"{repo['provider']} changed files 拉取失败，降级为空上下文检视：{exc}",
                {"reason": str(exc)},
            )
            recorder.finish(fetch_span, "degraded")
            return {**state, "files": [], "llm_files": [], "policy_decisions": [], "fetch_degraded": True}

    return fetch_mr_node
