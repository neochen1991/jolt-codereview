# Final Finding Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add one fail-open, globally scoped LLM clustering pass that merges semantically duplicate final findings after Critic and before persistence without allowing the model to add or rewrite findings.

**Architecture:** A new `final_consolidation` quality module owns compact prompt construction, strict response validation, deterministic field merging, and the bounded LLM exchange. `judge_findings` invokes it after final quality selection, records merged members as terminal merge decisions, applies the existing canonical guard again, and persists only consolidated findings. Existing routing, retry, replay, token accounting, and model capability handling remain the only network execution path.

**Tech Stack:** Python 3.14, existing OpenAI-compatible LLM client and exchange envelope, PostgreSQL worker orchestration, pytest-style executable worker tests, npm verification scripts.

---

### Task 1: Define strict clustering and validation contracts

**Files:**
- Create: `mr-backend/worker/orchestration/quality/final_consolidation.py`
- Create: `mr-backend/worker/tests/test_final_finding_consolidation.py`

**Step 1: Write failing contract tests**

Add tests that call `parse_consolidation_response()` with:

```python
findings = [
    {"dedupe_hash": "a", "title": "退款缺少幂等", "file_path": "Refund.java", "line_start": 10},
    {"dedupe_hash": "b", "title": "重复退款未防护", "file_path": "Refund.java", "line_start": 12},
]

valid = {
    "version": "final_finding_consolidation_v1",
    "groups": [{"member_ids": ["f_01", "f_02"], "reason": "same root cause"}],
}
```

Verify a valid response is accepted and that invalid version, unknown ID, duplicate member, overlapping groups, empty group, and single-member group each return an atomic failure with the expected structured reason.

**Step 2: Run the focused test and verify failure**

Run:

```bash
PYTHONPATH=mr-backend/worker mr-backend/.venv/bin/python -m pytest mr-backend/worker/tests/test_final_finding_consolidation.py -q
```

Expected: FAIL because `orchestration.quality.final_consolidation` does not exist.

**Step 3: Implement compact input and strict validation**

Implement:

```python
CONTRACT_VERSION = "final_finding_consolidation_v1"

@dataclass(frozen=True)
class ConsolidationFailure:
    reason: str
    detail: str = ""

def compact_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]: ...
def parse_consolidation_response(content: str, known_ids: set[str]) -> tuple[list[dict[str, Any]], ConsolidationFailure | None]: ...
```

Use request-local IDs `f_01`, `f_02`, and so on. Limit evidence excerpts and text fields before serialization. Reject the entire response on any malformed group.

**Step 4: Run tests and verify pass**

