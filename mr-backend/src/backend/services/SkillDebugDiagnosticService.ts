function statusSuccess(status: unknown) {
  return ["completed", "cache_hit"].includes(String(status || ""));
}

function eventPayload(event: any): Record<string, any> {
  const value = event?.payload_json;
  if (value && typeof value === "object") return value;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function semanticFindingKey(finding: any) {
  let coveredRules: unknown = finding?.covered_rules_json;
  try { if (typeof coveredRules === "string") coveredRules = JSON.parse(coveredRules); } catch { coveredRules = []; }
  const primaryRule = Array.isArray(coveredRules) ? String(coveredRules[0] || "") : "";
  return [finding?.file_path, finding?.line_start || finding?.line_end, primaryRule || finding?.rule_id || "", finding?.agent_id || ""].map(String).join("|");
}

function findingSignature(finding: any) {
  return [finding?.severity, finding?.title, finding?.problem_description, finding?.recommendation, finding?.evidence].map((value) => String(value || "").trim()).join("|");
}

function variantSummary(detail: any, targetAgent: string, skillKey: string) {
  if (!detail) return null;
  const trace = Array.isArray(detail.trace) ? detail.trace : [];
  const llmCalls = Array.isArray(detail.llm_calls) ? detail.llm_calls : [];
  const toolCalls = Array.isArray(detail.tool_calls) ? detail.tool_calls : [];
  const findings = Array.isArray(detail.findings) ? detail.findings : [];
  const targetAgentEvents = trace.filter((event: any) => String(event.agent_id || "") === targetAgent);
  const agentExecuted = targetAgentEvents.some((event: any) => event.event_type === "agent_started");
  const skillEvents = targetAgentEvents.filter((event: any) => {
    if (event.event_type !== "skill_context_loaded" || String(event.agent_id || "") !== targetAgent) return false;
    const customSkills = eventPayload(event).custom_skills;
    return Array.isArray(customSkills) && customSkills.map(String).includes(skillKey);
  });
  const targetSkillCheckpoints = targetAgentEvents.filter((event: any) => {
    const eventType = String(event.event_type || "");
    if (!eventType.includes("checkpoint") && !eventType.includes("bound_skill")) return false;
    const payload = eventPayload(event);
    const payloadSkills = Array.isArray(payload.custom_skills) ? payload.custom_skills.map(String) : [];
    return String(payload.skill_key || "") === skillKey || payloadSkills.includes(skillKey) || String(payload.checkpoint_id || "").startsWith(`${skillKey}:`);
  });
  const targetLlmCalls = llmCalls.filter((call: any) => String(call.agent_id || "") === targetAgent);
  const targetToolCalls = toolCalls.filter((call: any) => String(call.agent_id || "") === targetAgent);
  const targetFindings = findings.filter((finding: any) => String(finding.agent_id || "") === targetAgent);
  return {
    status: detail.run?.status || detail.job?.status || "queued",
    run_id: detail.run?.id || null,
    agent_executed: agentExecuted,
    skill_loaded: skillEvents.length > 0,
    skill_event_count: skillEvents.length,
    checkpoints: {
      total: targetSkillCheckpoints.length,
      completed: targetSkillCheckpoints.filter((event: any) => !String(event.event_type || "").includes("skipped")).length,
      skipped: targetSkillCheckpoints.filter((event: any) => String(event.event_type || "").includes("skipped")).length
    },
    llm: { total: targetLlmCalls.length, succeeded: targetLlmCalls.filter((call: any) => statusSuccess(call.status)).length },
    tools: { total: targetToolCalls.length, succeeded: targetToolCalls.filter((call: any) => statusSuccess(call.status)).length },
    findings: targetFindings.length,
    target_findings: targetFindings,
    attribution_scope: "target_agent_and_skill_checkpoints",
    tokens: targetLlmCalls.reduce((sum: number, call: any) => sum + Number(call.input_tokens || 0) + Number(call.output_tokens || 0), 0),
    duration_ms: targetLlmCalls.reduce((sum: number, call: any) => sum + Number(call.duration_ms || 0), 0) + targetToolCalls.reduce((sum: number, call: any) => sum + Number(call.duration_ms || 0), 0)
  };
}

export class SkillDebugDiagnosticService {
  build(session: Record<string, any>, baseline: any, candidate: any) {
    const baselineTargetFindings = (baseline?.findings || []).filter((finding: any) => String(finding.agent_id || "") === String(session.agent_key));
    const candidateTargetFindings = (candidate?.findings || []).filter((finding: any) => String(finding.agent_id || "") === String(session.agent_key));
    const baselineFindings = new Map(baselineTargetFindings.map((finding: any) => [semanticFindingKey(finding), finding]));
    const candidateFindings = new Map(candidateTargetFindings.map((finding: any) => [semanticFindingKey(finding), finding]));
    const added = [...candidateFindings.keys()].filter((key) => !baselineFindings.has(key));
    const removed = [...baselineFindings.keys()].filter((key) => !candidateFindings.has(key));
    const shared = [...candidateFindings.keys()].filter((key) => baselineFindings.has(key));
    const unchanged = shared.filter((key) => findingSignature(candidateFindings.get(key)) === findingSignature(baselineFindings.get(key)));
    const changed = shared.filter((key) => !unchanged.includes(key));
    const baselineSummary = variantSummary(baseline, session.agent_key, session.skill_key);
    const candidateSummary = variantSummary(candidate, session.agent_key, session.skill_key);
    return {
      contract: "production_review_pipeline_v1",
      snapshot_sha256: session.snapshot_sha256,
      head_sha: session.head_sha,
      mode: session.mode,
      baseline: baselineSummary,
      candidate: candidateSummary,
      target_executed: Boolean(candidateSummary?.agent_executed),
      target_not_executed_reason: candidateSummary?.agent_executed ? null : session.mode === "production_route" ? "production_route_did_not_select_target_agent" : "target_agent_did_not_start",
      comparison: {
        added: added.map((key) => candidateFindings.get(key)),
        removed: removed.map((key) => baselineFindings.get(key)),
        unchanged: unchanged.map((key) => candidateFindings.get(key)),
        changed: changed.map((key) => ({ before: baselineFindings.get(key), after: candidateFindings.get(key) })),
        token_delta: Number(candidateSummary?.tokens || 0) - Number(baselineSummary?.tokens || 0),
        duration_delta_ms: Number(candidateSummary?.duration_ms || 0) - Number(baselineSummary?.duration_ms || 0)
      }
    };
  }
}
