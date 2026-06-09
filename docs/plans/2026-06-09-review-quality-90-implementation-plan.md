# Review Quality 90% Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Raise Java/Spring MR review quality toward 90% effective recall with <=10% false positives by preserving all candidates, forcing evidence-based adjudication, and expanding generic Java Web static rules.

**Architecture:** The review pipeline keeps static-tool observations, expert findings, verifier rejections, and judge rejections as auditable first-class signals. Static tool hits remain candidates, but high-confidence promotable observations must be adjudicated and either become final findings or carry an explicit rejection reason. Final findings require exact file/line evidence, matched rule/tool provenance, actionable suggested code, and type-aware dedupe.

**Tech Stack:** Python worker, LangGraph node pipeline, SQLite trace tables, Semgrep/PMD/Checkstyle/Gitleaks/SpotBugs tool observations, React/TS backend APIs.

---

### Task 1: Preserve Candidate Rejections

**Files:**
- Modify: `worker/review_runtime.py`
- Modify: `worker/orchestration/nodes/verify_findings.py`
- Test: `scripts/verify_worker_orchestration_nodes.py`

**Steps:**
1. Add a detailed verifier function that returns `(accepted, rejected)`.
2. Keep the current `verify_findings()` compatibility wrapper returning only accepted findings.
3. Pass the detailed function into `make_verify_findings_node()`.
4. Store `verifier_rejections` and candidate counts in graph state.
5. Emit rejection reason counts in trace events.

### Task 2: Force Static Candidate Adjudication

**Files:**
- Modify: `worker/orchestration/nodes/judge_findings.py`
- Test: `scripts/verify_worker_orchestration_nodes.py`

**Steps:**
1. Mark diff-rejected tool observations as `rejected_not_on_diff`.
2. Promote all mapped high-confidence tool observations into candidate findings before final selection.
3. When a promoted candidate is dropped, mark the source observation `rejected_by_judge`.
4. Return `candidate_rejections` in graph state.
5. Add coverage metrics for verifier/judge/promoted/rejected counts.

### Task 3: Reduce Agent Candidate Loss

**Files:**
- Modify: `worker/prompts/builder.py`

**Steps:**
1. Increase per-agent candidate cap for complex PRs.
2. Tell experts to adjudicate high-confidence tool observations one by one.
3. Require Chinese output and precise line evidence to remain unchanged.

### Task 4: Add Generic Java Web Rule Coverage

**Files:**
- Modify: `config/static-rules/semgrep/java/jolt/rare-java-web-quality.yml`
- Modify: `worker/tools/tool_normalizer.py`
- Modify: `worker/orchestration/nodes/judge_findings.py`
- Test: `scripts/verify-static-rule-bundles.mjs`
- Test: `scripts/verify_worker_orchestration_nodes.py`

**Steps:**
1. Add generic Semgrep rules for SpEL injection, failure-default-allow, fixed cache key, BigDecimal.equals money comparison, weak Random in business/security decisions, ZIP/CSV/file response risks, and unsafe deserialization.
2. Map each new rule to a normalized category and primary platform rule.
3. Add the primary rules to promotable static-tool adjudication where missing.
4. Ensure suggested-code templates exist for newly promoted rules.

### Task 5: Verify First-Stage Quality Gate

**Commands:**
- `python3 scripts/verify_worker_orchestration_nodes.py`
- `node scripts/verify-static-rule-bundles.mjs`
- `npm test`

**Expected:**
- Worker node verification passes.
- Static rule bundle verification passes.
- Frontend/backend test suite remains green.
- Trace/coverage includes candidate acceptance/rejection counts.
