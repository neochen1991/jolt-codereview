from __future__ import annotations

import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from llm.model_capabilities import resolve_model_capabilities  # noqa: E402


def test_glm_52_disables_thinking_and_keeps_json_object() -> None:
    profile = resolve_model_capabilities("dashscope-openai-compatible", "glm-5.2", {})

    assert profile.family == "glm"
    assert profile.thinking == {"type": "disabled"}
    assert profile.response_format == {"type": "json_object"}
    assert profile.recommended_output_tokens == 32768
    assert profile.max_output_tokens == 131072
    assert profile.supports_seed is False


def test_glm_51_does_not_add_reasoning_effort() -> None:
    profile = resolve_model_capabilities("zhipu", "GLM-5.1", {})

    assert profile.family == "glm"
    assert profile.thinking == {"type": "disabled"}
    assert profile.reasoning_effort is None


def test_minimax_keeps_prompt_json_and_seed() -> None:
    profile = resolve_model_capabilities("dashscope-openai-compatible", "MiniMax-M2.7", {})

    assert profile.family == "minimax"
    assert profile.thinking is None
    assert profile.response_format is None
    assert profile.supports_seed is True
    assert profile.recommended_output_tokens == 8192


def test_exact_model_override_cannot_reenable_reasoning() -> None:
    profile = resolve_model_capabilities(
        "gateway",
        "glm-5.2",
        {
            "model_overrides": {
                "glm-5.2": {
                    "recommended_output_tokens": 49152,
                    "thinking": {"type": "enabled"},
                    "reasoning_effort": "high",
                }
            }
        },
    )

    assert profile.family == "glm"
    assert profile.recommended_output_tokens == 49152
    assert profile.thinking == {"type": "disabled"}
    assert profile.reasoning_effort is None
    assert profile.response_format == {"type": "json_object"}


def test_unknown_model_override_cannot_enable_reasoning() -> None:
    profile = resolve_model_capabilities(
        "private-gateway",
        "custom-model",
        {
            "model_overrides": {
                "custom-model": {
                    "thinking": {"type": "enabled"},
                    "reasoning_effort": "high",
                }
            }
        },
    )

    assert profile.thinking is None
    assert profile.reasoning_effort is None


def test_unknown_model_uses_conservative_openai_compatible_profile() -> None:
    profile = resolve_model_capabilities("private-gateway", "custom-model", {})

    assert profile.family == "openai-compatible"
    assert profile.recommended_output_tokens == 8192
    assert profile.max_output_tokens == 32768
    assert profile.thinking is None


if __name__ == "__main__":
    test_glm_52_disables_thinking_and_keeps_json_object()
    test_glm_51_does_not_add_reasoning_effort()
    test_minimax_keeps_prompt_json_and_seed()
    test_exact_model_override_cannot_reenable_reasoning()
    test_unknown_model_override_cannot_enable_reasoning()
    test_unknown_model_uses_conservative_openai_compatible_profile()
    print("model capability tests passed")
