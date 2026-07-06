# Real Task Review Evaluation Set

This directory contains review-quality fixtures that are scored from real Jolt
review runs rather than from static sample findings.

Current scope:

- `real_gold_set.jsonl` starts with a production-style Java MR fixture that must
  already have a completed review run in the local database.
- `scripts/seed-real-prs.mjs` is the reproducible import path for adding fixed
  GitHub PR fixtures to the local MR backend queue.
- `npm run verify:split-full-regression` exercises the current Postgres-backed
  split-service review flow before scoring exported findings.
- `scripts/score_real_pr_reviews.py` scores precision, recall, and false
  positives against the gold labels.
- `npm run report:real-prs` renders a Markdown quality report with summary
  metrics, rule/MR gaps, weak evidence findings, and concrete action items.
- `npm run export:real-findings` exports the latest completed review findings
  for seeded real PR fixtures into `evaluation/real_findings.jsonl`.
- `npm run verify:real-pr-dataset` audits manifest/gold/finding structure and
  catches duplicate labels, missing MR ids, and malformed finding ids.
- `npm run verify:real-prs` gates current real-review quality and requires every
  finding to carry `evidence_score`, `consensus_agents`, and
  `quality_trace.critic_verdict`.
- `npm run verify:real-prs:target` is the final target gate for this uplift. It
  requires at least 4 MRs, at least 25 positive gold findings, at least 1
  negative MR, precision >= 0.80, recall >= 0.65, high-severity accuracy >=
  0.80, and zero negative false positives.

The set is intentionally small at first so the gate is executable. The target
state for the review-quality uplift is at least 4 real open-source PR fixtures,
at least 1 negative MR, and at least 25 manually reviewed gold findings.
Some target fixtures may start as curated offline labels with `source_url` and
`curated-offline-labels` tags when GitHub API access is unavailable; refresh
their cached PR payloads with `scripts/seed-real-prs.mjs` before treating the
metrics as a live runtime benchmark.

## Adding a Real PR Fixture

Create one manifest per PR in this directory. Use `.json` for active manifests:

```json
{
  "id": "spring-framework-12345",
  "repository": {
    "owner": "spring-projects",
    "repo": "spring-framework",
    "default_branch": "main"
  },
  "pull_number": 12345,
  "expected_gold_ids": ["spring-12345-001"],
  "tags": ["real-open-source", "backend"]
}
```

Use `fixture_type: "real_open_source"` for target-gate fixtures. Local baseline
fixtures may use `fixture_type: "local_fixture"` so their gold labels can be
audited without counting toward the 4 real open-source PR target.

Fetch and cache GitHub data without writing the database:

```bash
GITHUB_TOKEN=... node scripts/seed-real-prs.mjs
```

Use cached data only, useful for CI or offline reproduction:

```bash
node scripts/seed-real-prs.mjs --offline
```

Seed the local MR backend PostgreSQL database:

```bash
MR_CONFIG_PATH=$PWD/mr-backend/config.json \
GITHUB_TOKEN=... \
node scripts/seed-real-prs.mjs --write-db
```

After the worker completes those seeded review jobs, export the final findings
to `evaluation/real_findings.jsonl`:

```bash
MR_CONFIG_PATH=$PWD/mr-backend/config.json npm run export:real-findings
```

Then append manually reviewed labels to `evaluation/real_gold_set.jsonl`. Do not
mark a fixture as negative by adding empty expected findings only; negative MRs
must be represented in the gold set with `ground_truth: "negative"` and must
produce zero final findings.

Run the target gate when deciding whether the quality-uplift work is complete:

```bash
npm run verify:real-prs:target
```

Generate a reviewer-friendly report after exporting findings:

```bash
npm run report:real-prs
```

Read `docs/reports/real-pr-quality-report.md` before changing prompts or judge
thresholds. Fix `recall_gap` items by adding or improving detectors/examples;
fix `precision_gap` items by tightening required evidence or adding negative
examples; fix `weak_evidence` items by improving source quotes, tool backing, or
critic evidence.
