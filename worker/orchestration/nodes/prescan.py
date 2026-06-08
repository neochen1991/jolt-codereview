from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable


def make_prescan_node(
    *,
    conn: sqlite3.Connection,
    recorder: Any,
    sandbox_dir: Path,
    run_id: str,
    job: Any,
    project_config: dict[str, Any],
    data_policy: dict[str, Any],
    agent_configs: list[dict[str, Any]],
    graph_node_keys: list[str],
    new_id: Callable[[str], str],
    package_version: Callable[[str], str | None],
    build_diff_slices: Callable[[list[Any]], list[dict[str, Any]]],
    build_code_context_snapshot: Callable[[list[Any]], dict[str, Any]],
    build_repo_related_context: Callable[[list[Any]], dict[str, Any]],
    run_external_static_prescan: Callable[..., tuple[dict[str, Any], list[dict[str, Any]]]],
    sanitize_findings_for_policy: Callable[[list[dict[str, Any]], dict[str, Any], list[Any]], list[dict[str, Any]]],
    findings_to_observations: Callable[[list[dict[str, Any]]], list[Any]],
    save_tool_observations: Callable[[sqlite3.Connection, str, list[Any], Callable[[str], str]], None],
    write_json_artifact: Callable[..., Path],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def prescan_node(state: dict[str, Any]) -> dict[str, Any]:
        files = state["files"]
        prescan_span = recorder.span("prescan")
        prescan_started = time.time()
        total_additions = sum(item.additions for item in files)
        total_deletions = sum(item.deletions for item in files)
        prescan_summary = {
            "file_count": len(files),
            "additions": total_additions,
            "deletions": total_deletions,
            "large_change_files": [
                {"filename": item.filename, "additions": item.additions, "deletions": item.deletions}
                for item in files
                if item.additions + item.deletions >= 80
            ],
            "agents": [agent["agent_id"] for agent in agent_configs],
        }
        diff_slices = build_diff_slices(files)
        diff_slices_artifact = write_json_artifact(
            recorder,
            sandbox_dir,
            "context",
            "diff_slices.json",
            {"max_added_lines_per_slice": 800, "items": diff_slices},
            {"strategy": "hunk_line_slicing", "head_sha": job["head_sha"]},
        )
        fetched_source_contents = state.get("source_file_contents") or {}
        code_context = build_code_context_snapshot(files)
        repo_related_context = build_repo_related_context(files, source_file_contents=fetched_source_contents)
        code_context_artifact = write_json_artifact(
            recorder,
            sandbox_dir,
            "context",
            "code_context_snapshot.json",
            {**code_context, "related_context": {key: value for key, value in repo_related_context.items() if key != "source_file_contents"}},
            {"strategy": repo_related_context.get("index_kind") or code_context.get("index_kind", "diff_symbol_index"), "head_sha": job["head_sha"]},
        )
        mr_row = conn.execute("SELECT repository_id FROM merge_requests WHERE id = ?", (job["merge_request_id"],)).fetchone()
        if mr_row:
            conn.execute(
                """
                INSERT INTO code_index_snapshots (
                  id, review_run_id, repository_id, commit_sha, index_kind, storage_uri
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("idx"),
                    run_id,
                    mr_row["repository_id"],
                    job["head_sha"],
                    str(repo_related_context.get("index_kind") or code_context.get("index_kind") or "diff_symbol_index"),
                    str(code_context_artifact),
                ),
            )
        external_toolchain, external_tool_findings = run_external_static_prescan(
            recorder,
            prescan_span,
            sandbox_dir,
            files,
            job["head_sha"],
            conn,
            job["merge_request_id"],
            project_config,
            fetched_source_contents or repo_related_context.get("source_file_contents") or {},
        )
        external_tool_findings = sanitize_findings_for_policy(external_tool_findings, data_policy, files)
        tool_observations = findings_to_observations(external_tool_findings)
        save_tool_observations(conn, run_id, tool_observations, new_id)
        conn.commit()
        tool_observation_items = [item.to_prompt_item() for item in tool_observations]
        prescan_summary["static_tools"] = external_toolchain
        prescan_summary["tool_observations"] = {"count": len(tool_observation_items)}
        prescan_summary["diff_slices"] = {"artifact": str(diff_slices_artifact), "count": len(diff_slices)}
        prescan_summary["code_context"] = {
            "artifact": str(code_context_artifact),
            "status": code_context["status"],
            "related_context_status": repo_related_context.get("status"),
            "modified_symbol_count": len(repo_related_context.get("modified_symbols") or []),
        }
        mcp_enabled = bool(project_config.get("tool_policy", {}).get("enable_mcp", False))
        mcp_manifest = {
            "status": "enabled_by_policy" if mcp_enabled else "disabled_by_policy",
            "enabled": mcp_enabled,
            "reason": "project tool_policy.enable_mcp is true" if mcp_enabled else "project tool_policy.enable_mcp is false",
        }
        prescan_artifact = write_json_artifact(
            recorder,
            sandbox_dir,
            "prescan",
            "prescan_summary.json",
            prescan_summary,
            {"strategy": "oss_static_toolchain_prescan", "head_sha": job["head_sha"]},
        )
        recorder.tool_call(
            prescan_span,
            "static.oss_prescan",
            "completed",
            int((time.time() - prescan_started) * 1000),
            args_summary=f"{len(files)} files",
            output_summary=f"additions={total_additions}, deletions={total_deletions}",
            output_ref={"artifact": str(prescan_artifact)},
            tool_version="oss-static-toolchain-v1",
        )
        static_results_artifact = write_json_artifact(
            recorder,
            sandbox_dir,
            "prescan",
            "static_tool_results.json",
            external_toolchain,
            {"strategy": "oss_static_toolchain", "head_sha": job["head_sha"]},
        )
        recorder.event(
            prescan_span,
            "diff_summary",
            f"新增 {total_additions} 行，删除 {total_deletions} 行",
            {"additions": total_additions, "deletions": total_deletions},
        )
        recorder.event(
            prescan_span,
            "static_tool_summary",
            f"外部静态工具可用 {len(external_toolchain['available_tools'])} 个，产出 {len(tool_observation_items)} 个候选观察",
            {"artifact": str(static_results_artifact), **external_toolchain},
        )
        recorder.event(
            prescan_span,
            "context_structured",
            f"结构化上下文完成：{len(diff_slices)} 个 diff slice，{len(code_context['changed_files'])} 个文件摘要",
            {"diff_slices_artifact": str(diff_slices_artifact), "code_context_artifact": str(code_context_artifact)},
        )
        conn.execute(
            "UPDATE review_runs SET toolchain_manifest = ? WHERE id = ?",
            (
                json.dumps(
                    {
                        "orchestration": {
                            "engine": state.get("orchestration_engine", "langgraph"),
                            "graph": "mr_review_v1",
                            "nodes": graph_node_keys,
                            "langgraph_version": package_version("langgraph"),
                            "deepagents": {
                                "package_version": package_version("deepagents"),
                                "mode": "bounded_single_agent_node",
                                "planner": "langgraph_node_input",
                                "sub_agents": "disabled",
                                "tool_calling": "platform_wrapper",
                                "max_llm_calls_per_agent": 8,
                            },
                        },
                        "static": {
                            "mode": "open_source_tools_first",
                            "oss_toolchain": external_toolchain,
                            "builtin_static_analysis": {
                                "tool": "java_web_static",
                                "version": "jolt-builtin-static-analysis-v1",
                                "enabled": bool((external_toolchain.get("scan_policy") or {}).get("builtin_java_heuristics_enabled")),
                                "role": "optional project-enabled supplement, not default scanner",
                            },
                        },
                        "context": {
                            "diff_slicing": {
                                "strategy": "hunk_line_slicing",
                                "max_added_lines_per_slice": 800,
                                "artifact": str(diff_slices_artifact),
                                "slice_count": len(diff_slices),
                            },
                            "code_context_service": {
                                "status": code_context["status"],
                                "index_kind": repo_related_context.get("index_kind") or code_context["index_kind"],
                                "artifact": str(code_context_artifact),
                                "related_context_status": repo_related_context.get("status"),
                                "modified_symbol_count": len(repo_related_context.get("modified_symbols") or []),
                                "supported_tools": code_context["supported_tools"],
                            },
                            "mcp": {
                                **mcp_manifest,
                            },
                        },
                        "llm": project_config.get("llm", {}).get("default_model"),
                    },
                    ensure_ascii=False,
                ),
                run_id,
            ),
        )
        conn.commit()
        recorder.finish(prescan_span)
        return {
            **state,
            "tool_observations": tool_observation_items,
            "external_toolchain": external_toolchain,
            "diff_slices": diff_slices,
            "code_context": {**code_context, "related_context": {key: value for key, value in repo_related_context.items() if key != "source_file_contents"}},
            "related_context": {key: value for key, value in repo_related_context.items() if key != "source_file_contents"},
            "source_file_contents": fetched_source_contents or repo_related_context.get("source_file_contents") or {},
        }

    return prescan_node
