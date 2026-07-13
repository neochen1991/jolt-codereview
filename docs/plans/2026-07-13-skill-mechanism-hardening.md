# Skill Mechanism Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Skill versions immutable and production-equivalent, gate activation on valid debug evidence, isolate diagnostics and queue resources, add a scoped Skill developer role, and make the non-executable script contract explicit.

**Architecture:** Introduce one version resolver shared by API snapshots and the Python Worker, with `custom_skills.active_version_id` acting only as a pointer. Build validity and attribution from structured run evidence, reuse a frozen input artifact for paired A/B jobs, and keep one Review Graph while reserving production queue capacity. Authorization moves from role-rank-only checks to explicit Skill capabilities.

**Tech Stack:** TypeScript backend, PostgreSQL migrations, Python Review Worker, React/Vite frontend, Node/Python verification scripts.

---

### Task 1: Add schema and migration for canonical Skill versions

**Files:**
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Modify: `mr-backend/worker/review_runtime.py`
- Create: `scripts/verify-skill-version-canonicalization.mjs`
- Modify: `package.json`

**Step 1: Write the failing migration verification**

Create a verification script that initializes PostgreSQL with legacy active Skill rows, runs migrations, and asserts:

- `custom_skills.active_version_id` points to a version;
- the version contains all legacy assets;
- `bundle_sha256` is stable and non-empty;
- rerunning migration does not create another version or change the hash.

**Step 2: Run test to verify it fails**

Run: `node scripts/verify-skill-version-canonicalization.mjs`

Expected: FAIL because the pointer/hash/repair fields and migration do not exist.

**Step 3: Implement the minimal schema and idempotent repair migration**

Add `active_version_id`, `bundle_sha256`, `validation_json`, `created_by`, debug validity fields, input artifact fields, and capability-supporting metadata. Backfill active versions from the legacy projection and only repair versions whose asset manifest is missing or inconsistent.

**Step 4: Run test to verify it passes**

Run: `node scripts/verify-skill-version-canonicalization.mjs`

Expected: PASS with the same bundle hash on two migrations.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/db/migrations.ts mr-backend/worker/review_runtime.py scripts/verify-skill-version-canonicalization.mjs package.json
git commit -m "feat: canonicalize immutable skill versions"
```

### Task 2: Use one version resolver in API and production Worker

**Files:**
- Create: `mr-backend/src/backend/services/SkillVersionService.ts`
- Modify: `mr-backend/src/backend/repositories/RuleDocumentRepository.ts`
- Modify: `mr-backend/src/backend/services/SkillDebugSnapshotService.ts`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `scripts/verify-skill-version-canonicalization.mjs`

**Step 1: Extend the failing test**

Assert that API snapshot resolution and production resolution return the same version ID, content, assets and `bundle_sha256`, including a migrated legacy Skill.

**Step 2: Verify RED**

Run: `node scripts/verify-skill-version-canonicalization.mjs`

Expected: FAIL because production still reads `custom_skill_assets` independently.

**Step 3: Implement shared canonical behavior**

Make TypeScript resolve version metadata once. Change Python production loading to join `custom_skills.active_version_id -> custom_skill_versions` and parse `assets_json`. Keep a read-only fallback for unmigrated rows, with a trace warning.

**Step 4: Verify GREEN**

Run: `node scripts/verify-skill-version-canonicalization.mjs && python3 mr-backend/worker/tests/test_skill_bound_review_contract.py`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/services/SkillVersionService.ts mr-backend/src/backend/repositories/RuleDocumentRepository.ts mr-backend/src/backend/services/SkillDebugSnapshotService.ts mr-backend/worker/review_runtime.py scripts/verify-skill-version-canonicalization.mjs
git commit -m "fix: share skill bundle resolution across debug and production"
```

### Task 3: Enforce draft-only creation and debug-gated activation

**Files:**
- Modify: `mr-backend/src/backend/routes/rules.routes.ts`
- Modify: `mr-backend/src/backend/repositories/RuleDocumentRepository.ts`
- Create: `mr-backend/src/backend/services/SkillActivationPolicyService.ts`
- Create: `scripts/verify-skill-activation-policy.mjs`
- Modify: `package.json`

