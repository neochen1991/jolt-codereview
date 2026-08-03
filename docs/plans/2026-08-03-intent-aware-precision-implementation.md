# Intent-Aware Review Precision Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce safe-change, style, null-safety, broad-catch, and duplicate false positives while preserving Skill/standard coverage and high-severity recall.

**Architecture:** Add deterministic change-intent metadata to each V2 ContextUnit, source-grounded counter-evidence and causality calibration to Verify/Judge, and typed duplicate aggregation. Skill and bound Markdown rules remain complete inputs; intent raises the proof requirement for free-review claims but never skips a bound checkpoint.

**Tech Stack:** Python 3 worker pipeline, dataclasses, existing diff/semantic graph utilities, repository verification scripts, Node.js quality gates.

---

### Task 1: ContextUnit Change Intent Classifier

**Files:**
- Create: `mr-backend/worker/context/change_intent.py`
- Modify: `mr-backend/worker/context/context_unit.py`
- Modify: `mr-backend/worker/context/context_planner.py`
- Test: `mr-backend/worker/tests/test_change_intent.py`
- Test: `mr-backend/worker/tests/test_context_planner.py`

**Step 1: Write failing classifier tests**

Cover logging-only, comment-only, rename-like, test-only, behavior-changing, and mixed patches. Assert conservative `unknown` or `mixed` classification when deterministic evidence is insufficient.

**Step 2: Run tests and verify RED**

Run: `PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_change_intent.py`

Expected: FAIL because `context.change_intent` does not exist.

**Step 3: Implement the minimal deterministic classifier**

Add an immutable `ChangeIntent` record with `labels`, `semantic_delta`, `confidence`, and `evidence`. Classify only from patch/file signals; never call an LLM and never classify ambiguous code as safe.

**Step 4: Add intent to ContextUnit and its stable hash**

Include the record in `ContextUnit.to_prompt_item()` and `ContextPlan.to_record()`. Ensure the context hash changes when intent metadata changes.

**Step 5: Run tests and verify GREEN**

Run the classifier and context planner tests. Expected: PASS.

**Step 6: Commit**

Commit message: `feat: classify context unit change intent`

### Task 2: Intent-Aware Expert Contract Without Skill Loss

**Files:**
- Modify: `mr-backend/worker/prompts/builder.py`
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Test: `mr-backend/worker/tests/test_context_planner.py`
- Test: `mr-backend/worker/tests/test_skill_context_requirements.py`

**Step 1: Write failing prompt tests**

Assert that ContextUnit prompt items contain `change_intent`, require an `introduced` or `worsened` causal claim for safe-intent free review, and still contain the complete Skill checkpoint/bound-rule contract.

**Step 2: Verify RED**

Run the two focused test files. Expected: FAIL on missing intent/causality instructions.

**Step 3: Implement minimal prompt contract**

Add `causal_delta` to the requested Finding fields. State that intent cannot skip Skill or Markdown checks and that `unknown/mixed` uses normal review behavior.

**Step 4: Verify GREEN and commit**

Commit message: `feat: add intent aware expert evidence contract`

### Task 3: Severity Caps for Style and Broad-Catch Advisories

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Modify: `mr-backend/worker/rules/registry.json`
- Test: `mr-backend/worker/tests/test_judge_retains_needs_review.py`
- Test: `scripts/verify_java_convention_rules.py`

**Step 1: Write failing severity tests**

Assert that free-review/tool naming, comments, ordinary logging, and broad catch without proven swallowing are calibrated to `info` and are not reviewer-selectable. Assert that sensitive-data logging and explicitly bound Skill/Markdown severity remain unchanged.

**Step 2: Verify RED**

Run focused Judge and Java convention tests. Expected: FAIL because registry and Judge currently allow medium promotion.

**Step 3: Implement category severity calibration**

Add an explicit-bound-policy check and category caps. Change generic naming/logging registry defaults so they cannot become blocking findings solely through tool promotion.

**Step 4: Verify GREEN and commit**

Commit message: `fix: cap advisory finding severity`

### Task 4: Source-Grounded Exception Handling Counter-Evidence

**Files:**
- Modify: `mr-backend/worker/static/heuristics.py`
- Modify: `mr-backend/worker/orchestration/nodes/verify_findings.py`
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Test: `mr-backend/worker/tests/test_verify_findings_soft_reject.py`
- Test: `mr-backend/worker/tests/test_judge_retains_needs_review.py`

**Step 1: Write failing negative and positive tests**

