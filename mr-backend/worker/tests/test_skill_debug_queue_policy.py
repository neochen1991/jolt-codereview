from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "review_runtime.py").read_text("utf-8")
required = {
    "production-first ordering": "CASE WHEN queued.execution_kind = 'production_review' THEN 0 ELSE 1 END",
    "debug concurrency function": "project_debug_job_concurrency",
    "production queue reservation": "queued_production_count",
    "debug active job count": "active_debug_count",
}
missing = [label for label, snippet in required.items() if snippet not in source]
if missing:
    raise AssertionError("skill debug queue policy missing: " + ", ".join(missing))
