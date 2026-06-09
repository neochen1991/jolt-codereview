from __future__ import annotations

import sqlite3
from typing import Any, Callable

from orchestration.deepagents_runner import run_bounded_deepagent


def _builtin_java_heuristics_enabled(project_config: dict[str, Any]) -> bool:
    policy = project_config.get("tool_policy") if isinstance(project_config.get("tool_policy"), dict) else {}
    static_runners = policy.get("static_runners") if isinstance(policy.get("static_runners"), dict) else {}
    runner_cfg = static_runners.get("java_web_static") if isinstance(static_runners.get("java_web_static"), dict) else {}
    return bool(
        policy.get("enable_builtin_java_heuristics")
        or policy.get("enable_jolt_builtin_rules")
        or runner_cfg.get("enabled") is True
    )


def make_run_experts_node(
    *,
    conn: sqlite3.Connection,
    recorder: Any,
    job: Any,
    run_id: str,
    project_config: dict[str, Any],
    data_policy: dict[str, Any],
    tool_gateway: Any,
    package_version: Callable[[str], str | None],
    load_skill_summary: Callable[[str], str],
    load_tool_observations: Callable[[sqlite3.Connection, str], list[dict[str, Any]]],
    static_findings: Callable[[str, list[Any], str], list[dict[str, Any]]],
    sanitize_findings_for_policy: Callable[[list[dict[str, Any]], dict[str, Any], list[Any]], list[dict[str, Any]]],
    call_llm: Callable[..., list[dict[str, Any]]],
    dedupe: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def run_experts_node(state: dict[str, Any]) -> dict[str, Any]:
        files = state["files"]
        llm_files = state.get("llm_files") or []
        effort = state["effort"]
        selected_agents = state["selected_agents"]
        conn.execute("UPDATE review_jobs SET status = 'reviewing', heartbeat_at = CURRENT_TIMESTAMP WHERE id = ?", (job["id"],))
        conn.execute("UPDATE merge_requests SET review_status = 'reviewing' WHERE id = ?", (job["merge_request_id"],))
        conn.commit()
        all_findings: list[dict[str, Any]] = []
        tool_observations = state.get("tool_observations") or load_tool_observations(conn, run_id)
        if effort == "trivial":
            trivial_span = recorder.span("trivial_short_circuit", "router_agent")
            recorder.event(trivial_span, "trivial_short_circuit", "trivial 检视强度跳过 LLM，仅保留静态摘要")
            recorder.finish(trivial_span)
        for agent in selected_agents:
            budget_tracker = state.get("budget_tracker")
            if budget_tracker and budget_tracker.should_stop():
                budget_span = recorder.span("budget_truncated", "budget_guard")
                recorder.event(
                    budget_span,
                    "budget_truncated",
                    f"预算已触发熔断，跳过剩余专家：{budget_tracker.truncated_reason}",
                    budget_tracker.snapshot(),
                )
                recorder.finish(budget_span, "completed")
                break
            agent_id = agent["agent_id"]
            span = recorder.span(agent_id, agent_id)
            recorder.event(span, "agent_started", f"{agent_id} 开始检视")
            applies_to = agent.get("applies_to") or {}
            recorder.event(
                span,
                "agent_profile_loaded",
                f"{agent.get('display_name', agent_id)} 载入角色画像和唯一检视范围",
                {
                    "persona": applies_to.get("persona"),
                    "review_scope": applies_to.get("review_scope"),
                    "exclusive_scope": applies_to.get("exclusive_scope"),
                    "skills": agent.get("skills", []),
                },
            )
            recorder.event(
                span,
                "deepagents_bounded_node",
                "DeepAgents 能力按单层专家节点约束执行：skill + tool wrapper + scoped context，不启用 sub-agent 调度",
                {
                    "skills": agent.get("skills", []),
                    "custom_skills": agent.get("custom_skills", []),
                    "skill_assets": [
                        {
                            "skill_key": item.get("skill_key"),
                            "asset_path": item.get("asset_path"),
                            "asset_type": item.get("asset_type"),
                        }
                        for item in (agent.get("skill_assets") or [])
                        if isinstance(item, dict)
                    ],
                    "tools": agent.get("tools", []),
                    "deepagents_version": package_version("deepagents"),
                    "sub_agents": "disabled",
                    "tool_calling": "platform_wrapper",
                },
            )
            skill_summary = "\n\n".join(load_skill_summary(skill, files) for skill in agent.get("skills", []))
            agent_context = {
                **agent,
                "tool_observations": tool_observations,
                "related_context": state.get("related_context") or {},
                "budget_tracker": budget_tracker,
            }
            recorder.message(
                span,
                "system",
                agent_id,
                "instruction",
                (
                    f"角色画像：{applies_to.get('persona')}; "
                    f"唯一范围：{applies_to.get('exclusive_scope')} / {applies_to.get('review_scope')}; "
                    f"使用 skill: {','.join(agent.get('skills', []))}; "
                    "按规范逐条检视 + 按角色定义检视，输出两部分结果并集；"
                    f"最小置信度 {agent.get('min_confidence')}"
                ),
            )
            if _builtin_java_heuristics_enabled(project_config):
                static_decision = tool_gateway.check(agent_id, "static.heuristic_prescan")
            else:
                static_decision = None
                recorder.event(
                    span,
                    "legacy_static_heuristics_skipped",
                    "内置启发式扫描默认禁用；专家仅使用开源静态工具观察和 LLM/Skill 检视",
                    {"reason": "disabled_by_default_use_open_source_tools"},
                )
            if static_decision and static_decision.allowed:
                static_items = sanitize_findings_for_policy(static_findings(agent_id, files, job["head_sha"]), data_policy, files)
                recorder.tool_call(
                    span,
                    "static.heuristic_prescan",
                    "completed",
                    0,
                    args_summary=f"agent={agent_id}",
                    output_summary=f"{len(static_items)} built-in static findings",
                    tool_version="jolt-builtin-static-analysis-v1",
                )
            elif static_decision:
                static_items = []
                recorder.tool_call(
                    span,
                    "static.heuristic_prescan",
                    "rejected_by_policy",
                    0,
                    args_summary=f"agent={agent_id}",
                    output_summary=static_decision.reason,
                    tool_version="jolt-builtin-static-analysis-v1",
                )
            else:
                static_items = []
            has_skill_bundle = bool(agent.get("custom_skills") or agent.get("skill_assets"))
            if effort == "deep" or agent.get("requires_deepagents") or has_skill_bundle:
                try:
                    max_tool_calls = int(agent.get("max_tool_calls") or 12)
                    if has_skill_bundle:
                        max_tool_calls = max(max_tool_calls, 14)
                    deep_result = run_bounded_deepagent(
                        agent=agent_context,
                        files=llm_files,
                        skill_summary=skill_summary,
                        tool_observations=tool_observations,
                        llm_config=project_config.get("llm", {}),
                        max_tool_calls=max_tool_calls,
                        llm_trace=lambda fields: recorder.llm_call(
                            span,
                            str(fields.get("provider") or project_config.get("llm", {}).get("default_provider") or ""),
                            str(fields.get("model") or project_config.get("llm", {}).get("default_model") or ""),
                            str(fields.get("prompt") or ""),
                            str(fields.get("status") or "completed"),
                            int(fields.get("duration_ms") or 0),
                            int(fields.get("input_tokens") or 0),
                            int(fields.get("output_tokens") or 0),
                            str(fields.get("request_id") or "") or None,
                            fields.get("request_messages") if isinstance(fields.get("request_messages"), list) else [],
                            str(fields.get("response_text") or ""),
                        ),
                    )
                    for call in deep_result.get("tool_calls", []):
                        recorder.tool_call(
                            span,
                            f"deepagents.{call.get('tool_name')}",
                            "completed",
                            0,
                            args_summary=f"agent={agent_id}",
                            output_summary=str(call.get("content") or "")[:500],
                            tool_version=f"deepagents:{package_version('deepagents') or 'unknown'}",
                        )
                    recorder.event(
                        span,
                        "deepagents_completed",
                        f"DeepAgents 子图完成 {len(deep_result.get('tool_calls', []))} 次工具调用",
                        deep_result,
                    )
                    skill_summary = f"{skill_summary}\n\nDeepAgents 上下文摘要：\n{deep_result.get('content') or ''}".strip()
                except Exception as exc:
                    recorder.event(span, "deepagents_fallback", f"DeepAgents 子图失败，回退普通 LLM 检视：{exc}")
            if effort == "trivial":
                llm_items = []
            elif budget_tracker and budget_tracker.should_stop():
                recorder.event(span, "llm_skipped_by_budget", f"预算已触发熔断：{budget_tracker.truncated_reason}", budget_tracker.snapshot())
                llm_items = []
            else:
                llm_items = call_llm(project_config, recorder, span, agent_context, llm_files, skill_summary)
            for item in llm_items:
                item["head_sha"] = job["head_sha"]
            merged = dedupe(static_items + llm_items)
            recorder.event(span, "finding_candidate", f"{agent_id} 产出 {len(merged)} 个候选问题")
            all_findings.extend(merged)
            recorder.finish(span)
        return {**state, "all_findings": all_findings}

    return run_experts_node
