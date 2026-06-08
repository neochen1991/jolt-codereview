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
    load_incremental_context: Callable[[], dict[str, Any]] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def fetch_mr_node(state: dict[str, Any]) -> dict[str, Any]:
        fetch_span = recorder.span("fetch_mr")
        fetch_started = time.time()
        repo_ref = f"{repo['provider']}:{repo['external_repo_id']}#{mr['number']}"
        tool_version = "github-rest-2022-11-28" if repo["provider"] == "github" else "codehub-configured-rest"
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
            llm_files, policy_decisions = apply_data_policy_to_files(recorder, fetch_span, sandbox_dir, files, data_policy)
            incremental_context = load_incremental_context() if load_incremental_context else {"incremental_diff_only": False}
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