Run the focused test command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/worker/orchestration/quality/final_consolidation.py mr-backend/worker/tests/test_final_finding_consolidation.py
git commit -m "feat(review): validate final finding consolidation groups"
```

### Task 2: Implement deterministic merge invariants

**Files:**
- Modify: `mr-backend/worker/orchestration/quality/final_consolidation.py`
- Modify: `mr-backend/worker/tests/test_final_finding_consolidation.py`
- Reference: `mr-backend/worker/orchestration/quality/issue_identity.py`

**Step 1: Write failing merge tests**

Cover:

- tool-backed member wins primary selection
- highest severity and confidence are preserved
- primary title, description, recommendation, and suggested code remain unchanged
- rules, agents, source observations, tool provenance, and evidence variants are unioned without duplicates
- secondary source anchors are stored in `related_locations`
- `quality_trace.final_consolidation` contains member hashes, primary hash, reason, and merged count
- output count never exceeds input count
- source input dictionaries are not mutated

**Step 2: Run focused tests and verify failure**

Use the Task 1 pytest command.

Expected: FAIL because deterministic merge functions are missing.

**Step 3: Implement deterministic merging**

Add:

```python
def merge_consolidation_groups(
    findings: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    *,
    model_metadata: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...
```

Reuse `canonical_issue_fingerprint()` after fields are merged. Use a stable JSON fingerprint to deduplicate dict-valued provenance. Bound merged evidence length. Return rejected member records with `rejected_reasons=["deduped_final_llm_consolidation"]` and `merged_into_dedupe_hash`.

**Step 4: Run focused tests and verify pass**

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/worker/orchestration/quality/final_consolidation.py mr-backend/worker/tests/test_final_finding_consolidation.py
git commit -m "feat(review): merge final finding groups deterministically"
```

### Task 3: Add the bounded LLM consolidator

**Files:**
- Modify: `mr-backend/worker/orchestration/quality/final_consolidation.py`
- Modify: `mr-backend/worker/tests/test_final_finding_consolidation.py`
- Modify: `mr-backend/worker/tests/test_worker_exact_replay.py`
- Reference: `mr-backend/worker/orchestration/nodes/critic_pass.py`
- Reference: `mr-backend/worker/llm/exchange.py`

**Step 1: Write failing invocation tests**

Inject a fake `consolidation_llm` callable and verify:

- fewer than `min_findings` skips the model
- disabled configuration skips the model
- valid model groups are applied
- invalid JSON, invalid IDs, model exception, and budget stop return the original findings
- fallback metadata contains the structured reason
- the prompt says “only merge, never add, delete, or rewrite findings” and includes counterexamples
- operation name is `final_consolidation`

Extend exact replay coverage so a recorded consolidation response replays without another network call.

**Step 2: Run focused tests and verify failure**

```bash
PYTHONPATH=mr-backend/worker mr-backend/.venv/bin/python -m pytest mr-backend/worker/tests/test_final_finding_consolidation.py mr-backend/worker/tests/test_worker_exact_replay.py -q
```

Expected: FAIL because the invocation entry point is missing.

**Step 3: Implement the LLM execution path**

Add:

```python
def consolidate_final_findings(
    *,
    findings: list[dict[str, Any]],
    config: dict[str, Any],
    recorder: Any,
    span_id: str,
    head_sha: str,
    budget_tracker: Any | None = None,
    consolidation_llm: Callable[[str], dict[str, Any]] | None = None,
) -> ConsolidationResult: ...
```

Use `candidate_providers`, `build_chat_payload`, `invoke_with_parameter_fallback`, `execute_chat_exchange`, and `replay_mode_from_config`. Use structured JSON output, temperature zero, configured timeout and output-token cap, and the existing reasoning-disabled model payload. Charge the budget only from actual usage. Catch transport, timeout, parse, and validation failures and return the untouched findings.

For more than `max_findings`, create deterministic candidate batches by canonical file and nearby line window; do not send an unbounded request.

**Step 4: Run focused tests and verify pass**

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/worker/orchestration/quality/final_consolidation.py mr-backend/worker/tests/test_final_finding_consolidation.py mr-backend/worker/tests/test_worker_exact_replay.py
git commit -m "feat(review): add fail-open final consolidation model pass"
```

### Task 4: Integrate consolidation after Critic and before persistence

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/judge_findings.py`
- Modify: `mr-backend/worker/tests/test_final_finding_consolidation.py`
- Modify: `mr-backend/worker/tests/test_judge_decision_accountability.py`

**Step 1: Write failing pipeline-order and accounting tests**

Assert from the node source or a focused fake-node execution that:

- `run_critic_pass` and final quality selection happen before `consolidate_final_findings`
- consolidation happens before `ensure_judge_decision_accountability`
- consolidation happens before `INSERT INTO review_findings`
- only consolidated primaries are persisted
- merged members are recorded with `deduped_final_llm_consolidation`
- a fallback result preserves all original findings and task completion

**Step 2: Run focused tests and verify failure**

```bash
PYTHONPATH=mr-backend/worker mr-backend/.venv/bin/python -m pytest mr-backend/worker/tests/test_final_finding_consolidation.py mr-backend/worker/tests/test_judge_decision_accountability.py -q
```

Expected: FAIL because the node does not invoke consolidation.

**Step 3: Wire the node**

In `judge_findings_node`, call `consolidate_final_findings()` immediately after `quality_selected_findings` is finalized. Extend `judge_rejections` with merged members, rerun `cluster_canonical_issues()` as the final deterministic guard, and record:

- `final_consolidation_completed`
- `final_consolidation_fallback`
- input/output counts
- group/member counts
- duration and failure reason

Then call decision accountability and persist only the consolidated output.

**Step 4: Run focused tests and verify pass**

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/worker/orchestration/nodes/judge_findings.py mr-backend/worker/tests/test_final_finding_consolidation.py mr-backend/worker/tests/test_judge_decision_accountability.py
git commit -m "feat(review): consolidate findings before persistence"
```

### Task 5: Add defaults and precision regression gates

**Files:**
- Modify: `mr-backend/worker/config.py`
- Modify: `mr-backend/config.example.json`
- Modify: `scripts/verify_review_precision_hardening.py`
- Modify: `scripts/test_verify_review_precision_hardening.py`
- Modify: `package.json`

**Step 1: Write failing configuration and quality-gate tests**

Verify default values for `enabled`, `min_findings`, `max_findings`, `timeout_seconds`, `max_output_tokens`, `temperature`, and `fail_open`. Add adversarial duplicate fixtures covering paraphrases, same-line different rules, nearby anchors, and cross-agent wording. Add negative fixtures for SQL injection versus unbounded query, production defect versus missing test, and authorization versus idempotency.

**Step 2: Run verification and confirm failure**

```bash
npm run verify:review-precision-hardening
```

Expected: FAIL because the final consolidation gate and defaults do not exist.

**Step 3: Add defaults and evaluator assertions**

Add final consolidation defaults under `review_quality.final_consolidation` in worker defaults and the example config. Extend the precision verifier to report:

- duplicate rate before and after
- false merge count
- final duplicate groups
- output count invariant

Fail verification when same-line paraphrase merge is below 100%, clear nearby-root merge is below 90%, false merge rate is at least 2%, or final duplicate rate is at least 3%.

Add the new focused worker test to `verify:review-precision-hardening` or `verify:worker-quality` without duplicating the same execution in both scripts.

**Step 4: Run verification and confirm pass**

Run:

```bash
npm run verify:review-precision-hardening
npm run verify:worker-quality
```

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/worker/config.py mr-backend/config.example.json scripts/verify_review_precision_hardening.py scripts/test_verify_review_precision_hardening.py package.json
git commit -m "test(review): gate final finding consolidation quality"
```

### Task 6: Complete full verification and document evidence

**Files:**
- Create: `docs/reports/2026-08-10-final-finding-consolidation-verification.md`
- Modify only if tests expose a defect: files from Tasks 1-5

**Step 1: Run focused Python tests**

```bash
PYTHONPATH=mr-backend/worker mr-backend/.venv/bin/python -m pytest \
  mr-backend/worker/tests/test_final_finding_consolidation.py \
  mr-backend/worker/tests/test_worker_exact_replay.py \
  mr-backend/worker/tests/test_judge_decision_accountability.py -q
```

Expected: PASS.

**Step 2: Run repository quality checks**

```bash
npm run verify:model-capabilities
npm run verify:worker-quality
npm run verify:review-precision-hardening
npm run build
git diff --check
```

Expected: all commands PASS and `git diff --check` reports no errors.

**Step 3: Run the available 25-MR evaluation**

Use the repository's existing Windows/Linux evaluation command and record model, configuration, timestamp, total findings, duplicate groups, false merges, precision, and added latency. If the Windows MiniMax environment is not accessible locally, record that limitation and provide the exact command and expected artifact path for the user to run there.

Expected acceptance:

- final duplicate rate below 3%
- distinct-root false merge rate below 2%
- output count never increases
- consolidation failure does not fail review tasks
- P95 added latency at most 45 seconds

**Step 4: Write the verification report**

Distinguish unit/build evidence from live 25-MR evidence. Include commands, results, remaining limitations, and before/after metrics.

**Step 5: Commit**

```bash
git add docs/reports/2026-08-10-final-finding-consolidation-verification.md
git commit -m "docs: record final consolidation verification"
```

