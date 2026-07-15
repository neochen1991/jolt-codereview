# Recall-Safe Context and Judge Recovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore MiniMax 2.7 review recall without restoring all-context prompts or weakening contradiction and duplicate filtering.

**Architecture:** Convert hard recall gates into bounded fallbacks and auditable soft states. Context selection first tries strict rule/tool/semantic matches, then uses a maximum-three-unit fallback; bound attribution mismatches continue to Judge with flags; Judge distinguishes absent evidence from incomplete evidence and protects critical/high findings from advisory pruning.

**Tech Stack:** Python 3, existing Review Worker orchestration, JSONL trace recorder, unittest-style worker tests, npm verification scripts.

---

### Task 1: Add bounded ContextUnit fallback

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Test: `mr-backend/worker/tests/test_skill_bound_review_contract.py`

**Step 1: Write failing tests**

Add tests proving:

- strict rule/tool/semantic matches still win;
- an empty strict result falls back to at most three changed ContextUnits;
- fallback ranking prefers source/patch technical-anchor overlap, then typed dependency presence, then stable file order;
- fallback never returns every unit when more than three exist;
- a truly empty ContextUnit list still skips the call.

**Step 2: Run tests and verify RED**

Run:

```bash
python3 mr-backend/worker/tests/test_skill_bound_review_contract.py
```

Expected: FAIL because current empty strict selection returns no ContextUnits.

**Step 3: Implement the bounded fallback**

Add a helper with this contract:

```python
def _context_units_with_fallback(
    context_units: list[Any],
    batch: dict[str, Any],
    agent_id: str,
    *,
    limit: int = 3,
) -> tuple[list[Any], str]:
    strict = _context_units_for_batch(context_units, batch, agent_id)
    if strict:
        return strict, "strict"
    if not context_units:
        return [], "empty"
    ranked = sorted(context_units, key=lambda unit: _fallback_unit_rank(unit, batch))
    return ranked[: max(1, min(limit, 3))], "fallback"
```

The caller must emit `context_units_fallback` with the batch, selected files, and before/after counts. Do not restore `scoped or context_units`.

Make free review and one coverage retry default to enabled when bound rules are present, while continuing to honor explicit `false` configuration.

**Step 4: Run tests and verify GREEN**

Run the focused test and `test_context_planner.py`.

**Step 5: Commit**

```bash
git add mr-backend/worker/orchestration/nodes/run_experts.py mr-backend/worker/tests/test_skill_bound_review_contract.py
git commit -m "fix: add bounded review context fallback"
```

### Task 2: Preserve bound attribution mismatches

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Modify: `mr-backend/worker/tools/candidate_store.py`
- Test: `mr-backend/worker/tests/test_skill_bound_review_contract.py`

**Step 1: Write failing tests**

Cover both `bound_rule_mismatch` and `bound_skill_checkpoint_mismatch`. A valid finding payload with an out-of-batch rule must remain in `kept`, preserve its original rules, and contain:

```python
"verification_flags": ["rule_attribution_mismatch"]
"bound_attribution_status": "mismatch"
"expected_bound_ids": ["..."]
```

A missing attribution in a multi-rule batch must use `rule_attribution_missing`. Skip markers remain unchanged.

**Step 2: Verify RED**

Run `test_skill_bound_review_contract.py`; expect the existing rejection assertions to fail.

**Step 3: Implement soft attribution**

Change `_enforce_bound_batch_findings` so mismatch and missing attribution findings are retained and flagged. Do not assign an expected rule unless the batch contains exactly one ID and the model omitted all attribution. Preserve rejected output only for malformed non-finding payloads.

**Step 4: Verify GREEN and commit**

Run focused tests, then commit with:

```bash
git commit -m "fix: retain bound attribution mismatches"
```

### Task 3: Protect critical and high test findings

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Test: `mr-backend/worker/tests/test_judge_retains_needs_review.py`

**Step 1: Write failing tests**

Create critical, high, and medium `TEST-*` findings. Assert `_prune_low_signal_final_findings` keeps critical/high and may classify medium as `secondary_test_advisory`.

**Step 2: Verify RED**

Run the Judge test and confirm current code removes all three severities.

**Step 3: Implement severity guard**

Apply `secondary_test_advisory` only when severity is not `critical` or `high`. Keep existing exact-duplicate handling.

**Step 4: Verify GREEN and commit**

