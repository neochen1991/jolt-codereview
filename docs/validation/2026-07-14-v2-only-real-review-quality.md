# v2-only Review Engine Real-task Validation

Date: 2026-07-14

Branch: `codex/v2-only-review-engine`

## Scope

This validation covers the v2-only review engine after removing the v1 runtime/rollback path and after applying the review-quality controls needed for real tasks:

- route only to bounded, relevant agents;
- batch v2 `ContextUnit` prompts without dropping any unit;
- cap coverage-retry fanout;
- keep replay/fingerprint metadata for reproducibility;
- surface real-task quality metrics in the workbench.

## Code changes validated

1. v2 is the only review context engine.
   - Removed v1 shadow/rollback surfaces from runtime behavior.
   - README and config examples now describe v2-only startup and quality knobs.

2. ContextUnit batching.
   - `build_context_units_prompt(...)` sends multiple structured ContextUnits in one LLM prompt.
   - LLM exchange metadata records the comma-joined ContextUnit IDs/checkpoints/hashes.
   - Executor backfills `context_unit_id`, `context_hash`, hunk IDs and semantic paths by explicit ID or file/line matching.
   - Default: `review_quality.context_units_per_llm_call = 6`, bounded to 1-10.

3. Coverage retry fanout cap.
   - Default: `review_quality.coverage_retry_context_units_limit = 2`.
   - Retry prefers full-source ContextUnits with dependencies.

4. Router precision cap.
   - Standard effort now routes to at most `routing.max_standard_agents = 6` agents by default.
   - Preferred order favors security/dependency/database/performance/coding/backend/test and avoids the previous broad 9-10 agent spread.

## Automated verification

Targeted verification already passed:

```bash
PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_context_planner.py
npm run verify:review-quality-v2
```

Full verification passed:

```bash
npm run verify
```

Notable gates included:

- `verify:real-prs`: precision 1.0, recall 1.0, high severity accuracy 1.0 on the existing labeled fixture set.
- `verify:real-pr-repeatability`: deterministic scorer result on the labeled real-pr set.
- `verify:review-quality-v2`: context metrics, planner, budget window, semantic graph, source tools, exact replay, evidence pack, dashboard and v2-only checks.
- `verify:v2-only-review-engine`: no v1 runtime fallback remnants in the scanned implementation surface.
- `verify:postgres-only-runtime`: no SQLite runtime remnants.

## Browser / real-task evidence

The app was tested in the browser at `http://127.0.0.1:9020` with the default local admin account.

### Real task A: apache/dubbo !16305

MR: `Fix CompositeInputStream close handling`

Observed before the router cap was added:

- Workbench loaded the real-task quality dashboard.
- v2 context path was active.
- Run showed fingerprinting/reproducibility in the UI.
- The run selected too many agents: 10 agents.
- It reached 30/30 LLM success with 0 findings before being stopped from the UI.

Assessment:

- This proved the v2 path and quality dashboard worked in a real GitHub MR.
- It also exposed a real quality problem: router over-selection created unnecessary cost and diluted precision.
- The router cap was added because of this live evidence.
- A post-fix rerun of !16305 could not be completed because the UI reported: `该 MR 已合入，不能再开始检视。`

### Real task B: apache/dubbo !16176

MR: `fix(remoting): stop ReconnectTimerTask when client is closed`

Post-fix run:

- Job: `job_583fd196ba1a492d`
- Run: `run_95e10d51ee9e4924`
- Progress observed: `AI 专家分析`
- Tool calls: 23
- LLM calls: 14
- LLM success: 14/14, 100%
- Skill calls: 11
- Agent messages: 7
- Participating agents: 6
- Findings while observed: 0
- Reproducibility: 14 LLM calls, fingerprint 100%, `fingerprinted`
- The run was then stopped from the UI to avoid continuing live LLM cost after the validation evidence was collected.

Assessment:

- Router precision control took effect: the observed real run used 6 agents instead of the previous 9-10.
- Context batching took effect: calls grew by agent/retry batch rather than exploding per ContextUnit.
- Replay/fingerprint metadata was complete for all observed LLM calls.
- No final precision/recall claim is made from this single run because there is no gold label for this MR.

## Quality impact assessment

Expected improvements that are directly supported by code and browser evidence:

- Precision should improve because irrelevant broad-agent fanout is capped and routed in a priority order.
- Cost and latency should improve because ContextUnits are batched and coverage retries are capped.
- Reproducibility is stronger because LLM calls carry replay/fingerprint metadata and the dashboard exposes fingerprint coverage.
- Recall should be safer than v1 because v2 keeps full-source ContextUnits, dependency hints, semantic paths and hunk IDs; batching explicitly asks the model to cover every unit instead of truncating to a single patch-only view.

Claims not made yet:

- No statistically valid recall/precision uplift is claimed yet.
- The two real-task browser checks prove runtime behavior and fix effectiveness, not benchmark-grade review quality.
- A 30+ paired MR gold-label evaluation is still required before saying precision/recall has objectively improved.

## Remaining risks / follow-up

1. Gold labels are still missing for the observed real tasks, so `v2 Quality` remains `unlabeled / 评估中`.
2. Some real-task context health can still be `blocked` when source fetch or coverage JSON is incomplete.
3. External dependency scanners were disabled in local validation because they timed out in this environment; this must be re-enabled in CI or a network-ready worker.
4. The browser showed an unrelated `skill-debug-demo` local fixture with stale/failed LLM metrics. That fixture should be reset or excluded from real-task validation reports.
5. A larger quality gate should run at least 30 paired real MRs with deterministic replay, gold labels, accepted/false-positive feedback and cost data.

## Verdict

The v2-only review engine is functionally validated for real-task invocation and the latest fixes address the concrete quality problem found during browser testing: excessive agent fanout.

The current evidence supports merging the v2-only implementation behind the documented config defaults. The honest next quality milestone is not more plumbing; it is a gold-labeled benchmark run that measures recall, precision, false positives and cost on a representative MR set.
