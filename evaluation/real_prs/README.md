# Real Task Review Evaluation Set

This directory contains review-quality fixtures that are scored from real Jolt
review runs rather than from static sample findings.

Current scope:

- `real_gold_set.jsonl` starts with a production-style Java MR fixture that must
  already have a completed review run in the local database.
- `scripts/evaluate-real-prs.mjs` exports the latest findings for each MR.
- `scripts/score_real_pr_reviews.py` scores precision, recall, and false
  positives against the gold labels.

The set is intentionally small at first so the gate is executable. Add real
open-source PR fixtures over time by appending manually reviewed labels to
`evaluation/real_gold_set.jsonl`.
