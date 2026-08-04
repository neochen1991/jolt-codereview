from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ModelCapabilities:
    family: str
    recommended_output_tokens: int
    max_output_tokens: int
    response_format: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    supports_seed: bool = True


_DEFAULT_PROFILE = ModelCapabilities(
    family="openai-compatible",
    recommended_output_tokens=8192,
    max_output_tokens=32768,
)

_MINIMAX_PROFILE = ModelCapabilities(
    family="minimax",
    recommended_output_tokens=8192,
    max_output_tokens=32768,
)

_GLM_PROFILE = ModelCapabilities(
    family="glm",
    recommended_output_tokens=32768,
    max_output_tokens=131072,
    response_format={"type": "json_object"},
    thinking={"type": "enabled"},
    supports_seed=False,
)


def _base_profile(provider: str, model: str) -> ModelCapabilities:
    normalized_model = str(model or "").strip().lower()
    normalized_provider = str(provider or "").strip().lower()
    if normalized_model.startswith("glm-") or normalized_provider in {"zhipu", "bigmodel", "zai"}:
        return _GLM_PROFILE
    if "minimax" in normalized_model or "minimax" in normalized_provider:
        return _MINIMAX_PROFILE
    return _DEFAULT_PROFILE


def _safe_positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def resolve_model_capabilities(provider: str, model: str, llm_config: dict[str, Any] | None) -> ModelCapabilities:
    profile = _base_profile(provider, model)
    config = llm_config or {}
    overrides = config.get("model_overrides") if isinstance(config.get("model_overrides"), dict) else {}
    family_override = overrides.get(profile.family) if isinstance(overrides.get(profile.family), dict) else {}
    model_override = overrides.get(str(model or "")) if isinstance(overrides.get(str(model or "")), dict) else {}
    merged = {**family_override, **model_override}
    if not merged:
        return profile

    max_output_tokens = _safe_positive_int(merged.get("max_output_tokens"), profile.max_output_tokens)
    recommended_output_tokens = min(
        max_output_tokens,
        _safe_positive_int(merged.get("recommended_output_tokens"), profile.recommended_output_tokens),
    )
    response_format = merged.get("response_format", profile.response_format)
    thinking = merged.get("thinking", profile.thinking)
    reasoning_effort = merged.get("reasoning_effort", profile.reasoning_effort)
    supports_seed = merged.get("supports_seed", profile.supports_seed)
    return replace(
        profile,
        recommended_output_tokens=recommended_output_tokens,
        max_output_tokens=max_output_tokens,
        response_format=dict(response_format) if isinstance(response_format, dict) else None,
        thinking=dict(thinking) if isinstance(thinking, dict) else None,
        reasoning_effort=str(reasoning_effort) if reasoning_effort else None,
        supports_seed=bool(supports_seed),
    )
