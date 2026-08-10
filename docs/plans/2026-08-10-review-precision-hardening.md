# Review Precision Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate duplicate and out-of-diff review findings while preserving distinct defects and grouping their published presentation by source location.

**Architecture:** Add a deterministic `DiffScope` contract and canonical issue identity module to the Python worker. Enforce both at expert aggregation, verification, Judge, tool promotion, persistence, publishing, and evaluation boundaries.

**Tech Stack:** Python 3 worker and executable test scripts, TypeScript backend, React frontend, PostgreSQL-compatible persistence, npm verification gates.

---

### Task 1: Exact DiffScope contract

**Files:**
- Create: `mr-backend/worker/orchestration/quality/diff_scope.py`
- Create: `mr-backend/worker/tests/test_diff_scope_contract.py`
- Modify: `mr-backend/worker/orchestration/nodes/verify_findings.py`
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`

**Steps:**

1. Write failing tests for Windows path normalization, exact added-line acceptance, unchanged-file rejection, context-line rejection, empty-patch fail-closed behavior, and explicit changed file-level findings.
2. Run `PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_diff_scope_contract.py` and confirm the new contract tests fail.
3. Implement `DiffScope`, replace hunk-tolerance publication checks, remove automatic nearest-line relocation, and apply the same policy to tool observations.
4. Run the focused test and existing Judge/Verifier tests until all pass.
5. Commit the scope contract independently.

### Task 2: Canonical issue identity and cross-agent clustering

**Files:**
- Create: `mr-backend/worker/orchestration/quality/issue_identity.py`
- Create: `mr-backend/worker/tests/test_canonical_issue_identity.py`
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Modify: `mr-backend/worker/tools/candidate_store.py`
- Modify: `mr-backend/worker/orchestration/nodes/finalize.py`

**Steps:**

1. Write failing tests for cross-agent paraphrases, divergent rule ids, stable ordering, stable fingerprints, LLM/tool convergence, and distinct same-line root causes.
2. Run the focused test and confirm failures show the current surface-form identity.
3. Implement v2 fingerprints and deterministic cluster merge metadata.
4. Cluster after global expert collection and before final persistence; retain an idempotent final pass.
5. Run focused and existing typed-dedupe tests.
6. Commit canonical identity independently.

### Task 3: Location-level publication grouping

**Files:**
- Modify: `mr-backend/src/backend/routes/mr-review.routes.ts`
- Modify: `mr-backend/src/backend/reviewMarkdown.ts`
- Modify: `frontend/src/frontend/shared.ts`
- Modify: `frontend/src/frontend/components/ReviewViews.tsx`
- Create: `scripts/verify-review-location-grouping.mjs`
- Modify: `package.json`

**Steps:**

1. Write a failing verifier with two distinct findings on one line and one finding on another line.
2. Confirm the current renderer repeats the location rather than producing one group with sub-issues.
3. Add deterministic `file_path:line_start` grouping to publication Markdown and expose group metadata to the UI without changing finding ids.
4. Run the verifier and both TypeScript builds.
5. Commit presentation grouping independently.

### Task 4: Honest duplicate and scope quality gates

**Files:**
- Modify: `scripts/verify_intent_aware_precision.py`
- Modify: `scripts/test_verify_intent_aware_precision.py`
- Create: `scripts/verify_review_precision_hardening.py`
- Create: `scripts/test_verify_review_precision_hardening.py`
- Modify: `package.json`

**Steps:**

1. Write failing tests proving duplicate groups are derived from final findings and that off-diff and unchanged-file findings fail the gate.
2. Confirm the current `duplicate_groups=[]` fixture produces false confidence.
3. Implement automatic canonical duplicate metrics and scope violation metrics.
4. Add `verify:review-precision-hardening` to the repository verification chain.
5. Run focused evaluator tests and maintained real/gold fixtures.
6. Commit quality gates independently.

### Task 5: Full verification and completion audit

**Files:**
- Modify only if a failing regression exposes an in-scope defect.

**Steps:**

1. Run all new focused tests.
2. Run `npm run verify:worker-quality`, `npm run verify:typed-judge-dedupe`, `npm run verify:intent-aware-precision`, `npm run verify:gold-eval`, and `npm run verify:real-prs`.
3. Run `npm run build`.
4. Inspect git diff and confirm no files from the previous branch or `evaluation/real_prs/cache/` were added.
5. Record the unavailable boundary if the 25 Windows artifacts are still absent; do not represent maintained fixtures as production-model proof.
