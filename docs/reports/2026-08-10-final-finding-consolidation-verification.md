# Final Finding Consolidation Verification

Date: 2026-08-10

Branch: `codex/final-finding-consolidation`

Base: `68086b53`

Verified head: `14e3a778`

## Implemented behavior

- Runs one final semantic consolidation phase after Critic and final quality selection and before decision accountability and persistence.
- Sends compact summaries of all final findings to the configured LLM and accepts only groups of existing request-local IDs.
- Rejects invalid JSON, unsupported versions, unknown members, repeated members, overlapping groups, and malformed groups atomically.
- Merges accepted groups deterministically; the model cannot add findings or rewrite trusted finding content.
- Preserves severity, confidence, rules, agents, evidence, source observations, tool provenance, and related locations.
- Persists consolidation provenance in `quality_trace.final_consolidation`.
- Applies a final deterministic canonical issue guard before inserting `review_findings`.
- Fails open on disabled configuration, insufficient findings, budget exhaustion, timeout, provider failure, invalid response, malformed configuration, and merge invariant failure.
- Records input/output counts, merged counts, duplicate rates, tokens, duration, provider/model, and fallback reason.
- Reuses the existing model routing, capability payload, reasoning suppression, retry, token accounting, and exact replay path.

## Fresh verification evidence

### Model capability and payload checks

The worktree intentionally does not contain a copied `mr-backend/.venv`. The Python-only steps used the worktree interpreter, and the dependency-bearing DeepAgent step used the existing repository virtual environment:

```bash
PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_model_capabilities.py
PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_llm_model_payloads.py
PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_llm_findings_parser.py
PYTHONPATH=mr-backend/worker /Users/neochen/jolt-codereview/mr-backend/.venv/bin/python mr-backend/worker/tests/test_deepagent_model_adaptation.py
node scripts/verify-model-capability-config.mjs
```

Result: all five checks passed.

### Exact replay and worker quality

```bash
npm run verify:worker-exact-replay
npm run verify:worker-quality
```

Result:

- LLM execution envelope passed.
- Record/replay including `final_consolidation` passed without a second network call.
- Worker quality suite passed: 35 tests, 0 failures.

### Precision hardening gate

```bash
npm run verify:review-precision-hardening
```

Result: passed.

| Metric | Result |
|---|---:|
| consolidation input findings | 8 |
| consolidation output findings | 6 |
| duplicate rate before | 25% |
| duplicate rate after | 0% |
| same-line paraphrase merge rate | 100% |
| nearby same-root merge rate | 100% |
| false merge rate | 0% |
| output count invariant | passed |
| off-diff published findings | 0 |
| unchanged-file published findings | 0 |

The fixture also verifies that SQL injection is not merged with an unbounded query and that a production defect is not merged with a missing-test advisory.

### Build

```bash
npm run build
```

Result: common backend, MR backend TypeScript, frontend TypeScript, and Vite production build passed.

### Diff integrity

```bash
git diff --check 68086b53..HEAD
```

Result: passed with no whitespace errors.

## TDD evidence

The implementation was developed through observed red-green cycles:

- Missing contract module failed before protocol implementation.
- Missing deterministic merge function failed before merge implementation.
- Missing LLM invocation functions failed before the bounded exchange path was added.
- Missing pipeline call and decision reason failed before Judge integration.
- Missing defaults and quality metrics failed before configuration and gate implementation.
- Self-review added failing coverage for invalid configuration, router exceptions, persistent related locations, and duplicate-rate metrics before the fail-open hardening fix.

## External evaluation boundary

The repository and this macOS workspace do not contain the user's external Windows MiniMax 25-MR run artifacts, their manual labels, or a reproducible command that launches that exact population. Therefore this verification does not claim that production precision on those 25 MRs has already increased from 33%, nor does it claim a measured Windows P95 latency.

After deploying this branch to the Windows evaluation environment:

1. Re-run the same 25 labeled MRs with the same MiniMax model and configuration.
2. Export final findings and LLM call records.
3. Score them with the repository real-findings scorer or the existing external evaluator.
4. Confirm final duplicate rate below 3%, distinct-root false merge rate below 2%, review success on consolidation failures at 100%, and added P95 latency at most 45 seconds.

This external replay is production-population validation, not remaining implementation work.
