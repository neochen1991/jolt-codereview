# Skill Runtime Accountability Implementation Plan

> **For Codex:** Execute this plan task by task. For every behavior change, add the failing test first, observe the expected failure, then implement the minimum production change.

**Goal:** Compile Skill Markdown into one immutable Checkpoint Manifest consumed by debug and production, make every Judge removal auditable, and expose the real-task Skill lifecycle dashboard.

**Architecture:** Extend the existing immutable `custom_skill_versions` record with a versioned Checkpoint Manifest. New runs load that manifest into agent context and carry structured routing/checkpoint facts through finalize. The existing candidate ledger becomes a strict Judge decision ledger. Observability aggregates only production facts and the project UI renders the lifecycle funnel plus checkpoint details.

**Tech Stack:** TypeScript backend, Python worker, PostgreSQL-compatible SQL, React/Vite frontend, existing Node/Python verification scripts.

---

### Task 1: Add deterministic Checkpoint compiler contract

**Files:**
- Create: `mr-backend/src/backend/services/SkillCheckpointCompiler.ts`
- Modify: `mr-backend/src/backend/routes/rules.routes.ts`
- Create: `scripts/verify-skill-checkpoint-compiler.mjs`
- Modify: `package.json`

**Steps:**
1. Add a failing verifier covering explicit headings, field IDs, natural Checkpoint sections, Markdown tables, code-fence exclusion, stable generated IDs, source lines and duplicate diagnostics.
2. Run `node scripts/verify-skill-checkpoint-compiler.mjs` and confirm it fails because the compiler module or behaviors are absent.
3. Extract and extend the deterministic TypeScript compiler. Return a versioned manifest and structured diagnostics.
4. Make bundle validation use the compiler and reject non-compilable new bundles.
5. Re-run the verifier and backend build.

### Task 2: Persist and load the immutable Manifest

**Files:**
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Modify: `mr-backend/src/backend/repositories/RuleDocumentRepository.ts`
- Modify: `mr-backend/src/backend/routes/rules.routes.ts`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Create: `mr-backend/worker/tests/test_skill_checkpoint_manifest.py`
- Modify: `package.json`

**Steps:**
1. Add a failing worker test proving a supplied compiled Manifest wins over re-parsing Markdown and legacy assets still fall back.
2. Add manifest/compiler columns through additive migrations and repository persistence.
3. Load active-version manifests into each bound agent context.
4. Make batch construction consume compiled Checkpoints first, falling back only for legacy versions.
5. Verify debug and production agent construction share the same loader.
6. Run focused Python tests, canonical-version verification and backend build.

### Task 3: Enforce auditable Judge decisions

**Files:**
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/worker/tools/candidate_store.py`
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Create: `mr-backend/worker/tests/test_judge_decision_accountability.py`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `frontend/src/frontend/components/ReviewViews.tsx`
- Modify: `package.json`

**Steps:**
1. Add failing tests for rejected decisions with no reason, reason-code translation, merged decisions and candidate conservation.
2. Add additive decision-detail columns to `candidate_findings`.
3. Centralize reason normalization and human-readable reason details. A rejected/merged decision with no reason becomes `judge_unclassified_rejection` and emits a quality anomaly.
4. Reconcile Judge input identities against retained/rejected/merged output identities before commit.
5. Return decision details from trace APIs and render them in the admin review trace.
6. Run focused worker, API and frontend verifiers.

### Task 4: Record formal Skill runtime facts

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/route_agents.py`
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Modify: `mr-backend/worker/orchestration/nodes/finalize.py`
- Create: `mr-backend/worker/tests/test_skill_runtime_facts.py`
- Modify: `package.json`

**Steps:**
1. Add failing tests for applies-to matching, all configured Skill opportunities, routed state, loaded state and checkpoint terminal outcomes.
2. Evaluate applicability deterministically from compiled `applies_to` and changed paths before routing.
3. Carry Skill routing facts in graph state and record per-Skill load evidence.
4. At finalize, seal per-run Skill and Checkpoint facts into coverage, including manifest identity, terminal outcomes, Judge hits and unclassified deletion count.
5. Ensure debug facts remain visible on the run but carry `execution_kind=skill_debug` and are excluded from production aggregation.
6. Run focused runtime tests and worker-quality verification.

### Task 5: Implement production dashboard aggregation and API

**Files:**
- Modify: `mr-backend/src/backend/services/ObservabilityService.ts`
- Modify: `mr-backend/src/backend/routes/observability.routes.ts`
- Create: `scripts/verify-skill-runtime-dashboard.mjs`
- Modify: `package.json`

**Steps:**
1. Add a failing verifier for all-run route rate, applicable route rate, load rate, completion rate, unresolved rate, Judge-retained hit rate, false-positive rate, feedback coverage and zero denominators.
2. Aggregate structured facts only from `production_review`; report legacy-derived run counts separately.
3. Join final Skill findings and user feedback without counting unlabeled feedback as false positives.
4. Expose an admin-only dashboard endpoint with totals, denominator fields, health warnings and dimensions.
5. Run focused verifier and backend build.

### Task 6: Upgrade the project UI

**Files:**
- Modify: `frontend/src/frontend/components/ProjectViews.tsx`
- Modify: `frontend/src/frontend/styles.css`
- Create: `scripts/verify-skill-runtime-dashboard-ui.mjs`
- Modify: `package.json`

**Steps:**
1. Add a failing static/UI contract verifier for the six required KPIs, denominator labels, feedback coverage, legacy warning and detail table.
2. Fetch the new dashboard endpoint beside existing project settings.
3. Render project-level funnel cards and keep the Checkpoint table as drill-down detail.
4. Show `--` for null rates and display numerator/denominator next to each rate.
5. Run UI verifier and frontend build.

### Task 7: End-to-end verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/2026-07-13-skill-runtime-accountability-design.md` only if implementation-required clarifications emerge

**Steps:**
1. Document compilation, legacy migration, metric definitions and permission requirements.
2. Run all new focused verifiers.
3. Run existing Skill regression verifiers, worker quality, backend/frontend builds and `npm run verify`.
4. Start the local stack with documented configuration, seed or use a real production review, and verify the project dashboard in a browser as project admin.
5. Confirm lower roles cannot access the dashboard endpoint/page.
6. Review `git diff`, commit implementation, and report any external-data limitations honestly.
