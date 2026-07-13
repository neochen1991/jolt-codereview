function payload(event: any): Record<string, any> {
  if (event?.payload_json && typeof event.payload_json === "object") return event.payload_json;
  try { return JSON.parse(String(event?.payload_json || "{}")); } catch { return {}; }
}

export class SkillDebugValidityService {
  evaluate(input: { session: Record<string, any>; baseline: any; candidate: any; diagnostics: Record<string, any> }) {
    const variants = [input.baseline, input.candidate].filter(Boolean);
    const trace = variants.flatMap((variant) => Array.isArray(variant?.trace) ? variant.trace : []);
    const toolCalls = variants.flatMap((variant) => Array.isArray(variant?.tool_calls) ? variant.tool_calls : []);
    const reasons: string[] = [];
    const degradedFetch = trace.some((event) => event.event_type === "github_fetch_error")
      || toolCalls.some((call) => String(call.status || "").includes("failed_degraded"));
    const fetchedFileCount = trace.filter((event) => event.event_type === "github_files")
      .reduce((sum, event) => sum + (Array.isArray(payload(event).files) ? payload(event).files.length : 0), 0);
    const candidate = input.diagnostics.candidate || {};
    if (degradedFetch) reasons.push("mr_input_fetch_degraded");
    if (!degradedFetch && fetchedFileCount === 0) reasons.push("no_reviewable_files");
    if (!candidate.agent_executed) reasons.push("target_agent_not_executed");
    if (!candidate.skill_loaded) reasons.push("target_skill_not_loaded");
    if (Number(candidate.checkpoints?.total || 0) === 0
      || Number(candidate.checkpoints?.completed || 0) + Number(candidate.checkpoints?.skipped || 0) < Number(candidate.checkpoints?.total || 0)) {
      reasons.push("checkpoint_evidence_incomplete");
    }
    if (Number(candidate.llm?.succeeded || 0) === 0) reasons.push("no_successful_target_llm_call");
    if (degradedFetch) return { contract: "skill_debug_validity_v1", conclusive: false, status: "degraded", reasons, fetched_file_count: fetchedFileCount };
    if (reasons.length) return { contract: "skill_debug_validity_v1", conclusive: false, status: "inconclusive", reasons, fetched_file_count: fetchedFileCount };
    return { contract: "skill_debug_validity_v1", conclusive: true, status: "completed", reasons: [], fetched_file_count: fetchedFileCount };
  }
}
