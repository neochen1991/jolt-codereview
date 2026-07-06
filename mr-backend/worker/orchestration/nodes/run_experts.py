from __future__ import annotations

import json
from typing import Any, Callable

from orchestration.deepagents_runner import run_bounded_deepagent
from prompts.example_retriever import retrieve_examples
from rules.skill_checkpoint_parser import parse_skill_checkpoints


def _builtin_java_heuristics_enabled(project_config: dict[str, Any]) -> bool:
    policy = project_config.get("tool_policy") if isinstance(project_config.get("tool_policy"), dict) else {}
    static_runners = policy.get("static_runners") if isinstance(policy.get("static_runners"), dict) else {}
    runner_cfg = static_runners.get("java_web_static") if isinstance(static_runners.get("java_web_static"), dict) else {}
    return bool(
        policy.get("enable_builtin_java_heuristics")
        or policy.get("enable_jolt_builtin_rules")
        or runner_cfg.get("enabled") is True
    )


def _deepagents_policy(project_config: dict[str, Any]) -> dict[str, Any]:
    agent_policy = project_config.get("agent_policy") if isinstance(project_config.get("agent_policy"), dict) else {}
    policy = agent_policy.get("deepagents") if isinstance(agent_policy.get("deepagents"), dict) else {}
    return {
        "enabled": bool(policy.get("enabled")),
        "enable_for_deep_effort": policy.get("enable_for_deep_effort") is not False,
        "enable_for_required_agents": policy.get("enable_for_required_agents") is not False,
        "enable_for_skill_bundle": policy.get("enable_for_skill_bundle") is not False,
    }


def _deepagents_enabled_for_agent(project_config: dict[str, Any], *, effort: str, agent: dict[str, Any], has_skill_bundle: bool) -> tuple[bool, str]:
    policy = _deepagents_policy(project_config)
    if not policy["enabled"]:
        return False, "disabled_by_project_policy"
    if effort == "deep" and policy["enable_for_deep_effort"]:
        return True, "deep_effort"
    if agent.get("requires_deepagents") and policy["enable_for_required_agents"]:
        return True, "agent_requires_deepagents"
    if has_skill_bundle and policy["enable_for_skill_bundle"]:
        return True, "skill_bundle"
    return False, "no_enabled_trigger"


def _table_columns(conn: Any, table: str) -> set[str]:
    try:
        return {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT column_name AS name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table,),
            ).fetchall()
        }
    except Exception:
        return set()


def _project_id_for_job(conn: Any, job: Any) -> str:
    try:
        row = conn.execute(
            """
            SELECT r.project_id AS project_id
            FROM review_jobs rj
            JOIN merge_requests mr ON mr.id = rj.merge_request_id
            JOIN repositories r ON r.id = mr.repository_id
            WHERE rj.id = %s
            """,
            (job["id"],),
        ).fetchone()
        return str(row["project_id"] or "") if row else ""
    except Exception:
        return ""


def _bound_rule_batches(agent_context: dict[str, Any]) -> list[dict[str, Any]]:
    rules = [rule for rule in (agent_context.get("bound_rules") or []) if isinstance(rule, dict)]
    custom_skills = [str(skill).strip() for skill in (agent_context.get("custom_skills") or []) if str(skill).strip()]
    skill_assets = [asset for asset in (agent_context.get("skill_assets") or []) if isinstance(asset, dict)]
    if not rules and not custom_skills:
        return [{"label": "default", "agent": agent_context, "rule_id": ""}]
    batches: list[dict[str, Any]] = []
    for index, rule in enumerate(rules, start=1):
        rule_id = str(rule.get("rule_id") or f"rule_{index}")
        batches.append(
            {
                "label": f"bound_rule:{rule_id}",
                "rule_id": rule_id,
                "agent": {
                    **agent_context,
                    "bound_rules": [rule],
                    "bound_rule_batch": {
                        "index": index,
                        "total": len(rules),
                        "rule_id": rule_id,
                    },
                },
            }
        )
    for skill_index, skill_key in enumerate(custom_skills, start=1):
        filtered_assets = [asset for asset in skill_assets if str(asset.get("skill_key") or "") == skill_key]
        checkpoints = _skill_checkpoints(skill_key, filtered_assets)
        for checkpoint_index, checkpoint in enumerate(checkpoints, start=1):
            checkpoint_id = str(checkpoint.get("checkpoint_id") or f"SKILL:{skill_key}")
            batches.append(
                {
                    "label": f"bound_skill:{skill_key}:{checkpoint_id}",
                    "rule_id": "",
                    "skill_key": skill_key,
                    "checkpoint_id": checkpoint_id,
                    "agent": {
                        **agent_context,
                        "custom_skills": [skill_key],
                        "skill_assets": filtered_assets,
                        "skill_checkpoints": [checkpoint],
                        "bound_rules": [],
                        "bound_skill_batch": {
                            "index": skill_index,
                            "total": len(custom_skills),
                            "checkpoint_index": checkpoint_index,
                            "checkpoint_total": len(checkpoints),
                            "skill_key": skill_key,
                            "checkpoint_id": checkpoint_id,
                            "enforce_skill_scope": True,
                        },
                    },
                }
            )
    if not custom_skills:
        batches.append(
            {
                "label": "expert_free_review",
                "rule_id": "",
                "agent": {
                    **agent_context,
                    "bound_rules": [],
                    "bound_rule_batch": {
                        "index": len(rules) + 1,
                        "total": len(rules) + 1,
                        "rule_id": "",
                        "purpose": "free_review_after_all_bound_rules",
                    },
                },
            }
        )
    return batches


