# Isolated Skill Debug Sessions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver administrator-only, reproducible Skill debugging with draft snapshots, production-route verification, targeted A/B comparison, isolated side effects, quotas, cancellation, safe logs, history, export, and browser verification.

**Architecture:** Add first-class `skill_debug_sessions` and classify every review job by execution kind. Debug jobs consume the existing production Review Worker Graph with a frozen execution snapshot, while a shared side-effect policy prevents them from mutating MR production state, finding history, learning, or publishable results. Targeted mode creates baseline/candidate jobs; production-route mode creates a candidate job without routing overrides.

**Tech Stack:** PostgreSQL, TypeScript/Node HTTP routes, Python Review Worker, React, existing audit/config/cleanup infrastructure, Node and Python verification scripts.

---

### Task 1: Turn the design into failing behavioral contracts

**Files:**
- Modify: `scripts/verify-skill-debug-workbench.mjs`
- Create: `mr-backend/worker/tests/test_skill_debug_isolation.py`
- Modify: `package.json`

**Step 1: Extend the static contract verifier**

Require the session table, `execution_kind`, six session APIs, `project_admin`, debug publish protection by finding ownership, snapshot hash, baseline/candidate comparison, quota/cancel/timeout markers, UI history and export controls.

**Step 2: Write worker unit tests**

Add tests for:

```python
def test_debug_side_effect_policy_disables_production_mutations(): ...
def test_production_side_effect_policy_keeps_production_mutations(): ...
def test_targeted_baseline_removes_only_target_skill(): ...
def test_targeted_candidate_keeps_target_skill(): ...
def test_production_route_does_not_override_agents(): ...
def test_debug_snapshot_redacts_secret_fields(): ...
```

**Step 3: Run tests and verify RED**

Run:

```bash
npm run verify:skill-debug-workbench
PYTHONPATH=mr-backend/worker python3 -m pytest mr-backend/worker/tests/test_skill_debug_isolation.py -q
```

Expected: failures for missing session model, side-effect policy and snapshot helpers.

**Step 4: Commit the failing contracts**

```bash
git add scripts/verify-skill-debug-workbench.mjs mr-backend/worker/tests/test_skill_debug_isolation.py package.json
git commit -m "test: define isolated skill debug contracts"
```

### Task 2: Add isolated session and job persistence

**Files:**
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Create: `mr-backend/src/backend/repositories/SkillDebugSessionRepository.ts`
- Modify: `mr-backend/src/backend/repositories/ReviewJobRepository.ts`
- Modify: `mr-backend/src/backend/services/ReviewQueueService.ts`

**Step 1: Add migration assertions to the failing verifier**

Require:

```sql
review_jobs.execution_kind TEXT NOT NULL DEFAULT 'production_review'
review_jobs.debug_session_id TEXT
review_jobs.debug_variant TEXT
skill_debug_sessions (... snapshot_json, snapshot_sha256, candidate_job_id, baseline_job_id ...)
```

Use a partial unique index for production jobs only:

```sql
CREATE UNIQUE INDEX ... ON review_jobs(merge_request_id, head_sha)
WHERE execution_kind = 'production_review';
```

Drop the old two-column unique constraint safely by discovering its PostgreSQL constraint name.

**Step 2: Run the focused verifier and confirm RED**

Expected: missing columns/table/repository methods.

**Step 3: Implement repositories**

Add methods to create/update/find/list/cancel sessions. Add `enqueueDebug()` which always inserts a new job. Keep `enqueueOrReset()` limited to `production_review` and make all production lookup methods filter that kind.

**Step 4: Run focused verifier and backend build**

```bash
npm run verify:skill-debug-workbench
npm --prefix mr-backend run build
```

**Step 5: Commit**

```bash
git add mr-backend/src/backend/db/migrations.ts mr-backend/src/backend/repositories/SkillDebugSessionRepository.ts mr-backend/src/backend/repositories/ReviewJobRepository.ts mr-backend/src/backend/services/ReviewQueueService.ts
git commit -m "feat: isolate skill debug session persistence"
```

### Task 3: Build immutable draft-capable snapshots

**Files:**
- Create: `mr-backend/src/backend/services/SkillDebugSnapshotService.ts`
- Modify: `mr-backend/src/backend/repositories/RuleDocumentRepository.ts`
- Modify: `mr-backend/src/backend/routes/rules.routes.ts`
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Test: `scripts/verify-skill-debug-workbench.mjs`

**Step 1: Add failing snapshot tests**

Test that a draft Skill can be selected, assets are copied into the session snapshot, SHA256 is deterministic, and secret-bearing fields become credential references or `<redacted>`.

**Step 2: Run and verify RED**

