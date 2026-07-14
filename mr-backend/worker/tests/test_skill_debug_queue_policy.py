from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "review_runtime.py").read_text("utf-8")
required = {
    "production-first ordering": "CASE WHEN queued.execution_kind = 'production_review' THEN 0 ELSE 1 END",
    "only supported queued kinds are claimable": "queued.execution_kind LIKE 'skill_debug_%%'",
    "debug concurrency function": "project_debug_job_concurrency",
    "production queue reservation": "queued_production_count",
    "non-production queue classification": "is_non_production_job(candidate)",
    "shared non-production concurrency": "active_non_production_count",
    "skill debug failure does not mutate MR": "if production_side_effects_allowed(job):",
}
missing = [label for label, snippet in required.items() if snippet not in source]
if missing:
    raise AssertionError("skill debug queue policy missing: " + ", ".join(missing))
