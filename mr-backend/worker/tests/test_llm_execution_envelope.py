from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from llm.exchange import InMemoryExchangeStore, derive_seed, execute_chat_exchange  # noqa: E402


class Recorder:
    def __init__(self):
        self.calls: list[dict] = []
        self.run_id = "run-123"

    def llm_call(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})

    def event(self, *_args, **_kwargs):
        return None


def _response(content: str) -> dict:
    return {
        "id": "resp-1",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
    }


def test_seed_is_stable_per_operation_and_context_unit() -> None:
    first = derive_seed("head", "expert", "agent", "unit-a", "checkpoint")
    second = derive_seed("head", "expert", "agent", "unit-a", "checkpoint")
    different = derive_seed("head", "expert", "agent", "unit-b", "checkpoint")

    assert first == second
    assert first != different


def test_record_then_exact_replay_avoids_network() -> None:
    store = InMemoryExchangeStore()
    recorder = Recorder()
    network_calls: list[int] = []
    common = {
        "recorder": recorder,
        "span_id": "span",
        "operation": "critic",
        "agent_id": "critic",
        "context_unit_id": "unit-a",
        "checkpoint_id": "",
        "head_sha": "head",
        "provider": "provider",
        "model": "model",
        "prompt": "prompt",
        "messages": [
            {"role": "user", "content": "prompt"},
            {"role": "tool", "content": json.dumps({"result": ["caller-a"]}, sort_keys=True)},
        ],
        "temperature": 0.0,
        "store": store,
    }

    recorded = execute_chat_exchange(
        **common,
        replay_mode="record",
        invoke=lambda seed: network_calls.append(seed) or _response("recorded"),
    )
    replayed = execute_chat_exchange(
        **common,
        replay_mode="replay",
        invoke=lambda _seed: (_ for _ in ()).throw(AssertionError("network must not be called")),
    )

    assert recorded.response == replayed.response
    assert len(network_calls) == 1
    assert replayed.replay_source == "recorded_response"
    assert recorder.calls[-1]["kwargs"]["operation"] == "critic"
    assert recorder.calls[-1]["kwargs"]["replay_source"] == "recorded_response"
    envelope = recorded.envelope
    assert envelope.run_id == "run-123"
    assert envelope.input_hash
    assert envelope.context_hash == ""
    assert envelope.prompt_version == "review_prompt_v1"
    assert envelope.top_p is None
    assert envelope.replay_mode == "record"
    expected_tool_hash = hashlib.sha256(common["messages"][1]["content"].encode("utf-8")).hexdigest()
    assert envelope.tool_result_hashes == (expected_tool_hash,)
    assert replayed.envelope.replay_mode == "replay"


def test_replay_without_record_is_explicit_failure() -> None:
    try:
        execute_chat_exchange(
            recorder=Recorder(),
            span_id="span",
            operation="router",
            agent_id="router",
            context_unit_id="",
            checkpoint_id="",
            head_sha="head",
            provider="provider",
            model="model",
            prompt="prompt",
            messages=[],
            temperature=0.0,
            replay_mode="replay",
            store=InMemoryExchangeStore(),
            invoke=lambda _seed: _response("unexpected"),
        )
    except LookupError as exc:
        assert "replay" in str(exc)
    else:
        raise AssertionError("missing replay must fail")


def test_request_options_are_part_of_replay_fingerprint() -> None:
    recorder = Recorder()
    common = {
        "recorder": recorder,
        "span_id": "span",
        "operation": "expert",
        "agent_id": "agent",
        "context_unit_id": "unit",
        "checkpoint_id": "cp",
        "head_sha": "head",
        "provider": "gateway",
        "model": "glm-5.2",
        "prompt": "prompt",
        "messages": [{"role": "user", "content": "prompt"}],
        "temperature": 0.1,
        "replay_mode": "off",
        "store": InMemoryExchangeStore(),
        "invoke": lambda _seed: _response("ok"),
    }

    thinking = execute_chat_exchange(
        **common,
        request_options={"max_tokens": 32768, "thinking": {"type": "enabled"}, "response_format": {"type": "json_object"}},
    )
    non_thinking = execute_chat_exchange(
        **common,
        request_options={"max_tokens": 8192},
    )

    assert thinking.envelope.request_hash != non_thinking.envelope.request_hash
    assert thinking.envelope.cache_key != non_thinking.envelope.cache_key


if __name__ == "__main__":
    test_seed_is_stable_per_operation_and_context_unit()
    test_record_then_exact_replay_avoids_network()
    test_replay_without_record_is_explicit_failure()
    test_request_options_are_part_of_replay_fingerprint()
    print("llm execution envelope tests passed")
