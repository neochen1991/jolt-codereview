# Intent-Aware Review Precision Design

## Goal

Reduce false positives on behavior-preserving merge requests without weakening Skill and bound-standard coverage or losing high-severity recall.

## Confirmed Gaps

The V2 context planner already scopes source to changed hunks, enclosing symbols, and bounded semantic dependencies. The remaining precision problems are downstream:

- PR intent is summarized after Judge and cannot influence routing, candidate generation, or final selection.
- style categories such as naming and ordinary logging can be promoted as medium findings.
- broad catch detection infers exception swallowing from generated finding text instead of the catch body.
- counter-evidence recognizes only a few fixed null/resource patterns.
- semantic dedupe is strong near the same line but does not consistently aggregate repeated file-level style observations or differently worded findings with one root cause.

## Design Principles

1. Skill checkpoints and bound Markdown rules remain authoritative and must still be loaded and checked.
2. Change intent is evidence, not a switch that skips review.
3. Publish a defect only when the change introduces or worsens it; nearby unchanged code is context, not a new defect.
4. Deterministic source analysis takes precedence over LLM wording for null guards, catch behavior, severity caps, and dedupe.
5. Precision changes must be evaluated together with recall and high-severity recall.

## Architecture

### ContextUnit change intent

Each ContextUnit receives a `change_intent` record derived primarily from its patch:

```json
{
  "labels": ["refactor", "logging_only"],
  "semantic_delta": "behavior_preserving",
  "confidence": 0.9,
  "evidence": ["only logging statements were added"]
}
```

Supported labels are `behavior_change`, `bug_fix`, `refactor`, `rename_or_move`, `logging_only`, `comment_or_documentation`, `formatting`, `test_only`, `configuration_change`, `dependency_change`, `mixed`, and `unknown`.

The first implementation uses deterministic patch signals and remains conservative: ambiguous units are `unknown` or `mixed`, never silently classified as safe. The record is included in the expert prompt and quality trace.

### Diff causality

Findings gain a causal classification:

- `introduced`: the changed line creates the problem.
- `worsened`: the change expands an existing problem.
- `unchanged`: the problem exists in context but the change is behavior preserving.
- `mitigated`: the change adds a guard or otherwise reduces risk.
- `unknown`: available evidence cannot prove causality.

For behavior-preserving units, free-review findings require explicit source or tool evidence of `introduced` or `worsened`. Skill and bound-rule findings are still checked, but a final issue must satisfy the rule evidence contract against the changed behavior. Attribution or incomplete evidence may remain visible as `needs_review` according to existing recall-safe policy; it must not become a confirmed defect solely from proximity.

### Severity governance

Finding kind and severity are calibrated separately. Default category caps are:

- naming, comment, formatting, ordinary log-level or logging-style: `info`;
- broad catch without proven failure loss: `info`;
- exception swallowing with source-confirmed lost failure semantics: normal defect severity;
- sensitive-data logging and other security categories: unaffected.

An explicit Skill or bound-standard severity remains authoritative. Platform category caps apply to free review, generic profile rules, and tool observations that do not have an explicit bound policy.

### Counter-evidence

The verifier adds deterministic contradiction reasons for:

- a null guard that dominates the claimed unsafe use;
- `Objects.requireNonNull`, Optional, early return, or explicit throw protection;
- catch blocks that rethrow, wrap with the original cause, mark rollback, restore interrupt, record a failed state, or perform explicit compensation;
- a broad catch that is not exception swallowing.

`BROAD_EXCEPTION` and `SWALLOWED_EXCEPTION` become distinct semantic outcomes. Generated descriptions are never used as proof that the catch body swallows an exception.

### Dedupe and aggregation

Duplicates are clustered by canonical rule, typed root cause, primary symbol, and impact/sink. File-level style findings with the same canonical rule are aggregated into one advisory record with `related_locations`. Functional defects remain separate when triggers or sinks differ.

The retained finding preserves merged rules, agents, evidence, and locations so dedupe never makes evidence disappear silently.

## Data Flow

```text
fetch_mr
  -> prescan
  -> build_context (ContextUnit + change_intent)
  -> route_agents
  -> run_experts (intent included, Skill/standards unchanged)
  -> verify_findings (source counter-evidence)
  -> judge_findings (causality + severity caps + dedupe)
  -> critic_pass (high risk and precision-sensitive categories)
  -> finalize
```

## Testing Strategy

TDD regression fixtures cover:

- logging-only, rename, comment-only, and refactor ContextUnits;
- mixed changes where a real defect must still be found;
- normal null guards and genuine null dereferences;
- catch-and-rethrow, wrapped cause, rollback, interrupt restoration, explicit failure state, and true swallowed exceptions;
- naming and ordinary logging capped below publishable severity while sensitive logging remains publishable;
- repeated style findings aggregated per file and separate security sinks retained;
- bound Skill and Markdown rule coverage unchanged.

Quality gates report precision, recall, high-severity recall, false positives by intent/category, duplicate rate, and causal classification. The 25 Windows GLM 5.1 evaluation MRs should be imported as a labeled dataset when their artifacts are available; until then repository fixtures provide deterministic regression coverage.

## Acceptance Criteria

- normal null guards and reasonable catch blocks produce no final defect;
- naming/comment/ordinary logging findings do not appear as reviewer-visible issues by default;
- true swallowed exceptions and sensitive logging remain detectable;
- safe-intent classification never skips Skill or bound-rule execution;
- high-severity recall does not regress;
- overall recall decreases by no more than two percentage points on the maintained gold set;
- same-root duplicate rate is below five percent on the evaluation report;
- exact replay remains deterministic.
