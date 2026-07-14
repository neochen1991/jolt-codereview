from __future__ import annotations

import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from review_control import ReviewJobInterrupted, ensure_review_job_active  # noqa: E402


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, status: str | None):
        self.status = status

    def execute(self, sql: str, params: tuple[str]):
        assert "SELECT status FROM review_jobs" in sql
        assert params == ("job_1",)
        return _Cursor(None if self.status is None else {"status": self.status})


def test_active_review_job_is_allowed_to_continue() -> None:
    ensure_review_job_active(_Connection("reviewing"), "job_1")


def test_cancelled_review_job_aborts_worker_without_retry() -> None:
    try:
        ensure_review_job_active(_Connection("cancelled"), "job_1")
        raise AssertionError("cancelled job should interrupt the worker")
    except ReviewJobInterrupted as exc:
        assert exc.status == "cancelled"
        assert str(exc) == "review_job_cancelled"


def test_paused_or_deleted_review_job_also_aborts_current_work() -> None:
    for status, expected in (("paused", "paused"), (None, "missing")):
        try:
            ensure_review_job_active(_Connection(status), "job_1")
            raise AssertionError(f"{expected} job should interrupt the worker")
        except ReviewJobInterrupted as exc:
            assert exc.status == expected


def test_review_runtime_wires_cancellation_into_graph_and_context_units() -> None:
    runtime_source = (WORKER_ROOT / "review_runtime.py").read_text(encoding="utf-8")
    experts_source = (WORKER_ROOT / "orchestration" / "nodes" / "run_experts.py").read_text(encoding="utf-8")

    assert "graph_nodes = [(name, guarded(node)) for name, node in graph_nodes]" in runtime_source
    assert "if isinstance(exc, ReviewJobInterrupted):" in runtime_source
    assert "ensure_active=ensure_active" in experts_source


if __name__ == "__main__":
    test_active_review_job_is_allowed_to_continue()
    test_cancelled_review_job_aborts_worker_without_retry()
    test_paused_or_deleted_review_job_also_aborts_current_work()
    test_review_runtime_wires_cancellation_into_graph_and_context_units()
    print("review control tests passed")
