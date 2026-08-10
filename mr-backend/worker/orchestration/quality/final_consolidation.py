from __future__ import annotations

import json
import time
import urllib.error
from dataclasses import dataclass
from typing import Any, Callable

from llm.client import (
    build_chat_payload,
    estimate_tokens,
    http_json,
    invoke_with_parameter_fallback,
    llm_max_output_tokens,
    request_options_for_payload,
)
from llm.exchange import execute_chat_exchange, invoke_openai_chat, replay_mode_from_config
from llm.retry import call_with_retry
from llm_router import candidate_providers
from orchestration.quality.issue_identity import canonical_issue_fingerprint


CONTRACT_VERSION = "final_finding_consolidation_v1"
TEXT_LIMIT = 1200
EVIDENCE_LIMIT = 1600
MERGED_EVIDENCE_LIMIT = 12000
SEVERITY_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


@dataclass(frozen=True)
class ConsolidationFailure:
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ConsolidationResult:
    findings: list[dict[str, Any]]
    rejections: list[dict[str, Any]]
    fallback_reason: str | None
    metadata: dict[str, Any]


def _bounded_text(value: Any, limit: int = TEXT_LIMIT) -> str:
    return str(value or "").strip()[:limit]


def compact_findings(
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    compact: list[dict[str, Any]] = []
    lookup: dict[str, dict[str, Any]] = {}
    width = max(2, len(str(max(1, len(findings)))))
    for index, finding in enumerate(findings, start=1):
        request_id = f"f_{index:0{width}d}"
        lookup[request_id] = finding
        problem = _bounded_text(finding.get("problem_description"))
        compact.append(
            {
                "id": request_id,
                "file_path": _bounded_text(finding.get("file_path"), 500),
                "line_start": finding.get("line_start"),
                "line_end": finding.get("line_end"),
                "title": _bounded_text(finding.get("title"), 500),
                "root_cause": problem,
                "impact": problem,
                "recommendation": _bounded_text(finding.get("recommendation")),
                "covered_rules": [str(rule) for rule in (finding.get("covered_rules") or []) if str(rule).strip()][:16],
                "agent_id": _bounded_text(finding.get("agent_id"), 200),
                "evidence_excerpt": _bounded_text(finding.get("evidence"), EVIDENCE_LIMIT),
            }
        )
    return compact, lookup


def _json_object(content: str) -> dict[str, Any] | None:
    raw = str(content or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_consolidation_response(
    content: str,
    known_ids: set[str],
) -> tuple[list[dict[str, Any]], ConsolidationFailure | None]:
    parsed = _json_object(content)
    if parsed is None:
        return [], ConsolidationFailure("invalid_json")
    if parsed.get("version") != CONTRACT_VERSION:
        return [], ConsolidationFailure("invariant_violation", "unsupported contract version")
    groups = parsed.get("groups")
    if not isinstance(groups, list):
        return [], ConsolidationFailure("invariant_violation", "groups must be a list")

    validated: list[dict[str, Any]] = []
    used: set[str] = set()
    for raw_group in groups:
        if not isinstance(raw_group, dict):
            return [], ConsolidationFailure("invariant_violation", "group must be an object")
        members = raw_group.get("member_ids")
        reason = str(raw_group.get("reason") or "").strip()
        if not isinstance(members, list) or len(members) < 2 or not reason:
            return [], ConsolidationFailure("invariant_violation", "group requires at least two members and a reason")
        normalized = [str(member) for member in members]
        unknown = [member for member in normalized if member not in known_ids]
        if unknown:
            return [], ConsolidationFailure("unknown_member", ",".join(sorted(set(unknown))))
        if len(set(normalized)) != len(normalized) or used.intersection(normalized):
            return [], ConsolidationFailure("overlapping_groups")
        used.update(normalized)
        validated.append({"member_ids": normalized, "reason": reason[:1000]})
    return validated, None


def _priority_key(finding: dict[str, Any]) -> tuple[int, int, float, int, str]:
    flags = {str(flag) for flag in (finding.get("verification_flags") or [])}
    tool_backed = int(bool(finding.get("tool_name") or finding.get("source_tool_observation") or "tool_promoted" in flags))
    return (
        tool_backed,
        SEVERITY_RANK.get(str(finding.get("severity") or "").lower(), 0),
        float(finding.get("confidence") or 0),
        len(str(finding.get("evidence") or "")),
        str(finding.get("dedupe_hash") or ""),
    )


def _unique_scalars(values: list[Any]) -> list[str]:
    return sorted({str(value) for value in values if str(value).strip()})


def _unique_dicts(values: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(value))
    return result


def _merge_evidence(members: list[dict[str, Any]], primary: dict[str, Any]) -> str:
    variants: list[str] = []
    for member in [primary, *members]:
        evidence = str(member.get("evidence") or "").strip()
        if evidence and evidence not in variants:
            variants.append(evidence)
    return "\n\n合并证据：".join(variants)[:MERGED_EVIDENCE_LIMIT]


def _related_locations(members: list[dict[str, Any]], primary: dict[str, Any]) -> list[dict[str, Any]]:
    primary_location = (
        str(primary.get("file_path") or ""),
        primary.get("line_start"),
        primary.get("line_end"),
    )
    values: list[dict[str, Any]] = []
    for member in members:
        candidates = [
            {
                "file_path": str(member.get("file_path") or ""),
                "line_start": member.get("line_start"),
                "line_end": member.get("line_end"),
            },
            *(member.get("related_locations") or []),
        ]
        for location in candidates:
            if not isinstance(location, dict):
                continue
            key = (
                str(location.get("file_path") or ""),
                location.get("line_start"),
                location.get("line_end"),
            )
            if not key[0] or key == primary_location or location in values:
                continue
            values.append(
                {
                    "file_path": key[0],
                    "line_start": key[1],
                    "line_end": key[2],
                }
            )
    return values


def _merge_group(
    members: list[dict[str, Any]],
    *,
    reason: str,
    model_metadata: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    primary_source = max(members, key=_priority_key)
    primary = dict(primary_source)
    member_hashes = sorted({str(member.get("dedupe_hash") or "") for member in members if member.get("dedupe_hash")})
    covered_rules = _unique_scalars([rule for member in members for rule in (member.get("covered_rules") or [])])
    skipped_rules = [
        rule
        for rule in _unique_scalars([rule for member in members for rule in (member.get("skipped_rules") or [])])
        if rule not in covered_rules
    ]
    merged_agents = _unique_scalars(
        [
            value
            for member in members
            for value in [member.get("agent_id"), *(member.get("merged_agent_ids") or [])]
        ]
    )
    primary.update(
        {
            "severity": max(
                (str(member.get("severity") or "info").lower() for member in members),
                key=lambda value: SEVERITY_RANK.get(value, 0),
            ),
            "confidence": max(float(member.get("confidence") or 0) for member in members),
            "covered_rules": covered_rules,
            "skipped_rules": skipped_rules,
            "merged_agent_ids": merged_agents,
            "related_locations": _related_locations(members, primary_source),
            "evidence": _merge_evidence(members, primary_source),
            "source_observations": _unique_dicts(
                [value for member in members for value in (member.get("source_observations") or [])]
            ),
            "tool_provenance": _unique_dicts(
                [value for member in members for value in (member.get("tool_provenance") or [])]
            ),
        }
    )
    primary["dedupe_hash"] = canonical_issue_fingerprint(primary)
    trace = dict(primary_source.get("quality_trace") or {}) if isinstance(primary_source.get("quality_trace"), dict) else {}
    trace["final_consolidation"] = {
        "member_hashes": member_hashes,
        "primary_member_hash": str(primary_source.get("dedupe_hash") or ""),
        "reason": reason,
        "merged_count": len(members),
        **model_metadata,
    }
    primary["quality_trace"] = trace

    rejected = [
        {
            **member,
            "rejected_reasons": ["deduped_final_llm_consolidation"],
            "merged_into_dedupe_hash": primary["dedupe_hash"],
        }
        for member in members
        if member is not primary_source
    ]
    return primary, rejected


def merge_consolidation_groups(
    findings: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    *,
    model_metadata: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, lookup = compact_findings(findings)
    grouped_ids = {str(member_id) for group in groups for member_id in (group.get("member_ids") or [])}
    merged: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for group in groups:
        members = [lookup[str(member_id)] for member_id in group.get("member_ids") or []]
        primary, group_rejected = _merge_group(
            members,
            reason=str(group.get("reason") or "")[:1000],
            model_metadata=dict(model_metadata or {}),
        )
        merged.append(primary)
        rejected.extend(group_rejected)
    for request_id, finding in lookup.items():
        if request_id not in grouped_ids:
            merged.append(dict(finding))
    if len(merged) > len(findings):
        raise ValueError("final consolidation increased finding count")
    return merged, rejected


def build_consolidation_prompt(compact: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "task": (
                "对全部最终代码检视问题做一次全局语义归并。只能合并已有问题，不能新增问题，"
                "不能删除未分组问题，不能改写任何问题内容。只返回已有 id 的合并分组。"
            ),
            "contract": {
                "version": CONTRACT_VERSION,
                "output": {
                    "version": CONTRACT_VERSION,
                    "groups": [{"member_ids": ["f_01", "f_02"], "reason": "same root cause, impact, and remediation"}],
                },
            },
            "merge_only_when": [
                "根因实质相同",
                "风险影响实质相同",
                "核心修复动作相同",
                "位置相同或邻近，或属于同一条明确的跨文件因果链",
            ],
            "never_merge": [
                "同一 SQL 语句上的 SQL 注入与无界查询是两个独立问题",
                "生产代码缺陷与缺少测试是两个独立问题",
                "鉴权、幂等、事务等不同根因不能因为位置接近而合并",
                "无法明确证明同根因时必须保留为独立问题",
            ],
            "findings": compact,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _settings(config: dict[str, Any]) -> dict[str, Any]:
    quality = config.get("review_quality") if isinstance(config.get("review_quality"), dict) else {}
    review = config.get("review") if isinstance(config.get("review"), dict) else {}
    raw = quality.get("final_consolidation") if isinstance(quality.get("final_consolidation"), dict) else review.get("final_consolidation")
    raw = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "min_findings": max(2, int(raw.get("min_findings") or 2)),
        "max_findings": max(2, int(raw.get("max_findings") or 30)),
        "timeout_seconds": max(1, int(raw.get("timeout_seconds") or 45)),
        "max_output_tokens": max(256, int(raw.get("max_output_tokens") or 4096)),
        "temperature": float(raw.get("temperature") or 0),
        "fail_open": bool(raw.get("fail_open", True)),
    }


def _fallback(
    findings: list[dict[str, Any]],
    *,
    reason: str,
    started: float,
    detail: str = "",
) -> ConsolidationResult:
    return ConsolidationResult(
        findings=[dict(item) for item in findings],
        rejections=[],
        fallback_reason=reason,
        metadata={
            "operation": "final_consolidation",
            "input_finding_count": len(findings),
            "output_finding_count": len(findings),
            "merged_group_count": 0,
            "merged_finding_count": 0,
            "duration_ms": int((time.time() - started) * 1000),
            "fallback_reason": reason,
            "fallback_detail": detail[:500],
        },
    )


def _model_content(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict) and "choices" in response:
        return str(response.get("choices", [{}])[0].get("message", {}).get("content", ""))
    return json.dumps(response, ensure_ascii=False)


def _invoke_consolidation_model(
    *,
    prompt: str,
    config: dict[str, Any],
    settings: dict[str, Any],
    recorder: Any,
    span_id: str,
    head_sha: str,
    budget_tracker: Any | None,
    consolidation_llm: Callable[[str], Any] | None,
) -> tuple[str, dict[str, Any], ConsolidationFailure | None]:
    if consolidation_llm is not None:
        started = time.time()
        try:
            response = consolidation_llm(prompt)
        except TimeoutError as exc:
            return "", {}, ConsolidationFailure("timeout", str(exc))
        except Exception as exc:  # injected adapters must also fail open
            return "", {}, ConsolidationFailure("provider_unavailable", type(exc).__name__)
        return _model_content(response), {
            "provider": "injected",
            "model": "injected",
            "duration_ms": int((time.time() - started) * 1000),
        }, None

    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    prompt_tokens = estimate_tokens(prompt)
    providers = candidate_providers(llm, required_context=prompt_tokens)
    if not providers:
        return "", {}, ConsolidationFailure("provider_unavailable", "no compatible provider")
    messages = [
        {"role": "system", "content": "你是最终 Finding 语义归并器，只输出 JSON，不发现或改写问题。"},
        {"role": "user", "content": prompt},
    ]
    last_failure = ConsolidationFailure("provider_unavailable")
    for index, candidate in enumerate(providers):
        provider = str(candidate.get("provider") or "")
        model = str(candidate.get("model") or "")
        base_url = str(candidate.get("base_url") or "").rstrip("/")
        api_key = candidate.get("api_key")
        if not base_url or not api_key:
            continue
        max_tokens = min(settings["max_output_tokens"], llm_max_output_tokens(llm, provider, model))
        template_payload, _ = build_chat_payload(
            provider=provider,
            model=model,
            llm=llm,
            messages=messages,
            temperature=settings["temperature"],
            seed=None,
            structured=True,
            max_tokens=max_tokens,
        )
        started = time.time()
        try:
            def invoke(seed: int) -> dict[str, Any]:
                payload, _ = build_chat_payload(
                    provider=provider,
                    model=model,
                    llm=llm,
                    messages=messages,
                    temperature=settings["temperature"],
                    seed=seed,
                    structured=True,
                    max_tokens=max_tokens,
                )
                return invoke_with_parameter_fallback(
                    payload,
                    lambda active: invoke_openai_chat(
                        base_url=base_url,
                        api_key=str(api_key),
                        payload=active,
                        timeout_seconds=settings["timeout_seconds"],
                        stream=False,
                        transport=http_json,
                        retry=call_with_retry,
                    ),
                    on_downgrade=lambda parameter: recorder.event(
                        span_id,
                        "llm_parameter_downgraded",
                        f"{model} 最终归并调用移除不兼容参数：{parameter}",
                        {"provider": provider, "model": model, "parameter": parameter, "operation": "final_consolidation"},
                    ),
                )

            exchange = execute_chat_exchange(
                recorder=recorder,
                span_id=span_id,
                operation="final_consolidation",
                agent_id="final_finding_consolidator",
                context_unit_id="",
                checkpoint_id="",
                head_sha=head_sha,
                provider=provider,
                model=model,
                prompt=prompt,
                messages=messages,
                temperature=settings["temperature"],
                replay_mode=replay_mode_from_config(config),
                invoke=invoke,
                request_options=request_options_for_payload(template_payload),
            )
            response = exchange.response
            usage = response.get("usage") or {}
            if budget_tracker:
                budget_tracker.charge_llm(
                    model,
                    int(usage.get("prompt_tokens", prompt_tokens)),
                    int(usage.get("completion_tokens", 0)),
                )
            return _model_content(response), {
                "provider": provider,
                "model": model,
                "duration_ms": int((time.time() - started) * 1000),
                "input_tokens": int(usage.get("prompt_tokens", prompt_tokens)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            }, None
        except TimeoutError as exc:
            last_failure = ConsolidationFailure("timeout", str(exc))
        except (urllib.error.URLError, urllib.error.HTTPError, LookupError, ValueError, json.JSONDecodeError) as exc:
            last_failure = ConsolidationFailure("provider_unavailable", type(exc).__name__)
        if index == len(providers) - 1:
            break
    return "", {}, last_failure


def _candidate_batches(findings: list[dict[str, Any]], max_findings: int) -> list[list[dict[str, Any]]]:
    if len(findings) <= max_findings:
        return [findings]
    ordered = sorted(
        (dict(item) for item in findings),
        key=lambda item: (
            str(item.get("file_path") or ""),
            int(item.get("line_start") or 0),
            str(item.get("dedupe_hash") or ""),
        ),
    )
    return [ordered[index : index + max_findings] for index in range(0, len(ordered), max_findings)]


def consolidate_final_findings(
    *,
    findings: list[dict[str, Any]],
    config: dict[str, Any],
    recorder: Any,
    span_id: str,
    head_sha: str,
    budget_tracker: Any | None = None,
    consolidation_llm: Callable[[str], Any] | None = None,
) -> ConsolidationResult:
    started = time.time()
    settings = _settings(config)
    if not settings["enabled"]:
        return _fallback(findings, reason="disabled", started=started)
    if len(findings) < settings["min_findings"]:
        return _fallback(findings, reason="below_min_findings", started=started)
    if budget_tracker and budget_tracker.should_stop():
        return _fallback(
            findings,
            reason="budget_exhausted",
            detail=str(getattr(budget_tracker, "truncated_reason", "")),
            started=started,
        )

    consolidated: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    group_count = 0
    model_metadata: dict[str, Any] = {}
    for batch in _candidate_batches(findings, settings["max_findings"]):
        compact, lookup = compact_findings(batch)
        prompt = build_consolidation_prompt(compact)
        content, current_metadata, invocation_failure = _invoke_consolidation_model(
            prompt=prompt,
            config=config,
            settings=settings,
            recorder=recorder,
            span_id=span_id,
            head_sha=head_sha,
            budget_tracker=budget_tracker,
            consolidation_llm=consolidation_llm,
        )
        if invocation_failure:
            return _fallback(findings, reason=invocation_failure.reason, detail=invocation_failure.detail, started=started)
        groups, parse_failure = parse_consolidation_response(content, set(lookup))
        if parse_failure:
            return _fallback(findings, reason=parse_failure.reason, detail=parse_failure.detail, started=started)
        try:
            merged, batch_rejections = merge_consolidation_groups(batch, groups, model_metadata=current_metadata)
        except (KeyError, TypeError, ValueError) as exc:
            return _fallback(findings, reason="invariant_violation", detail=type(exc).__name__, started=started)
        consolidated.extend(merged)
        rejections.extend(batch_rejections)
        group_count += len(groups)
        model_metadata = current_metadata

    if len(consolidated) > len(findings):
        return _fallback(findings, reason="invariant_violation", detail="finding count increased", started=started)
    metadata = {
        "operation": "final_consolidation",
        "input_finding_count": len(findings),
        "output_finding_count": len(consolidated),
        "merged_group_count": group_count,
        "merged_finding_count": len(rejections),
        "duration_ms": int((time.time() - started) * 1000),
        "fallback_reason": None,
        **model_metadata,
    }
    return ConsolidationResult(
        findings=consolidated,
        rejections=rejections,
        fallback_reason=None,
        metadata=metadata,
    )
