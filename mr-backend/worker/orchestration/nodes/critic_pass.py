from __future__ import annotations

import json
import time
import urllib.error
from typing import Any, Callable

from llm.client import build_chat_payload, estimate_tokens, http_json, invoke_with_parameter_fallback, llm_max_output_tokens, llm_request_timeout_seconds, llm_stream_enabled
from llm.exchange import execute_chat_exchange, invoke_openai_chat, replay_mode_from_config
from llm.retry import call_with_retry
from llm_router import candidate_providers
from rules.registry import rule as registry_rule

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
DOWNGRADE = {"critical": "high", "high": "medium", "medium": "low", "low": "info", "info": "info"}
VALID_VERDICTS = {"confirmed", "rejected", "uncertain"}


def _evidence_total(finding: dict[str, Any]) -> float:
    score = finding.get("evidence_score") or {}
    if isinstance(score, dict):
        try:
            return float(score.get("total_score") or score.get("score") or 1.0)
        except (TypeError, ValueError):
            return 1.0
    return 1.0


def _targets(findings: list[dict[str, Any]], max_calls: int) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in findings
        if str(item.get("severity") or "").lower() in {"critical", "high"} or _evidence_total(item) < 0.55
    ]
    candidates.sort(key=lambda item: (_evidence_total(item), -SEVERITY_RANK.get(str(item.get("severity") or "info").lower(), 0)))
    return candidates[:max(0, max_calls)]


def _source_window(source_file_contents: dict[str, str], file_path: str, line_start: Any, radius: int = 20) -> str:
    source = source_file_contents.get(file_path) or source_file_contents.get(file_path.replace("\\", "/")) or ""
    if not source:
        return ""
    try:
        center = max(1, int(line_start or 1))
    except (TypeError, ValueError):
        center = 1
    lines = source.splitlines()
    start = max(1, center - radius)
    end = min(len(lines), center + radius)
    return "\n".join(f"{idx}: {lines[idx - 1][:240]}" for idx in range(start, end + 1))


