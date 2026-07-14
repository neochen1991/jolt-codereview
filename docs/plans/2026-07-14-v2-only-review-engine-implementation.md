# V2-only Review Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the executable Review Context Engine v1, v1/v2 Shadow comparison, and rollback-to-v1 paths so every production and Skill Debug review uses v2 only, then assess two new real reviews.

**Architecture:** Context Planner v2 becomes unconditional inside the Worker. Configuration, API and UI expose only v2 observability and single-engine quality status; protocol markers such as `finding_v1` remain unchanged for stored-data compatibility. Legacy Shadow/rollback tables are not dropped from existing databases, but no runtime code creates, writes or reads them.

**Tech Stack:** Python Worker/LangGraph, Node.js/TypeScript backends, React frontend, PostgreSQL, repository verification scripts, Playwright browser checks.

---

### Task 1: Add a v2-only architecture guard

**Files:**
- Create: `scripts/verify-v2-only-review-engine.mjs`
- Modify: `package.json`

**Step 1: Write the failing test**

Create a verifier that reads the relevant Worker, backend, frontend, package and README files. It must fail while any of these remain:

```text
context_engine == "v1"
quality_shadow_v1
quality_shadow_v2
enqueue_v1_shadow_pair
evaluate_and_request_runtime_rollback
v1_rolled_back
rollback_pending
verify:review-quality-shadow
verify:review-quality-rollback
```

The verifier must explicitly allow persisted protocol names such as `finding_v1`, `review_input_v1`, `skill_debug_validity_v1` and Skill version values.

**Step 2: Run test to verify it fails**

Run: `node scripts/verify-v2-only-review-engine.mjs`

Expected: FAIL and list concrete legacy Review Engine paths.

**Step 3: Register the verifier**

Add `verify:v2-only-review-engine` to `package.json`; do not add it to the full chain until the removal tasks pass.

**Step 4: Commit the red test**

```bash
git add scripts/verify-v2-only-review-engine.mjs package.json
git commit -m "test: require v2-only review engine"
```

### Task 2: Make Worker context construction unconditionally v2

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/build_context.py`
- Modify: `mr-backend/worker/context/context_metrics.py`
- Modify: `mr-backend/worker/config.py`
- Modify: `mr-backend/worker/tests/test_context_planner.py`
- Modify: `mr-backend/worker/tests/test_context_metrics.py`
- Delete: v1-engine-only assertions from `mr-backend/worker/tests/test_quality_shadow.py`

**Step 1: Add failing behavior tests**

Assert that legacy `review_quality.context_engine="v1"` input cannot suppress ContextUnits and that Context Health always reports `v2`.

**Step 2: Verify RED**

Run:

```bash
PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_context_planner.py
PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_context_metrics.py
```

Expected: the legacy override test fails because the current branch still empties ContextUnits.

**Step 3: Implement the single path**

- Remove the `context_engine` config read and the `if context_engine == "v1"` branch.
- Remove `context_engine`, Shadow, rollback and A/B fields from Python defaults and normalization.
- Keep `semantic_index` and `llm_replay` as supported v2 controls.
- Make context metrics derive `context_engine="v2"` without inspecting config.

**Step 4: Verify GREEN**

Run the two tests above plus `npm run verify:review-context-dashboard`.

**Step 5: Commit**

```bash
git add mr-backend/worker/orchestration/nodes/build_context.py mr-backend/worker/context/context_metrics.py mr-backend/worker/config.py mr-backend/worker/tests
git commit -m "refactor: make v2 the only context engine"
```

### Task 3: Remove Worker Shadow and rollback execution

**Files:**
- Delete: `mr-backend/worker/quality_shadow.py`
- Delete: `mr-backend/worker/review_quality_rollback.py`
- Delete: `mr-backend/worker/review_quality_evaluator.py`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/worker/orchestration/nodes/finalize.py`
- Modify: `mr-backend/worker/skill_debug.py`
- Delete: `mr-backend/worker/tests/test_quality_shadow.py`
- Delete: `mr-backend/worker/tests/test_review_quality_rollback.py`
- Delete: `mr-backend/worker/tests/test_review_quality_evaluator.py`
- Modify: `mr-backend/worker/tests/test_skill_debug_isolation.py`

**Step 1: Add failing production-job tests**

Assert that a completed production review performs no insert/update against `review_quality_shadow_pairs` or `review_quality_rollback_events`, and that `quality_shadow_*` is no longer classified as a valid non-production job.

**Step 2: Verify RED**

Run the focused Worker tests and confirm existing enqueue/rollback behavior makes them fail.

**Step 3: Remove runtime behavior**

- Remove Shadow/rollback imports, job controls, input snapshot capture and completion callbacks.
- Remove Shadow-specific queue selection and error handling.
- Keep Skill Debug side-effect isolation independent of Shadow.
- Remove Worker-side creation of the two legacy tables; do not issue `DROP TABLE`.

**Step 4: Verify GREEN**

Run focused Worker tests and `PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_review_control.py`.

**Step 5: Commit**

```bash
git add -A mr-backend/worker
git commit -m "refactor: remove v1 shadow and rollback runtime"
```

### Task 4: Remove backend configuration and API dual-engine surfaces

**Files:**
- Modify: `mr-backend/src/backend/config.ts`
- Modify: `mr-backend/src/backend/types.ts`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Modify: `common-backend/src/backend/routes/models.routes.ts`
- Modify: `common-backend/src/backend/services/ProjectConfigService.ts`
- Modify: `mr-backend/config.example.json`
- Modify: `config.example.json`

**Step 1: Extend the v2-only verifier**

Require backend config types to expose only `semantic_index`, `llm_replay` and optional absolute v2 quality thresholds. Require Review API to avoid querying Shadow/rollback tables.

