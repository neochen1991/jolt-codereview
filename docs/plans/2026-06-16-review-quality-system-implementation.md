# Review Quality System Implementation Plan

**Goal:** Complete the model-agnostic review quality optimization and evaluate it with the Java benchmark MRs.

**Architecture:** Reuse the current worker graph and existing tables. Add structured rule metadata, feedback suppression hints, symbol-level context enrichment, stronger evidence scoring, and benchmark gates without adding new database columns.

**Tech Stack:** TypeScript backend/frontend, Python worker orchestration, PostgreSQL-compatible SQL, tree-sitter Java parser, Node/Python verification scripts.

---

### Task 1: Structured Rule Knowledge

**Files:**
- Modify: `worker/rules/markdown_rule_parser.py`
- Modify: `worker/rules/rule_loader.py`
- Test: `scripts/verify_quality_rule_registry.py`

**Steps:**
1. Add a parser that extracts `rule_id`, title, category, severity, required evidence, positive examples, negative examples, false-positive patterns, and fix guidance from rule documents.
2. Normalize missing fields to conservative defaults.
3. Add a verification script with representative Markdown rule sections.
4. Run `node scripts/run-python.mjs scripts/verify_quality_rule_registry.py`.

### Task 2: Feedback Suppression Hints

**Files:**
- Modify: `worker/orchestration/nodes/verify_findings.py`
- Modify: `worker/orchestration/nodes/judge_findings.py`
- Test: `scripts/verify_quality_rule_registry.py`

**Steps:**
1. Use existing `rule_precision_history.auto_suppress` and finding metadata to attach suppression reasons.
2. Ensure final trace records suppression and rule-health risk.
3. Do not hard-delete all candidates at first; downgrade or reject only when feedback says the same rule/agent is unhealthy.
4. Verify rejected candidates include clear reasons.

### Task 3: Symbol-Level Context Enrichment

**Files:**
- Modify: `worker/tools/tree_sitter_tool.py`
- Modify: `worker/context/symbol_resolver.py`
- Modify: `worker/orchestration/nodes/build_context.py`
- Modify: `worker/prompts/builder.py`
- Test: `scripts/verify_quality_symbol_context.py`

**Steps:**
1. Extract changed symbol summaries from code graph output.
2. Include symbol role, changed functions/classes, imports, call targets, and likely related tests.
3. Compact the symbol context into agent prompt `related_context`.
4. Verify generic Java/Spring/security/performance rules receive symbol context, not only DDD rules.

### Task 4: Evidence Quality Gate

**Files:**
- Modify: `worker/orchestration/nodes/judge_findings.py`
- Modify: `worker/orchestration/nodes/finalize.py`
- Test: `scripts/verify_quality_evidence_contract.py`

**Steps:**
1. Extend evidence contracts with source type and blocking/non-blocking decision hints.
2. Keep Phase 1 visible-only behavior for now, but record weak contracts as risk in `candidate_quality`.
3. Make run-level coverage include weak/partial contract counts and tool failure counts.
4. Verify contract summaries are present in final run coverage.

### Task 5: Benchmark MR Evaluation

**Files:**
- Modify: `scripts/evaluate-java-5mr-demo.mjs`
- Modify: `scripts/evaluate-java-complex-mr.mjs`
- Create: `scripts/verify-review-quality-system.mjs`

**Steps:**
1. Extend benchmark output with evidence-contract metrics.
2. Run the existing Java 5-MR and complex 10-file MR evaluation scripts against current data.
3. Add a single verification command that checks precision/recall style metrics and evidence-contract coverage.
4. Save a report under `docs/reports/`.

### Task 6: Final Verification

**Commands:**
- `npm run verify:quality-contract`
- `npm run verify:worker-orchestration`
- `npm run verify:java-conventions`
- `npm run verify:java-5mr`
- `npm run verify:java-complex-10file`
- `npm run build`

**Completion Criteria:**
- Final findings expose evidence contracts.
- Run coverage exposes evidence-contract summary.
- Rule documents can be parsed into structured rule metadata.
- Tree-sitter symbol context is available to generic review flow.
- Benchmark MR reports include evidence-contract and rule coverage metrics.
- All listed verification commands pass or any environment limitation is explicitly documented.