Expected: snapshot service is absent.

**Step 3: Implement minimal snapshot service**

The service reads server-side project data and returns:

```ts
{ version: "skill_debug_snapshot_v1", mr, skill, assets, agent, bindings,
  llmPolicy, dataPolicy, queuePolicy, contract: "production_review_pipeline_v1" }
```

Compute SHA256 over stable-key JSON. Never accept arbitrary snapshot JSON from the client.

**Step 4: Preserve draft lifecycle**

Allow `draft`, `reviewed`, `active`, `archived`; production loaders continue selecting active enabled bindings only. Add a project-admin activation endpoint that audits the version/hash and surfaces the most recent debug result without requiring it as a hard gate.

**Step 5: Verify and commit**

```bash
npm run verify:skill-debug-workbench
npm --prefix mr-backend run build
git add mr-backend/src/backend/services/SkillDebugSnapshotService.ts mr-backend/src/backend/repositories/RuleDocumentRepository.ts mr-backend/src/backend/routes/rules.routes.ts mr-backend/src/backend/db/migrations.ts scripts/verify-skill-debug-workbench.mjs
git commit -m "feat: snapshot draft skills for reproducible debugging"
```

### Task 4: Replace legacy debug routes with administrator-only session APIs

**Files:**
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `mr-backend/src/backend/routes/context.ts`
- Modify: `mr-backend/src/backend/routes/mr-review.routes.ts`
- Test: `scripts/verify-skill-debug-workbench.mjs`

**Step 1: Write failing route/permission assertions**

Require all session APIs to call:

```ts
ensureProjectRole(projectId, actorId, "project_admin")
```

Require creation, list, detail, cancel, rerun and export routes. Keep legacy job detail read-only and administrator-only during migration.

**Step 2: Run and verify RED**

Expected: session routes absent and old routes still use reviewer/read access.

**Step 3: Implement create/list/detail**

Creation validates MR ownership, resolves the selected Skill version server-side, freezes a snapshot and enqueues:

- production route: candidate only;
- targeted: baseline and candidate with the same snapshot SHA and distinct variants.

Return the session ID and stable job IDs immediately.

**Step 4: Implement cancel/rerun/export**

Cancellation marks queued/running jobs and session status. Rerun creates a new session from the prior frozen inputs. Export returns recursively redacted JSON and writes an audit event.

**Step 5: Verify and commit**

```bash
npm run verify:skill-debug-workbench
npm --prefix mr-backend run build
git add mr-backend/src/backend/routes/review.routes.ts mr-backend/src/backend/routes/context.ts mr-backend/src/backend/routes/mr-review.routes.ts scripts/verify-skill-debug-workbench.mjs
git commit -m "feat: add administrator skill debug session APIs"
```

### Task 5: Enforce quotas, timeout and stable session polling

**Files:**
- Create: `mr-backend/src/backend/services/SkillDebugPolicyService.ts`
- Modify: `mr-backend/src/backend/config.ts`
- Modify: `mr-backend/src/backend/types.ts`
- Modify: `mr-backend/config.example.json`
- Modify: `README.md`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`

**Step 1: Write failing policy tests/assertions**

Cover project/user concurrency, daily sessions, daily tokens, maximum duration and retention days. Verify detail lookup uses session-linked job/run IDs, never `ORDER BY latest run` on a reused job.

**Step 2: Verify RED**

Expected: missing `skill_debug_policy` config and enforcement.

**Step 3: Implement policy defaults**

Add conservative defaults such as project concurrency 2, user concurrency 1, daily sessions 20, duration 30 minutes and retention 14 days. Quota rejection returns 429 with the exceeded limit.

**Step 4: Document config**

Document Windows/intranet-safe JSON configuration and clarify that credentials remain environment references.

**Step 5: Verify and commit**

```bash
npm run verify:skill-debug-workbench
npm --prefix mr-backend run build
git add mr-backend/src/backend/services/SkillDebugPolicyService.ts mr-backend/src/backend/config.ts mr-backend/src/backend/types.ts mr-backend/config.example.json README.md mr-backend/src/backend/routes/review.routes.ts
git commit -m "feat: govern skill debug quotas and retention"
```

### Task 6: Apply frozen execution context in the production Worker Graph

**Files:**
- Create: `mr-backend/worker/skill_debug.py`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/worker/orchestration/nodes/route_agents.py`
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Test: `mr-backend/worker/tests/test_skill_debug_isolation.py`

**Step 1: Run existing worker tests and retain RED evidence**

The new isolation tests must still fail while existing routing tests pass.

**Step 2: Implement execution context helpers**

Provide:

```python
is_debug_job(job)
debug_variant(job)
production_side_effects_allowed(job)
apply_debug_snapshot(project_config, agent_configs, snapshot, variant)
check_debug_cancelled_or_timed_out(conn, job)
```

Baseline removes only the target Skill from the frozen target Agent. Candidate retains it. Production-route never changes selected agents; targeted baseline/candidate both append the same target Agent after production routing.

**Step 3: Validate MR head**

After fetch, compare the fetched/source head with the session SHA. Mark the session `stale_head` and stop before expert execution when it differs.

**Step 4: Add node-boundary cancellation checks**

Use the existing graph invocation wrapper so both baseline and candidate stop consistently without adding a second graph.

**Step 5: Run tests and commit**

```bash
PYTHONPATH=mr-backend/worker python3 -m pytest mr-backend/worker/tests/test_skill_debug_mode.py mr-backend/worker/tests/test_skill_debug_isolation.py -q
npm run verify:skill-debug-workbench
git add mr-backend/worker/skill_debug.py mr-backend/worker/review_runtime.py mr-backend/worker/orchestration/nodes/route_agents.py mr-backend/worker/orchestration/nodes/run_experts.py mr-backend/worker/tests/test_skill_debug_isolation.py
git commit -m "feat: execute frozen skill debug snapshots in production graph"
```

### Task 7: Isolate every production side effect and publish path

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/choose_effort.py`
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Modify: `mr-backend/worker/orchestration/nodes/verify_findings.py`
- Modify: `mr-backend/worker/orchestration/nodes/finalize.py`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `mr-backend/src/backend/services/FeedbackLearningService.ts`
- Test: `mr-backend/worker/tests/test_skill_debug_isolation.py`

**Step 1: Add failing side-effect regression tests**

Test that Debug finalize does not update MR status or `mr_finding_history`, while production finalize still does. Add route assertion that publish checks finding -> run -> job execution kind.

**Step 2: Verify RED**

Expected: current finalize and intermediate nodes mutate MR state.

**Step 3: Guard shared side effects**

Keep job/run/session state writes. Wrap MR status, incremental history and learning/quality aggregation behind `production_side_effects_allowed(job)`.

**Step 4: Fix all formal-result queries**

Add `execution_kind = 'production_review'` to latest-run, incremental-context, summary, metrics and feedback-learning queries where Debug data must be excluded.

**Step 5: Replace publish guard**

Reject selected findings whose owning job is not `production_review`, regardless of MR latest job.

**Step 6: Run tests and commit**

```bash
PYTHONPATH=mr-backend/worker python3 -m pytest mr-backend/worker/tests/test_skill_debug_isolation.py -q
npm run verify:skill-debug-workbench
npm --prefix mr-backend run build
git add mr-backend/worker/orchestration/nodes/choose_effort.py mr-backend/worker/orchestration/nodes/run_experts.py mr-backend/worker/orchestration/nodes/verify_findings.py mr-backend/worker/orchestration/nodes/finalize.py mr-backend/worker/review_runtime.py mr-backend/src/backend/routes/review.routes.ts mr-backend/src/backend/services/FeedbackLearningService.ts
git commit -m "fix: prevent skill debug side effects from reaching reviews"
```

### Task 8: Aggregate diagnostics, A/B comparison and safe logs

**Files:**
- Create: `mr-backend/src/backend/services/SkillDebugDiagnosticService.ts`
- Create: `mr-backend/src/backend/services/SensitiveDataRedactionService.ts`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `mr-backend/worker/file_logger.py`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/src/backend/services/RuntimeFileCleanupService.ts`
- Test: `scripts/verify-skill-debug-workbench.mjs`

**Step 1: Write failing diagnostic assertions**

Require loading, routing, checkpoints, LLM/tool success, findings, consistency evidence and A/B diff. Require recursive key/value redaction and retention cleanup.

**Step 2: Verify RED**

Expected: raw job detail exists but structured diagnostics/comparison do not.

**Step 3: Implement diagnostic aggregation**

Derive findings added/removed/unchanged using stable dedupe hashes. Attribute target Skill results through `skill_key` and checkpoint trace. Report “not executed” instead of success when production routing omits the target Agent.

**Step 4: Implement recursive redaction and retention**

Redact authorization, passwords, tokens, API keys, common token patterns and configured project patterns. Keep prompt hashes by default. Extend cleanup to expired debug exports/logs and session retention.

**Step 5: Verify and commit**

```bash
npm run verify:skill-debug-workbench
npm run verify:runtime-cleanup
npm --prefix mr-backend run build
git add mr-backend/src/backend/services/SkillDebugDiagnosticService.ts mr-backend/src/backend/services/SensitiveDataRedactionService.ts mr-backend/src/backend/routes/review.routes.ts mr-backend/worker/file_logger.py mr-backend/worker/review_runtime.py mr-backend/src/backend/services/RuntimeFileCleanupService.ts
git commit -m "feat: add safe skill debug diagnostics and comparisons"
```

