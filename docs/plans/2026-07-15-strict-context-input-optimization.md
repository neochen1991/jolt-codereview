# Strict Context Input Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Strictly scope ContextUnits and tool observations per rule batch, structure prompts for stable-prefix caching, and log per-category input-token composition.

**Architecture:** Selection is performed in `run_experts.py` before execution. Prompt construction in `prompts/builder.py` returns deterministic stable and dynamic sections plus token composition metadata. `llm/client.py` sends the stable section before the dynamic section and emits composition telemetry.

**Tech Stack:** Python 3, existing worker orchestration, OpenAI-compatible Chat Completions, repository script-style unit tests.

---

### Task 1: Strict ContextUnit evidence gating

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Test: `mr-backend/worker/tests/test_skill_bound_review_contract.py`

1. Add failing tests proving unrelated family-matched ContextUnits are excluded and empty matches do not fall back to all units.
2. Run the focused test and verify the old implementation fails.
3. Add normalized rule evidence and semantic-anchor matching.
4. Run the focused test and verify it passes.

### Task 2: Batch-scoped tool observations

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Test: `mr-backend/worker/tests/test_skill_bound_review_contract.py`

1. Add a failing test with matching/non-matching rule IDs and primary/dependency files.
2. Verify the old batch retains unrelated observations.
3. Filter observations by target ID and selected ContextUnit file set before the LLM call.
4. Verify only the doubly matching observations remain.

### Task 3: Stable Skill/standard prompt prefix

**Files:**
- Modify: `mr-backend/worker/prompts/builder.py`
- Modify: `mr-backend/worker/llm/client.py`
- Test: `mr-backend/worker/tests/test_context_planner.py`

1. Add failing tests proving two batches share an identical stable prefix while dynamic rule/context bodies differ.
2. Preserve complete Skill/standard content in the stable section.
3. Send stable prefix before dynamic body and keep cache/replay hashes deterministic over the combined request.
4. Verify existing prompt-contract tests still pass.

### Task 4: Input composition telemetry

**Files:**
- Modify: `mr-backend/worker/prompts/builder.py`
- Modify: `mr-backend/worker/llm/client.py`
- Test: `mr-backend/worker/tests/test_context_planner.py`

1. Add a failing test for source, dependency, Skill, tool, fixed, patch, and total token categories.
2. Compute categories using the same token estimator semantics as the client.
3. Emit `llm_input_composition` before every expert exchange.
4. Verify the category sum and stable-prefix hash are deterministic.

### Task 5: Regression and real-task validation

**Files:**
- Test: existing worker tests and verification scripts

1. Run focused ContextUnit, Skill, and LLM-envelope tests.
2. Run worker quality and router verification.
3. Run the complex Gold MR with the optimized worker.
4. Compare recall, precision, LLM calls, average input tokens, and empty-context audit events against the previous run.
