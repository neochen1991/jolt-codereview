# Cross-File Evidence and Cost Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve complex MR review quality by generating auditable cross-file evidence paths, closing the `BE-API-001` recall gap, and reducing repeated LLM context.

**Architecture:** Feed tree-sitter semantic graph data into Context Planner v2, enrich ContextUnits with dependency/evidence-path hints, synthesize conservative evidence paths after LLM output when validated static graph evidence exists, and scope rule batches to relevant context units. Keep Judge strict: cross-file conclusions without evidence paths remain needs-review or filtered.

**Tech Stack:** Python worker, tree-sitter-derived semantic graph, ContextUnit planner/executor, LangGraph worker nodes, Node/Python verification scripts, PostgreSQL-backed real run verification.

---

### Task 1: Add failing tests for Java cross-file evidence path

**Files:**
- Modify: `mr-backend/worker/tests/test_context_planner.py`
- Modify: `mr-backend/worker/tests/test_evidence_pack.py`

**Step 1: Write the failing test**

Add a Java-style controller/service graph fixture where:

- `PaymentAdminController.search()` calls `paymentQueryService.searchByUser(userId)`.
- `PaymentQueryService.searchByUser()` contains SQL string concatenation.
- The planned ContextUnit for the controller or service exposes a dependency/evidence hint linking the two files.

Assert:

- the ContextUnit has a dependency for the other file;
- a finding with `evidence_scope="cross_file"` and validated static dependency can receive a non-empty evidence path;
- a high-severity cross-file finding without a path remains needs-review.

**Step 2: Run test to verify it fails**

Run:

```bash
python3 mr-backend/worker/tests/test_context_planner.py
python3 mr-backend/worker/tests/test_evidence_pack.py
```

Expected: new cross-file evidence assertions fail before implementation.

### Task 2: Feed tree-sitter semantic graph into Context Planner

**Files:**
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/worker/orchestration/nodes/prescan.py`
- Modify: `mr-backend/worker/context/semantic_graph.py`
- Modify: `mr-backend/worker/context/context_planner.py`

**Step 1: Preserve tree-sitter graph in state**

Return a compact `semantic_graph_record` or `semantic_graph` from external static prescan, and store it in worker state before expert execution.

**Step 2: Merge semantic symbols**

Use tree-sitter functions/classes as fallback `changed_symbols` when repo index resolution is weak. This should improve `changed_symbol_resolution_rate` for changed Java methods/classes.

**Step 3: Add Java receiver-aware call edges**

Extend `semantic_graph_from_tree_sitter` so a call record with receiver/type hints can map `receiver.method()` to the target class method when available. If type is not certain, mark edge confidence as `heuristic`, not `typed`.

**Step 4: Run focused tests**

Run:

```bash
python3 mr-backend/worker/tests/test_semantic_graph.py
python3 mr-backend/worker/tests/test_context_planner.py
python3 mr-backend/worker/tests/test_context_metrics.py
```

Expected: planner tests pass and changed symbol metrics improve in fixture cases.

### Task 3: Synthesize conservative evidence_path from validated dependencies

**Files:**
- Modify: `mr-backend/worker/context/context_executor.py`
- Modify: `mr-backend/worker/orchestration/judging/evidence_pack.py`
- Modify: `mr-backend/worker/orchestration/judging/evidence_score.py`

**Step 1: Add synthesis helper**

When a finding lacks `evidence_path`, use the matched ContextUnit primary source plus validated `semantic_paths` or dependency hints to create a two-step path:

1. changed location;
2. related caller/callee/config/test location.

Only synthesize if file paths and line numbers are known.

**Step 2: Keep Judge strict**

Do not synthesize arbitrary paths from text. If no static dependency exists, preserve `cross_file_evidence_path_missing`.

**Step 3: Run evidence tests**

Run:

```bash
python3 mr-backend/worker/tests/test_context_planner.py
python3 mr-backend/worker/tests/test_evidence_pack.py
python3 mr-backend/worker/tests/test_evidence_score.py
```

Expected: cross-file finding with validated static dependency receives path credit; unsupported finding remains needs-review.

### Task 4: Fix `BE-API-001` recall for controller request validation

**Files:**
- Modify: `mr-backend/worker/tools/code_graph_rules.py` or backend rule extraction path found during implementation
- Modify: relevant backend/rule tests under `mr-backend/worker/tests/`

**Step 1: Write regression**

Create a controller method accepting `@RequestBody Map<String,Object>` without `@Valid` or a typed request DTO. Assert it produces a `BE-API-001` finding.

**Step 2: Implement minimal rule**

Detect controller methods with `@RequestBody Map`, raw `Map`, or missing validation annotations on request body inputs. Keep the rule narrow to avoid flagging typed DTOs already validated elsewhere.

**Step 3: Run rule tests**

Run the focused worker tests and the router policy verifier.

Expected: new BE rule regression passes.

### Task 5: Scope LLM context by agent/rule relevance

**Files:**
- Modify: `mr-backend/worker/orchestration/nodes/run_experts.py`
- Modify: `mr-backend/worker/context/context_executor.py`
- Modify: `mr-backend/worker/tests/test_skill_bound_review_contract.py`

**Step 1: Add context-unit filtering**

Before each bound-rule batch, select only ContextUnits whose primary file, dependency file, tool observation, or rule family is relevant to the current agent/batch.

**Step 2: Preserve Skill/rule context**

Do not remove Skill summaries, bound rules, or standards context. Only reduce source/diff ContextUnits.

**Step 3: Gate free review**

Skip or shrink free review when all bound rules for the agent are resolved and no high-risk unmatched context remains.

**Step 4: Run contract tests**

Run:

```bash
python3 mr-backend/worker/tests/test_skill_bound_review_contract.py
python3 scripts/verify_router_policy.py
```

Expected: bound-rule coverage remains complete; context payload size decreases in tests.

### Task 6: Re-run real complex MR and score quality/cost

**Files:**
- Modify: optional verification script under `scripts/` if needed

**Step 1: Run unit verification**

Run:

```bash
npm run verify:worker-quality
```

Expected: worker quality suite passes.

**Step 2: Run the complex Java fixture**

Use the same 10-file complex Java MR fixture and capture:

- run id;
- final finding count;
- Gold recall;
- cross-file evidence path count;
- input/output tokens;
- wall seconds.

**Step 3: Compare to baseline**

Baseline:

- Run: `run_12a864655a7c4703`
- Gold: 9/10
- Cross-file path count: 0
- Input tokens: ~519k
- Output tokens: ~127k
- Wall time: ~1896s

Expected:

- Gold 10/10;
- at least one real cross-file evidence path;
- lower token usage;
- no obvious Gold regression.
