# Intent-Aware Precision Verification

Date: 2026-08-03

## Scope

This verification covers deterministic change-intent classification, diff causality, source counter-evidence for exception/null claims, advisory severity caps, same-file advisory aggregation, bound-rule recall protection, and unchanged mixed-intent behavior.

## Results

| Gate | Dataset | Precision | Recall | High-severity recall/accuracy | Duplicate/negative FP |
| --- | --- | ---: | ---: | ---: | ---: |
| `verify:intent-aware-precision` | 7 focused positive/negative cases | 1.0000 | 1.0000 | 1.0000 | 0.0000 duplicate rate |
| `verify:gold-eval` | 30 gold findings | 1.0000 | 1.0000 | 1.0000 | 0 false positives |
| `verify:real-prs` | 25 findings, 5 maintained real-PR fixtures | 1.0000 | 1.0000 | 1.0000 | 0 negative-MR false positives |

The focused gate also confirms that two distant naming findings in one file become one advisory with related locations. A real swallowed-failure case, a mixed-change SQL injection, and a bound-rule finding remain publishable. Rethrown exceptions, guarded null access, logging-only unchanged findings, and ordinary naming style are not published as defects.

## Recall Safety

- `unknown` and `mixed` ContextUnits keep normal review behavior.
- `behavior_preserving` only raises the causality requirement for free review.
- Bound Skill/Markdown findings bypass safe-intent suppression and continue through their evidence contract.
- Exact promoted tool evidence is preserved when it proves the changed sink.
- Sensitive logging is not treated as an ordinary logging-style advisory.

## Limitations

The repository does not contain the user's 25 Windows GLM 5.1 MR run artifacts or their manual labels. The results above are from maintained repository fixtures and deterministic focused cases, not a re-score of those 25 external runs. Import those artifacts into the real-PR evaluation dataset before using this report as evidence of production-model uplift on that population.
