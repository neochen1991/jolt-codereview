# Review Quality Shadow Job Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an auditable native Shadow A/B job path that replays one frozen production Review input through the same Worker graph with v1/v2 context engines and zero production side effects.

**Architecture:** Store a bounded, hash-verified input snapshot when production Shadow capture is enabled. Enqueue `quality_shadow_v1` and `quality_shadow_v2` jobs that carry only the snapshot reference and engine override; the existing Worker graph loads the frozen input and persists normal run artifacts while all production mutations remain disabled. A PostgreSQL-backed case runner waits for both jobs and scores their findings against the supplied Gold records.

**Tech Stack:** Python 3, psycopg/PostgreSQL, existing Worker orchestration graph, Node.js quality aggregation scripts, unittest-style repository tests.

---

### Task 1: Non-production job classification and side-effect isolation

**Files:**
- Modify: `mr-backend/worker/skill_debug.py`
- Modify: `mr-backend/worker/review_runtime.py`
- Test: `mr-backend/worker/tests/test_skill_debug_isolation.py`
- Test: `mr-backend/worker/tests/test_skill_debug_queue_policy.py`

**Step 1: Write the failing tests**

Add assertions that `quality_shadow_v1` and `quality_shadow_v2` are Shadow and non-production jobs, cannot publish production side effects, do not update `merge_requests.review_status`, and are lower priority than production jobs.

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_skill_debug_isolation.py && PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_skill_debug_queue_policy.py`

Expected: FAIL because Shadow kinds are not classified or isolated.

**Step 3: Write minimal implementation**

Add `is_shadow_job()`, `is_non_production_job()` and `shadow_context_engine()` helpers. Make `production_side_effects_allowed()` false for debug and Shadow jobs. Generalize Worker status/error branches so only production jobs mutate MR status, while debug-only session updates stay debug-only.

**Step 4: Run tests to verify they pass**

Run the command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/worker/skill_debug.py mr-backend/worker/review_runtime.py mr-backend/worker/tests/test_skill_debug_isolation.py mr-backend/worker/tests/test_skill_debug_queue_policy.py
git commit -m "feat: isolate review quality shadow jobs"
```

### Task 2: Frozen production input capture and Shadow replay

**Files:**
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/worker/orchestration/nodes/fetch_mr.py`
- Create: `mr-backend/worker/quality_shadow.py`
- Create: `mr-backend/worker/tests/test_quality_shadow.py`

**Step 1: Write the failing tests**

Cover canonical SHA256 generation, TTL validation, head-SHA validation, engine-only config override, snapshot capture only when `review_quality.quality_shadow_mode=true`, and loading identical input for v1/v2.

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_quality_shadow.py`

Expected: FAIL because the Shadow snapshot module and schema do not exist.

**Step 3: Write minimal implementation**

Create `review_input_snapshots` with source job/run, MR, head SHA, canonical artifact JSON/SHA256, expiry and timestamps. Capture the fetched changed-file records and source contents only when Shadow mode is enabled. Load the referenced snapshot for Shadow jobs, reject missing/expired/hash-mismatched data, and override only `review_quality.context_engine` from the execution kind.

**Step 4: Run tests and backend build**

Run: `PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_quality_shadow.py && npm --prefix mr-backend run build`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/db/migrations.ts mr-backend/worker/review_runtime.py mr-backend/worker/orchestration/nodes/fetch_mr.py mr-backend/worker/quality_shadow.py mr-backend/worker/tests/test_quality_shadow.py
git commit -m "feat: capture and replay frozen review inputs"
```

### Task 3: Native PostgreSQL Shadow case runner

**Files:**
- Create: `scripts/run_review_quality_shadow_case.py`
- Create: `scripts/test_run_review_quality_shadow_case.py`
- Modify: `scripts/run-review-quality-shadow.mjs`
- Modify: `scripts/test-review-quality-shadow.mjs`
- Modify: `package.json`

**Step 1: Write the failing tests**

Test deterministic job creation, terminal-state polling, v1/v2 snapshot SHA equality, finding export, Gold matching via `scripts/score_real_pr_reviews.py`, token/duration extraction, and hard failure on any publish attempt or invalid terminal state.

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=mr-backend/worker:scripts python3 scripts/test_run_review_quality_shadow_case.py`

Expected: FAIL because the native runner is missing.

**Step 3: Write minimal implementation**

Read one case from stdin, connect through `DATABASE_URL`, validate the referenced frozen snapshot, enqueue the requested `quality_shadow_v1/v2` job, wait with a bounded timeout, query its run/findings/LLM usage, evaluate against inline Gold records, and emit the aggregation row. Update the Node runner to use explicit execution kinds and reject mismatched returned engine or snapshot SHA.

**Step 4: Run focused verification**

Run: `PYTHONPATH=mr-backend/worker:scripts python3 scripts/test_run_review_quality_shadow_case.py && npm run verify:review-quality-shadow`

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/run_review_quality_shadow_case.py scripts/test_run_review_quality_shadow_case.py scripts/run-review-quality-shadow.mjs scripts/test-review-quality-shadow.mjs package.json
git commit -m "feat: run native review quality shadow cases"
```

### Task 4: Operations documentation and full regression

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/2026-07-13-review-quality-recall-precision-optimization-plan.md`
- Modify: `docs/plans/2026-07-13-review-quality-shadow-job-design.md`

**Step 1: Document exact operation**

Document capture opt-in, retention/privacy implications, Windows intranet commands, Worker prerequisite, snapshot export/query, native runner command, timeout/failure behavior, stage sample minimum and rollback.

**Step 2: Record current evidence honestly**

Keep production v1 as default and record that the current database has one production MR and zero valid 30-MR A/B cohorts. Do not count fixture or repeated MR runs as production evidence.

**Step 3: Run full verification**

Run: `npm run verify`

Expected: PASS, including Shadow isolation, replay and quality gates.

**Step 4: Inspect repository state**

Run: `git diff --check && git status --short`

Expected: only intended documentation changes before commit.

**Step 5: Commit**

```bash
git add README.md docs/plans/2026-07-13-review-quality-recall-precision-optimization-plan.md docs/plans/2026-07-13-review-quality-shadow-job-design.md
git commit -m "docs: document native review quality shadow rollout"
```

### Task 5: External production evidence gate

**Files:**
- Modify after evidence exists: `docs/plans/2026-07-13-review-quality-recall-precision-optimization-plan.md`

**Step 1: Obtain independent Gold labels**

Two reviewers independently label the expanded real-MR set and resolve disagreements with recorded reasons.

**Step 2: Accumulate valid cohorts**

Run each rollout stage on at least 30 distinct real MRs using frozen input and the native Shadow runner.

**Step 3: Run final quality gate**

Run: `npm run verify:real-prs && node scripts/verify-review-quality-uplift.mjs --baseline <v1-report> --candidate <v2-report>`

Expected: Recall, cross-file Recall and Critical/High Recall improve; Precision, Negative FP, P95 Token and P95 duration stay within approved limits.

**Step 4: Switch only after evidence passes**

Change the default context engine to v2 only after every stage passes. Otherwise keep v1 and record the failed metric and rollback.
