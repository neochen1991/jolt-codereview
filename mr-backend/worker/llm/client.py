from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any

from db_postgres import open_app_database
from llm_router import candidate_providers
from llm.exchange import derive_seed, execute_chat_exchange, replay_mode_from_config
from llm.model_capabilities import resolve_model_capabilities
from llm.retry import call_with_retry
from prompts.builder import build_context_unit_prompt_parts, build_context_units_prompt_parts, build_prompt
from prompts.system import REVIEW_SYSTEM_PROMPT

LLM_REVIEW_SEED = 13
LLM_REVIEW_SCHEMA_NAME = "review_findings_v2"
LLM_REVIEW_FALLBACK_SCHEMA_NAME = "review_findings_v2_unstructured"
_SCHEMA_UNSUPPORTED_PROVIDERS: set[tuple[str, str]] = set()


def sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def estimate_tokens(text: str) -> int:
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    non_cjk = max(0, len(text) - cjk)
    return max(1, int(cjk * 0.6 + non_cjk / 4) + 1)


def _estimate_optional(value: Any) -> int:
    text = str(value or "")
    return estimate_tokens(text) if text else 0


def input_composition_for_prompt(prompt: str, metadata: dict[str, Any]) -> dict[str, Any]:
    stable_prompt = str(metadata.get("stable_prompt") or "")
    dynamic_prompt = str(metadata.get("dynamic_prompt") or "")
    try:
        stable = json.loads(stable_prompt) if stable_prompt else {}
    except json.JSONDecodeError:
        stable = {}
    try:
        dynamic = json.loads(dynamic_prompt) if dynamic_prompt else {}
    except json.JSONDecodeError:
        dynamic = {}
    stable_rules = stable.get("review_rules") if isinstance(stable.get("review_rules"), dict) else {}
    skill_text = str(stable_rules.get("dedicated_markdown_standard") or "")
    structured = dynamic.get("structured_diff") if isinstance(dynamic.get("structured_diff"), dict) else {}
    items = [item for item in (structured.get("items") or []) if isinstance(item, dict)]
    source_text = "\n".join(str(item.get("source_text") or "") for item in items)
    patch_text = "\n".join(str(item.get("patch_text") or "") for item in items)
    dependency_text = "\n".join(
        str(dependency.get("source_text") or "")
        for item in items
        for dependency in (item.get("dependencies") or [])
        if isinstance(dependency, dict)
    )
    tool_section = dynamic.get("static_tool_scan_findings") if isinstance(dynamic.get("static_tool_scan_findings"), dict) else {}
    tool_items = tool_section.get("items") or []
    source_tokens = _estimate_optional(source_text)
    dependency_tokens = _estimate_optional(dependency_text)
    patch_tokens = _estimate_optional(patch_text)
    skill_tokens = _estimate_optional(skill_text)
    tool_tokens = _estimate_optional(json.dumps(tool_items, ensure_ascii=False, sort_keys=True)) if tool_items else 0
    stable_total = _estimate_optional(REVIEW_SYSTEM_PROMPT) + _estimate_optional(stable_prompt)
    fixed_tokens = max(0, stable_total - skill_tokens)
    dynamic_total = _estimate_optional(dynamic_prompt or prompt)
    known_dynamic = source_tokens + dependency_tokens + patch_tokens + tool_tokens
    other_dynamic = max(0, dynamic_total - known_dynamic)
    estimated_total = source_tokens + dependency_tokens + skill_tokens + tool_tokens + fixed_tokens + patch_tokens + other_dynamic
    return {
        "source_tokens": source_tokens,
        "dependency_tokens": dependency_tokens,
        "skill_tokens": skill_tokens,
        "tool_observation_tokens": tool_tokens,
        "fixed_instruction_tokens": fixed_tokens,
        "patch_tokens": patch_tokens,
        "other_dynamic_tokens": other_dynamic,
        "estimated_input_tokens": estimated_total,
        "stable_prefix_hash": str(metadata.get("stable_prefix_hash") or ""),
        "context_unit_count": len(items),
        "tool_observation_count": len(tool_items) if isinstance(tool_items, list) else 0,
    }


