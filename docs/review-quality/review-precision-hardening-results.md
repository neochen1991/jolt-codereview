# Review Precision Hardening Verification

Date: 2026-08-10

## Implemented Controls

- exact changed-file and added-line `DiffScope`, including Windows path normalization;
- fail-closed handling for missing patches, unchanged files, and context lines;
- no automatic semantic or nearest-line relocation;
- deterministic cross-agent `issue_v2` identity and clustering;
- a second cluster pass after tool promotion;
- independent same-line findings grouped into one publication location;
- automatic duplicate and scope-violation quality metrics in the main verification chain.

## Focused Regression Result

`npm run verify:review-precision-hardening` produced:

| Metric | Result |
| --- | ---: |
| Raw findings | 4 |
| Raw duplicate groups | 1 |
| Canonical findings | 3 |
| Final duplicate groups | 0 |
| Final duplicate rate | 0.0 |
| Scope rejections | 2 |
| Off-diff published | 0 |
| Unchanged-file published | 0 |
| Missing-patch published | 0 |
| Automatic relocations | 0 |

The fixture also confirms that two differently worded authorization findings from different agents merge, while SQL injection and unbounded query results on the same line remain independent findings.

## Existing Quality Gates

Fresh verification on 2026-08-10 passed:

- `npm run verify`: complete repository verification chain;
- `npm run build`: common backend, MR backend, and frontend;
- `npm run verify:worker-quality`: 35 Worker quality tests;
- `npm run verify:typed-judge-dedupe`;
- `npm run verify:intent-aware-precision`: precision 1.0, recall 1.0, high-severity recall 1.0 on focused fixtures;
- `npm run verify:gold-eval`: 30/30 gold findings, no false positives;
- `npm run verify:real-prs`: 25/25 findings across five maintained MR fixtures, no false positives;
- `npm run verify:review-location-grouping`: three findings rendered into two location groups.

## Validation Boundary

The repository still does not contain the external Windows Minimax 25-MR run artifacts or their manual labels. The implementation and maintained regression gates are complete, but the production-population precision increase from the reported 33% cannot be measured locally until those artifacts are exported and replayed. Maintained fixture precision must not be presented as the Windows Minimax result.
