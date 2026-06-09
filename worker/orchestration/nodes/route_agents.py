from __future__ import annotations

from typing import Any, Callable

from tools.tool_normalizer import CATEGORY_PRIMARY_RULE, normalized_rule_category


SECURITY_CATEGORIES = {
    "AUTHORIZATION_BYPASS",
    "CSV_OUTPUT_INJECTION",
    "DEBUG_ENDPOINT_EXPOSURE",
    "ERROR_INFORMATION_LEAK",
    "FAILURE_DEFAULT_ALLOW",
    "INSECURE_RANDOM",
    "PREDICTABLE_TEMP_FILE",
    "REGEX_DOS",
    "RISK_CONTROL_BYPASS",
    "SECRET_LEAK",
    "SPEL_INJECTION",
    "SPRING_ACTUATOR_EXPOSED",
    "SQL_INJECTION",
    "SSRF_CALLBACK",
    "UNSAFE_DESERIALIZATION",
    "UNSAFE_FILE_RESPONSE",
    "UNSAFE_REFLECTION",
    "UNTRUSTED_FORWARDED_HEADER",
    "WEAK_SIGNATURE_ALGORITHM",
    "WEAK_SIGNATURE_COMPARE",
    "WEAK_WEBHOOK_TRUST",
    "ZIP_SLIP",
}

PERFORMANCE_CATEGORIES = {
    "ARCHIVE_BOMB_RISK",
    "IBATIS_MEMORY_PAGINATION",
    "LIKE_LEADING_WILDCARD_INDEX_RISK",
    "REQUEST_THREAD_BLOCKING",
    "UNBOUNDED_EXECUTOR",
    "UNBOUNDED_QUERY",
    "UNBOUNDED_RESULT_MEMORY",
}

DATABASE_CATEGORIES = {
    "DB_BREAKING_CHANGE",
    "DB_CONNECTION_STATE_LEAK",
    "DB_MAP_RESULT_TYPE",
    "DB_NOT_NULL_NO_DEFAULT",
    "MYBATIS_SQL_INJECTION",
}

CODING_CATEGORIES = {
    "AUDIT_TIME_ZONE",
    "BIGDECIMAL_PRECISION",
    "BROAD_EXCEPTION",
    "CACHE_KEY_COLLISION",
    "DEFAULT_CHARSET_IO",
    "EQUALS_HASHCODE_CONTRACT",
    "JAVA_NAMING",
    "NULL_RETURN_COLLECTION",
    "NULL_SAFETY",
    "PRINT_STACK_TRACE",
    "SPRING_FIELD_INJECTION",
    "STATE_MACHINE_INTEGRITY",
    "SYSTEM_OUT_LOGGING",
    "THREADLOCAL_LEAK",
    "THREAD_UNSAFE_DATE_FORMAT",
    "THREAD_UNSAFE_SHARED_STATE",
    "ZIP_ENTRY_MKDIRS_IGNORED",
    "ZIP_STREAM_RESOURCE_LEAK",
}

DDD_CATEGORIES = {
    "DDD_AGGREGATE_OWNERSHIP",
    "DDD_WEAK_DOMAIN_MODEL",
    "LAYER_VIOLATION",
}


def _agent_ids_for_tool_observations(tool_observations: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, str]]]:
    required: list[str] = []
    evidence: list[dict[str, str]] = []

    def add(agent_id: str, category: str, rule_id: str, primary_rule: str) -> None:
        if agent_id not in required:
            required.append(agent_id)
        evidence.append(
            {
                "agent_id": agent_id,
                "category": category,
                "rule_id": rule_id,
                "primary_rule": primary_rule,
            }
        )

    for observation in tool_observations:
        raw_rule = str(observation.get("rule_id") or observation.get("tool_rule_id") or "")
        message = str(observation.get("message") or observation.get("title") or "")
        category = normalized_rule_category(raw_rule, message)
        primary_rule = CATEGORY_PRIMARY_RULE.get(category, raw_rule)

        if category in SECURITY_CATEGORIES or primary_rule.startswith("SEC-"):
            add("security_agent", category, raw_rule, primary_rule)
        if category in PERFORMANCE_CATEGORIES or primary_rule.startswith("PERF-"):
            add("performance_agent", category, raw_rule, primary_rule)
        if category in DATABASE_CATEGORIES or primary_rule.startswith("DB-") or primary_rule.startswith("ALI-DB") or primary_rule.startswith("ALI-MYBATIS"):
            add("database_agent", category, raw_rule, primary_rule)
        if category in CODING_CATEGORIES or primary_rule.startswith(("CODE-", "ALI-", "HW-TX-")):
            add("coding_agent", category, raw_rule, primary_rule)
        if category in DDD_CATEGORIES or primary_rule.startswith("DDD-") or category.startswith("DDD_"):
            add("ddd_agent", category, raw_rule, primary_rule)
        if primary_rule.startswith("REDIS-"):
            add("redis_agent", category, raw_rule, primary_rule)
        if primary_rule.startswith("DEP-"):
            add("dependency_agent", category, raw_rule, primary_rule)
        if primary_rule.startswith("TEST-"):
            add("test_agent", category, raw_rule, primary_rule)

    return required, evidence


def _augment_agents_from_tool_observations(
    selected_agents: list[dict[str, Any]],
    agent_configs: list[dict[str, Any]],
    tool_observations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    if not tool_observations:
        return selected_agents, [], []

    required_ids, evidence = _agent_ids_for_tool_observations(tool_observations)
    if not required_ids:
        return selected_agents, [], evidence

    by_id = {str(agent.get("agent_id")): agent for agent in agent_configs}
    selected_ids = {str(agent.get("agent_id")) for agent in selected_agents}
    augmented = list(selected_agents)
    appended: list[str] = []
    for agent_id in required_ids:
        if agent_id in selected_ids or agent_id not in by_id:
            continue
        augmented.append(by_id[agent_id])
        selected_ids.add(agent_id)
        appended.append(agent_id)
    return augmented, appended, evidence


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
        selected_agents, tool_augmented_agents, tool_route_evidence = _augment_agents_from_tool_observations(
            selected_agents,
            agent_configs,
            state.get("tool_observations") or [],
        )
        if tool_augmented_agents:
            recorder.event(
                router_span,
                "router_tool_observation_experts_appended",
                f"基于静态工具观察追加 {len(tool_augmented_agents)} 个专家 Agent",
                {
                    "agents": tool_augmented_agents,
                    "evidence": tool_route_evidence[:50],
                },
            )
        recorder.event(
            router_span,
            "agent_routed",
            f"Router 选择 {len(selected_agents)} 个 Agent，effort={effort}",
            {
                "agents": [agent["agent_id"] for agent in selected_agents],
                "effort": effort,
                "tool_augmented_agents": tool_augmented_agents,
            },
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