def llm_request_timeout_seconds(llm: dict[str, Any] | None, operation: str = "default") -> int:
    config = llm or {}
    defaults = {"router": 60, "debate": 60, "summary": 60, "expert": 120, "deepagents": 240, "default": 120}
    timeouts = config.get("timeouts") if isinstance(config.get("timeouts"), dict) else {}
    configured = (
        timeouts.get(operation)
        or timeouts.get("default")
        or config.get("request_timeout_seconds")
        or config.get("timeout_seconds")
        or config.get("default_timeout_seconds")
        or defaults.get(operation)
        or defaults["default"]
    )
    try:
        return max(1, min(600, int(configured)))
    except (TypeError, ValueError):
        return defaults.get(operation) or defaults["default"]


def llm_stream_enabled(llm: dict[str, Any] | None) -> bool:
    config = llm or {}
    configured = config.get("enable_stream", config.get("stream", True))
    if isinstance(configured, str):
        return configured.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return bool(configured)


def collect_openai_sse_lines(raw_lines: Any, started: float) -> dict[str, Any]:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
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
        if delta.get("reasoning_content"):
            reasoning_parts.append(str(delta.get("reasoning_content")))
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
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
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
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if stream and "text/event-stream" in content_type:
                return collect_openai_sse_response(response, started)
            return parse_openai_response_text(response.read().decode("utf-8", errors="replace"), started)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            detail = ""
        setattr(exc, "jolt_detail", detail)
        raise


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


def llm_max_output_tokens(llm: dict[str, Any] | None, provider: str = "", model: str = "") -> int:
    config = llm or {}
    capabilities = resolve_model_capabilities(provider, model, config)
    configured = config.get("max_output_tokens") or config.get("default_max_output_tokens") or capabilities.recommended_output_tokens
    try:
        return max(1024, min(capabilities.max_output_tokens, int(configured)))
    except (TypeError, ValueError):
        return capabilities.recommended_output_tokens


def build_chat_payload(
    *,
    provider: str,
    model: str,
    llm: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    temperature: float,
    seed: int | None,
    structured: bool,
    max_tokens: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = llm or {}
    capabilities = resolve_model_capabilities(provider, model, config)
    effective_max_tokens = max_tokens or llm_max_output_tokens(config, provider, model)
    effective_max_tokens = max(1, min(int(effective_max_tokens), capabilities.max_output_tokens))
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": effective_max_tokens,
    }
    if capabilities.thinking:
        payload["thinking"] = dict(capabilities.thinking)
    if capabilities.reasoning_effort:
        payload["reasoning_effort"] = capabilities.reasoning_effort
    if capabilities.supports_seed and seed is not None:
        payload["seed"] = int(seed)
    if structured and capabilities.response_format:
        payload["response_format"] = dict(capabilities.response_format)
    response_format = payload.get("response_format") or {}
    metadata = {
        "model_family": capabilities.family,
        "effective_max_output_tokens": effective_max_tokens,
        "thinking_mode": str((payload.get("thinking") or {}).get("type") or "disabled"),
        "structured_output_mode": str(response_format.get("type") or "prompt_json" if structured else "text"),
        "seed_enabled": "seed" in payload,
    }
    return payload, metadata


def unsupported_request_parameter(exc: Exception, candidates: set[str]) -> str | None:
    detail = str(getattr(exc, "jolt_detail", "") or "")
    message = f"{exc} {detail}".lower()
    compatibility_markers = ("unsupported", "not supported", "unknown parameter", "unrecognized", "invalid parameter")
    if not any(marker in message for marker in compatibility_markers):
        return None
    for parameter in sorted(candidates):
        aliases = {parameter.lower(), parameter.lower().replace("_", " ")}
        if any(alias in message for alias in aliases):
            return parameter
    return None


def invoke_with_parameter_fallback(
    payload: dict[str, Any],
    invoke: Any,
    *,
    on_downgrade: Any | None = None,
) -> dict[str, Any]:
    active_payload = dict(payload)
    optional_parameters = {"response_format", "thinking", "reasoning_effort", "seed"}
    while True:
        try:
            return invoke(active_payload)
        except Exception as exc:
            parameter = unsupported_request_parameter(exc, optional_parameters.intersection(active_payload))
            if not parameter:
                raise
            active_payload.pop(parameter, None)
            if on_downgrade:
                on_downgrade(parameter)


