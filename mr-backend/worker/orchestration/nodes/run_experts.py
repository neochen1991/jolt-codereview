from __future__ import annotations

import json
import re
from typing import Any, Callable
from skill_debug import production_side_effects_allowed

from context.context_executor import call_llm_for_context_units
from orchestration.deepagents_runner import run_bounded_deepagent
from prompts.example_retriever import retrieve_examples
from rules.skill_checkpoint_parser import parse_skill_checkpoints
from orchestration.skill_runtime_facts import checkpoint_applies_to_files


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


def _batch_size(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 8))


def _chunks(values: list[Any], size: int) -> list[list[Any]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _bound_batch_limits(config: dict[str, Any] | None = None) -> dict[str, int]:
    quality = config.get("review_quality") if isinstance(config, dict) and isinstance(config.get("review_quality"), dict) else {}
    return {
        "bound_rules_per_llm_call": _batch_size(quality.get("bound_rules_per_llm_call"), 4),
        "skill_checkpoints_per_llm_call": _batch_size(quality.get("skill_checkpoints_per_llm_call"), 4),
    }


def _bound_rule_batches(
    agent_context: dict[str, Any],
    files: list[dict[str, Any]] | None = None,
    batch_limits: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    rules = [rule for rule in (agent_context.get("bound_rules") or []) if isinstance(rule, dict)]
    custom_skills = [str(skill).strip() for skill in (agent_context.get("custom_skills") or []) if str(skill).strip()]
    skill_assets = [asset for asset in (agent_context.get("skill_assets") or []) if isinstance(asset, dict)]
    skill_manifests = agent_context.get("skill_checkpoint_manifests") if isinstance(agent_context.get("skill_checkpoint_manifests"), dict) else {}
    if not rules and not custom_skills:
        return [{"label": "default", "agent": agent_context, "rule_id": ""}]
    batches: list[dict[str, Any]] = []
    rule_batch_size = _batch_size((batch_limits or {}).get("bound_rules_per_llm_call"), 1)
    checkpoint_batch_size = _batch_size((batch_limits or {}).get("skill_checkpoints_per_llm_call"), 1)
    indexed_rules = [
        (index, rule, str(rule.get("rule_id") or f"rule_{index}"))
        for index, rule in enumerate(rules, start=1)
    ]
    for rule_chunk in _chunks(indexed_rules, rule_batch_size):
        rule_ids = [item[2] for item in rule_chunk]
        chunk_rules = [item[1] for item in rule_chunk]
        first_index = rule_chunk[0][0]
        label = f"bound_rule:{rule_ids[0]}" if len(rule_ids) == 1 else f"bound_rule_batch:{','.join(rule_ids)}"
        batches.append(
            {
                "label": label,
                "rule_id": rule_ids[0] if len(rule_ids) == 1 else "",
                "rule_ids": rule_ids,
                "agent": {
                    **agent_context,
                    "bound_rules": chunk_rules,
                    "bound_rule_batch": {
                        "index": first_index,
                        "total": len(rules),
                        "rule_id": rule_ids[0] if len(rule_ids) == 1 else "",
                        "rule_ids": rule_ids,
                        "batch_size": len(rule_ids),
                    },
                },
            }
        )
    for skill_index, skill_key in enumerate(custom_skills, start=1):
        filtered_assets = [asset for asset in skill_assets if str(asset.get("skill_key") or "") == skill_key]
        manifest = skill_manifests.get(skill_key) if isinstance(skill_manifests.get(skill_key), dict) else None
        checkpoints = _skill_checkpoints(skill_key, filtered_assets, manifest=manifest)
        if files is not None:
            checkpoints = [checkpoint for checkpoint in checkpoints if checkpoint_applies_to_files(checkpoint, files)]
        indexed_checkpoints = [
            (checkpoint_index, checkpoint, str(checkpoint.get("checkpoint_id") or f"SKILL:{skill_key}"))
            for checkpoint_index, checkpoint in enumerate(checkpoints, start=1)
        ]
        for checkpoint_chunk in _chunks(indexed_checkpoints, checkpoint_batch_size):
            checkpoint_ids = [item[2] for item in checkpoint_chunk]
            chunk_checkpoints = [item[1] for item in checkpoint_chunk]
            first_checkpoint_index = checkpoint_chunk[0][0]
            label = (
                f"bound_skill:{skill_key}:{checkpoint_ids[0]}"
                if len(checkpoint_ids) == 1
                else f"bound_skill_batch:{skill_key}:{','.join(checkpoint_ids)}"
            )
            batches.append(
                {
                    "label": label,
                    "rule_id": "",
                    "skill_key": skill_key,
                    "checkpoint_id": checkpoint_ids[0] if len(checkpoint_ids) == 1 else "",
                    "checkpoint_ids": checkpoint_ids,
                    "agent": {
                        **agent_context,
                        "custom_skills": [skill_key],
                        "skill_assets": filtered_assets,
                        "skill_checkpoints": chunk_checkpoints,
                        "bound_rules": [],
                        "bound_skill_batch": {
                            "index": skill_index,
                            "total": len(custom_skills),
                            "checkpoint_index": first_checkpoint_index,
                            "checkpoint_total": len(checkpoints),
                            "skill_key": skill_key,
                            "checkpoint_id": checkpoint_ids[0] if len(checkpoint_ids) == 1 else "",
                            "checkpoint_ids": checkpoint_ids,
                            "batch_size": len(checkpoint_ids),
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


def _coverage_retry_batch(batch: dict[str, Any], *, reason: str) -> dict[str, Any] | None:
    rule_ids = _batch_rule_ids(batch)
    checkpoint_ids = _batch_checkpoint_ids(batch)
    rule_id = rule_ids[0] if len(rule_ids) == 1 else ""
    checkpoint_id = checkpoint_ids[0] if len(checkpoint_ids) == 1 else ""
    target_ids = rule_ids or checkpoint_ids
    if not target_ids:
        return None
    agent = dict(batch.get("agent") or {})
    applies_to = dict(agent.get("applies_to") or {})
    target_id = ",".join(target_ids)
    existing_prompt = str(applies_to.get("custom_prompt") or "").strip()
    retry_prompt = (
        f"绑定规则/Skill 补检视：上一轮没有输出 {target_id} 的命中或明确跳过结果。"
        "本轮只复核该规则/Checkpoint；如果命中，必须输出精确源码证据和 covered_rules；"
        "如果没有命中，返回空 JSON 数组，不要输出相邻问题。"
    )
    applies_to["custom_prompt"] = f"{existing_prompt}\n\n{retry_prompt}".strip()
    agent["applies_to"] = applies_to
    if rule_id:
        rule_batch = dict(agent.get("bound_rule_batch") or {})
        rule_batch.update({"coverage_retry": True, "retry_reason": reason, "target_id": target_id, "target_ids": target_ids})
        agent["bound_rule_batch"] = rule_batch
    elif rule_ids:
        rule_batch = dict(agent.get("bound_rule_batch") or {})
        rule_batch.update({"coverage_retry": True, "retry_reason": reason, "target_id": target_id, "target_ids": target_ids})
        agent["bound_rule_batch"] = rule_batch
    if checkpoint_id:
        skill_batch = dict(agent.get("bound_skill_batch") or {})
        skill_batch.update({"coverage_retry": True, "retry_reason": reason, "target_id": target_id, "target_ids": target_ids})
        agent["bound_skill_batch"] = skill_batch
    elif checkpoint_ids:
        skill_batch = dict(agent.get("bound_skill_batch") or {})
        skill_batch.update({"coverage_retry": True, "retry_reason": reason, "target_id": target_id, "target_ids": target_ids})
        agent["bound_skill_batch"] = skill_batch
    return {**batch, "label": f"{batch.get('label')}:coverage_retry", "agent": agent, "coverage_retry": True}


def _coverage_retry_context_units(config: dict[str, Any], context_units: list[Any]) -> list[Any]:
    quality = config.get("review_quality") if isinstance(config.get("review_quality"), dict) else {}
    raw = quality.get("coverage_retry_context_units_limit", 2)
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 2
    limit = max(0, min(limit, len(context_units)))
    if limit == 0:
        return []
    ranked = sorted(
        enumerate(context_units),
        key=lambda item: (
            1 if str(getattr(item[1], "fallback_reason", "") or (item[1].get("fallback_reason") if isinstance(item[1], dict) else "") or "") else 0,
            -len(getattr(item[1], "dependencies", ()) or (item[1].get("dependencies") if isinstance(item[1], dict) else []) or []),
            item[0],
        ),
    )
    return [unit for _index, unit in ranked[:limit]]


def _skill_checkpoints(
    skill_key: str,
    skill_assets: list[dict[str, Any]],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if manifest:
        compiler_version = str(manifest.get("compiler_version") or "")
        source_hash = str(manifest.get("source_hash") or "")
        compiled = [item for item in (manifest.get("checkpoints") or []) if isinstance(item, dict)]
        if compiled:
            return [
                {
                    **item,
                    "skill_key": str(item.get("skill_key") or skill_key),
                    "compiler_version": compiler_version,
                    "manifest_source_hash": source_hash,
                    "manifest_mode": "compiled",
                }
                for item in compiled
            ]
    source_assets = [asset for asset in skill_assets if _is_checkpoint_source_asset(asset)]
    combined: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for asset in source_assets:
        content = str(asset.get("content") or "")
        if not content.strip():
            continue
        parsed = parse_skill_checkpoints(
            skill_key,
            content,
            source_path=str(asset.get("asset_path") or "SKILL.md"),
        )
        structured = [item for item in parsed if str(item.get("parse_quality") or "") == "structured"]
        if structured:
            combined.extend({**item, "manifest_mode": "legacy_fallback"} for item in structured)
        else:
            fallback.extend({**item, "manifest_mode": "legacy_fallback"} for item in parsed)
    if combined:
        return combined
    if fallback:
        return fallback[:1]
    return [{**item, "manifest_mode": "legacy_fallback"} for item in parse_skill_checkpoints(skill_key, "", source_path="SKILL.md")]


def _is_checkpoint_source_asset(asset: dict[str, Any]) -> bool:
    asset_path = str(asset.get("asset_path") or "").replace("\\", "/").lower()
    asset_type = str(asset.get("asset_type") or "").lower()
    if asset_path == "skill.md":
        return True
    if asset_path.startswith("references/") and asset_path.endswith((".md", ".mdx", ".txt")):
        return True
    return asset_type in {"skill", "reference"} and asset_path.endswith((".md", ".mdx", ".txt"))


def _has_required_bound_review(agent_context: dict[str, Any]) -> bool:
    return bool(agent_context.get("bound_rules") or agent_context.get("custom_skills") or agent_context.get("skill_assets"))


def _rule_checked_status(items: list[dict[str, Any]], rule_id: str) -> dict[str, Any]:
    if not rule_id:
        return {"rule_id": "", "checked": True, "hit": False, "skipped": False, "finding_count": _bound_finding_count(items)}
    hit_count = 0
    skipped_count = 0
    for item in items:
        if _is_bound_skip_marker(item):
            skipped_count += 1
            continue
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
        "finding_count": _bound_finding_count(items),
        "hit_count": hit_count,
        "skipped_count": skipped_count,
    }


def _batch_rule_ids(batch: dict[str, Any]) -> list[str]:
    values = [str(item).strip() for item in (batch.get("rule_ids") or []) if str(item).strip()]
    single = str(batch.get("rule_id") or "").strip()
    if single and single not in values:
        values.insert(0, single)
    return _unique_strings(values)


def _batch_checkpoint_ids(batch: dict[str, Any]) -> list[str]:
    values = [str(item).strip() for item in (batch.get("checkpoint_ids") or []) if str(item).strip()]
    single = str(batch.get("checkpoint_id") or "").strip()
    if single and single not in values:
        values.insert(0, single)
    return _unique_strings(values)


def _expected_batch_ids(batch: dict[str, Any]) -> list[str]:
    return _batch_rule_ids(batch) or _batch_checkpoint_ids(batch)


def _enforce_bound_batch_findings(batch: dict[str, Any], items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_rule_ids = _batch_rule_ids(batch)
    expected_checkpoint_ids = _batch_checkpoint_ids(batch)
    expected_ids = expected_rule_ids or expected_checkpoint_ids
    if not expected_ids:
        return items, []

    is_skill_checkpoint = bool(expected_checkpoint_ids)
    mismatch_reason = "bound_skill_checkpoint_mismatch" if is_skill_checkpoint else "bound_rule_mismatch"
    attribution_flag = "bound_skill_checkpoint_attributed" if is_skill_checkpoint else "bound_rule_attributed"
    expected_set = set(expected_ids)
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in items:
        finding = dict(item)
        covered_rules = _string_list(finding.get("covered_rules"))
        skipped_rules = _string_list(finding.get("skipped_rules"))
        matched_skipped = [rule for rule in skipped_rules if rule in expected_set]
        matched_covered = [rule for rule in covered_rules if rule in expected_set]
        if not covered_rules and matched_skipped and not _has_finding_payload(finding):
            kept.append(
                {
                    **finding,
                    "__bound_skip_marker": True,
                    "covered_rules": [],
                    "skipped_rules": matched_skipped,
                    "review_batch_label": str(batch.get("label") or ""),
                    "bound_rule_id": matched_skipped[0] if expected_rule_ids else "",
                    "skill_key": str(batch.get("skill_key") or ""),
                    "checkpoint_id": matched_skipped[0] if is_skill_checkpoint else "",
                    "verification_flags": _unique_strings([*(_string_list(finding.get("verification_flags"))), "bound_rule_or_checkpoint_skipped"]),
                }
            )
            continue
        if not covered_rules and skipped_rules and not matched_skipped:
            rejected.append(_with_rejected_reason(finding, mismatch_reason))
            continue
        if covered_rules and not matched_covered:
            rejected.append(_with_rejected_reason(finding, mismatch_reason))
            continue

        if not covered_rules:
            if len(expected_ids) > 1:
                rejected.append(_with_rejected_reason(finding, "bound_batch_missing_rule_attribution"))
                continue
            matched_covered = [expected_ids[0]]
            finding["verification_flags"] = _unique_strings([*(_string_list(finding.get("verification_flags"))), attribution_flag])
        finding["covered_rules"] = matched_covered
        primary_id = matched_covered[0]
        finding["rule_id"] = primary_id
        finding["review_batch_label"] = str(batch.get("label") or "")
        if expected_rule_ids:
            finding["bound_rule_id"] = primary_id
        if is_skill_checkpoint:
            finding["skill_key"] = str(batch.get("skill_key") or "")
            finding["checkpoint_id"] = primary_id
        contract_source = _bound_batch_contract_source(batch, primary_id)
        contract = _audit_bound_evidence_contract(finding, contract_source, primary_id)
        if contract:
            finding["bound_evidence_contract"] = contract
            if contract["status"] == "false_positive_pattern_matched":
                rejected.append(_with_rejected_reason(finding, "bound_false_positive_pattern_match"))
                continue
            if contract["missing_required_evidence"]:
                finding["verification_flags"] = _unique_strings([*(_string_list(finding.get("verification_flags"))), "bound_required_evidence_incomplete"])
        kept.append(finding)
    return kept, rejected


def _bound_batch_contract_source(batch: dict[str, Any], expected_id: str | None = None) -> dict[str, Any]:
    agent = batch.get("agent") if isinstance(batch.get("agent"), dict) else {}
    is_skill_batch = bool(_batch_checkpoint_ids(batch))
    checkpoint_id = str(expected_id or batch.get("checkpoint_id") or "").strip() if is_skill_batch else ""
    if is_skill_batch and checkpoint_id:
        for checkpoint in agent.get("skill_checkpoints") or []:
            if isinstance(checkpoint, dict) and str(checkpoint.get("checkpoint_id") or "") == checkpoint_id:
                return checkpoint
        return {}
    rule_id = str(expected_id or batch.get("rule_id") or "").strip()
    if rule_id:
        for rule in agent.get("bound_rules") or []:
            if isinstance(rule, dict) and str(rule.get("rule_id") or "") == rule_id:
                return rule
    return {}


def _audit_bound_evidence_contract(finding: dict[str, Any], contract_source: dict[str, Any], expected_id: str) -> dict[str, Any]:
    if not contract_source:
        return {}
    required = str(contract_source.get("required_evidence") or contract_source.get("evidence_required") or "").strip()
    false_positive_patterns = str(contract_source.get("false_positive_patterns") or "").strip()
    finding_text = _finding_contract_text(finding)
    required_clauses = _contract_clauses(required)
    false_positive_clauses = _contract_clauses(false_positive_patterns)
    matched_required = [clause for clause in required_clauses if _contract_clause_matches(clause, finding_text, allow_concepts=True)]
    missing_required = [clause for clause in required_clauses if clause not in matched_required]
    false_positive_text = _finding_contract_text(finding, include_fix_fields=False)
    false_positive_matches = [
        clause
        for clause in false_positive_clauses
        if _false_positive_clause_matches(clause, false_positive_text)
    ]
    if false_positive_matches:
        status = "false_positive_pattern_matched"
    elif missing_required and matched_required:
        status = "partial"
    elif missing_required:
        status = "weak"
    else:
        status = "satisfied"
    return {
        "version": "bound_evidence_contract_v1",
        "rule_id": expected_id,
        "checkpoint_id": str(finding.get("checkpoint_id") or "") or expected_id,
        "required_evidence": required,
        "false_positive_patterns": false_positive_patterns,
        "matched_required_evidence": matched_required,
        "missing_required_evidence": missing_required,
        "false_positive_matches": false_positive_matches,
        "status": status,
    }


def _finding_contract_text(finding: dict[str, Any], *, include_fix_fields: bool = True) -> str:
    parts = [
        finding.get("title"),
        finding.get("problem_description"),
        finding.get("evidence"),
    ]
    if include_fix_fields:
        parts.extend([finding.get("recommendation"), finding.get("suggested_code")])
    return "\n".join(str(part or "") for part in parts)


def _contract_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    normalized = re.sub(r"([:：])\s*[-*]\s*", r"\1\n- ", str(text or ""))
    normalized = re.sub(r"\s+[-*]\s+", "\n- ", normalized)
    for raw in re.split(r"[\n;；。]", normalized):
        cleaned = re.sub(r"^\s*[-*]\s*", "", raw).strip()
        cleaned = re.sub(
            r"^(?:证据要求|输出要求|required evidence|误报模式|误报排除|例外|false positive patterns?)[:：]\s*",
            "",
            cleaned,
            flags=re.I,
        ).strip()
        if len(cleaned) >= 2:
            clauses.append(cleaned)
    return _unique_strings(clauses)


def _contract_clause_matches(clause: str, text: str, *, allow_concepts: bool) -> bool:
    normalized_clause = _contract_normalize(clause)
    normalized_text = _contract_normalize(text)
    if normalized_clause and normalized_clause in normalized_text:
        return True
    if allow_concepts and _concept_clause_matches(clause, normalized_text):
        return True
    parts = [part for part in re.split(r"\s+|,|，|、|/|或|和|及", clause) if len(part.strip()) >= 2]
    if not parts:
        return False
    matched = sum(1 for part in parts if _contract_normalize(part) in normalized_text)
    return matched >= max(1, len(parts) - 1)


def _false_positive_clause_matches(clause: str, text: str) -> bool:
    if not _contract_clause_matches(clause, text, allow_concepts=False):
        return False
    return not _contract_clause_negated_in_text(clause, text)


def _contract_clause_negated_in_text(clause: str, text: str) -> bool:
    normalized_text = _contract_normalize(text)
    terms = [
        _contract_normalize(part)
        for part in re.split(r"\s+|,|，|、|/|或|和|及", clause)
        if len(_contract_normalize(part)) >= 2
    ]
    generic_terms = {
        "代码",
        "紧随其后",
        "调用",
        "设置",
        "明确",
        "等价",
        "key",
        "配置",
    }
    negations = ("缺少", "缺失", "未", "没有", "无", "不包含", "不存在", "missing", "without", "no")
    for term in terms:
        if term in generic_terms:
            continue
        start = 0
        while True:
            index = normalized_text.find(term, start)
            if index < 0:
                break
            window = normalized_text[max(0, index - 18): index + len(term) + 4]
            if any(negation in window for negation in negations):
                return True
            start = index + len(term)
    return False


def _concept_clause_matches(clause: str, normalized_text: str) -> bool:
    lowered = clause.lower()
    concepts = [
        (("外部输入", "用户输入", "请求参数", "输入来源"), ("request.getparameter", "request", "payload", "body", "query", "param", "用户输入", "外部输入", "请求参数")),
        (("命令执行", "command", "sink"), ("runtime.getruntime().exec", "runtime.exec", "processbuilder", ".exec(", "命令执行")),
        (("白名单", "枚举", "allowlist", "whitelist"), ("白名单", "枚举", "allowlist", "whitelist", "未看到白名单", "缺少白名单")),
        (("路径规范化", "normalize", "canonical"), ("normalize", "canonical", "torealpath", "路径规范化", "目录限制")),
    ]
    for markers, evidence_markers in concepts:
        if any(marker.lower() in lowered for marker in markers):
            return any(_contract_normalize(marker) in normalized_text for marker in evidence_markers)
    return False


def _contract_normalize(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _bound_review_coverage_record(
    agent_id: str,
    batch: dict[str, Any],
    items: list[dict[str, Any]],
    rejected_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    records = _bound_review_coverage_records(agent_id, batch, items, rejected_items)
    return records[0] if records else None


def _bound_review_coverage_records(
    agent_id: str,
    batch: dict[str, Any],
    items: list[dict[str, Any]],
    rejected_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rule_ids = _batch_rule_ids(batch)
    checkpoint_ids = _batch_checkpoint_ids(batch)
    expected_ids = rule_ids or checkpoint_ids
    if not expected_ids:
        return []
    records: list[dict[str, Any]] = []
    for expected_id in expected_ids:
        skip_markers = [
            item
            for item in items
            if _is_bound_skip_marker(item) and expected_id in _string_list(item.get("skipped_rules"))
        ]
        matched_findings = [
            item
            for item in items
            if not _is_bound_skip_marker(item) and expected_id in _string_list(item.get("covered_rules"))
        ]
        matched_rejected = [
            item
            for item in rejected_items
            if expected_id in _string_list(item.get("covered_rules")) or expected_id in _string_list(item.get("skipped_rules"))
        ]
        checkpoint_id = expected_id if checkpoint_ids else ""
        rule_id = expected_id if rule_ids else ""
        records.append(
            {
                "agent_id": agent_id,
                "batch_label": str(batch.get("label") or ""),
                "type": "skill_checkpoint" if checkpoint_id else "rule",
                "rule_id": rule_id,
                "skill_key": str(batch.get("skill_key") or ""),
                "checkpoint_id": checkpoint_id,
                "checked": True,
                "finding_count": len(matched_findings),
                "rejected_count": len(matched_rejected),
                "hit": len(matched_findings) > 0,
                "skipped": bool(skip_markers),
                "skipped_count": len(skip_markers),
            }
        )
    return records


def _summarize_bound_review_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    required_records = [record for record in records if record.get("type") in {"rule", "skill_checkpoint"}]
    required_count = len(required_records)
    checked_count = sum(1 for record in required_records if record.get("checked"))
    hit_count = sum(1 for record in required_records if int(record.get("finding_count") or 0) > 0)
    skipped_count = sum(1 for record in required_records if record.get("skipped"))
    resolved_count = hit_count + skipped_count
    rejected_count = sum(int(record.get("rejected_count") or 0) for record in required_records)
    missed = [
        record
        for record in required_records
        if record.get("checked") and int(record.get("finding_count") or 0) == 0 and not record.get("skipped")
    ]
    resolution_rate = round(resolved_count / required_count, 4) if required_count else 1.0
    unresolved_rate = round(len(missed) / required_count, 4) if required_count else 0.0
    alerts: list[dict[str, Any]] = []
    if missed:
        alerts.append(
            {
                "type": "bound_rule_resolution_unresolved",
                "severity": "warning" if resolution_rate >= 0.7 else "high",
                "required_count": required_count,
                "resolved_count": resolved_count,
                "unresolved_count": len(missed),
                "resolution_rate": resolution_rate,
                "unresolved_rate": unresolved_rate,
            }
        )
    return {
        "required_count": required_count,
        "checked_count": checked_count,
        "hit_count": hit_count,
        "skipped_count": skipped_count,
        "missed_count": len(missed),
        "resolved_count": resolved_count,
        "unresolved_count": len(missed),
        "coverage_rate": round(checked_count / required_count, 4) if required_count else 1.0,
        "resolution_rate": resolution_rate,
        "unresolved_rate": unresolved_rate,
        "hit_rate": round(hit_count / required_count, 4) if required_count else 1.0,
        "skip_rate": round(skipped_count / required_count, 4) if required_count else 0.0,
        "rule_count": sum(1 for record in required_records if record.get("type") == "rule"),
        "skill_checkpoint_count": sum(1 for record in required_records if record.get("type") == "skill_checkpoint"),
        "rejected_count": rejected_count,
        "alerts": alerts,
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


def _is_bound_skip_marker(item: dict[str, Any]) -> bool:
    return bool(item.get("__bound_skip_marker"))


def _has_finding_payload(item: dict[str, Any]) -> bool:
    payload_fields = ["title", "problem_description", "evidence", "recommendation", "suggested_code", "file_path"]
    if any(str(item.get(field) or "").strip() for field in payload_fields):
        return True
    return bool(item.get("line_start") or item.get("line_end"))


def _bound_finding_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if not _is_bound_skip_marker(item))


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


def _file_glob_matches(file_glob: str, file_path: str) -> bool:
    glob = str(file_glob or "").replace("\\", "/")
    path = str(file_path or "").replace("\\", "/")
    if not glob or glob == "**/*":
        return True
    if glob.endswith("/**"):
        return path.startswith(glob[:-3].rstrip("/") + "/")
    return path == glob


def _changed_filenames(files: list[Any]) -> list[str]:
    names: list[str] = []
    for item in files or []:
        if isinstance(item, dict):
            filename = str(item.get("filename") or item.get("file_path") or item.get("file") or "")
        else:
            filename = str(getattr(item, "filename", "") or "")
        if filename:
            names.append(filename)
    return names


def _load_suppression_hints_for_prompt(conn: Any, project_id: str, files: list[Any], *, limit: int = 5) -> list[dict[str, Any]]:
    if not project_id:
        return []
    filenames = _changed_filenames(files)
    try:
        rows = conn.execute(
            """
            SELECT project_id, rule_id, file_glob, snippet_hash, snippet_excerpt, count, last_marked_at
            FROM rule_suppression_hints
            WHERE project_id = %s
            ORDER BY count DESC, last_marked_at DESC
            LIMIT 50
            """,
            (project_id,),
        ).fetchall()
    except Exception:
        return []
    hints: list[dict[str, Any]] = []
    for row in rows:
        item = {key: row[key] for key in row.keys()}
        file_glob = str(item.get("file_glob") or "")
        if filenames and not any(_file_glob_matches(file_glob, filename) for filename in filenames):
            continue
        hints.append(
            {
                "rule_id": str(item.get("rule_id") or ""),
                "file_glob": file_glob,
                "snippet_hash": str(item.get("snippet_hash") or ""),
                "snippet_excerpt": str(item.get("snippet_excerpt") or "")[:240],
                "count": int(item.get("count") or 1),
            }
        )
        if len(hints) >= limit:
            break
    return hints


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
    ensure_active: Callable[[], None],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def run_experts_node(state: dict[str, Any]) -> dict[str, Any]:
        ensure_active()
        files = state["files"]
        llm_files = state.get("llm_files") or []
        effort = state["effort"]
        selected_agents = state["selected_agents"]
        project_id = _project_id_for_job(conn, job)
        conn.execute(
            "UPDATE review_jobs SET status = 'reviewing', heartbeat_at = CURRENT_TIMESTAMP WHERE id = %s AND status NOT IN ('cancelled', 'paused')",
            (job["id"],),
        )
        ensure_active()
        if production_side_effects_allowed(job):
            conn.execute(
                "UPDATE merge_requests SET review_status = 'reviewing' WHERE id = %s AND review_status NOT IN ('merged', 'closed', 'cancelled', 'paused')",
                (job["merge_request_id"],),
            )
        conn.commit()
        all_findings: list[dict[str, Any]] = []
        bound_review_coverage_records: list[dict[str, Any]] = []
        context_units = list(state.get("context_units") or [])
        executed_context_unit_ids: set[str] = set()
        unresolved_context_units = list(state.get("unresolved_context_units") or [])
        tool_observations = state.get("tool_observations") or load_tool_observations(conn, run_id)
        suppression_hints = _load_suppression_hints_for_prompt(conn, project_id, llm_files or files)
        if effort == "trivial":
            trivial_span = recorder.span("trivial_short_circuit", "router_agent")
            recorder.event(trivial_span, "trivial_short_circuit", "trivial 检视强度跳过 LLM，仅保留静态摘要")
            recorder.finish(trivial_span)
        for agent in selected_agents:
            ensure_active()
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
                "head_sha": str(job["head_sha"]),
            }
            if suppression_hints:
                agent_context["suppression_hints"] = suppression_hints
                recorder.event(
                    span,
                    "suppression_hints_loaded",
                    f"{agent_id} 注入 {len(suppression_hints)} 条项目 FP 抑制提示",
                    {
                        "project_id": project_id,
                        "count": len(suppression_hints),
                        "rules": sorted({str(item.get("rule_id") or "") for item in suppression_hints if item.get("rule_id")}),
                    },
                )
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
                        source_worktree_path=state.get("source_worktree_path"),
                        head_sha=str(job["head_sha"]),
                        semantic_graph=state.get("semantic_graph"),
                        exchange_recorder=recorder,
                        exchange_span_id=span,
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
                rule_batches = _bound_rule_batches(
                    agent_context,
                    state.get("files") or [],
                    batch_limits=_bound_batch_limits(project_config),
                )
                for batch in rule_batches:
                    ensure_active()
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
                    batch_rule_ids = _batch_rule_ids(batch)
                    batch_checkpoint_ids = _batch_checkpoint_ids(batch)
                    if batch_rule_ids:
                        batch_event_type = "bound_rule_batch_started"
                        batch_payload = batch_agent.get("bound_rule_batch") or {}
                    elif batch.get("skill_key") or batch_checkpoint_ids:
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
                    batch_items, executed_units, unresolved_units = call_llm_for_context_units(
                        call_llm=call_llm,
                        config=project_config,
                        recorder=recorder,
                        span=span,
                        agent=batch_agent,
                        files=llm_files,
                        skill_summary=batch_skill_summary,
                        context_units=context_units,
                        budget_tracker=budget_tracker,
                        ensure_active=ensure_active,
                    )
                    executed_context_unit_ids.update(executed_units)
                    unresolved_context_units.extend(unresolved_units)
                    batch_items, rejected_batch_items = _enforce_bound_batch_findings(batch, batch_items)
                    retry_count = 0
                    retry_hit = False
                    if (
                        not batch_items
                        and _expected_batch_ids(batch)
                        and not (budget_tracker and budget_tracker.should_stop())
                    ):
                        retry_batch = _coverage_retry_batch(batch, reason="missing_after_first_pass")
                        if retry_batch:
                            ensure_active()
                            recorder.event(
                                span,
                                "bound_rule_coverage_low",
                                f"{agent_id} 对 {batch['label']} 首轮未命中，发起补检视",
                                {
                                    "batch_label": batch["label"],
                                    "rule_id": batch.get("rule_id") or "",
                                    "skill_key": batch.get("skill_key") or "",
                                    "checkpoint_id": batch.get("checkpoint_id") or "",
                                    "reason": "missing_after_first_pass",
                                },
                            )
                            retry_agent = retry_batch["agent"]
                            retry_skill_summary = batch_skill_summary
                            if retry_batch.get("skill_key"):
                                retry_skill_summary = load_skill_summary(str(retry_batch["skill_key"]), files)
                            retry_items, retry_executed_units, retry_unresolved_units = call_llm_for_context_units(
                                call_llm=call_llm,
                                config=project_config,
                                recorder=recorder,
                                span=span,
                                agent=retry_agent,
                                files=llm_files,
                                skill_summary=retry_skill_summary,
                                context_units=_coverage_retry_context_units(project_config, context_units),
                                budget_tracker=budget_tracker,
                                ensure_active=ensure_active,
                            )
                            executed_context_unit_ids.update(retry_executed_units)
                            unresolved_context_units.extend(retry_unresolved_units)
                            retry_items, retry_rejected_items = _enforce_bound_batch_findings(batch, retry_items)
                            retry_count = 1
                            retry_hit = bool(retry_items)
                            batch_items.extend(retry_items)
                            rejected_batch_items.extend(retry_rejected_items)
                            recorder.event(
                                span,
                                "bound_rule_coverage_retry_completed",
                                f"{agent_id} 完成 {batch['label']} 补检视，新增 {len(retry_items)} 个 finding",
                                {
                                    "batch_label": batch["label"],
                                    "rule_id": batch.get("rule_id") or "",
                                    "skill_key": batch.get("skill_key") or "",
                                    "checkpoint_id": batch.get("checkpoint_id") or "",
                                    "finding_count": len(retry_items),
                                    "rejected_count": len(retry_rejected_items),
                                },
                            )
                    coverage_records = _bound_review_coverage_records(agent_id, batch, batch_items, rejected_batch_items)
                    for coverage_record in coverage_records:
                        coverage_record["retry_count"] = retry_count
                        coverage_record["retry_hit"] = retry_hit
                    bound_review_coverage_records.extend(coverage_records)
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
                                "rejected_items": [
                                    {
                                        "title": item.get("title") or "",
                                        "file_path": item.get("file_path") or "",
                                        "line_start": item.get("line_start"),
                                        "line_end": item.get("line_end"),
                                        "covered_rules": item.get("covered_rules") or [],
                                        "skipped_rules": item.get("skipped_rules") or [],
                                        "rejected_reasons": item.get("rejected_reasons") or [],
                                        "bound_evidence_contract": item.get("bound_evidence_contract") or {},
                                    }
                                    for item in rejected_batch_items[:20]
                                ],
                            },
                        )
                    if batch_rule_ids:
                        recorder.event(
                            span,
                            "bound_rule_checked",
                            f"{agent_id} 完成绑定规则 {','.join(batch_rule_ids)} 检视",
                            {
                                "rule_ids": batch_rule_ids,
                                "checked": True,
                                "rules": [_rule_checked_status(batch_items, rule_id) for rule_id in batch_rule_ids],
                            },
                        )
                    elif batch.get("skill_key") or batch_checkpoint_ids:
                        recorder.event(
                            span,
                            "bound_skill_checked",
                            f"{agent_id} 完成绑定 Skill {batch.get('skill_key') or ''} checkpoint {','.join(batch_checkpoint_ids)} 检视",
                            {
                                "skill_key": batch.get("skill_key") or "",
                                "checkpoint_id": batch.get("checkpoint_id"),
                                "checkpoint_ids": batch_checkpoint_ids,
                                "checked": True,
                                "finding_count": _bound_finding_count(batch_items),
                                "skipped_count": sum(1 for item in batch_items if _is_bound_skip_marker(item)),
                            },
                        )
                    llm_items.extend([item for item in batch_items if not _is_bound_skip_marker(item)])
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
                    f"闭环 {bound_review_coverage['resolved_count']}，未闭环 {bound_review_coverage['unresolved_count']}"
                ),
                bound_review_coverage,
            )
            if bound_review_coverage.get("alerts"):
                recorder.event(
                    coverage_span,
                    "bound_rule_resolution_alert",
                    (
                        f"绑定规则/Skill 存在 {bound_review_coverage['unresolved_count']} 个未闭环，"
                        f"闭环率 {bound_review_coverage['resolution_rate']}"
                    ),
                    {"alerts": bound_review_coverage.get("alerts"), "missed": bound_review_coverage.get("missed")},
                )
            recorder.finish(coverage_span)
        unique_unresolved = {
            (str(item.get("unit_id") or item.get("hunk_id") or ""), str(item.get("reason") or "unresolved")): item
            for item in unresolved_context_units
            if isinstance(item, dict)
        }
        context_health = dict(state.get("context_health") or {})
        context_health.update(
            {
                "context_units_total": len(context_units),
                "context_units_executed": len(executed_context_unit_ids),
                "context_units_unresolved": len(unique_unresolved),
                "status": "partial" if unique_unresolved else context_health.get("status", "full"),
            }
        )
        return {
            **state,
            "all_findings": all_findings,
            "executed_context_unit_ids": sorted(executed_context_unit_ids),
            "unresolved_context_units": list(unique_unresolved.values()),
            "context_health": context_health,
            "candidate_quality": {
                **(state.get("candidate_quality") or {}),
                "bound_review_coverage": bound_review_coverage,
            },
        }

    return run_experts_node
