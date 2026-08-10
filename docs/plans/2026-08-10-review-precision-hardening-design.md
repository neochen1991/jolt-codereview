# Review Precision Hardening Design

## Goal

Raise review precision by eliminating same-root duplicate findings, preventing publication outside the exact MR diff, and grouping distinct findings at one source location without destroying their independent semantics.

## Scope

This design applies to the `new-dev` review pipeline only. It does not import or depend on changes from `codex/review-engineering-controls`.

The implementation covers:

- exact changed-file and added-line scope validation, including Windows path normalization;
- fail-closed handling for missing or malformed patches;
- cross-agent canonical issue identity and deterministic clustering;
- a second idempotent cluster pass after tool promotion and before persistence;
- location-level presentation grouping while retaining distinct root-cause findings;
- real duplicate, off-diff, and unchanged-file quality metrics and gates.

## Design Principles

1. A publishable line-level finding must prove an exact causal anchor in the MR diff.
2. Nearby unchanged code is context, not evidence that the change introduced a defect.
3. Missing diff evidence produces `needs_review`, never a confirmed publishable issue.
4. Finding identity must not depend on agent, free-form title, evidence wording, or a model-selected rule identifier.
5. Same-root findings merge; different roots remain independently reviewable even when they share a line.
6. Presentation grouping must not corrupt evaluation, feedback, severity, or lifecycle identity.
7. Every merge and scope rejection must be observable and replay-deterministic.

## Exact Diff Scope

`DiffScope` is the single source of truth for changed paths, added lines, added text, and patch health. It normalizes Windows separators and diff prefixes while preserving the repository's canonical Git path casing.

Line-level findings and tool observations are publishable only when their canonical path is changed and their causal anchor is an exact added line. The existing hunk tolerance and automatic nearest-line relocation are removed from the publication path.

Explicit file-level rules may omit a line only when the file itself changed and the finding declares a supported file-level scope. Empty, missing, or malformed patches are recorded as unhealthy; affected findings remain diagnostic artifacts with `needs_review` disposition.

## Canonical Issue Identity

The v2 identity is derived from deterministic review semantics:

```text
canonical path + causal anchor or changed symbol + typed root cause + sink signature
```

Agent id, title text, evidence prose, and raw model rule id are excluded. Canonical rule families are fallback evidence, not the identity's primary source.

Clustering occurs after all experts have completed and again after promoted tool findings enter Judge. A retained primary preserves all merged agents, rules, evidence variants, source observations, and member fingerprints in `quality_trace`.

Distinct findings on the same line remain separate when their typed root cause, trigger, or sink differs. This protects cases such as SQL injection and unbounded query results on the same statement.

## Location Comment Groups

Persisted findings remain independent. Publishing and review presentation group selected findings by canonical `file_path:line_start`. A group renders one location heading and ordered sub-issues, while publish records and user feedback continue to reference each finding id.

## Metrics and Quality Gates

The evaluator derives duplicate groups from canonical identity rather than accepting a caller-provided empty list. Reports include:

- same-root duplicate count and rate;
- off-diff published count;
- unchanged-file published count;
- missing-patch suppression count;
- automatic relocation count, required to remain zero;
- precision, recall, and high-severity recall.

The maintained fixtures are regression evidence only. Production uplift on the Windows Minimax population requires importing and replaying the 25 labeled MR artifacts.

## Rollout

The change is delivered in deterministic layers: tests and scope contract, canonical identity, comment grouping, evaluation gates, then replay. Each layer has an independent rollback boundary. Exact scope and canonical identity become the production defaults only after focused and full regression gates pass.

## Acceptance Criteria

- cross-agent paraphrases of one root cause produce one final finding;
- different root causes at one line remain separate but render in one location group;
- line-level findings outside exact added lines are not published;
- findings and tool observations from unchanged files are not published;
- missing patches fail closed;
- Windows and POSIX paths resolve to the same canonical changed path;
- duplicate rate is computed from output data, not a hard-coded empty input;
- replay output and v2 fingerprints are deterministic;
- high-severity recall does not regress on maintained fixtures.
