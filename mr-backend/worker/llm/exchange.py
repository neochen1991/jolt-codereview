from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Callable, Protocol


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def invoke_openai_chat(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    stream: bool,
    transport: Callable[..., dict[str, Any]],
    retry: Callable[[Callable[[], dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    return retry(
        lambda: transport(
            endpoint,
            {"Authorization": f"Bearer {api_key}"},
            method="POST",
            body=payload,
            timeout_seconds=timeout_seconds,
            stream=stream,
        )
    )


def derive_seed(
    head_sha: str,
    operation: str,
    agent_id: str = "",
    context_unit_id: str = "",
    checkpoint_id: str = "",
) -> int:
    """Return a provider-safe, stable seed for one logical LLM operation."""
    digest = hashlib.sha256(
        "\x1f".join((head_sha, operation, agent_id, context_unit_id, checkpoint_id)).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFF


@dataclass(frozen=True)
class ExecutionEnvelope:
    run_id: str
    operation: str
    agent_id: str
    context_unit_id: str
    checkpoint_id: str
    input_hash: str
    head_sha: str
    context_hash: str
    prompt_version: str
    provider: str
    model: str
    seed: int
    temperature: float
    top_p: float | None
    request_hash: str
    cache_key: str
    tool_result_hashes: tuple[str, ...]
    replay_mode: str


@dataclass(frozen=True)
class ExchangeResult:
    response: dict[str, Any]
    envelope: ExecutionEnvelope
    response_hash: str
    replay_source: str


class ExchangeStore(Protocol):
    def get(self, cache_key: str) -> dict[str, Any] | None: ...

    def put(self, cache_key: str, envelope: ExecutionEnvelope, response: dict[str, Any]) -> None: ...


class InMemoryExchangeStore:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def get(self, cache_key: str) -> dict[str, Any] | None:
        item = self._items.get(cache_key)
        return json.loads(_stable_json(item)) if item is not None else None

    def put(self, cache_key: str, envelope: ExecutionEnvelope, response: dict[str, Any]) -> None:
        self._items[cache_key] = {
            "envelope": envelope.__dict__,
            "response": response,
            "response_hash": _sha256(_stable_json(response)),
        }


class DatabaseExchangeStore:
    """Durable exchange store used by production reviews and exact replay."""

    def __init__(self, conn: Any, *, review_run_id: str = "", ttl_days: int = 14) -> None:
        self.conn = conn
        self.review_run_id = review_run_id
        self.expires_at = (datetime.now(timezone.utc) + timedelta(days=max(1, ttl_days))).isoformat()

    def get(self, cache_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT response_json, response_hash
            FROM llm_exchange_records
            WHERE cache_key = %s
              AND (expires_at IS NULL OR expires_at = '' OR NULLIF(expires_at, '')::timestamptz > CURRENT_TIMESTAMP)
            """,
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        raw = row["response_json"] if hasattr(row, "keys") else row[0]
        response_hash = row["response_hash"] if hasattr(row, "keys") else row[1]
        return {"response": json.loads(raw), "response_hash": str(response_hash or "")}

    def put(self, cache_key: str, envelope: ExecutionEnvelope, response: dict[str, Any]) -> None:
        response_json = _stable_json(response)
        self.conn.execute(
            """
            INSERT INTO llm_exchange_records (
              cache_key, operation, agent_id, context_unit_id, context_hash, checkpoint_id,
              head_sha, provider, model, seed, temperature, request_hash,
              response_hash, response_json, review_run_id, expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(cache_key) DO UPDATE SET
              response_hash = EXCLUDED.response_hash,
              response_json = EXCLUDED.response_json,
              review_run_id = EXCLUDED.review_run_id,
              expires_at = EXCLUDED.expires_at,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                cache_key,
                envelope.operation,
                envelope.agent_id,
                envelope.context_unit_id,
                envelope.context_hash,
                envelope.checkpoint_id,
                envelope.head_sha,
                envelope.provider,
                envelope.model,
                envelope.seed,
                envelope.temperature,
                envelope.request_hash,
                _sha256(response_json),
                response_json,
                self.review_run_id,
                self.expires_at,
            ),
        )


def exchange_store_for_recorder(recorder: Any) -> ExchangeStore | None:
    conn = getattr(recorder, "conn", None)
    config = getattr(recorder, "config", {}) or {}
    llm = config.get("llm") if isinstance(config, dict) and isinstance(config.get("llm"), dict) else {}
    policy = config.get("data_policy") if isinstance(config, dict) and isinstance(config.get("data_policy"), dict) else {}
    allowed = bool(llm.get("allow_exact_replay_storage")) or str(policy.get("llm_response_retention") or "") in {"replay", "full_debug"}
    debug_policy = config.get("skill_debug_policy") if isinstance(config, dict) and isinstance(config.get("skill_debug_policy"), dict) else {}
    retention_days = debug_policy.get("retention_days") or policy.get("llm_response_retention_days") or 14
    return DatabaseExchangeStore(
        conn,
        review_run_id=str(getattr(recorder, "run_id", "") or ""),
        ttl_days=int(retention_days),
    ) if conn is not None and allowed else None


def replay_mode_from_config(config: dict[str, Any] | None) -> str:
    root = config or {}
    llm = root.get("llm") if isinstance(root.get("llm"), dict) else root
    configured = llm.get("exchange_mode", llm.get("replay_mode", "record")) if isinstance(llm, dict) else "record"
    mode = str(configured or "record").strip().lower()
    if mode not in {"off", "record", "replay", "live_repeat"}:
        raise ValueError(f"unsupported llm exchange mode: {mode}")
    return mode


def execute_chat_exchange(
    *,
    recorder: Any,
    span_id: str,
    operation: str,
    agent_id: str,
    context_unit_id: str,
    checkpoint_id: str,
    head_sha: str,
    provider: str,
    model: str,
    prompt: str,
    messages: list[dict[str, Any]],
    temperature: float,
    replay_mode: str,
    invoke: Callable[[int], dict[str, Any]],
    store: ExchangeStore | None = None,
    context_hash: str = "",
    prompt_version: str = "review_prompt_v1",
    top_p: float | None = None,
    response_source: str = "",
    input_composition: dict[str, Any] | None = None,
    request_options: dict[str, Any] | None = None,
) -> ExchangeResult:
    seed = derive_seed(head_sha, operation, agent_id, context_unit_id, checkpoint_id)
    normalized_mode = str(replay_mode or "off").strip().lower()
    input_hash = _sha256(_stable_json({"prompt": prompt, "messages": messages}))
    tool_result_hashes = tuple(
        _sha256(item.get("content", "") if isinstance(item.get("content"), str) else _stable_json(item.get("content")))
        for item in messages
        if isinstance(item, dict) and str(item.get("role") or "") == "tool"
    )
    request_payload = {
        "operation": operation,
        "agent_id": agent_id,
        "context_unit_id": context_unit_id,
        "checkpoint_id": checkpoint_id,
        "head_sha": head_sha,
        "provider": provider,
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "seed": seed,
        "context_hash": context_hash,
        "prompt_version": prompt_version,
        "tool_result_hashes": tool_result_hashes,
        "request_options": request_options or {},
    }
    request_hash = _sha256(_stable_json(request_payload))
    cache_key = _sha256(f"llm-exchange-v1:{request_hash}")
    envelope = ExecutionEnvelope(
        run_id=str(getattr(recorder, "run_id", "") or ""),
        operation=operation,
        agent_id=agent_id,
        context_unit_id=context_unit_id,
        checkpoint_id=checkpoint_id,
        input_hash=input_hash,
        head_sha=head_sha,
        context_hash=context_hash,
        prompt_version=prompt_version,
        provider=provider,
        model=model,
        seed=seed,
        temperature=temperature,
        top_p=top_p,
        request_hash=request_hash,
        cache_key=cache_key,
        tool_result_hashes=tool_result_hashes,
        replay_mode=normalized_mode,
    )
    active_store = store or exchange_store_for_recorder(recorder)
    started = time.time()
    replay_source = "live_response"
    if normalized_mode == "replay":
        if active_store is None:
            raise LookupError("exact replay requested but no exchange store is available")
        recorded = active_store.get(cache_key)
        if not recorded:
            raise LookupError(f"exact replay record not found for request_hash={request_hash}")
        response = recorded.get("response") or {}
        replay_source = "recorded_response"
    else:
        response = invoke(seed)
        if response_source:
            replay_source = str(response_source)
        if normalized_mode in {"record", "live_repeat"} and active_store is not None:
            active_store.put(cache_key, envelope, response)

    response_hash = _sha256(_stable_json(response))
    usage = response.get("usage") if isinstance(response, dict) else {}
    usage = usage if isinstance(usage, dict) else {}
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    provider_cached_tokens = int(prompt_details.get("cached_tokens") or input_details.get("cached_tokens") or 0)
    choice = (response.get("choices") or [{}])[0] if isinstance(response, dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    response_content = str(message.get("content") or "")
    reasoning_content = str(message.get("reasoning_content") or "")
    logged_composition = {
        **(input_composition or {}),
        "provider_cached_input_tokens": provider_cached_tokens,
        "finish_reason": str(choice.get("finish_reason") or ""),
        "response_content_chars": len(response_content),
        "reasoning_content_chars": len(reasoning_content),
    }
    recorder.llm_call(
        span_id,
        provider,
        model,
        prompt,
        "replayed" if replay_source == "recorded_response" else "cache_hit" if replay_source == "legacy_response_cache" else "completed",
        int((time.time() - started) * 1000),
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
        str(response.get("id") or "") if isinstance(response, dict) else "",
        messages,
        _stable_json(response),
        operation=operation,
        agent_id=agent_id,
        context_unit_id=context_unit_id,
        context_hash=context_hash,
        checkpoint_id=checkpoint_id,
        seed=seed,
        temperature=temperature,
        request_hash=request_hash,
        response_hash=response_hash,
        cache_key=cache_key,
        replay_source=replay_source,
        input_composition=logged_composition,
    )
    return ExchangeResult(response=response, envelope=envelope, response_hash=response_hash, replay_source=replay_source)