**Step 1: Write failing API policy tests**

Test that:

- direct `status=active` creation is stored as draft;
- invalid Bundle is rejected even without `enforce_validation`;
- activation without valid targeted and production-route sessions returns 409;
- activation succeeds only when both sessions match the same version hash;
- only root/system admin can use break-glass with a non-empty reason.

**Step 2: Verify RED**

Run: `node scripts/verify-skill-activation-policy.mjs`

Expected: FAIL because direct activation and ungated activation are currently accepted.

**Step 3: Implement policy and repository transaction**

Create versions as draft only, persist the server validation report and hash, query valid evidence by bundle hash, and activate by changing the pointer inside one transaction.

**Step 4: Verify GREEN**

Run: `node scripts/verify-skill-activation-policy.mjs`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/routes/rules.routes.ts mr-backend/src/backend/repositories/RuleDocumentRepository.ts mr-backend/src/backend/services/SkillActivationPolicyService.ts scripts/verify-skill-activation-policy.mjs package.json
git commit -m "feat: gate skill activation on valid debug evidence"
```

### Task 4: Add conclusive debug validity states

**Files:**
- Create: `mr-backend/src/backend/services/SkillDebugValidityService.ts`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `mr-backend/src/backend/repositories/SkillDebugSessionRepository.ts`
- Modify: `mr-backend/worker/orchestration/nodes/fetch_mr.py`
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Create: `scripts/verify-skill-debug-validity.mjs`
- Modify: `package.json`

**Step 1: Write failing validity tests**

Cover empty diff, degraded VCS, target not executed, Skill not loaded, missing checkpoint coverage, zero successful target LLM calls, static-only success, and fully conclusive success.

**Step 2: Verify RED**

Run: `node scripts/verify-skill-debug-validity.mjs`

Expected: FAIL because terminal jobs are always collapsed to completed.

**Step 3: Implement explicit evidence contract**

Persist fetch validity events, evaluate target-scoped evidence, derive `degraded` or `inconclusive` before `completed`, and store structured invalid reasons.

**Step 4: Verify GREEN**

Run: `node scripts/verify-skill-debug-validity.mjs && npm run verify:skill-debug-workbench`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/services/SkillDebugValidityService.ts mr-backend/src/backend/routes/review.routes.ts mr-backend/src/backend/repositories/SkillDebugSessionRepository.ts mr-backend/worker/orchestration/nodes/fetch_mr.py mr-backend/worker/orchestration/nodes/run_experts.py scripts/verify-skill-debug-validity.mjs package.json
git commit -m "feat: distinguish conclusive and degraded skill debug runs"
```

### Task 5: Scope diagnostics to the target Skill

**Files:**
- Modify: `mr-backend/src/backend/services/SkillDebugDiagnosticService.ts`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Create: `scripts/verify-skill-debug-attribution.mjs`
- Modify: `package.json`

**Step 1: Write failing attribution tests**

Create trace/call/finding fixtures for two Agents and two Skills. Assert only the requested Agent/Skill/checkpoint contributes to counters and comparison, and changed findings are not reported as removed plus added.

**Step 2: Verify RED**

Run: `node scripts/verify-skill-debug-attribution.mjs`

Expected: FAIL because current counters use the whole run.

**Step 3: Implement target-scoped normalization**

Propagate Skill/checkpoint metadata in event payloads, filter calls by target Agent/span and batch labels, compute checkpoint coverage by unique IDs, and add a stable semantic finding key plus changed classification.

**Step 4: Verify GREEN**

