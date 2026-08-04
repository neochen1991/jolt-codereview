from __future__ import annotations

import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from langchain_core.messages import AIMessage  # noqa: E402
from orchestration.deepagents_runner import _message_to_openai, deepagent_request_payload  # noqa: E402


def test_glm_deepagent_payload_uses_thinking_without_seed() -> None:
    payload, metadata = deepagent_request_payload(
        provider="gateway",
        model="glm-5.2",
        llm_config={"max_output_tokens": 32768},
        messages=[{"role": "user", "content": "inspect"}],
        tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
        seed=13,
    )

    assert payload["thinking"] == {"type": "enabled", "clear_thinking": False}
    assert payload["max_tokens"] == 32768
    assert "seed" not in payload
    assert payload["tool_choice"] == "auto"
    assert metadata["model_family"] == "glm"


def test_minimax_deepagent_payload_keeps_seed() -> None:
    payload, _metadata = deepagent_request_payload(
        provider="gateway",
        model="MiniMax-M2.7",
        llm_config={"max_output_tokens": 8192},
        messages=[{"role": "user", "content": "inspect"}],
        tools=[],
        seed=23,
    )

    assert payload["seed"] == 23
    assert "thinking" not in payload


def test_reasoning_content_is_preserved_between_tool_rounds() -> None:
    message = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "read_file", "args": {"path": "src/App.java"}}],
        additional_kwargs={"reasoning_content": "需要先读取源码"},
    )

    converted = _message_to_openai(message)

    assert converted["reasoning_content"] == "需要先读取源码"
    assert converted["tool_calls"][0]["function"]["name"] == "read_file"


if __name__ == "__main__":
    test_glm_deepagent_payload_uses_thinking_without_seed()
    test_minimax_deepagent_payload_keeps_seed()
    test_reasoning_content_is_preserved_between_tool_rounds()
    print("deepagent model adaptation tests passed")