def _skill_checkpoints(skill_key: str, skill_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    skill_docs = [
        asset
        for asset in skill_assets
        if str(asset.get("asset_path") or "").lower() == "skill.md"
    ]
    source_assets = skill_docs or skill_assets
    combined: list[dict[str, Any]] = []
    for asset in source_assets:
        content = str(asset.get("content") or "")
        if not content.strip():
            continue
        combined.extend(
            parse_skill_checkpoints(
                skill_key,
                content,
                source_path=str(asset.get("asset_path") or "SKILL.md"),
            )
        )
    if combined:
        return combined
    return parse_skill_checkpoints(skill_key, "", source_path="SKILL.md")


def _has_required_bound_review(agent_context: dict[str, Any]) -> bool:
    return bool(agent_context.get("bound_rules") or agent_context.get("custom_skills") or agent_context.get("skill_assets"))


def _rule_checked_status(items: list[dict[str, Any]], rule_id: str) -> dict[str, Any]:
    if not rule_id:
        return {"rule_id": "", "checked": True, "hit": False, "skipped": False, "finding_count": len(items)}
    hit_count = 0
    skipped_count = 0
    for item in items:
        covered = {str(rule) for rule in (item.get("covered_rules") or [])}
        skipped = {str(rule) for rule in (item.get("skipped_rules") or [])}
        if rule_id in covered:
            hit_count += 1
        if rule_id in skipped:
            skipped_count += 1
    return {
        "rule_id": rule_id,
        "checked": True,
        "hit": hit_count > 0,
        "skipped": skipped_count > 0,
        "finding_count": len(items),
        "hit_count": hit_count,
        "skipped_count": skipped_count,
    }


def _enforce_bound_batch_findings(batch: dict[str, Any], items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_rule_id = str(batch.get("rule_id") or "").strip()
    expected_checkpoint_id = str(batch.get("checkpoint_id") or "").strip()
    expected_id = expected_rule_id or expected_checkpoint_id
    if not expected_id:
        return items, []

    is_skill_checkpoint = bool(expected_checkpoint_id)
    mismatch_reason = "bound_skill_checkpoint_mismatch" if is_skill_checkpoint else "bound_rule_mismatch"
    attribution_flag = "bound_skill_checkpoint_attributed" if is_skill_checkpoint else "bound_rule_attributed"
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in items:
        finding = dict(item)
        covered_rules = _string_list(finding.get("covered_rules"))
        if covered_rules and expected_id not in covered_rules:
            rejected.append(_with_rejected_reason(finding, mismatch_reason))
            continue

        if not covered_rules:
            finding["verification_flags"] = _unique_strings([*(_string_list(finding.get("verification_flags"))), attribution_flag])
        finding["covered_rules"] = [expected_id]
        finding["rule_id"] = expected_id
        finding["review_batch_label"] = str(batch.get("label") or "")
        if expected_rule_id:
            finding["bound_rule_id"] = expected_rule_id
        if is_skill_checkpoint:
            finding["skill_key"] = str(batch.get("skill_key") or "")
            finding["checkpoint_id"] = expected_checkpoint_id
        kept.append(finding)
    return kept, rejected


def _bound_review_coverage_record(
    agent_id: str,
    batch: dict[str, Any],
    items: list[dict[str, Any]],
    rejected_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    rule_id = str(batch.get("rule_id") or "").strip()
    checkpoint_id = str(batch.get("checkpoint_id") or "").strip()
    if not rule_id and not checkpoint_id:
        return None
    record = {
        "agent_id": agent_id,
        "batch_label": str(batch.get("label") or ""),
        "type": "skill_checkpoint" if checkpoint_id else "rule",
        "rule_id": rule_id,
        "skill_key": str(batch.get("skill_key") or ""),
        "checkpoint_id": checkpoint_id,
        "checked": True,
        "finding_count": len(items),
        "rejected_count": len(rejected_items),
        "hit": len(items) > 0,
    }
    return record


def _summarize_bound_review_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    required_records = [record for record in records if record.get("type") in {"rule", "skill_checkpoint"}]
    required_count = len(required_records)
    checked_count = sum(1 for record in required_records if record.get("checked"))
    hit_count = sum(1 for record in required_records if int(record.get("finding_count") or 0) > 0)
    rejected_count = sum(int(record.get("rejected_count") or 0) for record in required_records)
    missed = [record for record in required_records if record.get("checked") and int(record.get("finding_count") or 0) == 0]
    return {
        "required_count": required_count,
        "checked_count": checked_count,
        "hit_count": hit_count,
        "missed_count": len(missed),
        "coverage_rate": round(checked_count / required_count, 4) if required_count else 1.0,
        "hit_rate": round(hit_count / required_count, 4) if required_count else 1.0,
        "rule_count": sum(1 for record in required_records if record.get("type") == "rule"),
        "skill_checkpoint_count": sum(1 for record in required_records if record.get("type") == "skill_checkpoint"),
        "rejected_count": rejected_count,
        "missed": [
            {
                "agent_id": record.get("agent_id") or "",
                "batch_label": record.get("batch_label") or "",
                "type": record.get("type") or "",
                "rule_id": record.get("rule_id") or "",
                "skill_key": record.get("skill_key") or "",
                "checkpoint_id": record.get("checkpoint_id") or "",
            }
            for record in missed
        ],
        "items": required_records,
    }


def _with_rejected_reason(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**item, "rejected_reasons": _unique_strings([*(_string_list(item.get("rejected_reasons"))), reason])}


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if str(value).strip()]


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _first_rule_id(row: Any) -> str:
    if "covered_rules_json" not in row.keys():
        return ""
    try:
        values = json.loads(str(row["covered_rules_json"] or "[]"))
    except (TypeError, ValueError):
        values = []
    return str(values[0]) if isinstance(values, list) and values else ""


def _load_feedback_examples(conn: Any, project_id: str, agent_id: str) -> list[dict[str, Any]]:
    if not project_id or not agent_id:
        return []
    finding_columns = _table_columns(conn, "review_findings")
    if not {"id", "review_run_id", "agent_id", "file_path", "lifecycle_state"}.issubset(finding_columns):
        return []
    optional = {
        "line_start": "rf.line_start",
        "severity": "rf.severity",
        "title": "rf.title",
        "problem_description": "rf.problem_description",
        "evidence": "rf.evidence",
        "covered_rules_json": "rf.covered_rules_json",
    }
    select_parts = [
        "rf.agent_id AS agent_id",
        "rf.file_path AS file_path",
        "rf.lifecycle_state AS lifecycle_state",
        "uf.feedback_type AS feedback_type",
        "uf.created_at AS created_at",
    ]
    for column, expression in optional.items():
        select_parts.append(f"{expression} AS {column}" if column in finding_columns else f"'' AS {column}")
    try:
        rows = conn.execute(
            f"""
            SELECT {", ".join(select_parts)}
            FROM user_feedback uf
            JOIN review_findings rf ON rf.id = uf.finding_id
            JOIN review_runs rr ON rr.id = rf.review_run_id
            JOIN review_jobs rj ON rj.id = rr.review_job_id
            JOIN merge_requests mr ON mr.id = rj.merge_request_id
            JOIN repositories r ON r.id = mr.repository_id
            WHERE r.project_id = %s
              AND rf.agent_id = %s
              AND (
                uf.feedback_type = 'false_positive'
                OR rf.lifecycle_state IN ('false_positive', 'rejected_false_positive', 'judge_rejected')
              )
              AND NULLIF(uf.created_at, '')::timestamptz >= CURRENT_TIMESTAMP - INTERVAL '90 days'
            ORDER BY uf.created_at DESC
            LIMIT 50
            """,
            (project_id, agent_id),
        ).fetchall()
    except Exception:
        return []
    examples = []
    for row in rows:
        item = {key: row[key] for key in row.keys()}
        item["label"] = "skip_false_positive"
        item["rule_id"] = _first_rule_id(row)
        examples.append(item)
    return examples


def make_run_experts_node(
    *,
    conn: Any,
    recorder: Any,
    job: Any,
    run_id: str,
    project_config: dict[str, Any],
    data_policy: dict[str, Any],
    tool_gateway: Any,
    package_version: Callable[[str], str | None],
    load_skill_summary: Callable[[str], str],
    load_tool_observations: Callable[[Any, str], list[dict[str, Any]]],
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
        project_id = _project_id_for_job(conn, job)
        conn.execute("UPDATE review_jobs SET status = 'reviewing', heartbeat_at = CURRENT_TIMESTAMP WHERE id = %s", (job["id"],))
        conn.execute(
            "UPDATE merge_requests SET review_status = 'reviewing' WHERE id = %s AND review_status NOT IN ('merged', 'closed')",
            (job["merge_request_id"],),
        )
        conn.commit()
        all_findings: list[dict[str, Any]] = []
        bound_review_coverage_records: list[dict[str, Any]] = []
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
            agent_skills = [str(skill) for skill in (agent.get("skills") or []) if str(skill).strip()]
            custom_skills = [str(skill) for skill in (agent.get("custom_skills") or []) if str(skill).strip()]
            skill_assets = [item for item in (agent.get("skill_assets") or []) if isinstance(item, dict)]
            skill_summary = "\n\n".join(load_skill_summary(skill, files) for skill in agent_skills)
            if agent_skills or skill_assets:
                recorder.event(
                    span,
                    "skill_context_loaded",
                    f"{agent_id} 加载 {len(agent_skills)} 个 Skill 作为检视上下文",
                    {
                        "skills": agent_skills,
                        "custom_skills": custom_skills,
                        "skill_assets": [
                            {
                                "skill_key": item.get("skill_key"),
                                "asset_path": item.get("asset_path"),
                                "asset_type": item.get("asset_type"),
                            }
                            for item in skill_assets
                        ],
                        "skill_context_chars": len(skill_summary),
                    },
                )
            agent_context = {
                **agent,
                "tool_observations": tool_observations,
                "related_context": state.get("related_context") or {},
                "budget_tracker": budget_tracker,
            }
            feedback_examples = _load_feedback_examples(conn, project_id, agent_id)
            learned_examples = retrieve_examples(agent_id, llm_files or files, feedback_rows=feedback_examples, k=3)
            if learned_examples:
                agent_context["learned_examples"] = learned_examples
                recorder.event(
                    span,
                    "learned_examples_loaded",
                    f"{agent_id} 注入 {len(learned_examples)} 条自检索样例",
                    {
                        "project_id": project_id,
                        "sources": sorted({str(item.get("source") or "") for item in learned_examples}),
                        "labels": sorted({str(item.get("label") or "") for item in learned_examples}),
                    },
                )
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
            deepagents_allowed, deepagents_reason = _deepagents_enabled_for_agent(
                project_config,
                effort=effort,
                agent=agent,
                has_skill_bundle=has_skill_bundle,
            )
            recorder.event(
                span,
                "deepagents_policy_evaluated",
                "DeepAgents 子图已按项目显式配置门控",
                {
                    "allowed": deepagents_allowed,
                    "reason": deepagents_reason,
                    "effort": effort,
                    "requires_deepagents": bool(agent.get("requires_deepagents")),
                    "has_skill_bundle": has_skill_bundle,
                },
            )
            if deepagents_allowed:
                try:
                    max_tool_calls = int(agent.get("max_tool_calls") or 12)
                    if has_skill_bundle:
                        max_tool_calls = max(max_tool_calls, 14)
                    if agent_skills or skill_assets:
                        recorder.event(
                            span,
                            "skill_deepagents_invoked",
                            f"{agent_id} 调用 Skill Bundle 受控工具链",
                            {
                                "skills": agent_skills,
                                "custom_skills": custom_skills,
                                "asset_count": len(skill_assets),
                                "max_tool_calls": max_tool_calls,
                            },
                        )
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
            if effort == "trivial" and not _has_required_bound_review(agent_context):
                llm_items = []
            elif budget_tracker and budget_tracker.should_stop():
                recorder.event(span, "llm_skipped_by_budget", f"预算已触发熔断：{budget_tracker.truncated_reason}", budget_tracker.snapshot())
                llm_items = []
            else:
                llm_items = []
                rule_batches = _bound_rule_batches(agent_context)
                for batch in rule_batches:
                    if budget_tracker and budget_tracker.should_stop():
                        recorder.event(span, "llm_skipped_by_budget", f"预算已触发熔断：{budget_tracker.truncated_reason}", budget_tracker.snapshot())
                        break
                    batch_agent = batch["agent"]
                    if agent_skills or skill_assets:
                        recorder.event(
                            span,
                            "skill_llm_context_used",
                            f"{agent_id} 使用 Skill 上下文检视 {batch['label']}",
                            {
                                "skills": agent_skills,
                                "custom_skills": custom_skills,
                                "asset_count": len(skill_assets),
                                "batch_label": batch["label"],
                                "rule_id": batch["rule_id"],
                            },
                        )
                    if batch["rule_id"]:
                        batch_event_type = "bound_rule_batch_started"
                        batch_payload = batch_agent.get("bound_rule_batch") or {}
                    elif batch.get("skill_key"):
                        batch_event_type = "bound_skill_started"
                        batch_payload = batch_agent.get("bound_skill_batch") or {}
                    else:
                        batch_event_type = "expert_free_review_started"
                        batch_payload = batch_agent.get("bound_rule_batch") or {}
                    recorder.event(
                        span,
                        batch_event_type,
                        f"{agent_id} 开始检视 {batch['label']}",
                        batch_payload,
                    )
                    batch_skill_summary = skill_summary
                    if batch.get("skill_key"):
                        batch_skill_summary = load_skill_summary(str(batch["skill_key"]), files)
                    batch_items = call_llm(project_config, recorder, span, batch_agent, llm_files, batch_skill_summary)
                    batch_items, rejected_batch_items = _enforce_bound_batch_findings(batch, batch_items)
                    coverage_record = _bound_review_coverage_record(agent_id, batch, batch_items, rejected_batch_items)
                    if coverage_record:
                        bound_review_coverage_records.append(coverage_record)
                    if rejected_batch_items:
                        recorder.event(
                            span,
                            "bound_batch_findings_rejected",
                            f"{agent_id} 过滤 {len(rejected_batch_items)} 个越界批次 finding",
                            {
                                "batch_label": batch["label"],
                                "rule_id": batch.get("rule_id") or "",
                                "skill_key": batch.get("skill_key") or "",
                                "checkpoint_id": batch.get("checkpoint_id") or "",
                                "rejected_count": len(rejected_batch_items),
                                "rejected_reasons": sorted({reason for item in rejected_batch_items for reason in (item.get("rejected_reasons") or [])}),
                            },
                        )
                    if batch["rule_id"]:
                        recorder.event(
                            span,
                            "bound_rule_checked",
                            f"{agent_id} 完成绑定规则 {batch['rule_id']} 检视",
                            _rule_checked_status(batch_items, str(batch["rule_id"])),
                        )
                    elif batch.get("skill_key"):
                        recorder.event(
                            span,
                            "bound_skill_checked",
                            f"{agent_id} 完成绑定 Skill {batch['skill_key']} checkpoint {batch.get('checkpoint_id') or ''} 检视",
                            {
                                "skill_key": batch["skill_key"],
                                "checkpoint_id": batch.get("checkpoint_id"),
                                "checked": True,
                                "finding_count": len(batch_items),
                            },
                        )
                    llm_items.extend(batch_items)
            for item in llm_items:
                item["head_sha"] = job["head_sha"]
            merged = dedupe(static_items + llm_items)
            recorder.event(span, "finding_candidate", f"{agent_id} 产出 {len(merged)} 个候选问题")
            all_findings.extend(merged)
            recorder.finish(span)
        bound_review_coverage = _summarize_bound_review_coverage(bound_review_coverage_records)
        if bound_review_coverage["required_count"]:
            coverage_span = recorder.span("bound_review_coverage", "quality_audit")
            recorder.event(
                coverage_span,
                "bound_review_coverage_summarized",
                (
                    f"绑定规则/Skill 覆盖审计：检查 {bound_review_coverage['checked_count']}/"
                    f"{bound_review_coverage['required_count']}，命中 {bound_review_coverage['hit_count']}，"
                    f"未命中 {bound_review_coverage['missed_count']}"
                ),
                bound_review_coverage,
            )
            recorder.finish(coverage_span)
        return {
            **state,
            "all_findings": all_findings,
            "candidate_quality": {
                **(state.get("candidate_quality") or {}),
                "bound_review_coverage": bound_review_coverage,
            },
        }

    return run_experts_node
