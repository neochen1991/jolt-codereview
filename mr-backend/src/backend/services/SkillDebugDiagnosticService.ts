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

function variantSummary(detail: any, targetAgent: string, skillKey: string) {
  if (!detail) return null;
  const trace = Array.isArray(detail.trace) ? detail.trace : [];
  const llmCalls = Array.isArray(detail.llm_calls) ? detail.llm_calls : [];
  const toolCalls = Array.isArray(detail.tool_calls) ? detail.tool_calls : [];
  const findings = Array.isArray(detail.findings) ? detail.findings : [];
  const agentExecuted = trace.some((event: any) => event.event_type === "agent_started" && String(event.agent_id || "") === targetAgent);
  const skillEvents = trace.filter((event: any) => {
    if (event.event_type !== "skill_context_loaded" || String(event.agent_id || "") !== targetAgent) return false;
    const customSkills = eventPayload(event).custom_skills;
    return Array.isArray(customSkills) && customSkills.map(String).includes(skillKey);
  });
  const checkpoints = trace.filter((event: any) => String(event.event_type || "").includes("checkpoint") || String(event.event_type || "").includes("bound_skill"));
  return {
    status: detail.run?.status || detail.job?.status || "queued",
    run_id: detail.run?.id || null,
    agent_executed: agentExecuted,
    skill_loaded: skillEvents.length > 0,
    skill_event_count: skillEvents.length,
    checkpoints: {
      total: checkpoints.length,
      completed: checkpoints.filter((event: any) => !String(event.event_type || "").includes("skipped")).length,
      skipped: checkpoints.filter((event: any) => String(event.event_type || "").includes("skipped")).length
    },
    llm: { total: llmCalls.length, succeeded: llmCalls.filter((call: any) => statusSuccess(call.status)).length },
    tools: { total: toolCalls.length, succeeded: toolCalls.filter((call: any) => statusSuccess(call.status)).length },
    findings: findings.length,
    tokens: llmCalls.reduce((sum: number, call: any) => sum + Number(call.input_tokens || 0) + Number(call.output_tokens || 0), 0),
    duration_ms: llmCalls.reduce((sum: number, call: any) => sum + Number(call.duration_ms || 0), 0) + toolCalls.reduce((sum: number, call: any) => sum + Number(call.duration_ms || 0), 0)
  };
}

export class SkillDebugDiagnosticService {
  build(session: Record<string, any>, baseline: any, candidate: any) {
    const baselineFindings = new Map((baseline?.findings || []).map((finding: any) => [String(finding.dedupe_hash || finding.id), finding]));
    const candidateFindings = new Map((candidate?.findings || []).map((finding: any) => [String(finding.dedupe_hash || finding.id), finding]));
    const added = [...candidateFindings.keys()].filter((key) => !baselineFindings.has(key));
    const removed = [...baselineFindings.keys()].filter((key) => !candidateFindings.has(key));
    const unchanged = [...candidateFindings.keys()].filter((key) => baselineFindings.has(key));
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
        token_delta: Number(candidateSummary?.tokens || 0) - Number(baselineSummary?.tokens || 0),
        duration_delta_ms: Number(candidateSummary?.duration_ms || 0) - Number(baselineSummary?.duration_ms || 0)
      }
    };
  }
}
