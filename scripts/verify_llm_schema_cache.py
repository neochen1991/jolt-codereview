from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mr-backend" / "worker"))

from llm import client  # noqa: E402


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def llm_call(
        self,
        span_id: str,
        provider: str,
        model: str,
        prompt: str,
        status: str,
        duration_ms: int,
        input_tokens: int,
        output_tokens: int,
        request_id: str | None = None,
        messages: list[dict[str, str]] | None = None,
        response_text: str = "",
        **metadata: Any,
    ) -> None:
        self.calls.append({
            "span_id": span_id,
            "provider": provider,
            "model": model,
            "status": status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "request_id": request_id,
            "response_text": response_text,
            "metadata": metadata,
        })

    def event(self, span_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append({
            "span_id": span_id,
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
        })


def main() -> None:
    original_candidate_providers = client.candidate_providers
    original_build_prompt = client.build_prompt
    original_http_json = client.http_json
    original_read_cache = client._read_cached_llm_response
    original_write_cache = client._write_cached_llm_response
    cache: dict[str, dict[str, Any]] = {}
    http_bodies: list[dict[str, Any]] = []

    def fake_candidate_providers(_llm: dict[str, Any], required_context: int = 0) -> list[dict[str, Any]]:
        return [{
            "provider": "gateway",
            "model": "glm-5.2",
            "base_url": "https://llm.internal/v1",
            "api_key": "test-key",
        }]

    def fake_build_prompt(_agent: dict[str, Any], _files: list[Any], _skill_summary: str = "") -> tuple[str, dict[str, Any]]:
        return "Review src/App.java and return JSON findings.", {"injection_patterns": [], "redactions": []}

    def fake_http_json(
        _url: str,
        _headers: dict[str, str],
        method: str = "GET",
        body: dict[str, Any] | None = None,
        timeout_seconds: int = 120,
        stream: bool = False,
    ) -> dict[str, Any]:
        assert method == "POST"
        assert body is not None
        assert "seed" not in body
        assert body.get("thinking") == {"type": "enabled"}
        http_bodies.append(json.loads(json.dumps(body)))
        if "response_format" in body:
            raise ValueError("unsupported parameter: response_format")
        return {
            "id": "fallback-response-1",
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            "choices": [{
                "message": {
                    "content": json.dumps({"findings": [{
                            "severity": "high",
                            "confidence": 0.91,
                            "file_path": "src/App.java",
                            "line_start": 3,
                            "line_end": 3,
                            "title": "Missing validation",
                            "problem_description": "Request body is not validated.",
                            "recommendation": "Add validation.",
                            "suggested_code": "Add @Valid.",
                            "evidence": "@RequestBody payload",
                            "covered_rules": ["BE-API-001"],
                            "skipped_rules": [],
                        }]})
                }
            }],
        }

    def fake_read_cache(_config: dict[str, Any], cache_key: str, _project_id: str) -> dict[str, Any] | None:
        return cache.get(cache_key)

    def fake_write_cache(
        _config: dict[str, Any],
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
        assert project_id == "project_q02"
        assert provider == "gateway"
        assert model == "glm-5.2"
        assert schema_name == "review_findings_v3_json_object"
        assert seed == client.derive_seed("", "expert", "backend_agent", "", "")
        assert prompt
        cache[cache_key] = response

    try:
        client.candidate_providers = fake_candidate_providers
        client.build_prompt = fake_build_prompt
        client.http_json = fake_http_json
        client._read_cached_llm_response = fake_read_cache
        client._write_cached_llm_response = fake_write_cache

        config = {"_project_id": "project_q02", "llm": {"enable_response_cache": True, "enable_stream": False}}
        agent = {"agent_id": "backend_agent", "max_findings": 8}
        files = [SimpleNamespace(filename="src/App.java", patch="@@ -0,0 +1,3 @@\n+class App {}\n")]
        recorder = Recorder()

        first = client.call_llm(config, recorder, "span-1", agent, files)
        second = client.call_llm(config, recorder, "span-1", agent, files)
        live_repeat_config = {
            **config,
            "llm": {**config["llm"], "exchange_mode": "live_repeat"},
        }
        repeated_live = client.call_llm(live_repeat_config, recorder, "span-1", agent, files)

        assert len(first) == 1, first
        assert first == second, (first, second)
        assert first == repeated_live, (first, repeated_live)
        assert first[0]["covered_rules"] == ["BE-API-001"], first
        assert len(http_bodies) == 4, http_bodies
        assert "response_format" in http_bodies[0], http_bodies
        assert "response_format" not in http_bodies[1], http_bodies
        assert "response_format" in http_bodies[2], http_bodies
        assert "response_format" not in http_bodies[3], http_bodies
        assert len(cache) == 1, cache
        event_types = [event["event_type"] for event in recorder.events]
        assert "llm_parameter_downgraded" in event_types, recorder.events
        statuses = [call["status"] for call in recorder.calls]
        assert "completed" in statuses, recorder.calls
        assert "cache_hit" in statuses, recorder.calls
    finally:
        client.candidate_providers = original_candidate_providers
        client.build_prompt = original_build_prompt
        client.http_json = original_http_json
        client._read_cached_llm_response = original_read_cache
        client._write_cached_llm_response = original_write_cache

    print(json.dumps({"ok": True, "verified": "llm_schema_cache", "http_calls": len(http_bodies), "cache_entries": len(cache)}))


if __name__ == "__main__":
    main()