**Step 2: Verify RED**

Run: `npm run verify:v2-only-review-engine`

Expected: FAIL on TypeScript config, API queries and Common rollback endpoint.

**Step 3: Implement backend cleanup**

- Remove dual-engine fields from defaults/types/examples.
- Delete the Common Backend automatic rollback route/service method.
- Remove fresh-install migrations for Shadow/rollback tables while leaving existing deployed tables untouched.
- Replace `v2_validation` with `v2_quality_status` derived from current v2 Run feedback: `v2_unlabeled`, `v2_evaluating`, `v2_validated`.
- Return labeled count and precision only; do not claim Recall without Gold labels.

**Step 4: Verify builds and API contracts**

Run:

```bash
npm --prefix common-backend run build
npm --prefix mr-backend run build
npm run verify:review-context-dashboard
```

**Step 5: Commit**

```bash
git add common-backend mr-backend/src mr-backend/config.example.json config.example.json
git commit -m "refactor: expose only v2 review configuration"
```

### Task 5: Simplify the quality dashboard to single-engine metrics

**Files:**
- Modify: `frontend/src/frontend/components/ReviewViews.tsx`
- Modify: `frontend/src/frontend/shared.ts`
- Modify: `scripts/verify-review-context-dashboard.mjs`

**Step 1: Write failing UI contract checks**

Require the dashboard to show v2 status, labeled count, feedback precision, Context Health, Candidate Funnel, Checkpoints and reproducibility. Forbid Pair count, v1 baseline, rollback state and “相对 v1 提升” wording.

**Step 2: Verify RED**

Run: `npm run verify:review-context-dashboard`

Expected: FAIL on the current Pair/rollback labels.

**Step 3: Implement UI cleanup**

Render `v2_quality_status` and retain the existing evidence-oriented metrics. Empty labels remain visibly `v2_unlabeled` rather than success.

**Step 4: Verify GREEN**

Run:

```bash
npm run verify:review-context-dashboard
npm --prefix frontend run build
```

**Step 5: Commit**

```bash
git add frontend scripts/verify-review-context-dashboard.mjs
git commit -m "refactor: show single-engine v2 quality status"
```

### Task 6: Delete obsolete A/B scripts and update documentation

**Files:**
- Delete: `scripts/run-review-quality-shadow.mjs`
- Delete: `scripts/run_review_quality_shadow_case.py`
- Delete: `scripts/test-review-quality-shadow.mjs`
- Delete: `scripts/test_run_review_quality_shadow_case.py`
- Delete: `scripts/verify-review-quality-rollback-api.mjs`
- Delete: `scripts/verify-review-quality-uplift.mjs`
- Delete: `scripts/test-review-quality-uplift.mjs`
- Delete: Shadow/uplift fixtures under `scripts/fixtures/`
- Modify: `package.json`
- Modify: `README.md`
- Modify: `docs/plans/2026-07-13-review-quality-recall-precision-optimization-plan.md`

**Step 1: Verify the v2-only guard still fails**

Run: `npm run verify:v2-only-review-engine`

Expected: FAIL with remaining script/doc references.

**Step 2: Remove obsolete files and commands**

Delete only Review Engine A/B artifacts. Keep generic Gold evaluation, real-PR evaluation, replay and Skill validation tooling.

**Step 3: Rewrite startup and quality docs**

Document that v2 is the only engine, old fields are ignored, no v1 rollback exists, and operational recovery is restart/retry/stop rather than engine downgrade.

**Step 4: Verify GREEN**

Run:

```bash
npm run verify:v2-only-review-engine
npm run verify:review-quality-v2
git diff --check
```

**Step 5: Commit**

```bash
git add -A
git commit -m "docs: remove v1 review engine workflow"
```

### Task 7: Full verification and runtime restart

**Files:** No source changes expected.

**Step 1: Run full verification**

Run: `npm run verify`

Expected: PASS with no Shadow/rollback/A/B commands in the chain.

**Step 2: Verify repository state**

Run:

```bash
git diff --check
git status --short --branch
```

**Step 3: Restart Worker**

Stop the existing Worker only after any pre-change Review is terminal. Start a single new Worker from the committed v2-only code and confirm idle/claim logs.

### Task 8: Run and assess two new real reviews

**Files:**
- Create: `docs/validation/2026-07-14-v2-only-real-review-quality.md`

**Step 1: Select two different real MRs**

Choose one implementation/bug-fix MR and one dependency/configuration MR. Record their IDs and Head SHAs. Do not count a task started before the v2-only Worker restart.

**Step 2: Run the first production review**

Wait for terminal status. Capture Context Health, agents, LLM calls, candidates, final findings, rejection reasons, token usage, duration and truncation.

**Step 3: Inspect quality manually**

Read the MR diff and relevant source context. Classify each final Finding as supported, false positive or uncertain; list obvious risks searched for and whether they were found.

**Step 4: Run and inspect the second production review**

Repeat the same evidence capture and manual classification.

**Step 5: Fix any observed quality defect**

For each concrete false positive or missed detectable defect, first add a failing regression test, implement the smallest generic fix, rerun the affected Review or replay the exact evidence path, and rerun the full verification set.

**Step 6: Write the report**

The report must separate measured facts from inference and must not claim statistical Recall/Precision improvement from two unlabeled samples.

**Step 7: Browser verification**

Use Playwright to confirm both runs and the v2-only quality dashboard are visible with no v1/Pair/rollback UI.

**Step 8: Final commit**

```bash
git add docs/validation/2026-07-14-v2-only-real-review-quality.md
git commit -m "test: assess v2-only real review quality"
```