Negative fixtures: rethrow, wrapped cause, rollback, interrupt restoration, explicit failure-state update, and documented fallback. Positive fixtures: empty catch, log-and-continue, neutral return, and false-success return.

**Step 2: Verify RED**

Expected: reasonable catches are currently treated as broad/swallowed candidates.

**Step 3: Implement catch-body facts**

Remove swallowing language from the broad-catch line heuristic. Analyze the surrounding catch body for failure propagation/loss and emit structured contradiction reason codes. Never use generated Finding prose as the proof of swallowing.

**Step 4: Verify GREEN and commit**

Commit message: `fix: distinguish broad catches from swallowed failures`

### Task 5: Null-Guard Counter-Evidence

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/verify_findings.py`
- Modify: `mr-backend/worker/orchestration/judging/evidence_pack.py`
- Test: `mr-backend/worker/tests/test_verify_findings_soft_reject.py`
- Test: `mr-backend/worker/tests/test_evidence_pack.py`

**Step 1: Write failing tests**

Cover early-return guard, explicit throw, `Objects.requireNonNull`, Optional, collection guard, and genuine unguarded dereference.

**Step 2: Verify RED**

Expected: general null protection is not recognized as contradiction evidence.

**Step 3: Implement bounded guard detection**

Extract the claimed symbol when possible and detect guards before the sink within the verified source window. Emit `source_has_null_guard`/`contradicting_null_guard`; stay conservative when symbol identity is unknown.

**Step 4: Verify GREEN and commit**

Commit message: `fix: reject null findings contradicted by guards`

### Task 6: Intent and Causality Calibration in Judge

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Modify: `mr-backend/worker/orchestration/judging/evidence_score.py`
- Test: `mr-backend/worker/tests/test_judge_retains_needs_review.py`
- Test: `mr-backend/worker/tests/test_evidence_score.py`

**Step 1: Write failing causality tests**

Assert that unchanged free-review findings on logging-only/refactor units are rejected or retained only as non-final review candidates; introduced defects in mixed units remain selectable; bound findings still follow existing recall-safe evidence policy.

**Step 2: Verify RED**

Expected: Judge currently has no ContextUnit intent/causality calibration.

**Step 3: Implement minimal calibration**

Resolve Finding `context_unit_id` to its intent metadata, validate `causal_delta`, and add explicit decision reason codes. Do not apply safe-intent suppression to `unknown/mixed` or to strong tool evidence that proves a changed sink.

**Step 4: Verify GREEN and commit**

Commit message: `feat: calibrate findings by change causality`

### Task 7: Typed Duplicate Aggregation

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Test: `mr-backend/worker/tests/test_judge_retains_needs_review.py`
- Test: `mr-backend/worker/tests/test_judge_signatures.py`

**Step 1: Write failing aggregation tests**

Assert that differently worded naming/logging findings in one file aggregate with `related_locations`, same-root business findings merge, and distinct SQL/security sinks remain separate.

**Step 2: Verify RED**

Expected: distant same-file advisories are not currently aggregated.

**Step 3: Implement typed aggregation**

Use canonical rule, typed root cause, primary symbol, and sink/impact. Preserve merged locations, rules, agents, and evidence in quality trace.

**Step 4: Verify GREEN and commit**

Commit message: `fix: aggregate repeated review findings by root cause`

### Task 8: Quality Gates and Full Verification

**Files:**
- Create: `scripts/verify-intent-aware-precision.py`
- Modify: `package.json`
- Modify: `scripts/verify_live_review_recall.py`
- Test: `scripts/test_verify_intent_aware_precision.py`

**Step 1: Write failing gate tests**

Report false positives by intent/category, duplicate rate, precision, recall, and high-severity recall. Include explicit fixtures for normal null/catch behavior and mixed safe-plus-defect changes.

**Step 2: Verify RED, implement the gate, then verify GREEN**

Add `verify:intent-aware-precision` to the canonical `npm run verify` chain.

**Step 3: Run focused quality suites**

Run:

```bash
npm run verify:worker-quality
npm run verify:gold-eval
npm run verify:real-prs
npm run verify:live-review-recall
npm run verify:intent-aware-precision
```

Expected: all exit zero; no high-severity recall regression.

**Step 4: Run complete verification**

Run: `npm run verify`

Expected: exit zero with all builds, Skill gates, V2 context/evidence tests, real-PR evaluation, repeatability, and PostgreSQL-only runtime checks passing.

**Step 5: Document measured results and commit**

Record baseline/current precision, recall, high-severity recall, duplicate rate, and known limitations. Commit message: `test: gate intent aware review precision`
