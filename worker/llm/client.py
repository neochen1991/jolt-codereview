from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any

from llm_router import candidate_providers
from prompts.builder import build_prompt
from prompts.system import REVIEW_SYSTEM_PROMPT


def sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def llm_request_timeout_seconds(llm: dict[str, Any] | None) -> int:
    config = llm or {}
    configured = (
        config.get("request_timeout_seconds")
        or config.get("timeout_seconds")
        or config.get("default_timeout_seconds")
        or 120
    )
    try:
        return max(1, min(600, int(configured)))
    except (TypeError, ValueError):
        return 120


def llm_stream_enabled(llm: dict[str, Any] | None) -> bool:
    config = llm or {}
    configured = config.get("enable_stream", config.get("stream", True))
    if isinstance(configured, str):
        return configured.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return bool(configured)


def collect_openai_sse_lines(raw_lines: Any, started: float) -> dict[str, Any]:
    content_parts: list[str] = []
    tool_call_parts: dict[int, dict[str, Any]] = {}
    chunk_count = 0
    first_chunk_ms: int | None = None
    response_id = ""
    finish_reason = None
    usage: dict[str, Any] = {}

    for raw_line in raw_lines:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace").strip()
        else:
            line = str(raw_line).strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        chunk_count += 1
        if first_chunk_ms is None:
            first_chunk_ms = int((time.time() - started) * 1000)
        response_id = str(chunk.get("id") or response_id)
        if isinstance(chunk.get("usage"), dict):
            usage = chunk.get("usage") or usage
        choice = (chunk.get("choices") or [{}])[0]
        finish_reason = choice.get("finish_reason") or finish_reason
        delta = choice.get("delta") or {}
        if delta.get("content"):
            content_parts.append(str(delta.get("content")))
        for tool_call in delta.get("tool_calls") or []:
            index = int(tool_call.get("index") or 0)
            existing = tool_call_parts.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if tool_call.get("id"):
                existing["id"] = tool_call.get("id")
            if tool_call.get("type"):
                existing["type"] = tool_call.get("type")
            function = tool_call.get("function") or {}
            existing_function = existing.setdefault("function", {"name": "", "arguments": ""})
            if function.get("name"):
                existing_function["name"] = function.get("name")
            if function.get("arguments"):
                existing_function["arguments"] = str(existing_function.get("arguments") or "") + str(function.get("arguments"))

    message: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    if tool_call_parts:
        message["tool_calls"] = [tool_call_parts[index] for index in sorted(tool_call_parts)]
    return {
        "id": response_id,
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": usage,
        "_jolt_stream": {
            "enabled": True,
            "chunk_count": chunk_count,
            "first_chunk_ms": first_chunk_ms,
        },
    }


def collect_openai_sse_response(response: Any, started: float) -> dict[str, Any]:
    return collect_openai_sse_lines(response, started)


def looks_like_openai_sse(text: str) -> bool:
    return any(line.lstrip().startswith("data:") for line in text.splitlines())


def json_decode_error_with_preview(exc: json.JSONDecodeError, text: str) -> json.JSONDecodeError:
    preview = text[:500].replace("\r", "\\r").replace("\n", "\\n")
    return json.JSONDecodeError(f"{exc.msg}; response_preview={preview}", exc.doc, exc.pos)


def parse_openai_response_text(text: str, started: float) -> dict[str, Any]:
    if looks_like_openai_sse(text):
        return collect_openai_sse_lines(text.splitlines(), started)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise json_decode_error_with_preview(exc, text) from exc
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError(f"OpenAI response must be a JSON object; response_preview={text[:500]}", text, 0)
    return parsed