def review_findings_response_format() -> dict[str, Any]:
    finding_schema = {
        "type": "object",
        "additionalProperties": True,
        "required": [
            "severity",
            "confidence",
            "file_path",
            "line_start",
            "line_end",
            "title",
            "problem_description",
            "trigger_condition",
            "impact",
            "semantic_evidence",
            "recommendation",
            "suggested_code",
            "evidence",
            "covered_rules",
            "skipped_rules",
        ],
        "properties": {
            "severity": {"type": "string"},
            "confidence": {"type": "number"},
            "file_path": {"type": "string"},
            "line_start": {"type": "integer"},
            "line_end": {"type": "integer"},
            "title": {"type": "string"},
            "problem_description": {"type": "string"},
            "trigger_condition": {"type": "string"},
            "impact": {"type": "string"},
            "causal_delta": {"type": "string"},
            "semantic_evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["symbol_id", "relation", "file_path"],
                    "properties": {
                        "symbol_id": {"type": "string"},
                        "relation": {"type": "string"},
                        "file_path": {"type": "string"},
                    },
                },
            },
            "recommendation": {"type": "string"},
            "suggested_code": {"type": "string"},
            "evidence": {"type": "string"},
            "covered_rules": {"type": "array", "items": {"type": "string"}},
            "skipped_rules": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": LLM_REVIEW_SCHEMA_NAME,
            "strict": True,
            "schema": {
                "type": "array",
                "items": finding_schema,
            },
        },
    }


def _schema_provider_key(provider: str, model: str) -> tuple[str, str]:
    return (str(provider or ""), str(model or ""))


def _schema_error_is_unsupported(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError) and 400 <= int(getattr(exc, "code", 0) or 0) < 500:
        return True
    message = str(exc).lower()
    return "response_format" in message or "json_schema" in message or "schema" in message


def schema_strict_disabled(provider: str, model: str) -> bool:
    return _schema_provider_key(provider, model) in _SCHEMA_UNSUPPORTED_PROVIDERS


def mark_schema_strict_disabled(provider: str, model: str) -> None:
    _SCHEMA_UNSUPPORTED_PROVIDERS.add(_schema_provider_key(provider, model))


def llm_cache_key(provider: str, model: str, prompt: str, *, seed: int, schema_name: str, project_id: str) -> str:
    return sha1(json.dumps(
        {
            "project_id": project_id,
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "seed": seed,
            "schema_name": schema_name,
        },
        ensure_ascii=False,
        sort_keys=True,
    ))