```bash
git commit -m "fix: preserve high severity test findings"
```

### Task 4: Split absent and incomplete bound evidence

**Files:**
- Modify: `mr-backend/worker/orchestration/judging/evidence_pack.py`
- Test: `mr-backend/worker/tests/test_evidence_pack.py`

**Step 1: Write failing tests**

Add cases for:

- weak bound contract with no source excerpt, trigger, semantic path, or tool evidence: `rejected_with_reason` and `bound_required_evidence_absent`;
- weak bound contract with changed location plus direct source excerpt: `needs_review` and `bound_required_evidence_incomplete`;
- weak high-severity finding with direct evidence: never rejected solely for incomplete required evidence;
- explicit contradiction: still rejected.

**Step 2: Verify RED**

Run `test_evidence_pack.py`; current code should report `bound_required_evidence_missing` for both absent and incomplete cases.

**Step 3: Implement evidence states**

Replace unconditional `unsupported_bound_claim` rejection with explicit `has_direct_claim_evidence`. Contradictions retain highest precedence. Absent evidence may reject; incomplete evidence must become `needs_review`.

**Step 4: Verify GREEN and commit**

```bash
git commit -m "fix: distinguish absent and incomplete bound evidence"
```

### Task 5: Retain source-grounded unsupported claims for review

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Test: `mr-backend/worker/tests/test_judge_retains_needs_review.py`

**Step 1: Write failing tests**

Model the MiniMax output that triggered the regression: valid changed file and line, concrete source evidence, recommendation, high/medium severity, but incomplete structured rule evidence and no tool observation. Assert it is retained as `needs_review`, not `unsupported_low_precision_llm_finding` rejection.

Also assert a location-free, evidence-free claim remains rejectable.

**Step 2: Verify RED**

Run the focused Judge test and confirm the source-grounded case is currently rejected.

**Step 3: Implement minimal retention rule**

Make direct changed-source evidence sufficient for soft retention even without tool support. Do not bypass contradiction, non-diff location, malformed finding, or exact-duplicate rejection.

**Step 4: Verify GREEN and commit**

```bash
git commit -m "fix: retain source grounded judge candidates"
```

### Task 6: Add end-to-end recall regression gate

**Files:**
- Create: `scripts/verify_live_review_recall.py`
- Modify: `package.json`
- Test: `scripts/test_verify_live_review_recall.py`

**Step 1: Write failing scorer tests**

The scorer must consume a Gold JSONL file and actual run findings/trace. It must fail when:

- a Gold finding disappears at ContextUnit selection;
- a critical/high candidate is rejected for a soft reason;
- `judge_unclassified_rejection` exists;
- fallback selects more than three ContextUnits.

**Step 2: Verify RED**

Run the new test; expect failure because the live funnel checks do not exist.

**Step 3: Implement the scorer and npm command**

Add `verify:live-review-recall`. Keep frozen finding evaluation as a separate compatibility test; do not report it as live Worker recall.

**Step 4: Verify GREEN and commit**

```bash
git commit -m "test: gate live review recall funnel"
```

### Task 7: Full verification and real MiniMax task

**Files:**
- No production files unless a verified regression requires a focused correction.

**Step 1: Run offline verification**

```bash
python3 mr-backend/worker/tests/test_context_planner.py
python3 mr-backend/worker/tests/test_skill_bound_review_contract.py
python3 mr-backend/worker/tests/test_evidence_pack.py
python3 mr-backend/worker/tests/test_judge_retains_needs_review.py
npm run verify:worker-quality
npm run verify:router-policy
npm run verify:live-review-recall
git diff --check
```

**Step 2: Run actual Worker tasks**

Use the configured MiniMax 2.7 endpoint and run:

- the complex multi-file Gold MR;
- at least one cross-file positive MR;
- at least one negative MR.

**Step 3: Compare baseline and candidate**

Report Gold recall, final finding precision labels, candidate funnel, soft/hard rejection counts, LLM call count, average input tokens, fallback unit counts, and wall time.

Acceptance criteria:

- no Gold recall regression;
- no critical/high finding dropped for a soft reason;
- no `judge_unclassified_rejection`;
- fallback never exceeds three ContextUnits;
- average expert input remains below the pre-cropping baseline.

**Step 4: Commit final validation artifacts only if they are stable repository reports**

Do not commit runtime logs, API responses, sandboxes, or `evaluation/real_prs/cache/`.
