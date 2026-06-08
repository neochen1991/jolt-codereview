from __future__ import annotations

import json
import time
import urllib.error
from typing import Any

from llm.client import chat_completions_url, http_json, llm_request_timeout_seconds, llm_stream_enabled
from llm_router import candidate_providers

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
VALID_VERDICTS = {"keep", "drop", "downgrade"}
VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}


def run_targeted_debate(conflicts: list[dict[str, Any]], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    finding_by_hash = {str(item.get("dedupe_hash") or ""): item for item in findings}
    transcripts: list[dict[str, Any]] = []

    for conflict in conflicts:
        hashes = [value for value in conflict.get("finding_hashes", []) if value]
        related = [finding_by_hash[item] for item in hashes if item in finding_by_hash]
        if not related:
            continue
        agents = sorted({str(item.get("agent_id") or "unknown_agent") for item in related})
        from_agent = agents[0] if agents else "verifier"
        to_agent = "judge_findings"
        recommendation = "需要 Judge 保守处理：优先保留有直接证据、可复现位置和清晰修复建议的问题。"
        if conflict.get("type") == "severity_disagreement":
            recommendation = "需要 Judge 校准严重级别，并保留最高证据质量的问题。"
        elif conflict.get("type") == "issue_vs_no_issue":
            recommendation = "需要 Judge 检查证据是否落在当前 diff 和职责范围内，证据不足时过滤。"
        elif conflict.get("type") == "tool_supported_low_confidence":
            recommendation = "需要 Judge 结合工具观察重新评估置信度，避免直接丢弃工具支持的问题。"
        elif conflict.get("type") == "high_severity_weak_evidence":
            recommendation = "需要 Judge 降级或过滤缺少直接证据的高严重级别问题。"

        transcripts.append({
            "conflict_type": conflict.get("type"),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "role": "debate",
            "content_summary": f"{conflict.get('summary')}: {recommendation}",
            "finding_hashes": hashes,
            "location": conflict.get("location") or {}
        })

    return transcripts


def _finding_by_hash(findings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("dedupe_hash") or ""): item for item in findings if item.get("dedupe_hash")}


def _source_snippet(files: list[Any], file_path: str, line_start: int | None, radius: int = 12) -> str:
    for changed in files:
        filename = str(getattr(changed, "filename", ""))
        if filename != file_path:
            continue
        patch = str(getattr(changed, "patch", "") or "")
        lines: list[str] = []
        for raw in patch.splitlines():
            if raw.startswith(("+++", "---", "diff --git", "index ")):
                continue
            if raw.startswith("@@"):
                lines.append(raw)
                continue
            if raw.startswith(("+", "-", " ")):
                lines.append(raw[:240])
        if not line_start:
            return "\n".join(lines[:50])
        return "\n".join(lines[:50])[:4000]
    return ""


def _fallback_verdict(conflict: dict[str, Any]) -> dict[str, Any]:
    conflict_type = str(conflict.get("type") or "")
    if conflict_type == "high_severity_weak_evidence":
        return {
            "verdict": "downgrade",
            "calibrated_severity": "medium",
            "calibrated_confidence": 0.72,
            "reason": "高严重级别但证据不足，按保守策略降级。",
            "source": "fallback",
        }
    if conflict_type == "tool_supported_low_confidence":
        return {
            "verdict": "keep",
            "calibrated_severity": "",
            "calibrated_confidence": 0.78,
            "reason": "存在工具观察支持，保留给 Judge 继续排序。",
            "source": "fallback",
        }
    return {
        "verdict": "keep",
        "calibrated_severity": "",
        "calibrated_confidence": 0.75,
        "reason": "LLM 辩论不可用，保守保留并交给 Judge 去重排序。",
        "source": "fallback",
    }


