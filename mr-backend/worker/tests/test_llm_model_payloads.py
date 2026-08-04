from __future__ import annotations

import sys
import io
import urllib.error
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

import llm.client as llm_client  # noqa: E402
from llm.client import (  # noqa: E402
    build_chat_payload,
    invoke_with_parameter_fallback,
    llm_max_output_tokens,
    request_options_for_payload,
    unsupported_request_parameter,
)


MESSAGES = [{"role": "user", "content": "review"}]


def test_glm_52_payload_is_gateway_compatible() -> None:
    llm = {"max_output_tokens": 32768}

    payload, metadata = build_chat_payload(
        provider="dashscope-openai-compatible",
        model="glm-5.2",
        llm=llm,
        messages=MESSAGES,
        temperature=0.1,
        seed=13,
        structured=True,
    )

    assert payload["max_tokens"] == 32768
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert "seed" not in payload
    assert metadata["model_family"] == "glm"
    assert metadata["structured_output_mode"] == "json_object"
    assert request_options_for_payload(payload) == {
        "max_tokens": 32768,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
    }


def test_minimax_payload_preserves_seed_without_unsupported_schema() -> None:
    payload, metadata = build_chat_payload(
        provider="dashscope-openai-compatible",
        model="MiniMax-M2.7",
        llm={"max_output_tokens": 12000},
        messages=MESSAGES,
        temperature=0.1,
        seed=23,
        structured=True,
    )

    assert payload["max_tokens"] == 12000
    assert payload["seed"] == 23
    assert "thinking" not in payload
    assert "response_format" not in payload
    assert metadata["model_family"] == "minimax"


def test_output_limit_uses_model_max_instead_of_global_12000() -> None:
    assert llm_max_output_tokens({"max_output_tokens": 65536}, "gateway", "glm-5.2") == 65536
    assert llm_max_output_tokens({"max_output_tokens": 200000}, "gateway", "glm-5.2") == 131072
    assert llm_max_output_tokens({"max_output_tokens": 65536}, "gateway", "custom-model") == 32768


def test_unstructured_call_does_not_request_json_mode() -> None:
    payload, _metadata = build_chat_payload(
        provider="gateway",
        model="glm-5.2",
        llm={},
        messages=MESSAGES,
        temperature=0.0,
        seed=7,
        structured=False,
    )

    assert "response_format" not in payload
    assert payload["thinking"] == {"type": "enabled"}


def test_only_explicit_parameter_errors_trigger_compatibility_fallback() -> None:
    assert unsupported_request_parameter(ValueError("unsupported parameter: response_format"), {"response_format", "thinking"}) == "response_format"
    assert unsupported_request_parameter(ValueError("thinking is not supported"), {"response_format", "thinking"}) == "thinking"
    assert unsupported_request_parameter(ValueError("429 Too Many Requests"), {"response_format", "thinking"}) is None
    assert unsupported_request_parameter(ValueError("invalid authentication token"), {"response_format", "thinking"}) is None


def test_parameter_fallback_removes_only_rejected_parameter() -> None:
    attempts: list[dict] = []
    downgrades: list[str] = []

    def invoke(payload: dict) -> dict:
        attempts.append(dict(payload))
        if "response_format" in payload:
            raise ValueError("unsupported parameter: response_format")
        return {"ok": True}

    response = invoke_with_parameter_fallback(
        {"model": "glm-5.2", "thinking": {"type": "enabled"}, "response_format": {"type": "json_object"}},
        invoke,
        on_downgrade=downgrades.append,
    )

    assert response == {"ok": True}
    assert len(attempts) == 2
    assert "response_format" not in attempts[1]
    assert attempts[1]["thinking"] == {"type": "enabled"}
    assert downgrades == ["response_format"]


def test_parameter_fallback_does_not_hide_rate_limit() -> None:
    def invoke(_payload: dict) -> dict:
        raise ValueError("429 Too Many Requests")

    try:
        invoke_with_parameter_fallback({"thinking": {"type": "enabled"}}, invoke)
    except ValueError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("rate limit must not be converted into a compatibility downgrade")


def test_http_error_body_is_retained_for_parameter_diagnosis() -> None:
    original = llm_client.urllib.request.urlopen
    error = urllib.error.HTTPError(
        "https://gateway.example/chat/completions",
        400,
        "Bad Request",
        {},
        io.BytesIO(b'{"error":{"message":"unsupported parameter: thinking"}}'),
    )
    llm_client.urllib.request.urlopen = lambda *_args, **_kwargs: (_ for _ in ()).throw(error)
    try:
        try:
            llm_client.http_json("https://gateway.example/chat/completions", {}, method="POST", body={"thinking": {"type": "enabled"}})
        except urllib.error.HTTPError as exc:
            assert "unsupported parameter: thinking" in str(getattr(exc, "jolt_detail", ""))
        else:
            raise AssertionError("expected HTTPError")
    finally:
        llm_client.urllib.request.urlopen = original


if __name__ == "__main__":
    test_glm_52_payload_is_gateway_compatible()
    test_minimax_payload_preserves_seed_without_unsupported_schema()
    test_output_limit_uses_model_max_instead_of_global_12000()
    test_unstructured_call_does_not_request_json_mode()
    test_only_explicit_parameter_errors_trigger_compatibility_fallback()
    test_parameter_fallback_removes_only_rejected_parameter()
    test_parameter_fallback_does_not_hide_rate_limit()
    test_http_error_body_is_retained_for_parameter_diagnosis()
    print("LLM model payload tests passed")
