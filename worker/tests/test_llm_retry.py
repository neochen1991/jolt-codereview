from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from budget import BudgetTracker
from llm.client import estimate_tokens, llm_request_timeout_seconds
from llm.retry import call_with_retry


def test_call_with_retry_succeeds_after_retry() -> None:
    calls = {"count": 0}

    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError("https://llm.example", 429, "rate limited", {}, None)
        return "ok"

    assert call_with_retry(flaky, max_retries=2, backoff_seconds=(0, 0)) == "ok"
    assert calls["count"] == 2


def test_call_with_retry_exhausts_original_exception() -> None:
    calls = {"count": 0}

    def failing() -> None:
        calls["count"] += 1
        raise TimeoutError("slow provider")

    try:
        call_with_retry(failing, max_retries=1, backoff_seconds=(0,))
    except TimeoutError as exc:
        assert "slow provider" in str(exc)
    else:
        raise AssertionError("expected TimeoutError")
    assert calls["count"] == 2


def test_estimate_tokens_counts_cjk_more_fairly_than_len_div_four() -> None:
    assert estimate_tokens("这是一个中文检视提示") > len("这是一个中文检视提示") // 4
    assert estimate_tokens("plain english prompt") >= 4


def test_timeout_defaults_by_operation() -> None:
    assert llm_request_timeout_seconds({}, "router") == 60
    assert llm_request_timeout_seconds({}, "expert") == 120
    assert llm_request_timeout_seconds({"timeouts": {"router": 12}}, "router") == 12


def test_budget_snapshot_includes_token_totals() -> None:
    budget = BudgetTracker(max_wall_seconds=0, max_llm_calls=10)
    budget.charge_llm("model-a", 123, 45)
    snapshot = budget.snapshot()
    assert snapshot["llm_calls"] == 1
    assert snapshot["acc_input_tokens"] == 123
    assert snapshot["acc_output_tokens"] == 45


if __name__ == "__main__":
    test_call_with_retry_succeeds_after_retry()
    test_call_with_retry_exhausts_original_exception()
    test_estimate_tokens_counts_cjk_more_fairly_than_len_div_four()
    test_timeout_defaults_by_operation()
    test_budget_snapshot_includes_token_totals()