def _parse_verdict(content: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        start = content.find("{")
        end = content.rfind("}")
        parsed = json.loads(content[start : end + 1] if start >= 0 and end >= start else content)
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    verdict = str(parsed.get("verdict") or fallback["verdict"]).lower()
    severity = str(parsed.get("calibrated_severity") or fallback.get("calibrated_severity") or "").lower()
    try:
        confidence = float(parsed.get("calibrated_confidence") or fallback.get("calibrated_confidence") or 0.75)
    except (TypeError, ValueError):
        confidence = float(fallback.get("calibrated_confidence") or 0.75)
    if confidence > 1:
        confidence = confidence / 100
    return {
        "verdict": verdict if verdict in VALID_VERDICTS else str(fallback["verdict"]),
        "calibrated_severity": severity if severity in VALID_SEVERITIES else str(fallback.get("calibrated_severity") or ""),
        "calibrated_confidence": max(0.0, min(0.99, confidence)),
        "reason": str(parsed.get("reason") or fallback.get("reason") or "")[:600],
        "source": "llm",
    }


def _conflict_priority(conflict: dict[str, Any], finding_by_hash: dict[str, dict[str, Any]]) -> tuple[int, int]:
    hashes = [str(item) for item in conflict.get("finding_hashes", []) if item]
    max_severity = max((SEVERITY_RANK.get(str(finding_by_hash.get(item, {}).get("severity") or "info"), 0) for item in hashes), default=0)
    type_priority = {
        "high_severity_weak_evidence": 3,
        "severity_disagreement": 2,
        "tool_supported_low_confidence": 1,
        "issue_vs_no_issue": 1,
    }.get(str(conflict.get("type") or ""), 0)
    return (max_severity, type_priority)


def _build_debate_prompt(
    conflict: dict[str, Any],
    related_findings: list[dict[str, Any]],
    files: list[Any],
    tool_observations: list[dict[str, Any]],
) -> str:
    location = conflict.get("location") or {}
    file_path = str(location.get("file_path") or (related_findings[0].get("file_path") if related_findings else ""))
    line_start = location.get("line_start")
    if not isinstance(line_start, int):
        try:
            line_start = int(line_start) if line_start else None
        except (TypeError, ValueError):
            line_start = None
    relevant_tools = [
        item
        for item in tool_observations
        if str(item.get("file_path") or "") == file_path
        and (line_start is None or item.get("line_start") is None or abs(int(item.get("line_start") or line_start) - line_start) <= 5)
    ][:8]
    payload = {
        "task": (
            "你是代码检视 Judge。请只输出 JSON 对象："
            "{verdict: keep|drop|downgrade, calibrated_severity: critical|high|medium|low|info|'', "
            "calibrated_confidence: 0-1, reason: string}。"
            "drop 表示该冲突涉及 finding 应从最终结果移除；downgrade 表示按 calibrated_severity 降级；keep 表示保留并按 calibrated_confidence 校准。"
        ),
        "conflict": conflict,
        "findings": related_findings,
        "source_snippet": _source_snippet(files, file_path, line_start),
        "tool_observations": relevant_tools,
        "decision_policy": [
            "优先保留有明确源码证据、当前 diff 位置准确、且修复建议具体的问题。",
            "工具观察与源码都支持时，不要因为单个 Agent 置信度低而丢弃。",
            "高危但证据弱的问题应降级或丢弃，避免小题大做。",
            "不要引入新问题，只裁决输入 finding。",
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def run_targeted_debate_with_llm(
    *,
    config: dict[str, Any],
    recorder: Any,
    span_id: str,
    conflicts: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    files: list[Any],
    tool_observations: list[dict[str, Any]],
    budget_tracker: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    finding_by_hash = _finding_by_hash(findings)
    if not conflicts:
        return [], []
    max_debate_calls = max(1, int(len(findings) * 0.3))
    ranked_conflicts = sorted(conflicts, key=lambda item: _conflict_priority(item, finding_by_hash), reverse=True)[:max_debate_calls]
    llm = config.get("llm", {})
    transcripts: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for conflict in ranked_conflicts:
        hashes = [str(value) for value in conflict.get("finding_hashes", []) if value]
        related = [finding_by_hash[item] for item in hashes if item in finding_by_hash]
        if not related:
            continue
        fallback = _fallback_verdict(conflict)
        prompt = _build_debate_prompt(conflict, related, files, tool_observations)
        providers = candidate_providers(llm, required_context=max(1, len(prompt) // 4))
        first_provider = providers[0] if providers else {
            "provider": llm.get("default_provider") or "dashscope-openai-compatible",
            "model": llm.get("default_model") or "MiniMax-M2.7",
        }
        provider = str(first_provider.get("provider"))
        model = str(first_provider.get("model"))
        if budget_tracker and budget_tracker.should_stop():
            recorder.llm_call(span_id, provider, model, prompt, f"skipped_by_budget:{budget_tracker.truncated_reason}", 0, len(prompt) // 4, 0)
            verdict = {**fallback, "source": "fallback", "skip_reason": budget_tracker.truncated_reason}
        elif not providers:
            recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, len(prompt) // 4, 0)
            verdict = {**fallback, "source": "fallback", "skip_reason": "no_api_key"}
        else:
            verdict = fallback
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
                            "你是严格的代码检视裁判，只输出 JSON 对象。"
                            "除 file_path、rule_id、代码片段、类名、方法名和技术专有名词外，"
                            "reason 等自然语言字段必须使用中文。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
                timeout_seconds = llm_request_timeout_seconds(llm)
                stream_enabled = llm_stream_enabled(llm)
                try:
                    response = http_json(
                        chat_completions_url(base_url),
                        {"Authorization": f"Bearer {api_key}"},
                        method="POST",
                        body={
                            "model": model,
                            "messages": messages,
                            "temperature": 0.1,
                        },
                        timeout_seconds=timeout_seconds,
                        stream=stream_enabled,
                    )
                    duration_ms = int((time.time() - started) * 1000)
                    usage = response.get("usage") or {}
                    input_tokens = int(usage.get("prompt_tokens", len(prompt) // 4))
                    output_tokens = int(usage.get("completion_tokens", 0))
                    content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    response_debug_text = json.dumps({"content": content, "stream": response.get("_jolt_stream") or {"enabled": False}}, ensure_ascii=False)
                    recorder.llm_call(span_id, provider, model, prompt, "completed", duration_ms, input_tokens, output_tokens, str(response.get("id") or ""), messages, response_debug_text)
                    if budget_tracker:
                        budget_tracker.charge_llm(model, input_tokens, output_tokens)
                    verdict = _parse_verdict(content, fallback)
                    break
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
                    duration_ms = int((time.time() - started) * 1000)
                    error_text = json.dumps({"error": str(exc), "timeout_seconds": timeout_seconds, "stream": stream_enabled}, ensure_ascii=False)
                    recorder.llm_call(span_id, provider, model, prompt, f"failed:{type(exc).__name__}", duration_ms, len(prompt) // 4, 0, None, messages, error_text)
                    if index < len(providers) - 1:
                        recorder.event(span_id, "debate_llm_failover", f"{provider} 辩论调用失败，尝试下一个 provider", {"error": str(exc)[:300]})
                    else:
                        recorder.event(span_id, "debate_llm_error", f"辩论 LLM 调用失败，使用兜底裁决：{exc}")
                        verdict = {**fallback, "source": "fallback", "skip_reason": type(exc).__name__}
        result = {
            **verdict,
            "conflict_type": conflict.get("type"),
            "finding_hashes": hashes,
            "location": conflict.get("location") or {},
        }
        results.append(result)
        transcripts.append(
            {
                "conflict_type": conflict.get("type"),
                "from_agent": "debate_moderator",
                "to_agent": "judge_findings",
                "role": "debate",
                "content_summary": f"{conflict.get('summary')}: {result['verdict']} {result.get('calibrated_severity') or ''} {result.get('calibrated_confidence')}; {result.get('reason')}",
                "finding_hashes": hashes,
                "location": conflict.get("location") or {},
                "verdict": result,
            }
        )
    if len(conflicts) > len(ranked_conflicts):
        recorder.event(
            span_id,
            "debate_capped",
            f"冲突数 {len(conflicts)}，按配额仅辩论 {len(ranked_conflicts)} 个",
            {"max_debate_calls": max_debate_calls},
        )
    return transcripts, results


def make_run_targeted_debate_node(*, recorder: Any, project_config: dict[str, Any]):
    def run_targeted_debate_node(state: dict[str, Any]) -> dict[str, Any]:
        debate_span = recorder.span("run_targeted_debate", "debate_moderator")
        budget_tracker = state.get("budget_tracker")
        if budget_tracker and budget_tracker.should_stop():
            recorder.event(
                debate_span,
                "budget_truncated",
                f"预算已触发熔断，跳过定向辩论：{budget_tracker.truncated_reason}",
                budget_tracker.snapshot(),
            )
            recorder.finish(debate_span)
            return {**state, "debate_transcripts": [], "debate_results": []}
        transcripts, debate_results = run_targeted_debate_with_llm(
            config=project_config,
            recorder=recorder,
            span_id=debate_span,
            conflicts=state.get("conflicts") or [],
            findings=state["verified_findings"],
            files=state.get("files") or [],
            tool_observations=state.get("tool_observations") or [],
            budget_tracker=budget_tracker,
        )
        for transcript in transcripts:
            recorder.message(
                debate_span,
                str(transcript.get("from_agent") or "verifier"),
                str(transcript.get("to_agent") or "judge_findings"),
                str(transcript.get("role") or "debate"),
                str(transcript.get("content_summary") or ""),
            )
        recorder.event(
            debate_span,
            "targeted_debate_completed",
            f"定向辩论完成 {len(transcripts)} 条 transcript，{len(debate_results)} 条裁决",
            {"transcripts": transcripts[:20], "debate_results": debate_results[:20]},
        )
        recorder.finish(debate_span)
        return {**state, "debate_transcripts": transcripts, "debate_results": debate_results}

    return run_targeted_debate_node