Run: `node scripts/verify-skill-debug-attribution.mjs && npm run verify:skill-quality-metrics`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/services/SkillDebugDiagnosticService.ts mr-backend/src/backend/routes/review.routes.ts mr-backend/worker/orchestration/nodes/run_experts.py scripts/verify-skill-debug-attribution.mjs package.json
git commit -m "feat: attribute skill debug evidence to target checkpoints"
```

### Task 6: Freeze and reuse the A/B execution input

**Files:**
- Create: `mr-backend/src/backend/services/SkillDebugInputArtifactService.ts`
- Modify: `mr-backend/src/backend/services/SkillDebugSnapshotService.ts`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `mr-backend/worker/skill_debug.py`
- Modify: `mr-backend/worker/orchestration/nodes/fetch_mr.py`
- Modify: `mr-backend/worker/review_runtime.py`
- Create: `scripts/verify-skill-debug-input-replay.mjs`
- Modify: `package.json`

**Step 1: Write failing replay tests**

Assert baseline and candidate use the same content digest and frozen changed-file payload, a same-input rerun rejects a changed head, and a latest-head rerun creates a new artifact hash.

**Step 2: Verify RED**

Run: `node scripts/verify-skill-debug-input-replay.mjs`

Expected: FAIL because both jobs currently fetch VCS independently.

**Step 3: Implement content-addressed input artifact**

Fetch once at session creation through the existing VCS service, apply data-policy-safe serialization, persist the artifact and digest, and inject it into both jobs. Add separate same-input and latest-head rerun routes.

**Step 4: Verify GREEN**

Run: `node scripts/verify-skill-debug-input-replay.mjs && npm run verify:skill-debug-workbench`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/services/SkillDebugInputArtifactService.ts mr-backend/src/backend/services/SkillDebugSnapshotService.ts mr-backend/src/backend/routes/review.routes.ts mr-backend/worker/skill_debug.py mr-backend/worker/orchestration/nodes/fetch_mr.py mr-backend/worker/review_runtime.py scripts/verify-skill-debug-input-replay.mjs package.json
git commit -m "feat: replay one frozen input across skill debug variants"
```

### Task 7: Reserve production queue capacity

**Files:**
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/src/backend/services/SkillDebugPolicyService.ts`
- Modify: `mr-backend/src/backend/config.ts`
- Modify: `mr-backend/src/backend/types.ts`
- Create: `mr-backend/worker/tests/test_skill_debug_queue_policy.py`
- Modify: `package.json`

**Step 1: Write failing scheduler tests**

Test production-first ordering, no new debug claim while production is queued, debug Job concurrency rather than Session concurrency, and continued production progress when debug capacity is exhausted.

**Step 2: Verify RED**

Run: `python3 mr-backend/worker/tests/test_skill_debug_queue_policy.py`

Expected: FAIL because the scheduler currently orders only by MR/job creation time.

**Step 3: Implement category-aware scheduling**

Order production before debug, enforce `debug_max_concurrency`, reserve configured production capacity, and make quota messages reflect actual Job cost.

**Step 4: Verify GREEN**

Run: `python3 mr-backend/worker/tests/test_skill_debug_queue_policy.py && npm run verify:mr-queue-created-order`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/worker/review_runtime.py mr-backend/src/backend/services/SkillDebugPolicyService.ts mr-backend/src/backend/config.ts mr-backend/src/backend/types.ts mr-backend/worker/tests/test_skill_debug_queue_policy.py package.json
git commit -m "feat: reserve review capacity for production jobs"
```

### Task 8: Add scoped Skill developer authorization

**Files:**
- Modify: `mr-backend/src/backend/routes/mr-review.routes.ts`
- Modify: `mr-backend/src/backend/routes/rules.routes.ts`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `frontend/src/frontend/shared.ts`
- Modify: `frontend/src/frontend/components/ConfigViews.tsx`
- Create: `scripts/verify-skill-developer-authorization.mjs`
- Modify: `package.json`

**Step 1: Write failing authorization matrix tests**

Assert a Skill developer can create/validate/upload drafts and manage only their own debug sessions, but cannot activate, inspect another user's session, access project secrets or publish findings. Preserve reviewer 403 behavior and administrator full access.

**Step 2: Verify RED**

Run: `node scripts/verify-skill-developer-authorization.mjs`

