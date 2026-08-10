from __future__ import annotations

import json
import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from llm.exchange import DatabaseExchangeStore, InMemoryExchangeStore, execute_chat_exchange  # noqa: E402


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def llm_call(self, *args, **kwargs) -> None:
        self.calls.append({"args": args, "kwargs": kwargs})


def _response(content: object, response_id: str) -> dict:
    return {
        "id": response_id,
        "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8},
    }


def _run(mode: str, store: InMemoryExchangeStore, network_calls: list[str]) -> tuple[list[dict], list[dict]]:
    recorder = Recorder()
    expert_messages = [{"role": "user", "content": "review unit-a"}]
    expert = execute_chat_exchange(
        recorder=recorder,
        span_id="expert-span",
        operation="expert",
        agent_id="security_agent",
        context_unit_id="unit-a",
        checkpoint_id="cp-auth",
        context_hash="ctx-123",
        head_sha="head-abc",
        provider="test",
        model="deterministic",
        prompt="review unit-a",
        messages=expert_messages,
        temperature=0.0,
        replay_mode=mode,
        store=store,
        invoke=lambda _seed: network_calls.append("expert") or _response(
            [{"dedupe_hash": "finding-1", "severity": "high", "title": "missing authorization"}],
            "expert-1",
        ),
    )
    candidates = json.loads(expert.response["choices"][0]["message"]["content"])

    # Tool output is part of the second exchange request. A changed tool result therefore
    # produces a different request hash and cannot silently reuse an unrelated verdict.
    tool_result = {"tool": "find_callers", "result_hash": "tool-result-456", "callers": ["Api.handle"]}
    judge_messages = [
        {"role": "user", "content": "judge candidates"},
        {"role": "tool", "content": json.dumps(tool_result, sort_keys=True)},
    ]
    judge = execute_chat_exchange(
        recorder=recorder,
        span_id="judge-span",
        operation="judge",
        agent_id="finding_judge",
        context_unit_id="unit-a",
        checkpoint_id="cp-auth",
        context_hash="ctx-123",
        head_sha="head-abc",
        provider="test",
        model="deterministic",
        prompt="judge candidates",
        messages=judge_messages,
        temperature=0.0,
        replay_mode=mode,
        store=store,
        invoke=lambda _seed: network_calls.append("judge") or _response(candidates, "judge-1"),
    )
    findings = json.loads(judge.response["choices"][0]["message"]["content"])
    consolidation_messages = [{"role": "user", "content": "consolidate final findings"}]
    consolidation = execute_chat_exchange(
        recorder=recorder,
        span_id="final-consolidation-span",
        operation="final_consolidation",
        agent_id="final_finding_consolidator",
        context_unit_id="",
        checkpoint_id="",
        context_hash="ctx-123",
        head_sha="head-abc",
        provider="test",
        model="deterministic",
        prompt="consolidate final findings",
        messages=consolidation_messages,
        temperature=0.0,
        replay_mode=mode,
        store=store,
        invoke=lambda _seed: network_calls.append("final_consolidation")
        or _response({"version": "final_finding_consolidation_v1", "groups": []}, "consolidation-1"),
    )
    consolidation_result = json.loads(consolidation.response["choices"][0]["message"]["content"])
    assert consolidation_result == {"version": "final_finding_consolidation_v1", "groups": []}
    assert all(call["kwargs"]["request_hash"] for call in recorder.calls)
    assert all(call["kwargs"]["response_hash"] for call in recorder.calls)
    assert all(call["kwargs"]["seed"] is not None for call in recorder.calls)
    assert recorder.calls[0]["kwargs"]["context_hash"] == "ctx-123"
    return candidates, findings


def test_worker_record_and_exact_replay() -> None:
    store = InMemoryExchangeStore()
    network_calls: list[str] = []
    recorded = _run("record", store, network_calls)
    assert network_calls == ["expert", "judge", "final_consolidation"]
    replayed = _run("replay", store, network_calls)
    assert network_calls == ["expert", "judge", "final_consolidation"]
    assert recorded == replayed


def test_orchestration_nodes_do_not_build_chat_endpoints() -> None:
    files = [
        WORKER_ROOT / "orchestration" / "nodes" / "critic_pass.py",
        WORKER_ROOT / "orchestration" / "nodes" / "run_targeted_debate.py",
        WORKER_ROOT / "orchestration" / "deepagents_runner.py",
        WORKER_ROOT / "orchestration" / "quality" / "final_consolidation.py",
    ]
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "chat_completions_url" not in source, path
        assert "chat/completions" not in source, path
        assert "execute_chat_exchange" in source, path


class _Cursor:
    def fetchone(self):
        return None


class _Connection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, statement: str, params: tuple = ()) -> _Cursor:
        self.statements.append((statement, params))
        return _Cursor()


def test_database_exchange_store_uses_timestamp_cast_and_run_scoped_retention() -> None:
    conn = _Connection()
    store = DatabaseExchangeStore(conn, review_run_id="run-1", ttl_days=7)
    assert store.get("missing") is None
    query, params = conn.statements[-1]
    assert "NULLIF(expires_at, '')::timestamptz" in query
    assert params == ("missing",)

    response = _response([], "response-1")
    recorded = Recorder()
    result = execute_chat_exchange(
        recorder=recorded,
        span_id="span",
        operation="expert",
        agent_id="security_agent",
        context_unit_id="unit-a",
        checkpoint_id="cp-auth",
        context_hash="ctx-123",
        head_sha="head-abc",
        provider="test",
        model="deterministic",
        prompt="review unit-a",
        messages=[{"role": "user", "content": "review unit-a"}],
        temperature=0.0,
        replay_mode="record",
        store=store,
        invoke=lambda _seed: response,
    )
    assert result.response == response
    insert, values = conn.statements[-1]
    assert "review_run_id, expires_at" in insert
    assert values[-2] == "run-1"
    assert values[-1]


def test_worker_schema_creates_exchange_retention_columns_before_cleanup() -> None:
    source = (WORKER_ROOT / "review_runtime.py").read_text(encoding="utf-8")
    table_start = source.index("CREATE TABLE IF NOT EXISTS llm_exchange_records")
    table_end = source.index(");", table_start)
    table_sql = source[table_start:table_end]
    assert "review_run_id TEXT" in table_sql
    assert "expires_at TEXT" in table_sql
    assert "NULLIF(expires_at, '')::timestamptz <= CURRENT_TIMESTAMP" in source


if __name__ == "__main__":
    test_worker_record_and_exact_replay()
    test_orchestration_nodes_do_not_build_chat_endpoints()
    test_database_exchange_store_uses_timestamp_cast_and_run_scoped_retention()
    test_worker_schema_creates_exchange_retention_columns_before_cleanup()
    print("worker exact replay tests passed")
