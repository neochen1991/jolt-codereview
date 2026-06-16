# Code Review Quality System Design

## Goal

Build a model-agnostic quality improvement system for MR review. The review result should be driven by rules, source context, tool evidence, code graph context, judging, and feedback loops instead of relying on any single LLM to both discover and validate issues.

## Current Constraints

- The worker already has expert routing, verifier, static tool observations, tree-sitter code graph findings, judge, candidate storage, and final finding trace fields.
- `review_findings` already stores `covered_rules_json`, `tool_provenance_json`, `source_observations_json`, and `quality_trace_json`.
- `review_runs.coverage_json` already stores run-level coverage and candidate-quality data.
- The first phase should avoid schema churn and should work for PostgreSQL-only deployment.

## Quality Principles

1. Final findings must be evidence-backed.
2. Rules, tools, code graph, source windows, and reviewer feedback should be first-class inputs.
3. Candidate generation and final judgment should remain separate.
4. Low-value style comments and blocking findings must be distinguishable.
5. Quality must be measurable per run and per project.
6. Windows tool failures and context gaps must be visible, not silent.

## Phase 1: Evidence Contract And Quality Trace

Each final finding should expose an evidence contract in `quality_trace_json`:

- `has_rule`: at least one covered rule or normalized rule id exists.
- `has_location`: file and line are available.
- `has_source_context`: source or evidence text is available for the target line.
- `has_tool_evidence`: static/tool/code-graph observation supports the issue.
- `has_recommendation`: remediation text exists.
- `has_suggested_code`: concrete suggested code exists.
- `missing`: list of missing evidence dimensions.
- `score`: normalized score from 0 to 1.
- `status`: `satisfied`, `partial`, or `weak`.

`review_runs.coverage_json` should summarize contract quality:

- final finding count.
- contract status counts.
- average evidence score.
- findings missing rules.
- findings missing tool evidence.
- findings missing suggested code.
- tool failures from the existing tool coverage data.

This phase does not block findings yet. It makes quality visible and measurable first.

## Phase 2: Structured Rule Knowledge

Rules should become structured records with:

- `rule_id`
- `title`
- `category`
- `severity`
- applicable languages and paths
- required evidence
- positive examples
- negative examples
- false-positive patterns
- fix guidance

False positives should be handled in the rule layer whenever possible instead of prompt-only suppression.

## Phase 3: Symbol-Level Context

Tree-sitter and repository context should serve the whole review pipeline:

- changed function and class identification.
- caller and callee context.
- interface and implementation links.
- related tests.
- framework annotations and configuration relationships.
- DDD layer role detection.

The worker should pass a focused context package to review agents and judges, not broad file snippets.

## Phase 4: Candidate And Judgment Separation

The review pipeline should evolve toward:

```text
MR diff
 -> multi-source candidate generation
 -> evidence verification
 -> conflict and false-positive suppression
 -> ranking and judgment
 -> final user-facing issue rendering
```

Candidate sources include static tools, tree-sitter rules, project rules, historical feedback, security/dependency scanners, test-gap checks, and semantic review agents.

## Phase 5: Evaluation And Feedback Loop

Quality evaluation should use project-owned benchmark cases:

- Java/Spring rules.
- DDD rules.
- SQL and transaction risks.
- security risks.
- test gaps.
- configuration risks.
- historical false positives.
- historical missed issues.
- Windows path and tool-timeout scenarios.
- large MR and multi-project concurrency scenarios.

Key metrics:

- final finding precision.
- effective recall.
- duplicate rate.
- source-context completeness.
- rule coverage.
- evidence-contract score.
- tool failure rate.
- reviewer accepted and false-positive feedback.

Reviewer actions should feed back into rule precision and suppression:

- submitted/accepted findings become positive signals.
- dismissed or false-positive findings become suppression candidates.
- edited comments become wording examples.

## Implementation Order

1. Add evidence contract into `quality_trace_json`.
2. Add run-level quality summary into `coverage_json`.
3. Show evidence contract in finding detail.
4. Add verification scripts for contract presence and run coverage.
5. Structure rule knowledge and false-positive suppression.
6. Expand tree-sitter context from DDD-only signals to generic symbol context.
7. Split candidate generation and judgment more explicitly.
8. Add benchmark evaluation gates.