Expected: FAIL because `skill_developer` is not a recognized capability.

**Step 3: Implement explicit capabilities**

Add `ensureProjectCapability`, ownership checks for debug sessions, role selection in member management, and front-end navigation that exposes only the Skill workspace to Skill developers.

**Step 4: Verify GREEN**

Run: `node scripts/verify-skill-developer-authorization.mjs && npm run verify:skill-debug-workbench`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/routes/mr-review.routes.ts mr-backend/src/backend/routes/rules.routes.ts mr-backend/src/backend/routes/review.routes.ts frontend/src/frontend/shared.ts frontend/src/frontend/components/ConfigViews.tsx scripts/verify-skill-developer-authorization.mjs package.json
git commit -m "feat: add scoped skill developer capabilities"
```

### Task 9: Make the script contract explicit

**Files:**
- Modify: `mr-backend/src/backend/routes/rules.routes.ts`
- Modify: `mr-backend/worker/orchestration/deepagents_runner.py`
- Modify: `frontend/src/frontend/components/ConfigViews.tsx`
- Modify: `scripts/verify-skill-bundle-validation.mjs`
- Modify: `README.md`

**Step 1: Write failing contract tests**

Assert uploaded scripts receive a `non_executable_resource` warning, runtime always records `blocked_by_policy`, no script result can satisfy debug validity, and the UI never labels the asset as executable.

**Step 2: Verify RED**

Run: `npm run verify:skill-bundle-validation && python3 mr-backend/worker/tests/test_skill_bound_review_contract.py`

Expected: FAIL on the new warning/UI contract assertions.

**Step 3: Implement the explicit read-only contract**

Keep content readable, normalize executable to false for new uploads, return a structured blocked result, and document the future sandbox boundary.

**Step 4: Verify GREEN**

Run: `npm run verify:skill-bundle-validation && python3 mr-backend/worker/tests/test_skill_bound_review_contract.py`

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/routes/rules.routes.ts mr-backend/worker/orchestration/deepagents_runner.py frontend/src/frontend/components/ConfigViews.tsx scripts/verify-skill-bundle-validation.mjs README.md
git commit -m "docs: enforce read-only uploaded skill scripts"
```

### Task 10: Update workbench UX and complete verification

**Files:**
- Modify: `frontend/src/frontend/components/ConfigViews.tsx`
- Modify: `frontend/src/frontend/styles.css`
- Modify: `README.md`
- Modify: `scripts/verify-skill-debug-workbench.mjs`
- Modify: `scripts/verify-skill-debug-integration.mjs`

**Step 1: Write failing UI assertions**

Require draft-only creation, validity reasons, target-scoped metrics, changed Finding count, input artifact hash, same-input/latest-head rerun actions, activation gate status, queue cost and script read-only wording.

**Step 2: Verify RED**

Run: `npm run verify:skill-debug-workbench`

Expected: FAIL because the new controls and labels do not exist.

**Step 3: Implement the workbench and documentation**

Update the UI without redesigning the existing page. Add concise evidence and gate sections, preserve advanced logs, and document Windows/intranet configuration plus the new lifecycle.

**Step 4: Run focused and full automated verification**

Run:

```bash
npm run verify:skill-version-canonicalization
npm run verify:skill-activation-policy
npm run verify:skill-debug-validity
npm run verify:skill-debug-attribution
npm run verify:skill-debug-input-replay
npm run verify:skill-developer-authorization
npm run verify:skill-debug-integration
npm run verify
```

Expected: all commands exit 0.

**Step 5: Run browser acceptance**

Verify project admin activation gates, Skill developer own-session access, reviewer denial, conclusive completion, degraded/inconclusive display, export, rerun modes and production queue isolation in a real browser.

**Step 6: Commit**

```bash
git add frontend/src/frontend/components/ConfigViews.tsx frontend/src/frontend/styles.css README.md scripts/verify-skill-debug-workbench.mjs scripts/verify-skill-debug-integration.mjs
git commit -m "feat: complete reliable skill development workflow"
```
