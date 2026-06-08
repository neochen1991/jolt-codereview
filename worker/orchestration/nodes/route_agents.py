from __future__ import annotations

from typing import Any, Callable


def make_route_agents_node(
    *,
    recorder: Any,
    project_config: dict[str, Any],
    agent_configs: list[dict[str, Any]],
    route_agents: Callable[..., list[dict[str, Any]]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def route_agents_node(state: dict[str, Any]) -> dict[str, Any]:
        files = state["files"]
        effort = state["effort"]
        router_span = recorder.span("route_agents", "router_agent")
        budget_tracker = state.get("budget_tracker")
        if budget_tracker and budget_tracker.should_stop():
            recorder.event(
                router_span,
                "budget_truncated",
                f"预算已触发熔断，跳过 Agent 路由：{budget_tracker.truncated_reason}",
                budget_tracker.snapshot(),
            )
            recorder.finish(router_span)
            return {**state, "selected_agents": []}
        selected_agents = route_agents(
            agent_configs,
            files,
            effort,
            project_config,
            recorder,
            router_span,
            budget_tracker,
        )
        recorder.event(
            router_span,
            "agent_routed",
            f"Router 选择 {len(selected_agents)} 个 Agent，effort={effort}",
            {"agents": [agent["agent_id"] for agent in selected_agents], "effort": effort},
        )
        for agent in selected_agents:
            applies_to = agent.get("applies_to") or {}
            recorder.message(
                router_span,
                "router_agent",
                agent["agent_id"],
                "task",
                (
                    f"请基于 {len(files)} 个变更文件执行 {agent['agent_id']} 检视，输出 finding_v1。"
                    f"唯一范围={applies_to.get('exclusive_scope')}; "
                    f"Scope={applies_to.get('review_scope')}; "
                    f"Skill={','.join(agent.get('skills', []))}"
                ),
            )
        recorder.finish(router_span)
        return {**state, "selected_agents": selected_agents}

    return route_agents_node
