# Cross-File Evidence and Cost Optimization Design

## Goal

Improve review quality for complex multi-file MRs by turning changed-file call relationships into explicit `evidence_path` records, while reducing repeated LLM work across agents and rule batches.

## Current Findings

The real complex Java MR run `run_12a864655a7c4703` matched 9 of 10 Gold findings, but every final finding had `evidence_path_len=0`, `semantic_paths_len=0`, and `cross_file_evidence_path=0`. Context Health showed `context_engine=v2`, all 10 changed files loaded, and `semantic_parse_rate=1.0`, but `changed_symbol_resolution_rate=0.1`. This means the tool is finding many file-local issues but is not producing auditable cross-file evidence chains.

The same run used 37 LLM calls, about 519k input tokens, about 127k output tokens, and hit `wall_seconds_exceeded`. The cost comes from repeatedly sending all context units through multiple agents, bound-rule batches, and free-review passes.

## Design

### 1. Build semantic evidence before LLM review

Prescan should expose tree-sitter graph data to the context planner, not only to static tool observations. The planner should use that graph to attach dependency hints to each ContextUnit. For Java, add a receiver-aware call edge resolver so calls such as `paymentQueryService.searchByUser(...)` can connect the controller call site to `PaymentQueryService.searchByUser`.

### 2. Auto-fill validated evidence paths

When a finding has validated semantic paths or a changed-file dependency hint but lacks `evidence_path`, the worker should synthesize a conservative path from changed location to related caller/callee/config/test node. Synthesized paths must be marked as generated from static semantic evidence and should not invent relationships absent from planner dependencies.

### 3. Close the BE-API-001 recall gap

The backend review path should reliably flag controller methods accepting `@RequestBody Map` or request bodies without validation annotations under `BE-API-001`. This should be covered by a focused regression test and by the complex MR smoke scorer.

### 4. Reduce repeated LLM work

Only send relevant ContextUnits to each agent/rule batch. If a bound rule has strong static tool evidence for a specific file/rule, skip or shrink the corresponding broad LLM pass and rely on Judge verification. Keep free review, but gate it when bound-rule coverage is already high and the agent has no unmatched high-risk context.

## Success Criteria

- Complex Java MR Gold recall improves from 9/10 to 10/10.
- At least the controller-to-service SQL issue produces a non-empty `evidence_path` or semantic path score.
- No high/critical cross-file finding is confirmed without a path.
- Final findings retain all Gold matches while reducing obvious duplicate/low-evidence findings.
- LLM input tokens decrease materially versus the 519k-token baseline for the same fixture.