### Task 9: Build the complete administrator workbench

**Files:**
- Modify: `frontend/src/frontend/components/ConfigViews.tsx`
- Modify: `frontend/src/frontend/shared.ts`
- Modify: `frontend/src/frontend/styles.css`
- Test: `scripts/verify-skill-debug-workbench.mjs`

**Step 1: Extend failing UI contract**

Require draft/version selector, resource estimate, diagnostic cards, A/B sections, history filters, cancel, rerun, compare, copy link, export and advanced logs. Require the entry to remain under project-admin navigation.

**Step 2: Verify RED**

Expected: current modal only supports one run and raw JSON.

**Step 3: Implement session creation and stable polling**

Use session APIs, not legacy job APIs. Poll the session ID and render baseline/candidate independently.

**Step 4: Implement diagnostic-first views**

Default to conclusions and differences. Put raw Trace/LLM/tool JSON in a collapsed advanced section with a sensitive-data warning.

**Step 5: Implement history/actions**

Add filters, cancel, rerun, compare selection, copy link and download of the server-generated redacted export.

**Step 6: Verify and commit**

```bash
npm run verify:skill-debug-workbench
npm --prefix frontend run build
git add frontend/src/frontend/components/ConfigViews.tsx frontend/src/frontend/shared.ts frontend/src/frontend/styles.css scripts/verify-skill-debug-workbench.mjs
git commit -m "feat: complete the skill debug administrator workbench"
```

### Task 10: Add API-level authorization and PostgreSQL integration coverage

**Files:**
- Create: `scripts/verify-skill-debug-integration.mjs`
- Modify: `package.json`
- Modify: `README.md`

**Step 1: Write integration scenarios**

Using a disposable PostgreSQL database, seed root/project-admin/reviewer users and assert:

- reviewer gets 403 for create/list/detail/cancel/rerun/export;
- two Debug sessions on the same MR/SHA have different jobs;
- production job remains unchanged;
- Debug completion leaves MR and finding history unchanged;
- Debug finding publication returns 409;
- snapshot remains stable after Skill edit;
- stale head, quota and cancel statuses are visible.

**Step 2: Run and verify RED**

Expected: failures until all prior tasks are connected.

**Step 3: Complete only missing wiring**

Do not weaken assertions. Fix route construction, repository registration and migration compatibility found by the integration test.

**Step 4: Verify GREEN and document the command**

```bash
TEST_POSTGRES_URL=... npm run verify:skill-debug-integration
```

If PostgreSQL is unavailable, report this check as blocked rather than claiming it passed.

**Step 5: Commit**

```bash
git add scripts/verify-skill-debug-integration.mjs package.json README.md
git commit -m "test: cover skill debug authorization and isolation"
```

### Task 11: Full regression and real browser acceptance

**Files:**
- Modify only files required by defects reproduced during verification.

**Step 1: Run focused and full verification**

```bash
npm run verify:skill-debug-workbench
PYTHONPATH=mr-backend/worker python3 -m pytest mr-backend/worker/tests/test_skill_debug_mode.py mr-backend/worker/tests/test_skill_debug_isolation.py -q
npm run verify
```

Expected: zero failures.

**Step 2: Start PostgreSQL and all three services**

Use documented config/env variables and seed development users only in the local test environment.

**Step 3: Browser-test as project administrator**

Create or edit a draft Skill, select a real/local-fixture MR, run targeted A/B, inspect diagnostics, history, rerun, cancel, compare and export. Confirm the displayed SHA/version/hash match the frozen snapshot.

**Step 4: Browser/API-test as reviewer**

Confirm the entry is hidden and all session endpoints return 403.

**Step 5: Inspect production data isolation**

Confirm the production job, MR status and finding history are unchanged after Debug runs.

**Step 6: Final verification and commit**

Run the full verification command again after any browser-discovered fix, then commit only verified changes.

### Task 12: Push and hand off

**Files:**
- No source changes unless final verification exposes a defect.

**Step 1: Audit requirements against the design**

Check every section in `docs/plans/2026-07-13-skill-debug-workbench-design.md` and explicitly record any deferred item. Do not call the work complete with an undocumented gap.

**Step 2: Confirm clean intended diff and recent commits**

```bash
git status --short
git log --oneline -12
```

**Step 3: Push the current branch**

```bash
git push origin codex/three-service-split
```

**Step 4: Report evidence**

Provide focused tests, full verification, browser result, PostgreSQL integration result, commit IDs and pushed branch.