def _rule_ids_for(finding: dict[str, Any]) -> list[str]:
    raw_rules = finding.get("covered_rules") or finding.get("rule_ids") or finding.get("rule_id") or []
    if isinstance(raw_rules, str):
        raw_rules = [raw_rules]
    result: list[str] = []
    for rule_id in raw_rules if isinstance(raw_rules, list) else []:
        text = str(rule_id or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _rule_context(rule_ids: list[str]) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for rule_id in rule_ids[:8]:
        item = registry_rule(rule_id) or {}
        context.append(
            {
                "rule_id": rule_id,
                "category": str(item.get("category") or ""),
                "severity_floor": str(item.get("severity_floor") or ""),
                "agent_owners": [str(owner) for owner in item.get("agent_owners") or []],
                "is_bound_document_rule": bool(item.get("is_bound_document_rule")),
                "evidence_requirements": item.get("evidence_requirements") or {},
            }
        )
    return context


def _prompt(finding: dict[str, Any], source_snippet: str) -> str:
    rule_ids = _rule_ids_for(finding)
    public_finding = {
        "severity": finding.get("severity"),
        "confidence": finding.get("confidence"),
        "file_path": finding.get("file_path"),
        "line_start": finding.get("line_start"),
        "line_end": finding.get("line_end"),
        "title": finding.get("title"),
        "problem_description": finding.get("problem_description"),
        "recommendation": finding.get("recommendation"),
        "evidence": finding.get("evidence"),
        "suggested_code": finding.get("suggested_code"),
        "evidence_score": finding.get("evidence_score"),
        "covered_rules": rule_ids,
    }
    return json.dumps(
        {
            "task": (
                "你是代码检视 Critic。只依据 finding 和真实源码片段判断该问题是否有足够证据。"
                "只输出 JSON 对象：{verdict: confirmed|rejected|uncertain, reason: string}。"
                "rejected 表示源码片段不支持该 finding；uncertain 表示证据不完整但无法否定。"
            ),
            "finding": public_finding,
            "rule_context": _rule_context(rule_ids),
            "source_snippet": source_snippet,
            "decision_policy": [
                "不要引入新问题，只裁决输入 finding。",
                "必须结合 rule_context 的规则类别、最低严重级别和证据要求判断 finding 是否对齐。",
                "如果证据行、源码片段和问题描述对不上，返回 rejected。",
                "如果源码片段明确支持问题，返回 confirmed。",
                "如果需要更多上下文，返回 uncertain。",
            ],
        },
        ensure_ascii=False,
    )


def _parse(content: str) -> dict[str, str]:
    try:
        start = content.find("{")
        end = content.rfind("}")
        parsed = json.loads(content[start : end + 1] if start >= 0 and end >= start else content)
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    verdict = str(parsed.get("verdict") or "uncertain").lower()
    return {
        "verdict": verdict if verdict in VALID_VERDICTS else "uncertain",
        "reason": str(parsed.get("reason") or "")[:700],
    }


def _apply_verdict(finding: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
    result = dict(finding)
    severity = str(result.get("severity") or "info").lower()
    confidence = float(result.get("confidence") or 0.0)
    if verdict.get("verdict") == "rejected":
        result["severity"] = DOWNGRADE.get(severity, severity)
        result["confidence"] = max(0.0, min(0.99, confidence * 0.7))
        result["contradictions"] = [
            *(result.get("contradictions") or []),
            {"kind": "critic_counter_evidence", "evidence": str(verdict.get("reason") or "critic rejected the evidence")[:700]},
        ]
    trace = result.get("quality_trace") if isinstance(result.get("quality_trace"), dict) else {}
    result["quality_trace"] = {**trace, "critic_verdict": verdict}
    return result


def run_critic_pass(
    *,
    findings: list[dict[str, Any]],
    source_file_contents: dict[str, str],
    config: dict[str, Any],
    recorder: Any,
    span_id: str,
    budget_tracker: Any | None = None,
    critic_llm: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    critic_config = ((config.get("review") or {}).get("critic") if isinstance(config.get("review"), dict) else {}) or {}
    if critic_config.get("enabled") is False:
        recorder.event(span_id, "critic_skipped", "通用 Critic 二审被项目配置关闭")
        return findings
    try:
        max_calls = max(0, min(8, int(critic_config.get("max_calls") or 8)))
    except (TypeError, ValueError):
        max_calls = 8
    target_hashes = {str(item.get("dedupe_hash") or id(item)) for item in _targets(findings, max_calls)}
    if not target_hashes:
        return findings
    llm = config.get("llm", {}) if isinstance(config.get("llm"), dict) else {}
    reviewed: list[dict[str, Any]] = []
    for finding in findings:
        key = str(finding.get("dedupe_hash") or id(finding))
        if key not in target_hashes:
            reviewed.append(finding)
            continue
        prompt = _prompt(finding, _source_window(source_file_contents, str(finding.get("file_path") or ""), finding.get("line_start")))
        prompt_tokens = estimate_tokens(prompt)
        if critic_llm:
            verdict = critic_llm(prompt)
        else:
            providers = candidate_providers(llm, required_context=prompt_tokens)
            if not providers or (budget_tracker and budget_tracker.should_stop()):
                verdict = {"verdict": "uncertain", "reason": "critic unavailable", "source": "skipped"}
            else:
                verdict = {"verdict": "uncertain", "reason": "critic fallback", "source": "fallback"}
                for index, candidate in enumerate(providers):
                    provider = str(candidate.get("provider"))
                    model = str(candidate.get("model"))
                    base_url = str(candidate.get("base_url") or "").rstrip("/")
                    api_key = candidate.get("api_key")
                    if not base_url or not api_key:
                        continue
                    started = time.time()
                    messages = [{"role": "system", "content": "你是严格的代码检视 Critic，只输出 JSON。"}, {"role": "user", "content": prompt}]
                    try:
                        def invoke_critic(seed: int) -> dict[str, Any]:
                            payload, _metadata = build_chat_payload(
                                provider=provider,
                                model=model,
                                llm=llm,
                                messages=messages,
                                temperature=0.0,
                                seed=seed,
                                structured=True,
                                max_tokens=min(4096, llm_max_output_tokens(llm, provider, model)),
                            )
                            return invoke_with_parameter_fallback(
                                payload,
                                lambda active: invoke_openai_chat(base_url=base_url, api_key=str(api_key), payload=active, timeout_seconds=llm_request_timeout_seconds(llm, "critic"), stream=llm_stream_enabled(llm), transport=http_json, retry=call_with_retry),
                                on_downgrade=lambda parameter: recorder.event(span_id, "llm_parameter_downgraded", f"{model} Critic 调用移除不兼容参数：{parameter}", {"provider": provider, "model": model, "parameter": parameter, "operation": "critic"}),
                            )

                        exchange = execute_chat_exchange(
                            recorder=recorder,
                            span_id=span_id,
                            operation="critic",
                            agent_id="critic_agent",
                            context_unit_id=str(finding.get("context_unit_id") or ""),
                            checkpoint_id=str(finding.get("checkpoint_id") or ""),
                            head_sha=str(finding.get("head_sha") or ""),
                            provider=provider,
                            model=model,
                            prompt=prompt,
                            messages=messages,
                            temperature=0.0,
                            replay_mode=replay_mode_from_config(config),
                            invoke=invoke_critic,
                        )
                        response = exchange.response
                        usage = response.get("usage") or {}
                        content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                        if budget_tracker:
                            budget_tracker.charge_llm(model, int(usage.get("prompt_tokens", prompt_tokens)), int(usage.get("completion_tokens", 0)))
                        verdict = {**_parse(str(content)), "source": "llm"}
                        break
                    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
                        recorder.llm_call(span_id, provider, model, prompt, f"failed:{type(exc).__name__}", int((time.time() - started) * 1000), prompt_tokens, 0)
                        if index == len(providers) - 1:
                            verdict = {"verdict": "uncertain", "reason": type(exc).__name__, "source": "fallback"}
        reviewed.append(_apply_verdict(finding, verdict))
    recorder.event(span_id, "critic_pass_completed", f"通用 Critic 二审完成 {len(target_hashes)} 条 finding", {"reviewed_count": len(target_hashes)})
    return reviewed
