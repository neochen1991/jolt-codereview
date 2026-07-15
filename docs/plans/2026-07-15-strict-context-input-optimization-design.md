# Strict Context Input Optimization Design

## Goal

Reduce irrelevant LLM input without weakening Skill or bound-rule enforcement. Every source ContextUnit sent to an expert must be justified by auditable rule evidence or a semantic dependency, while the complete Skill and project standard remain available.

## Approaches considered

1. **Path-family filtering**: keep Java/SQL/config files based on expert type. This is cheap but too broad and is the current source of 7-8/10 ContextUnit batches.
2. **Tool-only filtering**: send only files with a matching static-tool observation. This is precise but harms recall for defects that require semantic reasoning and have no static-tool hit.
3. **Evidence-or-semantic gating (selected)**: accept a ContextUnit when a current rule/checkpoint observation points to its primary/dependency file, or when its changed symbols/dependencies match rule/checkpoint evidence anchors. This keeps a second recall path while eliminating unconditional full-context fallback.

## Context selection

Each batch derives normalized target IDs from `rule_ids` or checkpoint IDs. Tool observations are normalized from `rule_id`, `tool_rule_id`, and `covered_rules`. A ContextUnit is selected only when:

- a matching observation points to the ContextUnit primary file or one of its dependency files; or
- the batch rule/checkpoint evidence text matches a changed symbol, dependency symbol, relation, or dependency path in the ContextUnit.

No file-family fallback is allowed. If no ContextUnit qualifies, the batch records `no_relevant_context_units` and does not make an expert LLM call.

## Tool observation scope

Before prompt construction, observations are filtered twice:

1. their normalized rule IDs intersect the current batch target IDs;
2. their file path belongs to the selected ContextUnit primary/dependency file set.

The batch agent receives only this filtered list. The original agent-level observations remain unchanged for other batches and audit artifacts.

## Stable prompt prefix

The expert request is split into two user messages:

- stable prefix: agent identity, complete Skill/standard text, invariant contracts, output schema guidance;
- dynamic body: current bound rules/checkpoints, ContextUnits, scoped symbols, scoped tool observations, examples, and suppression hints.

The stable prefix is serialized deterministically and placed before the dynamic body so OpenAI-compatible providers that support automatic prefix caching can reuse it. Providers without prefix caching behave identically.

## Input composition telemetry

Every expert request emits `llm_input_composition` with estimated tokens for:

- source code;
- dependency source;
- Skill/standard;
- tool observations;
- fixed instructions;
- patch and remaining dynamic metadata;
- total estimated prompt tokens.

The normal `llm_call` log continues to record the provider-reported actual input total. The composition event includes agent, batch, ContextUnit IDs, and stable-prefix hash for comparison across calls.

## Recall and failure handling

- Complete Skill and standard text is never truncated.
- Semantic matching uses structured symbols and dependency relations, not only filenames.
- Empty selection is explicit and auditable.
- Existing context, Skill contract, Judge, and Gold evaluation tests remain mandatory.
