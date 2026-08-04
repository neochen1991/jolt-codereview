# MiniMax and GLM Model Capability Adaptation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adapt review LLM requests for MiniMax and GLM models and switch the local GLM-5.2 output budget without changing Skill, context, or Judge semantics.

**Architecture:** Add a model capability resolver and a single request-payload builder used by expert and summary calls. Keep prompt construction model-neutral, add provider-specific structured-output and Thinking settings, and expose truncation and parsing telemetry.

**Tech Stack:** Python 3, pytest/unittest, React/TypeScript, Vitest, JSON configuration.

---

### Task 1: Model capability resolver

**Files:**
- Create: `mr-backend/worker/llm/model_capabilities.py`
- Create: `mr-backend/worker/tests/test_model_capabilities.py`

1. Write failing tests for GLM-5.2, GLM-5.1, MiniMax and unknown models.
2. Run `python3 -m pytest mr-backend/worker/tests/test_model_capabilities.py -q` and confirm the missing module failure.
3. Implement immutable capability profiles plus `model_overrides` merging.
4. Run the focused test and confirm it passes.

### Task 2: Capability-aware request payloads

**Files:**
- Modify: `mr-backend/worker/llm/client.py`
- Modify: `mr-backend/worker/orchestration/nodes/critic_pass.py`
- Modify: `mr-backend/worker/orchestration/nodes/run_targeted_debate.py`
- Test: `mr-backend/worker/tests/test_llm_model_payloads.py`

1. Write failing payload tests for GLM `thinking` + `json_object`, MiniMax compatibility, configured output limits and parameter-specific fallback.
2. Run the focused tests and verify behavioral failures.
3. Add one shared payload builder and parameter-specific compatibility fallback.
4. Run focused and existing LLM retry/execution tests.

### Task 3: Structured parsing and truncation telemetry

**Files:**
- Modify: `mr-backend/worker/llm/client.py`
- Modify: `mr-backend/worker/llm/exchange.py`
- Modify: `mr-backend/worker/review_runtime.py`
- Test: `mr-backend/worker/tests/test_llm_findings_parser.py`

1. Write failing tests for `{"findings": [...]}`, legacy arrays, finish reason capture and parse-drop counters.
2. Run focused tests and verify failures.
3. Implement backward-compatible parsing and structured telemetry.
4. Add one bounded repair path for truncated or malformed JSON.
5. Run focused tests and existing exact-replay tests.

### Task 4: Configuration and frontend limits

**Files:**
- Modify: `frontend/src/frontend/shared.ts`
- Modify: `frontend/src/frontend/components/ConfigViews.tsx`
- Modify: `frontend/src/frontend/components/ProjectViews.tsx`
- Modify: `config.example.json`
- Modify: `common-backend/config.example.json`
- Modify: `mr-backend/config.example.json`
- Modify: `README.md`
- Test: existing frontend shared/config tests

1. Write or update a failing frontend clamp test proving values above 12000 are retained up to the supported global safety maximum.
2. Run the focused frontend test and verify failure.
3. Remove the 12000 UI clamp and document model profiles and overrides.
4. Update only non-secret fields in local untracked configs to GLM-5.2 and 32768.
5. Run frontend tests and build.

### Task 5: Full verification

**Files:**
- No production changes unless a verification failure requires a scoped fix.

1. Run the complete worker test suite.
2. Run frontend tests and production build.
3. Run repository configuration verification scripts.
4. Start local services and confirm the effective GLM-5.2 capability profile through logs/API without printing secrets.
5. If the gateway is available, run one bounded real review and inspect finish reason, parse funnel, findings and Judge results.
6. Review `git diff` and ensure no secret or evaluation cache is staged.
