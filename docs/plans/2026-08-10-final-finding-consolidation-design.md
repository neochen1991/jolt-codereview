# Final Finding Consolidation Design

## Background

The current review pipeline applies deterministic deduplication at several stages, including cross-agent canonical issue clustering, same-line semantic deduplication, and post-tool canonical clustering. Real review output can still contain semantically equivalent findings when agents use different rules, wording, source anchors, or remediation descriptions. Later quality processing also means the last deterministic dedupe is not the final operation before persistence.

The system therefore needs a final global semantic consolidation pass after all findings have completed Judge, evidence calibration, and Critic processing, but before findings are persisted and published.

## Goals

- Merge final findings that describe the same root cause, impact, and remediation.
- Merge duplicates even when wording, rule IDs, agents, or nearby source anchors differ.
- Prevent the consolidation model from adding findings or rewriting trusted evidence.
- Preserve deterministic behavior, traceability, and fail-open review execution.
- Keep the additional latency and token cost bounded to one compact LLM call for normal reviews.

## Non-goals

- Discovering new defects during consolidation.
- Re-evaluating whether a finding is correct.
- Rewriting all finding titles, descriptions, recommendations, or suggested code.
- Replacing the existing deterministic deduplication stages.
- Merging distinct risks merely because they share a file or source line.

## Selected Approach

The LLM acts only as a global semantic clustering component. It receives compact summaries of final findings and returns groups of existing finding IDs. Application code validates those groups and performs all field merging deterministically.

This is preferred over allowing the LLM to rewrite the final finding list because it prevents evidence loss, severity drift, hallucinated findings, and untraceable content changes. A pairwise or embedding-first design is deferred because normal reviews contain at most tens of final findings and can be handled in one structured request.

## Pipeline Position

The consolidator runs after Critic and final quality selection, and before decision accountability and `review_findings` persistence:

```text
Judge selection
  -> deterministic dedupe
  -> evidence calibration
  -> Critic
  -> final quality selection
  -> FinalFindingConsolidator
  -> deterministic field merge
  -> FinalDedupeGuard
  -> decision accountability
  -> review_findings persistence
```

This position ensures the consolidator sees exactly the issues eligible for final output and that no later stage can reintroduce another finding before persistence.

## LLM Input Contract

Each finding receives a stable request-local ID and a compact semantic summary:

```json
{
  "id": "f_01",
  "file_path": "src/PaymentService.java",
  "line_start": 42,
  "line_end": 45,
  "title": "退款接口缺少幂等保护",
  "root_cause": "重复请求未使用业务幂等键",
  "impact": "可能造成重复退款",
  "recommendation": "基于 refundRequestId 建立幂等约束",
  "covered_rules": ["BE-IDEMPOTENCY-001"],
  "agent_id": "backend_agent",
  "evidence_excerpt": "..."
}
```

The request instructs the model to merge only when findings have the same substantive root cause, impact, and core remediation. Same-line findings with different risks, production defects and missing-test advisories, and independent authorization, idempotency, transaction, injection, or performance issues must remain separate.

## LLM Output Contract

The model may return only groups of existing IDs:

```json
{
  "version": "final_finding_consolidation_v1",
  "groups": [
    {
      "member_ids": ["f_01", "f_07"],
      "reason": "同一退款入口、同一幂等缺失根因和同一修复动作"
    }
  ]
}
```

Findings omitted from all groups remain unchanged. The model cannot add a finding, delete an ungrouped finding, select replacement content, or change finding fields.

## Validation Invariants

The response is accepted only when all invariants hold:

- The response version is supported.
- Every member ID exists in the input.
- Every input ID appears in at most one group.
- Every group has at least two distinct members.
- No empty or malformed group is accepted.
- Consolidation never increases the finding count.
- Deterministic merging preserves all rules, agents, source observations, tool provenance, and evidence variants.

Any invalid group or invariant violation rejects the entire response. Partial application is not allowed.

## Deterministic Merge Rules

The primary finding is selected by the existing review priority principles:

1. Strong tool evidence.
2. Higher severity.
3. Higher confidence.
4. More complete evidence.
5. Stable ID ordering as the final tie-breaker.

The merged finding uses these rules:

- `severity`: highest member severity.
- `confidence`: highest member confidence without artificial consensus inflation.
- `title`, `problem_description`, `recommendation`, `suggested_code`: primary finding content.
- `file_path`, `line_start`, `line_end`: primary causal location.
- `related_locations`: distinct secondary locations.
- `covered_rules`, `skipped_rules`, `merged_agent_ids`: deterministic set union.
- `evidence`: deduplicated evidence variants with a bounded total size.
- `source_observations`, `tool_provenance`: deterministic union.
- `dedupe_hash`: regenerated from the merged canonical identity.
- `quality_trace.final_consolidation`: records member IDs, primary ID, model reason, model metadata, duration, and fallback state.

After merging, the existing deterministic dedupe guard runs once more and asserts that no duplicate ID or canonical fingerprint remains.

## Runtime Configuration

```json
{
  "review": {
    "final_consolidation": {
      "enabled": true,
      "min_findings": 2,
      "max_findings": 30,
      "timeout_seconds": 45,
      "max_output_tokens": 4096,
      "temperature": 0,
      "fail_open": true
    }
  }
}
```

The implementation reuses the existing model router, capability adaptation, retry, replay, token accounting, and structured exchange path. Reasoning remains disabled for all providers. Normal reviews use one request. Reviews above `max_findings` are partitioned into deterministic file and location candidate buckets rather than sending an unbounded prompt.

## Failure Handling

The consolidator is fail-open. Timeout, unavailable providers, exhausted budget, invalid JSON, unknown IDs, overlapping groups, or invariant violations preserve the pre-consolidation findings and do not fail the review task.

Failures are recorded with one of these structured reasons:

- `timeout`
- `provider_unavailable`
- `budget_exhausted`
- `invalid_json`
- `unknown_member`
- `overlapping_groups`
- `invariant_violation`

## Observability

The `final_consolidation` operation records:

- input and output finding counts
- merged group and member counts
- duration and token usage
- model and provider
- fallback reason
- duplicate rate before and after consolidation
- group members, selected primary finding, and model reason

Candidate decision history records merged members as merged rather than rejected.

## Testing Strategy

### Unit tests

- Valid same-line semantic groups merge.
- Valid nearby-line and cross-file causal groups merge.
- Unknown, duplicated, overlapping, empty, and single-member groups fail atomically.
- Deterministic field merging preserves rules, evidence, agents, locations, and tool provenance.
- Model failure and budget exhaustion return the original list.

### Prompt contract tests

- Paraphrased same-root-cause findings merge.
- Different rules and agents do not prevent a valid merge.
- SQL injection and unbounded query findings on the same statement remain separate.
- Production defects and missing-test advisories remain separate.
- Independent authorization, idempotency, and transaction findings remain separate.

### Pipeline integration tests

- Consolidation runs after Critic and before persistence.
- Only consolidated findings are persisted.
- Invalid model output does not fail the review.
- Merged members receive explicit terminal decision accounting.
- Replay mode reproduces the same consolidation result.

### Evaluation acceptance criteria

- Same-file, same-line paraphrased duplicates: 100% merged.
- Clear nearby-line duplicates with the same root cause: at least 90% merged.
- Distinct-root-cause false merges: below 2%.
- Final duplicate rate across the 25-MR evaluation: below 3%.
- Review success when consolidation fails: 100%.
- P95 additional latency: at most 45 seconds.
- Output finding count never increases.

