# v2 Production Auto Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Switch production Review to v2 immediately, automatically pair every successful v2 run with an identical-input v1 Shadow, and roll projects back to v1 when runtime or fully labeled quality gates fail.

**Architecture:** Deployment and project defaults select v2 and enable snapshot capture. The Worker records a durable v2/v1 pair and enqueues the v1 Shadow after production completion; pair completion drives runtime-safety evaluation and, when a dual-reviewed Gold dataset covers at least 30 distinct MRs, the existing precision/recall quality gate. All project rollback writes go through a token-protected Common Backend endpoint with audit evidence.

**Tech Stack:** TypeScript Common/MR backends, Python Review Worker, PostgreSQL, existing quality scorer and uplift gate, repository script tests.

---

### Task 1: Switch defaults and expose rollout configuration

**Files:**
- Modify: `mr-backend/worker/config.py`
- Modify: `mr-backend/src/backend/config.ts`
- Modify: `mr-backend/src/backend/types.ts`
- Modify: `mr-backend/config.example.json`
- Modify: `common-backend/src/backend/services/ProjectConfigService.ts`
- Test: `mr-backend/worker/tests/test_quality_shadow.py`
- Create: `scripts/verify-v2-production-default.mjs`
- Modify: `package.json`

**Steps:**

1. Write failing tests requiring `context_engine=v2`, capture enabled, auto baseline/rollback enabled, a 30-MR minimum, and `review_quality` as an allowed Common project setting.
2. Run `PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_quality_shadow.py && node scripts/verify-v2-production-default.mjs`; confirm failure.
3. Add normalized configuration fields and TypeScript types; change defaults and example config to v2 with validation enabled.
4. Run the focused tests and backend builds; expect PASS.
5. Commit `feat: switch production review default to v2`.

### Task 2: Automatically create and complete v2/v1 Shadow pairs

**Files:**
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/worker/quality_shadow.py`
- Modify: `mr-backend/worker/orchestration/nodes/finalize.py`
- Modify: `mr-backend/worker/tests/test_quality_shadow.py`

**Steps:**

1. Write failing tests for deterministic pair/job IDs, pair idempotency, v1-only Shadow creation after successful production v2, and pair completion after the baseline run.
2. Run `PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_quality_shadow.py`; confirm failure.
3. Add `review_quality_shadow_pairs`, enqueue helpers and finalize callbacks. Never enqueue from debug/shadow/v1 production runs, and never mutate production MR state from the baseline job.
4. Run focused Shadow, queue and Skill Debug isolation tests; expect PASS.
5. Commit `feat: auto pair v2 reviews with v1 shadow`.

### Task 3: Add audited automatic rollback control

**Files:**
- Modify: `common-backend/src/backend/routes/models.routes.ts`
- Modify: `common-backend/src/backend/services/ProjectConfigService.ts`
- Modify: `mr-backend/worker/config.py`
- Create: `mr-backend/worker/review_quality_rollback.py`
- Create: `mr-backend/worker/tests/test_review_quality_rollback.py`
- Create: `scripts/verify-review-quality-rollback-api.mjs`
- Modify: `package.json`

**Steps:**

1. Write failing tests for the internal-token requirement, v2-to-v1-only mutation, audit metadata, three consecutive production failures, and >20% failures among 10 distinct MRs.
2. Run the Python and Node verifiers; confirm failure.
3. Add the narrow Common rollback endpoint and Worker runtime-safety evaluator. Failed rollback calls persist `rollback_pending`; successful calls persist the response and trigger evidence.
4. Run focused tests and both backend builds; expect PASS.
5. Commit `feat: auto rollback unsafe v2 review rollout`.

### Task 4: Evaluate labeled real-task quality and enforce the uplift gate

**Files:**
- Create: `mr-backend/worker/review_quality_evaluator.py`
- Create: `mr-backend/worker/tests/test_review_quality_evaluator.py`
- Modify: `mr-backend/worker/orchestration/nodes/finalize.py`
- Modify: `scripts/lib/review-quality-gate.mjs`
- Modify: `evaluation/review_quality_cases/README.md`

**Steps:**

1. Write failing tests requiring two reviewer identities, adjudication reasons for disagreements, 30 distinct paired MRs, complete cost data, and the existing Recall/Precision/cross-file/high-severity/FP/cost thresholds.
2. Run evaluator tests; confirm failure.
3. Load only explicit Gold JSONL, query pair findings and costs, score v1/v2 using the existing matcher semantics, persist `provisional/verified/rollback_required`, and call the rollback client only for a fully evidenced failing gate.
4. Run evaluator and uplift gate tests; expect PASS.
5. Commit `feat: enforce labeled real-task v2 quality gate`.

### Task 5: Surface validation state and document operations

**Files:**
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `frontend/src/frontend/components/ReviewViews.tsx`
- Modify: `scripts/verify-review-context-dashboard.mjs`
- Modify: `README.md`
- Modify: `docs/plans/2026-07-13-review-quality-recall-precision-optimization-plan.md`

**Steps:**

1. Write failing API/UI verifier checks for `v2_provisional`, `v2_verified`, `rollback_pending`, pair counts, distinct MR counts and missing-evidence reasons.
2. Run the verifiers; confirm failure.
3. Extend the existing quality dashboard/API and document startup, Windows intranet paths, Gold location, rollback audit and the difference between switched and verified.
4. Run frontend/backend builds and dashboard verifiers; expect PASS.
5. Commit `feat: expose v2 real-task validation status`.

### Task 6: Apply current config and run a real MR verification

**Files:**
- Modify locally if present: `mr-backend/config.json`
- Record evidence: `docs/plans/2026-07-13-review-quality-recall-precision-optimization-plan.md`

**Steps:**

1. Update the live local MR config to v2 with automatic capture, baseline and rollback enabled.
2. Start Common and MR Backend with the configured service token, requeue the existing real MR, and run the production Worker.
3. Verify from PostgreSQL that the production run records v2 context coverage, a frozen Snapshot exists, a v1 baseline job/run exists, both share the same input hash, and production side effects originate only from the v2 job.
4. Record the exact observed scope. One MR proves the production chain only; it must remain `v2_provisional` until 30 distinct dual-reviewed MRs exist.
5. Run `npm run verify`, `git diff --check`, and inspect the worktree.
6. Commit `test: verify v2 production shadow validation`.