def http_json(
    url: str,
    headers: dict[str, str],
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout_seconds: int = 120,
    stream: bool = False,
) -> Any:
    data = None
    request_headers = dict(headers)
    request_headers.setdefault("Accept", "application/json")
    request_headers.setdefault("User-Agent", "Jolt-CodeReview-Worker/0.1")
    if body is not None:
        request_body = dict(body)
        if stream:
            request_body["stream"] = True
            request_body.setdefault("stream_options", {"include_usage": True})
        data = json.dumps(request_body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if stream and "text/event-stream" in content_type:
            return collect_openai_sse_response(response, started)
        return parse_openai_response_text(response.read().decode("utf-8", errors="replace"), started)


def normalize_line_number(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def normalize_confidence(value: Any, default: float = 0.75) -> float:
    if isinstance(value, str):
        mapped = {"critical": 0.95, "high": 0.9, "medium": 0.78, "low": 0.65}.get(value.strip().lower())
        if mapped is not None:
            return mapped
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    if confidence > 1:
        confidence = confidence / 100
    return max(0.0, min(1.0, confidence))


def llm_max_output_tokens(llm: dict[str, Any] | None) -> int:
    config = llm or {}
    configured = config.get("max_output_tokens") or config.get("default_max_output_tokens") or 8192
    try:
        return max(1024, min(12000, int(configured)))
    except (TypeError, ValueError):
        return 8192


def _extract_json_objects(content: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    for index, char in enumerate(content):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    raw = content[start : index + 1]
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = None
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                    start = None
    return objects


def parse_llm_findings(agent_id: str, content: str, files: list[Any]) -> list[dict[str, Any]]:
    try:
        start = content.find("[")
        end = content.rfind("]")
        parsed = json.loads(content[start : end + 1] if start >= 0 and end >= start else content)
    except json.JSONDecodeError:
        parsed = _extract_json_objects(content)
    if not isinstance(parsed, list):
        parsed = []
    valid_files = {item.filename for item in files}
    findings: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path") or "")
        if file_path not in valid_files:
            continue
        title = str(item.get("title") or "AI 检视问题")[:120]
        lowered_title = title.lower()
        if lowered_title.startswith(("semgrep 命中", "gitleaks 疑似", "ruff 命中", "eslint 命中", "bandit 命中")):
            continue
        line_start = normalize_line_number(item.get("line_start"))
        line_end = normalize_line_number(item.get("line_end")) or line_start
        if line_start is None:
            continue
        if line_end is not None and line_end < line_start:
            line_end = line_start
        evidence = str(item.get("evidence") or title)
        recommendation = str(item.get("recommendation") or "请结合上下文修复该问题。")
        suggested_code = str(item.get("suggested_code") or "").strip()
        if not suggested_code:
            suggested_code = (
                f"// 建议修改示例：请在 {file_path}"
                f":{line_start}{f'-{line_end}' if line_end and line_end != line_start else ''} 按以下方向调整\n"
                f"// {recommendation}"
            )
        findings.append(
            {
                "severity": str(item.get("severity") or "medium").lower(),
                "confidence": normalize_confidence(item.get("confidence"), 0.75),
                "agent_id": agent_id,
                "head_sha": "",
                "dedupe_hash": sha1("|".join([agent_id, title, file_path, evidence[:120]])),
                "file_path": file_path,
                "line_start": line_start,
                "line_end": line_end,
                "title": title,
                "problem_description": str(item.get("problem_description") or title),
                "recommendation": recommendation,
                "suggested_code": suggested_code[:4000],
                "evidence": evidence[:500],
                "covered_rules": item.get("covered_rules") if isinstance(item.get("covered_rules"), list) else [],
                "skipped_rules": item.get("skipped_rules") if isinstance(item.get("skipped_rules"), list) else [],
            }
        )
    return findings[:8]


def _json_object_from_content(content: str) -> dict[str, Any]:
    try:
        start = content.find("{")
        end = content.rfind("}")
        parsed = json.loads(content[start : end + 1] if start >= 0 and end >= start else content)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_text_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip()[:300] for item in value if str(item).strip()][:limit]
    if isinstance(value, str) and value.strip():
        return [value.strip()[:300]]
    return []


def _file_summary(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        filename = item.get("filename") or ""
        status = item.get("status") or ""
        additions = item.get("additions") or 0
        deletions = item.get("deletions") or 0
        patch = item.get("patch") or ""
    else:
        filename = getattr(item, "filename", "") or ""
        status = getattr(item, "status", "") or ""
        additions = getattr(item, "additions", 0) or 0
        deletions = getattr(item, "deletions", 0) or 0
        patch = getattr(item, "patch", "") or ""
    return {
        "filename": str(filename),
        "status": str(status),
        "additions": int(additions),
        "deletions": int(deletions),
        "patch_excerpt": str(patch)[:1600],
    }


def _row_value(row: Any, key: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        if hasattr(row, "keys") and key in row.keys():
            return row[key]
    except (KeyError, TypeError):
        pass
    return getattr(row, key, default)


def fallback_pr_summary(
    mr: Any,
    files: list[Any],
    final_findings: list[dict[str, Any]],
    *,
    source: str,
    skipped: bool = False,
    skip_reason: str = "",
) -> dict[str, Any]:
    change_map = [
        f"{item['filename']} (+{item['additions']}/-{item['deletions']})"
        for item in [_file_summary(file) for file in files[:12]]
        if item["filename"]
    ]
    high_risks = [
        f"{finding.get('severity', 'medium')} {finding.get('file_path')}:{finding.get('line_start') or '?'} {finding.get('title')}"
        for finding in final_findings
        if str(finding.get("severity") or "").lower() in {"critical", "high"}
    ][:6]
    test_files = [item for item in change_map if "test" in item.lower()]
    return {
        "intent": str(_row_value(mr, "title", "根据 MR 标题与变更文件推断本次变更意图。")),
        "change_map": change_map[:8],
        "risk_highlights": high_risks or ["未发现高危问题，仍需关注变更文件的业务路径和回归风险。"],
        "test_coverage_gaps": [] if test_files else ["当前 diff 未明显包含测试文件，建议确认关键路径已有回归覆盖。"],
        "cross_file_couplings": ["需要结合调用链与接口契约确认跨文件影响。"] if len(files) > 1 else [],
        "suggested_review_order": [item.split(" (+", 1)[0] for item in change_map[:5]],
        "source": source,
        "skipped": skipped,
        "skip_reason": skip_reason,
    }


def normalize_pr_summary(parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": str(parsed.get("intent") or fallback.get("intent") or "")[:800],
        "change_map": _as_text_list(parsed.get("change_map") or fallback.get("change_map"), 12),
        "risk_highlights": _as_text_list(parsed.get("risk_highlights") or fallback.get("risk_highlights"), 10),
        "test_coverage_gaps": _as_text_list(parsed.get("test_coverage_gaps") or fallback.get("test_coverage_gaps"), 8),
        "cross_file_couplings": _as_text_list(parsed.get("cross_file_couplings") or fallback.get("cross_file_couplings"), 8),
        "suggested_review_order": _as_text_list(parsed.get("suggested_review_order") or fallback.get("suggested_review_order"), 8),
        "source": str(parsed.get("source") or fallback.get("source") or "llm"),
        "skipped": bool(parsed.get("skipped") or fallback.get("skipped") or False),
        "skip_reason": str(parsed.get("skip_reason") or fallback.get("skip_reason") or ""),
    }


def summarize_pr_with_llm(
    config: dict[str, Any],
    recorder: Any,
    span_id: str,
    mr: Any,
    files: list[Any],
    final_findings: list[dict[str, Any]],
    context_bundle: dict[str, Any] | None = None,
    budget_tracker: Any | None = None,
) -> dict[str, Any]:
    llm = config.get("llm", {})
    file_payload = [_file_summary(file) for file in files[:20]]
    findings_payload = [
        {
            "severity": item.get("severity"),
            "agent_id": item.get("agent_id"),
            "file_path": item.get("file_path"),
            "line_start": item.get("line_start"),
            "title": item.get("title"),
            "recommendation": item.get("recommendation"),
        }
        for item in final_findings[:20]
    ]
    fallback = fallback_pr_summary(mr, files, final_findings, source="fallback")
    prompt = json.dumps(
        {
            "task": (
                "请作为资深代码检视负责人，为这个 MR 输出 PR 级 Walkthrough 摘要。"
                "只输出 JSON 对象，不要 Markdown。字段必须是：intent, change_map, risk_highlights, "
                "test_coverage_gaps, cross_file_couplings, suggested_review_order。"
            ),
            "mr": {
                "number": _row_value(mr, "number"),
                "title": _row_value(mr, "title"),
                "source_branch": _row_value(mr, "source_branch"),
                "target_branch": _row_value(mr, "target_branch"),
                "author": _row_value(mr, "author"),
                "repository_name": _row_value(mr, "repository_name"),
                "risk_score": _row_value(mr, "risk_score", 0),
            },
            "changed_files": file_payload,
            "selected_findings": findings_payload,
            "context_bundle": context_bundle or {},
            "constraints": {
                "language": "zh-CN",
                "style": "简洁、具体、面向 reviewer 决策",
                "max_items_per_section": 8,
            },
        },
        ensure_ascii=False,
    )
    providers = candidate_providers(llm, required_context=max(1, len(prompt) // 4))
    first_provider = providers[0] if providers else {
        "provider": llm.get("default_provider") or "dashscope-openai-compatible",
        "model": llm.get("default_model") or "MiniMax-M2.7",
    }
    provider = str(first_provider.get("provider"))
    model = str(first_provider.get("model"))
    if budget_tracker and budget_tracker.should_stop():
        recorder.llm_call(span_id, provider, model, prompt, f"skipped_by_budget:{budget_tracker.truncated_reason}", 0, len(prompt) // 4, 0)
        return normalize_pr_summary({}, {**fallback, "source": "fallback", "skipped": True, "skip_reason": str(budget_tracker.truncated_reason)})
    if not providers:
        recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, len(prompt) // 4, 0)
        return normalize_pr_summary({}, {**fallback, "source": "fallback", "skipped": True, "skip_reason": "no_api_key"})

    last_error: Exception | None = None
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
                    "你是资深代码检视负责人，只输出严格 JSON 对象。"
                    "除 file_path、rule_id、代码片段、类名、方法名和技术专有名词外，"
                    "所有自然语言字段必须使用中文。"
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
                    "max_tokens": min(2048, llm_max_output_tokens(llm)),
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
            recorder.llm_call(
                span_id,
                provider,
                model,
                prompt,
                "completed",
                duration_ms,
                input_tokens,
                output_tokens,
                str(response.get("id") or ""),
                messages,
                response_debug_text,
            )
            if budget_tracker:
                budget_tracker.charge_llm(model, input_tokens, output_tokens)
            return normalize_pr_summary({**_json_object_from_content(content), "source": "llm"}, fallback)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            duration_ms = int((time.time() - started) * 1000)
            error_text = json.dumps({"error": str(exc), "timeout_seconds": timeout_seconds, "stream": stream_enabled}, ensure_ascii=False)
            recorder.llm_call(span_id, provider, model, prompt, f"failed:{type(exc).__name__}", duration_ms, len(prompt) // 4, 0, None, messages, error_text)
            if index < len(providers) - 1:
                recorder.event(span_id, "pr_summary_llm_failover", f"{provider} 摘要调用失败，尝试下一个 provider", {"error": str(exc)[:300]})
                continue
            recorder.event(span_id, "pr_summary_llm_error", f"PR Summary LLM 调用失败，使用兜底摘要：{exc}")
    return normalize_pr_summary({}, {**fallback, "source": "fallback", "skipped": True, "skip_reason": type(last_error).__name__ if last_error else "llm_failed"})


def call_llm(
    config: dict[str, Any],
    recorder: Any,
    span_id: str,
    agent: dict[str, Any],
    files: list[Any],
    skill_summary: str = "",
) -> list[dict[str, Any]]:
    agent_id = str(agent.get("agent_id") or "unknown_agent")
    llm = config.get("llm", {})
    budget_tracker = agent.get("budget_tracker")
    prompt, safety = build_prompt(agent, files, skill_summary)
    providers = candidate_providers(llm, required_context=max(1, len(prompt) // 4))
    first_provider = providers[0] if providers else {
        "provider": llm.get("default_provider") or "dashscope-openai-compatible",
        "model": llm.get("default_model") or "MiniMax-M2.7",
    }
    provider = str(first_provider.get("provider"))
    model = str(first_provider.get("model"))
    if budget_tracker and budget_tracker.should_stop():
        recorder.llm_call(span_id, provider, model, prompt, f"skipped_by_budget:{budget_tracker.truncated_reason}", 0, len(prompt) // 4, 0)
        recorder.event(span_id, "llm_skipped_by_budget", f"预算已触发熔断：{budget_tracker.truncated_reason}", budget_tracker.snapshot())
        return []
    if not files:
        recorder.llm_call(span_id, provider, model, prompt, "skipped_no_llm_allowed_files", 0, len(prompt) // 4, 0)
        recorder.event(span_id, "llm_skipped_by_data_policy", "没有可进入 LLM 的变更文件，按数据策略跳过模型调用")
        return []
    if safety["injection_patterns"]:
        recorder.event(span_id, "injection_attempt_detected", "diff 中出现疑似 prompt injection 文本，已按 untrusted 内容处理", safety)
    if safety["redactions"]:
        recorder.event(span_id, "redaction_applied", "送入 LLM 前完成敏感片段脱敏", safety)
    if not providers:
        recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, len(prompt) // 4, 0)
        return []

    last_error: Exception | None = None
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
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": llm_max_output_tokens(llm),
        }
        timeout_seconds = llm_request_timeout_seconds(llm)
        stream_enabled = llm_stream_enabled(llm)
        try:
            response = http_json(
                chat_completions_url(base_url),
                {"Authorization": f"Bearer {api_key}"},
                method="POST",
                body=payload,
                timeout_seconds=timeout_seconds,
                stream=stream_enabled,
            )
            duration_ms = int((time.time() - started) * 1000)
            usage = response.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", len(prompt) // 4))
            output_tokens = int(usage.get("completion_tokens", 0))
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "[]")
            response_debug_text = json.dumps({"content": content, "stream": response.get("_jolt_stream") or {"enabled": False}}, ensure_ascii=False)
            recorder.llm_call(
                span_id,
                provider,
                model,
                prompt,
                "completed",
                duration_ms,
                input_tokens,
                output_tokens,
                str(response.get("id") or ""),
                messages,
                response_debug_text,
            )
            if budget_tracker:
                budget_tracker.charge_llm(model, input_tokens, output_tokens)
                if budget_tracker.truncated_reason:
                    recorder.event(span_id, "budget_truncated", f"LLM 调用后预算触发熔断：{budget_tracker.truncated_reason}", budget_tracker.snapshot())
            return parse_llm_findings(agent_id, content, files)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            duration_ms = int((time.time() - started) * 1000)
            error_text = json.dumps({"error": str(exc), "timeout_seconds": timeout_seconds, "stream": stream_enabled}, ensure_ascii=False)
            recorder.llm_call(span_id, provider, model, prompt, f"failed:{type(exc).__name__}", duration_ms, len(prompt) // 4, 0, None, messages, error_text)
            if index < len(providers) - 1:
                recorder.event(span_id, "llm_failover", f"{provider} 调用失败，尝试下一个 provider：{type(exc).__name__}", {"error": str(exc)[:300]})
                continue
            recorder.event(span_id, "llm_error", f"LLM 调用失败，使用静态检视结果兜底：{exc}")
            return []
    if last_error:
        recorder.event(span_id, "llm_error", f"LLM 调用失败，使用静态检视结果兜底：{last_error}")
    return []
