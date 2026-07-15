# Recall-Safe Context and Judge Recovery Design

## Problem

Windows deployments using MiniMax 2.7 expose a recall regression in the strict review pipeline. The model can produce valid source-grounded findings while omitting or misattributing structured rule fields. The current pipeline treats those formatting and evidence gaps as proof that the finding is invalid:

- empty ContextUnit selection skips the LLM call;
- bound-rule or checkpoint mismatches discard findings before Judge;
- `secondary_test_advisory` removes findings without respecting severity;
- missing required bound evidence is always treated as a rejection;
- `unsupported_bound_claim` rejects claims even when direct source evidence exists.

The result is a precision-first pipeline that loses valid findings before they can be reviewed.

## Design Principles

1. Routing evidence ranks context; it does not prove that unmatched code is irrelevant.
2. Missing evidence is not counter-evidence.
3. Critical and high findings may only be hard-rejected by contradiction, invalid location, invalid structure, or confirmed duplication.
4. Model formatting differences must not determine recall.
5. Fallback context remains bounded and must never restore the previous all-context prompt.

## Context Selection

Context selection becomes a three-state decision:

- **Strong match:** use ContextUnits selected by rule evidence, tool evidence, or typed semantic dependency.
- **Uncertain:** when strict selection is empty, choose at most three changed-file ContextUnits ranked by patch relevance, symbol overlap, file type, and existing dependency confidence.
- **Irrelevant:** skip only when there is no changed source ContextUnit or the batch is provably inapplicable to the changed languages/files.

The fallback emits an explicit `context_units_fallback` trace event and remains subject to the normal token budget. Bound agents regain one budget-controlled free-review batch, and empty or unresolved bound batches may perform one coverage retry.

## Bound Rule Attribution

`bound_rule_mismatch`, `bound_skill_checkpoint_mismatch`, and missing batch attribution become soft attribution states:

- preserve the finding and its original `covered_rules`;
- add `rule_attribution_mismatch` or `rule_attribution_missing` verification flags;
- retain the originating batch label and expected IDs;
- send the candidate to Judge for reconciliation or `needs_review`;
- never pretend the candidate satisfied the current batch rule.

Skip markers remain separate from findings.

## Judge Severity Protection

`secondary_test_advisory` may prune only medium or lower findings. Critical and high test findings remain eligible for final selection or `needs_review`.

The same safety rule applies to soft evidence failures: a critical/high finding with a valid changed location and direct source evidence cannot be hard-rejected solely because a tool did not match or a required-evidence field is incomplete.

## Evidence Pack States

Bound evidence is classified into three states:

- **Absent:** no changed location and no source excerpt, trigger, semantic path, or tool observation. This may be rejected as `bound_required_evidence_absent`.
- **Insufficient:** direct evidence exists, but one or more required evidence elements are missing. This becomes `needs_review` with `bound_required_evidence_incomplete`.
- **Supported:** required evidence or an equivalent trusted chain exists. Continue through normal confirmation logic.

`unsupported_bound_claim` is no longer an unconditional rejection. It is rejected only when contradicted or when evidence is truly absent; otherwise it is retained for review.

## Evaluation

Regression tests must cover all five failure modes and must fail against the current implementation before production code changes.

Validation must include:

- focused ContextUnit, bound-rule, Judge, and evidence-pack tests;
- worker quality verification;
- an actual Worker run using the MiniMax-compatible configuration;
- positive Gold, cross-file Gold, and negative MR cases;
- candidate funnel comparison from expert output through final findings;
- token comparison proving the fallback did not restore all-context prompts.

The release gate requires no Gold recall regression, no critical/high candidate dropped for a soft reason, no unclassified Judge rejection, and a bounded fallback of at most three ContextUnits.
