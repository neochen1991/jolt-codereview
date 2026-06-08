from __future__ import annotations

import os
from typing import Any


PROVIDER_CAPS = {
    "dashscope-openai-compatible": {"context": 128_000, "vision": False, "tier": "balanced"},
    "minimax": {"context": 128_000, "vision": False, "tier": "balanced"},
    "deepseek": {"context": 64_000, "vision": False, "tier": "fast"},
    "qwen": {"context": 128_000, "vision": True, "tier": "balanced"},
    "claude": {"context": 200_000, "vision": True, "tier": "premium"},
    "openai": {"context": 128_000, "vision": True, "tier": "premium"},
}

TIER_ORDER = {"fast": 0, "balanced": 1, "premium": 2}


def candidate_providers(llm_config: dict[str, Any], *, required_context: int, vision: bool = False) -> list[dict[str, Any]]:
    configured = llm_config.get("providers")
    if isinstance(configured, list) and configured:
        providers = [item for item in configured if isinstance(item, dict)]
    else:
        providers = [
            {
                "provider": llm_config.get("default_provider") or "dashscope-openai-compatible",
                "base_url": llm_config.get("default_base_url") or "",
                "model": llm_config.get("default_model") or "MiniMax-M2.7",
                "api_key_env": llm_config.get("default_api_key_env"),
                "api_key": llm_config.get("default_api_key"),
                "tier": llm_config.get("default_tier"),
                "context": llm_config.get("default_context"),
            }
        ]
    allowed = llm_config.get("allowed_providers")
    allowed_set = {str(item) for item in allowed} if isinstance(allowed, list) else None
    result: list[dict[str, Any]] = []
    for raw in providers:
        name = str(raw.get("provider") or raw.get("name") or raw.get("id") or "")
        if not name or (allowed_set is not None and name not in allowed_set):
            continue
        caps = PROVIDER_CAPS.get(name, {"context": int(raw.get("context") or 128_000), "vision": False, "tier": raw.get("tier") or "balanced"})
        context = int(raw.get("context") or caps["context"])
        if context < required_context:
            continue
        if vision and not bool(raw.get("vision", caps.get("vision"))):
            continue
        api_key_env = raw.get("api_key_env")
        api_key = os.environ.get(str(api_key_env)) if api_key_env else raw.get("api_key")
        result.append(
            {
                "provider": name,
                "base_url": str(raw.get("base_url") or raw.get("default_base_url") or ""),
                "model": str(raw.get("model") or raw.get("default_model") or "MiniMax-M2.7"),
                "api_key": api_key,
                "tier": str(raw.get("tier") or caps.get("tier") or "balanced"),
                "context": context,
            }
        )
    return sorted(result, key=lambda item: TIER_ORDER.get(str(item.get("tier")), 99))