def _ensure_llm_cache_schema(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_response_cache (
          cache_key TEXT PRIMARY KEY,
          project_id TEXT NOT NULL DEFAULT 'project_default',
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          schema_name TEXT NOT NULL,
          seed INTEGER NOT NULL,
          prompt_hash TEXT NOT NULL,
          response_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    try:
        conn.execute("ALTER TABLE llm_response_cache ADD COLUMN project_id TEXT NOT NULL DEFAULT 'project_default'")
    except Exception:
        pass


def _read_cached_llm_response(config: dict[str, Any], cache_key: str, project_id: str) -> dict[str, Any] | None:
    if (config.get("llm") or {}).get("enable_response_cache") is False:
        return None
    conn = None
    try:
        conn = open_app_database(config)
        _ensure_llm_cache_schema(conn)
        row = conn.execute("SELECT response_json FROM llm_response_cache WHERE cache_key = %s AND project_id = %s", (cache_key, project_id)).fetchone()
        if not row:
            return None
        raw = row["response_json"]
        parsed = json.loads(str(raw or "{}"))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _write_cached_llm_response(
    config: dict[str, Any],
    *,
    cache_key: str,
    project_id: str,
    provider: str,
    model: str,
    schema_name: str,
    seed: int,
    prompt: str,
    response: dict[str, Any],
) -> None:
    if (config.get("llm") or {}).get("enable_response_cache") is False:
        return
    conn = None
    try:
        conn = open_app_database(config)
        _ensure_llm_cache_schema(conn)
        conn.execute(
            """
            INSERT INTO llm_response_cache (
              cache_key, project_id, provider, model, schema_name, seed, prompt_hash, response_json, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT(cache_key) DO UPDATE SET
              project_id = excluded.project_id,
              response_json = excluded.response_json,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                cache_key,
                project_id,
                provider,
                model,
                schema_name,
                seed,
                sha1(prompt),
                json.dumps(response, ensure_ascii=False),
            ),
        )
        conn.commit()
    except Exception:
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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


def response_needs_json_repair(response: dict[str, Any]) -> bool:
    choice = (response.get("choices") or [{}])[0]
    if str(choice.get("finish_reason") or "").lower() == "length":
        return True
    content = str((choice.get("message") or {}).get("content") or "")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return True
    return not isinstance(parsed, (list, dict))


def build_json_repair_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        *messages,
        {
            "role": "user",
            "content": (
                "上一轮输出被截断或不是完整 JSON。请重新完成同一检视，只输出完整 JSON 对象 "
                '{"findings": [...]}。保留高置信问题，精简每个字段，确保 JSON 完整闭合。'
            ),
        },
    ]


def parse_llm_findings(
    agent_id: str,
    content: str,
    files: list[Any],
    max_findings: int = 32,
    *,
    metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    parse_status = "complete"
    try:
        start = content.find("[")
        end = content.rfind("]")
        parsed = json.loads(content[start : end + 1] if start >= 0 and end >= start else content)
    except json.JSONDecodeError:
        parsed = _extract_json_objects(content)
        parse_status = "recovered_objects" if parsed else "invalid_json"
    if isinstance(parsed, dict):
        parsed = parsed.get("findings")
    if not isinstance(parsed, list):
        parsed = []
        if parse_status == "complete":
            parse_status = "invalid_shape"
    counters = {
        "parse_status": parse_status,
        "candidate_count": len(parsed),
        "accepted_count": 0,
        "dropped_non_object": 0,
        "dropped_invalid_file": 0,
        "dropped_tool_echo": 0,
        "dropped_invalid_line": 0,
        "dropped_over_limit": 0,
    }
    valid_files = {item.filename for item in files}
    findings: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            counters["dropped_non_object"] += 1
            continue
        file_path = str(item.get("file_path") or "")
        if file_path not in valid_files:
            counters["dropped_invalid_file"] += 1
            continue
        title = str(item.get("title") or "AI 检视问题")[:120]
        lowered_title = title.lower()
        if lowered_title.startswith(("semgrep 命中", "gitleaks 疑似", "ruff 命中", "eslint 命中", "bandit 命中")):
            counters["dropped_tool_echo"] += 1
            continue
        line_start = normalize_line_number(item.get("line_start"))
        line_end = normalize_line_number(item.get("line_end")) or line_start
        if line_start is None:
            counters["dropped_invalid_line"] += 1
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
                "trigger_condition": str(item.get("trigger_condition") or "").strip()[:1000],
                "impact": str(item.get("impact") or "").strip()[:1000],
                "causal_delta": str(item.get("causal_delta") or "unknown").strip().lower()[:40],
                "semantic_evidence": [
                    {
                        "symbol_id": str(ref.get("symbol_id") or "")[:300],
                        "relation": str(ref.get("relation") or "")[:80],
                        "file_path": str(ref.get("file_path") or "")[:500],
                    }
                    for ref in (item.get("semantic_evidence") or [])
                    if isinstance(ref, dict)
                    and str(ref.get("symbol_id") or "")
                    and str(ref.get("relation") or "")
                    and str(ref.get("file_path") or "")
                ][:20],
                "recommendation": recommendation,
                "suggested_code": suggested_code[:4000],
                "evidence": evidence[:500],
                "covered_rules": item.get("covered_rules") if isinstance(item.get("covered_rules"), list) else [],
                "skipped_rules": item.get("skipped_rules") if isinstance(item.get("skipped_rules"), list) else [],
            }
        )
    try:
        limit = max(1, min(int(max_findings), 48))
    except (TypeError, ValueError):
        limit = 32
    counters["accepted_count"] = min(len(findings), limit)
    counters["dropped_over_limit"] = max(0, len(findings) - limit)
    if metrics is not None:
        metrics.clear()
        metrics.update(counters)
    return findings[:limit]


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
    prompt_tokens = estimate_tokens(prompt)
    providers = candidate_providers(llm, required_context=prompt_tokens)
    first_provider = providers[0] if providers else {
        "provider": llm.get("default_provider") or "dashscope-openai-compatible",
        "model": llm.get("default_model") or "MiniMax-M2.7",
    }
    provider = str(first_provider.get("provider"))
    model = str(first_provider.get("model"))
    exchange_mode = replay_mode_from_config(config)
    head_sha = str(_row_value(mr, "latest_head_sha", "") or _row_value(mr, "head_sha", ""))
    if budget_tracker and budget_tracker.should_stop():
        recorder.llm_call(span_id, provider, model, prompt, f"skipped_by_budget:{budget_tracker.truncated_reason}", 0, prompt_tokens, 0)
        return normalize_pr_summary({}, {**fallback, "source": "fallback", "skipped": True, "skip_reason": str(budget_tracker.truncated_reason)})
    if not providers:
        recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, prompt_tokens, 0)
        return normalize_pr_summary({}, {**fallback, "source": "fallback", "skipped": True, "skip_reason": "no_api_key"})

    last_error: Exception | None = None
    for index, candidate in enumerate(providers):
        provider = str(candidate.get("provider"))
        model = str(candidate.get("model"))
        base_url = str(candidate.get("base_url") or "").rstrip("/")
        api_key = candidate.get("api_key")
        if not base_url or not api_key:
            recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, prompt_tokens, 0)
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
        timeout_seconds = llm_request_timeout_seconds(llm, "summary")
        stream_enabled = llm_stream_enabled(llm)
        try:
            def invoke_summary(seed: int) -> dict[str, Any]:
                payload, _metadata = build_chat_payload(
                    provider=provider,
                    model=model,
                    llm=llm,
                    messages=messages,
                    temperature=0.1,
                    seed=seed,
                    structured=True,
                    max_tokens=min(8192, llm_max_output_tokens(llm, provider, model)),
                )
                return invoke_with_parameter_fallback(
                    payload,
                    lambda active: call_with_retry(
                        lambda: http_json(
                            chat_completions_url(base_url),
                            {"Authorization": f"Bearer {api_key}"},
                            method="POST",
                            body=active,
                            timeout_seconds=timeout_seconds,
                            stream=stream_enabled,
                        )
                    ),
                    on_downgrade=lambda parameter: recorder.event(
                        span_id,
                        "llm_parameter_downgraded",
                        f"{model} 摘要调用移除不兼容参数：{parameter}",
                        {"provider": provider, "model": model, "parameter": parameter, "operation": "summary"},
                    ),
                )

            exchange = execute_chat_exchange(
                recorder=recorder,
                span_id=span_id,
                operation="summary",
                agent_id="summary_agent",
                context_unit_id="",
                checkpoint_id="",
                head_sha=head_sha,
                provider=provider,
                model=model,
                prompt=prompt,
                messages=messages,
                temperature=0.1,
                replay_mode=exchange_mode,
                invoke=invoke_summary,
            )
            response = exchange.response
            duration_ms = int((time.time() - started) * 1000)
            usage = response.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", prompt_tokens))
            output_tokens = int(usage.get("completion_tokens", 0))
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            if budget_tracker:
                budget_tracker.charge_llm(model, input_tokens, output_tokens)
            return normalize_pr_summary({**_json_object_from_content(content), "source": "llm"}, fallback)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            duration_ms = int((time.time() - started) * 1000)
            error_text = json.dumps({"error": str(exc), "timeout_seconds": timeout_seconds, "stream": stream_enabled}, ensure_ascii=False)
            recorder.llm_call(span_id, provider, model, prompt, f"failed:{type(exc).__name__}", duration_ms, prompt_tokens, 0, None, messages, error_text)
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
    project_id = str(config.get("_project_id") or "project_default")
    budget_tracker = agent.get("budget_tracker")
    context_unit = agent.get("context_unit")
    context_units = agent.get("context_units") if isinstance(agent.get("context_units"), list) else []
    context_unit_ids = [
        str(getattr(item, "unit_id", "") or (item.get("unit_id") if isinstance(item, dict) else ""))
        for item in context_units
    ]
    context_hashes = [
        str(getattr(item, "context_hash", "") or (item.get("context_hash") if isinstance(item, dict) else ""))
        for item in context_units
    ]
    context_unit_id = ",".join(item for item in context_unit_ids if item) or str(getattr(context_unit, "unit_id", "") or (context_unit.get("unit_id") if isinstance(context_unit, dict) else ""))
    context_hash = ",".join(item for item in context_hashes if item) or str(getattr(context_unit, "context_hash", "") or (context_unit.get("context_hash") if isinstance(context_unit, dict) else ""))
    if context_units:
        checkpoint_values: list[str] = []
        for item in context_units:
            checkpoint_values.extend(str(value) for value in (getattr(item, "skill_checkpoint_ids", ()) or (item.get("skill_checkpoint_ids") if isinstance(item, dict) else []) or []))
        checkpoint_ids = tuple(dict.fromkeys(checkpoint_values))
    else:
        checkpoint_ids = getattr(context_unit, "skill_checkpoint_ids", ()) if context_unit is not None else ()
    checkpoint_id = ",".join(str(item) for item in checkpoint_ids) if checkpoint_ids else str(agent.get("checkpoint_id") or "")
    head_sha = str(agent.get("head_sha") or config.get("_head_sha") or "")
    exchange_mode = replay_mode_from_config(config)
    if context_units:
        prompt, safety = build_context_units_prompt_parts(agent, context_units, skill_summary)
    elif context_unit is not None:
        prompt, safety = build_context_unit_prompt_parts(agent, context_unit, skill_summary)
    else:
        prompt, safety = build_prompt(agent, files, skill_summary)
    input_composition = input_composition_for_prompt(prompt, safety)
    prompt_tokens = int(input_composition["estimated_input_tokens"])
    recorder.event(
        span_id,
        "llm_input_composition",
        f"{agent_id} 本次专家调用预计输入 {prompt_tokens} tokens",
        {
            **input_composition,
            "agent_id": agent_id,
            "batch_label": str(agent.get("review_batch_label") or ""),
            "context_unit_ids": context_unit_ids,
        },
    )
    providers = candidate_providers(llm, required_context=prompt_tokens)
    first_provider = providers[0] if providers else {
        "provider": llm.get("default_provider") or "dashscope-openai-compatible",
        "model": llm.get("default_model") or "MiniMax-M2.7",
    }
    provider = str(first_provider.get("provider"))
    model = str(first_provider.get("model"))
    if budget_tracker and budget_tracker.should_stop():
        recorder.llm_call(span_id, provider, model, prompt, f"skipped_by_budget:{budget_tracker.truncated_reason}", 0, prompt_tokens, 0, input_composition=input_composition)
        recorder.event(span_id, "llm_skipped_by_budget", f"预算已触发熔断：{budget_tracker.truncated_reason}", budget_tracker.snapshot())
        return []
    if not files:
        recorder.llm_call(span_id, provider, model, prompt, "skipped_no_llm_allowed_files", 0, prompt_tokens, 0, input_composition=input_composition)
        recorder.event(span_id, "llm_skipped_by_data_policy", "没有可进入 LLM 的变更文件，按数据策略跳过模型调用")
        return []
    public_safety = {
        "redactions": list(safety.get("redactions") or []),
        "injection_patterns": list(safety.get("injection_patterns") or []),
        "stable_prefix_hash": str(safety.get("stable_prefix_hash") or ""),
    }
    if public_safety["injection_patterns"]:
        recorder.event(span_id, "injection_attempt_detected", "diff 中出现疑似 prompt injection 文本，已按 untrusted 内容处理", public_safety)
    if public_safety["redactions"]:
        recorder.event(span_id, "redaction_applied", "送入 LLM 前完成敏感片段脱敏", public_safety)
    if not providers:
        recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, prompt_tokens, 0, input_composition=input_composition)
        return []

    last_error: Exception | None = None
    cache_prompt = f"expert_messages_v2\n{prompt}" if safety.get("stable_prompt") and safety.get("dynamic_prompt") else prompt
    for index, candidate in enumerate(providers):
        provider = str(candidate.get("provider"))
        model = str(candidate.get("model"))
        base_url = str(candidate.get("base_url") or "").rstrip("/")
        api_key = candidate.get("api_key")
        if not base_url or not api_key:
            recorder.llm_call(span_id, provider, model, prompt, "skipped_no_api_key", 0, prompt_tokens, 0, input_composition=input_composition)
            continue
        started = time.time()
        stable_prompt = str(safety.get("stable_prompt") or "")
        dynamic_prompt = str(safety.get("dynamic_prompt") or "")
        messages = [{"role": "system", "content": REVIEW_SYSTEM_PROMPT}]
        if stable_prompt and dynamic_prompt:
            messages.extend(
                [
                    {"role": "user", "content": stable_prompt},
                    {"role": "user", "content": dynamic_prompt},
                ]
            )
        else:
            messages.append({"role": "user", "content": prompt})
        operation_seed = derive_seed(head_sha, "expert", agent_id, context_unit_id, checkpoint_id)
        payload, model_metadata = build_chat_payload(
            provider=provider,
            model=model,
            llm=llm,
            messages=messages,
            temperature=0.1,
            seed=operation_seed,
            structured=True,
        )
        response_format_type = str((payload.get("response_format") or {}).get("type") or "prompt_json")
        schema_name = f"review_findings_v3_{response_format_type}"
        call_input_composition = {**input_composition, **model_metadata}
        recorder.event(
            span_id,
            "llm_model_capabilities",
            f"{model} 使用 {model_metadata['model_family']} 模型能力档案",
            {"provider": provider, "model": model, **model_metadata},
        )
        cache_key = llm_cache_key(provider, model, cache_prompt, seed=operation_seed, schema_name=schema_name, project_id=project_id)
        cached = None if exchange_mode in {"replay", "live_repeat"} else _read_cached_llm_response(config, cache_key, project_id)
        if cached is not None:
            exchange = execute_chat_exchange(
                recorder=recorder,
                span_id=span_id,
                operation="expert",
                agent_id=agent_id,
                context_unit_id=context_unit_id,
                checkpoint_id=checkpoint_id,
                head_sha=head_sha,
                provider=provider,
                model=model,
                prompt=cache_prompt,
                messages=messages,
                temperature=0.1,
                replay_mode="record" if exchange_mode == "record" else "off",
                invoke=lambda _seed: cached,
                context_hash=context_hash,
                response_source="legacy_response_cache",
                input_composition=call_input_composition,
            )
            content = exchange.response.get("choices", [{}])[0].get("message", {}).get("content", "[]")
            try:
                max_findings = int(agent.get("max_findings_per_mr") or agent.get("max_findings") or 32)
            except (TypeError, ValueError):
                max_findings = 32
            parse_metrics: dict[str, Any] = {}
            findings = parse_llm_findings(agent_id, str(content), files, max_findings=max_findings, metrics=parse_metrics)
            recorder.event(span_id, "llm_findings_parse_funnel", f"{agent_id} 缓存响应解析得到 {len(findings)} 条 finding", {"response_source": "cache", **parse_metrics})
            return findings
        timeout_seconds = llm_request_timeout_seconds(llm, "expert")
        stream_enabled = llm_stream_enabled(llm)
        try:
            def invoke_expert(seed: int) -> dict[str, Any]:
                active_payload, _metadata = build_chat_payload(
                    provider=provider,
                    model=model,
                    llm=llm,
                    messages=messages,
                    temperature=0.1,
                    seed=seed,
                    structured=True,
                )
                return invoke_with_parameter_fallback(
                    active_payload,
                    lambda compatible_payload: call_with_retry(
                        lambda: http_json(
                            chat_completions_url(base_url),
                            {"Authorization": f"Bearer {api_key}"},
                            method="POST",
                            body=compatible_payload,
                            timeout_seconds=timeout_seconds,
                            stream=stream_enabled,
                        )
                    ),
                    on_downgrade=lambda parameter: recorder.event(
                        span_id,
                        "llm_parameter_downgraded",
                        f"{model} 专家调用移除不兼容参数：{parameter}",
                        {"provider": provider, "model": model, "parameter": parameter, "operation": "expert"},
                    ),
                )

            exchange = execute_chat_exchange(
                recorder=recorder,
                span_id=span_id,
                operation="expert",
                agent_id=agent_id,
                context_unit_id=context_unit_id,
                checkpoint_id=checkpoint_id,
                head_sha=head_sha,
                provider=provider,
                model=model,
                prompt=cache_prompt,
                messages=messages,
                temperature=0.1,
                replay_mode=exchange_mode,
                invoke=invoke_expert,
                context_hash=context_hash,
                input_composition=call_input_composition,
            )
            response = exchange.response
            duration_ms = int((time.time() - started) * 1000)
            charged_responses = [response]
            if response_needs_json_repair(response):
                choice = (response.get("choices") or [{}])[0]
                recorder.event(
                    span_id,
                    "llm_json_repair_started",
                    f"{model} 输出被截断或 JSON 不完整，执行一次完整 JSON 重试",
                    {"provider": provider, "model": model, "finish_reason": str(choice.get("finish_reason") or "")},
                )
                repair_messages = build_json_repair_messages(messages)

                def invoke_repair(seed: int) -> dict[str, Any]:
                    repair_payload, _metadata = build_chat_payload(
                        provider=provider,
                        model=model,
                        llm=llm,
                        messages=repair_messages,
                        temperature=0.0,
                        seed=seed,
                        structured=True,
                    )
                    return invoke_with_parameter_fallback(
                        repair_payload,
                        lambda compatible_payload: call_with_retry(
                            lambda: http_json(
                                chat_completions_url(base_url),
                                {"Authorization": f"Bearer {api_key}"},
                                method="POST",
                                body=compatible_payload,
                                timeout_seconds=timeout_seconds,
                                stream=stream_enabled,
                            )
                        ),
                        on_downgrade=lambda parameter: recorder.event(
                            span_id,
                            "llm_parameter_downgraded",
                            f"{model} JSON 重试移除不兼容参数：{parameter}",
                            {"provider": provider, "model": model, "parameter": parameter, "operation": "expert_json_repair"},
                        ),
                    )

                try:
                    repair_exchange = execute_chat_exchange(
                        recorder=recorder,
                        span_id=span_id,
                        operation="expert_json_repair",
                        agent_id=agent_id,
                        context_unit_id=context_unit_id,
                        checkpoint_id=checkpoint_id,
                        head_sha=head_sha,
                        provider=provider,
                        model=model,
                        prompt=f"{cache_prompt}\njson_repair_v1",
                        messages=repair_messages,
                        temperature=0.0,
                        replay_mode=exchange_mode,
                        invoke=invoke_repair,
                        context_hash=context_hash,
                        input_composition={**call_input_composition, "json_repair_attempt": True},
                    )
                    charged_responses.append(repair_exchange.response)
                    if not response_needs_json_repair(repair_exchange.response):
                        response = repair_exchange.response
                        recorder.event(span_id, "llm_json_repair_completed", f"{model} JSON 重试已返回完整响应")
                    else:
                        recorder.event(span_id, "llm_json_repair_failed", f"{model} JSON 重试仍不完整，保留首轮可恢复内容")
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as repair_exc:
                    recorder.event(span_id, "llm_json_repair_failed", f"{model} JSON 重试失败，保留首轮可恢复内容", {"error": str(repair_exc)[:300]})
            usage = response.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", prompt_tokens))
            output_tokens = int(usage.get("completion_tokens", 0))
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "[]")
            _write_cached_llm_response(
                config,
                cache_key=cache_key,
                project_id=project_id,
                provider=provider,
                model=model,
                schema_name=schema_name,
                seed=operation_seed,
                prompt=cache_prompt,
                response=response,
            )
            if budget_tracker:
                for charged_response in charged_responses:
                    charged_usage = charged_response.get("usage") or {}
                    budget_tracker.charge_llm(model, int(charged_usage.get("prompt_tokens", prompt_tokens)), int(charged_usage.get("completion_tokens", 0)))
                if budget_tracker.truncated_reason:
                    recorder.event(span_id, "budget_truncated", f"LLM 调用后预算触发熔断：{budget_tracker.truncated_reason}", budget_tracker.snapshot())
            try:
                max_findings = int(agent.get("max_findings_per_mr") or agent.get("max_findings") or 32)
            except (TypeError, ValueError):
                max_findings = 32
            parse_metrics = {}
            findings = parse_llm_findings(agent_id, content, files, max_findings=max_findings, metrics=parse_metrics)
            recorder.event(
                span_id,
                "llm_findings_parse_funnel",
                f"{agent_id} 模型候选 {parse_metrics.get('candidate_count', 0)} 条，接受 {len(findings)} 条",
                {"provider": provider, "model": model, **parse_metrics},
            )
            return findings
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            duration_ms = int((time.time() - started) * 1000)
            error_text = json.dumps({"error": str(exc), "timeout_seconds": timeout_seconds, "stream": stream_enabled}, ensure_ascii=False)
            recorder.llm_call(span_id, provider, model, prompt, f"failed:{type(exc).__name__}", duration_ms, prompt_tokens, 0, None, messages, error_text, input_composition=input_composition)
            if index < len(providers) - 1:
                recorder.event(span_id, "llm_failover", f"{provider} 调用失败，尝试下一个 provider：{type(exc).__name__}", {"error": str(exc)[:300]})
                continue
            recorder.event(span_id, "llm_error", f"LLM 调用失败，使用静态检视结果兜底：{exc}")
            return []
    if last_error:
        recorder.event(span_id, "llm_error", f"LLM 调用失败，使用静态检视结果兜底：{last_error}")
    return []
