import { randomBytes } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import { formatMrReviewMarkdown, markdownFilename } from "../reviewMarkdown.js";
import { evaluateMrSizePolicy, evaluateMrSizePolicyWithFiles, mrSizeBlockedMessage, type MrSizePolicyDecision } from "../services/MrSizePolicy.js";
import { projectMrConcurrency } from "../services/QueuePolicy.js";
import type { FindingRow } from "../types.js";
import { CodeHubProvider } from "../vcs/CodeHubProvider.js";
import { GithubProvider } from "../vcs/GithubProvider.js";
import type { VcsProvider } from "../vcs/VcsProvider.js";
import type { BackendRouteContext } from "./context.js";

export function createReviewRoutes(ctx: BackendRouteContext): Route[] {
  const {
    all,
    get,
    db,
    config,
    runWorkerOnce,
    repoConfig,
    riskScore,
    verifyGitHubSignature,
    verifyCodeHubSignature,
    normalizeCodeHubWebhookPayload,
    codehubRepoMatches,
    bearerToken,
    currentUserId,
    ensureProjectRole,
    ensureProjectCapability,
    ensureProjectWrite,
    auditLog,
    syncProject,
    publishFindings,
    mrSyncService,
    projectRepository,
    repositoryRepository,
    mergeRequestRepository,
    reviewJobRepository,
    skillDebugSessionRepository,
    agentRepository,
    ruleDocumentRepository,
    auditRepository,
    reviewQueueService,
    skillDebugSnapshotService,
    skillDebugPolicyService,
    skillDebugDiagnosticService,
    skillDebugValidityService,
    sensitiveDataRedactionService,
    effectiveConfig,
    feedbackLearningService
  } = ctx;

  function projectIdForMr(mrId: string) {
    const row = get<{ project_id: string }>(`
      SELECT r.project_id
      FROM merge_requests mr
      JOIN repositories r ON r.id = mr.repository_id
      WHERE mr.id = $1
    `, [mrId]);
    return row?.project_id ?? "";
  }

  function projectIdForRun(runId: string) {
    const row = get<{ project_id: string }>(`
      SELECT r.project_id
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE rr.id = $1
    `, [runId]);
    return row?.project_id ?? "";
  }

  function ensureProjectRead(projectId: string, req: { headers: Record<string, any> }) {
    return ensureProjectRole(projectId, currentUserId(req), "observer");
  }

  function ensureMrRead(mrId: string, req: { headers: Record<string, any> }) {
    const projectId = projectIdForMr(mrId);
    if (!projectId) return notFound();
    return ensureProjectRead(projectId, req);
  }

  function ensureRunRead(runId: string, req: { headers: Record<string, any> }) {
    const projectId = projectIdForRun(runId);
    if (!projectId) return notFound();
    return ensureProjectRead(projectId, req);
  }

  function normalizeLegacyEvidenceReasonText(value: unknown) {
    if (typeof value !== "string" || !value.includes("evidence_not_in_source")) return value;
    return value
      .replace(/被过滤[:：]evidence_not_in_source/g, "证据未直接引用源码：已标记为 low_evidence_match，当前版本不再因此过滤")
      .replace(/evidence_not_in_source/g, "low_evidence_match");
  }

  function normalizeLegacyEvidenceTraceRow<T extends Record<string, any>>(row: T): T {
    return {
      ...row,
      summary: normalizeLegacyEvidenceReasonText(row.summary),
      payload_json: normalizeLegacyEvidenceReasonText(row.payload_json)
    };
  }

  function compareRunsForMr(mrId: string, limit = 200) {
    const runs = all<{ id: string; review_job_id: string; started_at: string }>(`
      SELECT rr.id, rr.review_job_id, rr.started_at
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      WHERE rj.merge_request_id = $1 AND rj.execution_kind = 'production_review'
      ORDER BY rr.started_at DESC
      LIMIT 2
    `, [mrId]);
    if (runs.length < 2) return { base_run: runs[1] ?? null, head_run: runs[0] ?? null, added: [], resolved: [], retained: [] };
    const [headRun, baseRun] = runs;
    const head = all<FindingRow>("SELECT * FROM review_findings WHERE review_run_id = $1 ORDER BY severity DESC, confidence DESC LIMIT $2", [headRun.id, limit]);
    const base = all<FindingRow>("SELECT * FROM review_findings WHERE review_run_id = $1 ORDER BY severity DESC, confidence DESC LIMIT $2", [baseRun.id, limit]);
    const headByHash = new Map(head.map((finding) => [finding.dedupe_hash, finding]));
    const baseByHash = new Map(base.map((finding) => [finding.dedupe_hash, finding]));
    return {
      base_run: baseRun,
      head_run: headRun,
      added: head.filter((finding) => !baseByHash.has(finding.dedupe_hash)),
      resolved: base.filter((finding) => !headByHash.has(finding.dedupe_hash)),
      retained: head.filter((finding) => baseByHash.has(finding.dedupe_hash))
    };
  }

  function providerFor(repository: { provider: string }, effectiveConfig: any): VcsProvider | null {
    if (repository.provider === "github") return new GithubProvider(effectiveConfig ?? config);
    if (repository.provider === "codehub") return new CodeHubProvider(effectiveConfig ?? config);
    return null;
  }

  function parseMetadataJson(value: unknown): Record<string, unknown> {
    if (!value) return {};
    if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
    try {
      const parsed = JSON.parse(String(value));
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
    } catch {
      return {};
    }
  }

  function hasSyncedAdditions(row: Record<string, unknown>) {
    if (row.additions !== undefined) return true;
    const metadata = parseMetadataJson(row.metadata_json ?? row.metadata);
    return metadata.additions !== undefined || metadata.added_lines !== undefined || metadata.addedLines !== undefined;
  }

  function mrSizePolicyHint(row: Record<string, unknown>, effectiveConfig: any) {
    const decision = evaluateMrSizePolicy(row, effectiveConfig);
    const knownAdditions = hasSyncedAdditions(row);
    if (!knownAdditions) {
      return {
        added_lines: null,
        max_added_lines_per_mr: decision.maxAddedLines,
        size_policy_state: "unknown",
        size_policy_message: `开始检视时将按变更文件统计新增行数，超过 ${decision.maxAddedLines} 行会停止检视`
      };
    }
    if (!decision.allowed) {
      return {
        added_lines: decision.addedLines,
        max_added_lines_per_mr: decision.maxAddedLines,
        size_policy_state: "over_limit",
        size_policy_message: `已同步新增 ${decision.addedLines} 行，超过项目阈值 ${decision.maxAddedLines} 行；点击开始检视会被拦截`
      };
    }
    return {
      added_lines: decision.addedLines,
      max_added_lines_per_mr: decision.maxAddedLines,
      size_policy_state: "within_limit",
      size_policy_message: `已同步新增 ${decision.addedLines} 行，项目阈值 ${decision.maxAddedLines} 行；开始检视时会按文件变更复核`
    };
  }

  function terminalMrMessage(status: string, action: string) {
    const label = status === "merged" ? "已合入" : "已关闭";
    return `该 MR ${label}，不能再${action}。`;
  }

  async function ensureMergeRequestOpenForAction(mrId: string, action: string) {
    const current = mergeRequestRepository.findById(mrId);
    if (!current) return notFound();
    if (["merged", "closed"].includes(current.review_status)) {
      return { statusCode: 400, error: "mr_not_open", message: terminalMrMessage(current.review_status, action) };
    }
    try {
      const remote = await mrSyncService.refreshMergeRequestStatusById(mrId);
      if (remote.ok && remote.terminal_status) {
        return { statusCode: 400, error: "mr_not_open", message: terminalMrMessage(remote.terminal_status, action) };
      }
    } catch {
      return null;
    }
    return null;
  }

  async function evaluateMrSizeWithRemoteFiles(
    mr: Record<string, unknown>,
    repository: Record<string, unknown>,
    effectiveConfig: any
  ): Promise<MrSizePolicyDecision> {
    const metadataDecision = evaluateMrSizePolicy(mr, effectiveConfig);
    if (!metadataDecision.allowed) return metadataDecision;
    const provider = providerFor({ provider: String(repository.provider || "") }, effectiveConfig);
    if (!provider) return metadataDecision;
    try {
      const files = await provider.fetchFiles({
        repository: repository as any,
        number: Number(mr.number),
        externalId: String(mr.external_mr_id || ""),
        headSha: String(mr.latest_head_sha || "")
      });
      return evaluateMrSizePolicyWithFiles(mr, files, effectiveConfig);
    } catch {
      return metadataDecision;
    }
  }

  function countByKind(items: Array<{ kind: string }>): Record<string, number> {
    return items.reduce<Record<string, number>>((acc, item) => {
      acc[item.kind] = (acc[item.kind] ?? 0) + 1;
      return acc;
    }, {});
  }

  function parseRecord(value: unknown): Record<string, any> {
    if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, any>;
    if (typeof value !== "string" || !value.trim()) return {};
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }

  function stringList(value: unknown): string[] {
    return Array.isArray(value)
      ? value.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
  }

  function skillStage(eventType: string): string {
    if (eventType === "skill_context_loaded" || eventType === "agent_profile_loaded") return "loaded";
    if (eventType === "skill_deepagents_invoked" || eventType === "deepagents_bounded_node") return "deepagents";
    if (eventType === "skill_llm_context_used" || eventType === "bound_skill_started" || eventType === "bound_skill_checked") return "llm";
    if (eventType === "bound_batch_findings_rejected") return "filtered";
    if (eventType === "bound_rule_coverage_low" || eventType === "bound_rule_coverage_retry_completed") return "retry";
    return "recorded";
  }

  function parseSkillBatchLabel(label: unknown) {
    const raw = String(label || "");
    const prefix = "bound_skill:";
    if (!raw.startsWith(prefix)) return { skill_key: "", checkpoint_id: "" };
    const body = raw.slice(prefix.length).replace(/:coverage_retry$/, "");
    const firstColon = body.indexOf(":");
    if (firstColon < 0) return { skill_key: body, checkpoint_id: "" };
    return { skill_key: body.slice(0, firstColon), checkpoint_id: body.slice(firstColon + 1) };
  }

  function normalizeSkillCalls(events: Array<Record<string, any>>): Array<Record<string, any>> {
    const skillEventTypes = new Set([
      "agent_profile_loaded",
      "deepagents_bounded_node",
      "skill_context_loaded",
      "skill_deepagents_invoked",
      "skill_llm_context_used",
      "bound_skill_started",
      "bound_skill_checked",
      "bound_batch_findings_rejected",
      "bound_rule_coverage_low",
      "bound_rule_coverage_retry_completed"
    ]);
    const rows: Array<Record<string, any>> = [];
    for (const event of events) {
      const eventType = String(event.event_type || "");
      if (!skillEventTypes.has(eventType)) continue;
      const payload = parseRecord(event.payload_json);
      const assets = Array.isArray(payload.skill_assets) ? payload.skill_assets.filter((item: unknown) => item && typeof item === "object") as Array<Record<string, any>> : [];
      const skills = Array.from(new Set([
        ...stringList(payload.skills),
        ...stringList(payload.custom_skills),
        ...assets.map((asset) => String(asset.skill_key || "").trim()).filter(Boolean)
      ]));
      if (!skills.length && !assets.length) continue;
      const assetPathsBySkill = assets.reduce<Record<string, string[]>>((acc, asset) => {
        const key = String(asset.skill_key || "").trim();
        const path = String(asset.asset_path || "").trim();
        if (!key || !path) return acc;
        acc[key] = [...(acc[key] || []), path];
        return acc;
      }, {});
      const skillKeys = skills.length ? skills : ["skill_bundle"];
      for (const skillKey of skillKeys) {
        const parsedLabel = parseSkillBatchLabel(payload.batch_label);
        const assetPaths = assetPathsBySkill[skillKey] || [];
        rows.push({
          id: `${String(event.id || event.event_id || event.created_at || event.timestamp || eventType)}:${skillKey}:${rows.length}`,
          created_at: event.created_at || event.timestamp,
          span_id: event.span_id,
          span_key: event.span_key,
          agent_id: event.agent_id,
          event_type: eventType,
          stage: skillStage(eventType),
          status: eventType === "skill_deepagents_invoked" || eventType === "skill_llm_context_used" ? "called" : "loaded",
          skill_key: skillKey,
          custom: stringList(payload.custom_skills).includes(skillKey),
          asset_count: assetPaths.length,
          asset_paths: assetPaths,
          tools: stringList(payload.tools),
          batch_label: payload.batch_label || "",
          rule_id: payload.rule_id || "",
          checkpoint_id: payload.checkpoint_id || parsedLabel.checkpoint_id || "",
          rejected_count: Number(payload.rejected_count || 0),
          rejected_reasons: stringList(payload.rejected_reasons),
          rejected_items: Array.isArray(payload.rejected_items) ? payload.rejected_items : [],
          skill_context_chars: Number(payload.skill_context_chars || 0),
          summary: event.summary
        });
      }
    }
    return rows;
  }

  function boundReviewCoverageFromRun(run: Record<string, any> | undefined) {
    const coverage = parseRecord(run?.coverage_json);
    const candidateQuality = parseRecord(coverage.candidate_quality);
    return parseRecord(candidateQuality.bound_review_coverage ?? coverage.bound_review_coverage);
  }

  function contextHealthFromRun(run: Record<string, any> | undefined) {
    const coverage = parseRecord(run?.coverage_json);
    const health = parseRecord(coverage.context_health);
    return Object.keys(health).length ? health : {
      version: "context_health_v1",
      context_engine: "unknown",
      status: "unavailable"
    };
  }

  function v2ValidationForRun(run: Record<string, any> | undefined) {
    const runId = String(run?.id || "");
    const empty = {
      status: "v2_provisional",
      pair_count: 0,
      distinct_mr_count: 0,
      minimum_distinct_mrs: 30,
      missing_evidence: ["minimum_30_distinct_paired_mrs", "dual_reviewed_gold_complete"],
      baseline: {},
      candidate: {},
      gate: {}
    };
    if (!runId) return empty;
    const scope = get<Record<string, any>>(`
      SELECT repo.project_id
      FROM review_runs rr
      JOIN review_jobs j ON j.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = j.merge_request_id
      JOIN repositories repo ON repo.id = mr.repository_id
      WHERE rr.id = $1
    `, [runId]);
    const projectId = String(scope?.project_id || "");
    if (!projectId) return empty;
    const pairs = get<Record<string, any>>(`
      SELECT COUNT(*) AS pair_count, COUNT(DISTINCT merge_request_id) AS distinct_mr_count
      FROM review_quality_shadow_pairs
      WHERE project_id = $1 AND status = 'completed'
    `, [projectId]) || {};
    const rollback = get<Record<string, any>>(`
      SELECT status, trigger, error_message, created_at, updated_at
      FROM review_quality_rollback_events
      WHERE project_id = $1
      ORDER BY created_at DESC
      LIMIT 1
    `, [projectId]);
    const evaluations = all<Record<string, any>>(`
      SELECT id, report_json, created_at
      FROM evaluation_reports
      WHERE project_id = $1
      ORDER BY created_at DESC
      LIMIT 20
    `, [projectId]);
    const latest = evaluations
      .map((row) => ({ row, report: parseRecord(row.report_json) }))
      .find((item) => String(item.report.schema_version || "").startsWith("review_quality_evaluation_"));
    const report = latest?.report || {};
    let status = "v2_provisional";
    if (rollback?.status === "rollback_pending") status = "rollback_pending";
    else if (rollback?.status === "rolled_back") status = "v1_rolled_back";
    else if (report.validation_status === "verified") status = "v2_verified";
    else if (report.validation_status === "rollback_required") status = "rollback_pending";
    return {
      status,
      pair_count: Number(pairs.pair_count || 0),
      distinct_mr_count: Number(pairs.distinct_mr_count || 0),
      minimum_distinct_mrs: 30,
      missing_evidence: Array.isArray(report.missing_evidence) ? report.missing_evidence : empty.missing_evidence,
      baseline: parseRecord(report.baseline),
      candidate: parseRecord(report.candidate),
      gate: parseRecord(report.gate),
      evaluation_report_id: latest?.row.id || "",
      evaluated_at: report.generated_at || latest?.row.created_at || "",
      rollback: rollback || {}
    };
  }

  function reviewQualityForRun(run: Record<string, any> | undefined) {
    const runId = String(run?.id || "");
    const empty = {
      context_health: contextHealthFromRun(run),
      candidate_recall: { value: null, metric_type: "candidate_funnel_retention", generated: 0, verifier_accepted: 0 },
      verify_rejection_reasons: [],
      judge_rejection_reasons: [],
      published_precision: { value: null, accepted: 0, false_positive: 0, labeled: 0, confidence: "unlabeled" },
      skill_checkpoint_metrics: boundReviewCoverageFromRun(run),
      reproducibility: { status: "unavailable", llm_call_count: 0, fingerprint_complete_rate: null, exact_replay_ready: false },
      v2_validation: v2ValidationForRun(run),
      unresolved_candidates: []
    };
    if (!runId) return empty;
    const candidates = all<Record<string, any>>(`SELECT * FROM candidate_findings WHERE review_run_id = $1 ORDER BY created_at`, [runId]);
    const generated = new Set(candidates.map((row) => String(row.dedupe_hash || "")).filter(Boolean)).size;
    const verifierAccepted = new Set(candidates.filter((row) => row.stage === "verifier" && row.status === "accepted").map((row) => String(row.dedupe_hash || ""))).size;
    const reasonsFor = (stage: string) => {
      const counts = new Map<string, number>();
      for (const row of candidates.filter((item) => item.stage === stage && ["rejected", "merged"].includes(String(item.status)))) {
        const details = Array.isArray(parseJsonValue(row.decision_reason_json)) ? parseJsonValue(row.decision_reason_json) : [];
        for (const detail of details) {
          const code = String((detail as Record<string, any>)?.code || "judge_unclassified_rejection");
          counts.set(code, (counts.get(code) || 0) + 1);
        }
      }
      return [...counts.entries()].map(([code, count]) => ({ code, count })).sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
    };
    const feedback = get<Record<string, any>>(`
      SELECT
        SUM(CASE WHEN uf.feedback_type = 'accepted' THEN 1 ELSE 0 END) AS accepted,
        SUM(CASE WHEN uf.feedback_type = 'false_positive' THEN 1 ELSE 0 END) AS false_positive
      FROM review_findings rf
      LEFT JOIN user_feedback uf ON uf.finding_id = rf.id
      WHERE rf.review_run_id = $1
    `, [runId]) || {};
    const accepted = Number(feedback.accepted || 0);
    const falsePositive = Number(feedback.false_positive || 0);
    const labeled = accepted + falsePositive;
    const llmCalls = all<Record<string, any>>(`SELECT l.* FROM llm_call_records l JOIN agent_trace_spans s ON s.id = l.span_id WHERE s.review_run_id = $1 ORDER BY l.created_at`, [runId]);
    const fingerprintComplete = llmCalls.filter((row) => row.seed !== null && row.seed !== undefined && row.request_hash && row.response_hash).length;
    const replayRecords = Number(get<Record<string, any>>(`
      SELECT COUNT(DISTINCT exchange.cache_key) AS count
      FROM llm_call_records call
      JOIN agent_trace_spans span ON span.id = call.span_id
      JOIN llm_exchange_records exchange
        ON exchange.cache_key = call.cache_key
       AND (exchange.expires_at IS NULL OR exchange.expires_at = '' OR NULLIF(exchange.expires_at, '')::timestamptz > CURRENT_TIMESTAMP)
      WHERE span.review_run_id = $1
    `, [runId])?.count || 0);
    const replayKeys = new Set(llmCalls.map((row) => String(row.cache_key || "")).filter(Boolean));
    const exactReplayReady = replayKeys.size > 0 && replayRecords === replayKeys.size;
    const judgeHashes = new Set(candidates.filter((row) => row.stage === "judge").map((row) => String(row.dedupe_hash || "")));
    const unresolved = candidates.filter((row) => row.stage === "verifier" && row.status === "accepted" && !judgeHashes.has(String(row.dedupe_hash || ""))).slice(0, 50);
    return {
      context_health: contextHealthFromRun(run),
      candidate_recall: { value: generated ? verifierAccepted / generated : null, metric_type: "candidate_funnel_retention", generated, verifier_accepted: verifierAccepted },
      verify_rejection_reasons: reasonsFor("verifier"),
      judge_rejection_reasons: reasonsFor("judge"),
      published_precision: { value: labeled ? accepted / labeled : null, accepted, false_positive: falsePositive, labeled, confidence: labeled >= 30 ? "measured" : labeled ? "low_sample" : "unlabeled" },
      skill_checkpoint_metrics: boundReviewCoverageFromRun(run),
      reproducibility: {
        status: !llmCalls.length ? "no_llm_calls" : fingerprintComplete === llmCalls.length ? (exactReplayReady ? "replay_ready" : "fingerprinted") : "partial",
        llm_call_count: llmCalls.length,
        fingerprint_complete_rate: llmCalls.length ? fingerprintComplete / llmCalls.length : null,
        exact_replay_ready: exactReplayReady,
        stored_exchange_count: replayRecords,
        replayed_call_count: llmCalls.filter((row) => row.replay_source === "recorded_response").length
      },
      v2_validation: v2ValidationForRun(run),
      unresolved_candidates: unresolved.map((row) => ({ id: row.id, dedupe_hash: row.dedupe_hash, title: row.title, file_path: row.file_path, line_start: row.line_start, stage: row.stage, status: row.status }))
    };
  }

  function compactRejectedItems(value: unknown) {
    if (!Array.isArray(value)) return [];
    return value.slice(0, 20).map((item) => {
      const row = parseRecord(item);
      const contract = parseRecord(row.bound_evidence_contract);
      return {
        title: row.title || "",
        file_path: row.file_path || "",
        line_start: row.line_start ?? null,
        line_end: row.line_end ?? null,
        covered_rules: stringList(row.covered_rules),
        skipped_rules: stringList(row.skipped_rules),
        rejected_reasons: stringList(row.rejected_reasons),
        contract_status: contract.status || "",
        false_positive_matches: stringList(contract.false_positive_matches),
        missing_required_evidence: stringList(contract.missing_required_evidence)
      };
    });
  }

  function skillKeyForTraceRow(row: Record<string, any>) {
    const payload = parseRecord(row.payload_json);
    const parsed = parseSkillBatchLabel(payload.batch_label);
    return String(payload.skill_key || parsed.skill_key || row.skill_key || "").trim();
  }

  function checkpointIdForTraceRow(row: Record<string, any>) {
    const payload = parseRecord(row.payload_json);
    const parsed = parseSkillBatchLabel(payload.batch_label);
    return String(payload.checkpoint_id || parsed.checkpoint_id || payload.rule_id || "").trim();
  }

  function buildSkillTracePayload(run: Record<string, any>, events: Array<Record<string, any>>, llmCalls: Array<Record<string, any>>) {
    const coverage = boundReviewCoverageFromRun(run);
    const coverageItems = Array.isArray(coverage.items) ? coverage.items.filter((item: unknown) => parseRecord(item).type === "skill_checkpoint").map(parseRecord) : [];
    const skills = new Map<string, Record<string, any>>();
    const ensureSkill = (skillKey: string) => {
      const key = skillKey || "skill_bundle";
      if (!skills.has(key)) {
        skills.set(key, {
          skill_key: key,
          checkpoint_count: 0,
          checked_count: 0,
          hit_count: 0,
          skipped_count: 0,
          rejected_count: 0,
          retry_count: 0,
          checkpoints: []
        });
      }
      return skills.get(key)!;
    };
    const checkpointsByKey = new Map<string, Record<string, any>>();
    for (const item of coverageItems) {
      const skillKey = String(item.skill_key || "skill_bundle");
      const checkpointId = String(item.checkpoint_id || item.rule_id || "");
      const skill = ensureSkill(skillKey);
      const checkpoint = {
        agent_id: item.agent_id || "",
        batch_label: item.batch_label || "",
        checkpoint_id: checkpointId,
        checked: Boolean(item.checked),
        hit: Boolean(item.hit),
        skipped: Boolean(item.skipped),
        finding_count: Number(item.finding_count || 0),
        rejected_count: Number(item.rejected_count || 0),
        retry_count: Number(item.retry_count || 0),
        retry_hit: Boolean(item.retry_hit),
        events: [],
        rejected_items: []
      };
      checkpointsByKey.set(`${skillKey}:${checkpointId}`, checkpoint);
      skill.checkpoints.push(checkpoint);
      skill.checkpoint_count += 1;
      if (checkpoint.checked) skill.checked_count += 1;
      if (checkpoint.hit) skill.hit_count += 1;
      if (checkpoint.skipped) skill.skipped_count += 1;
      skill.rejected_count += checkpoint.rejected_count;
      skill.retry_count += checkpoint.retry_count;
    }
    const traceEvents = events.map((row) => {
      const payload = parseRecord(row.payload_json);
      const skillKey = skillKeyForTraceRow(row);
      const checkpointId = checkpointIdForTraceRow(row);
      const normalized = {
        id: row.id || row.event_id || "",
        created_at: row.created_at,
        span_id: row.span_id,
        span_key: row.span_key,
        agent_id: row.agent_id,
        event_type: row.event_type,
        stage: skillStage(String(row.event_type || "")),
        summary: normalizeLegacyEvidenceReasonText(row.summary),
        skill_key: skillKey,
        checkpoint_id: checkpointId,
        batch_label: payload.batch_label || "",
        rejected_count: Number(payload.rejected_count || 0),
        rejected_reasons: stringList(payload.rejected_reasons),
        rejected_items: compactRejectedItems(payload.rejected_items)
      };
      if (skillKey) ensureSkill(skillKey);
      const checkpoint = checkpointsByKey.get(`${skillKey}:${checkpointId}`);
      if (checkpoint) {
        checkpoint.events.push(normalized);
        if (normalized.rejected_items.length) checkpoint.rejected_items.push(...normalized.rejected_items);
      }
      return normalized;
    });
    const skillItems: Array<Record<string, any>> = Array.from(skills.values()).map((skill: Record<string, any>) => ({
      ...skill,
      checkpoints: (skill.checkpoints || []).sort((a: Record<string, any>, b: Record<string, any>) => String(a.checkpoint_id).localeCompare(String(b.checkpoint_id)))
    }));
    skillItems.sort((a, b) => String(a.skill_key).localeCompare(String(b.skill_key)));
    return {
      run_id: run.id,
      summary: {
        required_count: Number(coverage.required_count || 0),
        skill_checkpoint_count: Number(coverage.skill_checkpoint_count || coverageItems.length || 0),
        checked_count: Number(coverage.checked_count || 0),
        hit_count: Number(coverage.hit_count || 0),
        skipped_count: Number(coverage.skipped_count || 0),
        rejected_count: Number(coverage.rejected_count || 0),
        coverage_rate: Number(coverage.coverage_rate || 0),
        resolution_rate: Number(coverage.resolution_rate || 0),
        llm_call_count: llmCalls.length,
        llm_success_count: llmCalls.filter((call) => ["completed", "cache_hit"].includes(String(call.status || ""))).length
      },
      skills: skillItems,
      events: traceEvents,
      llm_calls: llmCalls
    };
  }

  function boundedQueryLimit(url: URL, key: string, defaultValue: number, maxValue: number) {
    const value = Number(url.searchParams.get(key) || defaultValue);
    if (!Number.isFinite(value) || value <= 0) return defaultValue;
    return Math.min(Math.floor(value), maxValue);
  }

  function boundedQueryOffset(url: URL, key = "offset", maxValue = 100000) {
    const value = Number(url.searchParams.get(key) || 0);
    if (!Number.isFinite(value) || value <= 0) return 0;
    return Math.min(Math.floor(value), maxValue);
  }

  function truthyQuery(value: string | null) {
    return ["1", "true", "yes", "on"].includes(String(value || "").toLowerCase());
  }

  function unifiedReviewLogs(mrId: string, runId?: string | null) {
    const runs = all<Record<string, any>>(`
      SELECT rr.* FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      WHERE rj.merge_request_id = $1 AND rj.execution_kind = 'production_review'
      ORDER BY rr.started_at DESC
    `, [mrId]);
    const selectedRun = runId ? runs.find((run) => run.id === runId) : runs[0];
    const jobs = reviewJobRepository.listByMergeRequest(mrId) as Array<Record<string, any>>;
    const items: Array<Record<string, any> & { kind: string; timestamp: string }> = [];

    for (const job of jobs) {
      items.push({
        kind: "review_job",
        id: job.id,
        timestamp: String(job.created_at ?? ""),
        status: job.status,
        summary: `检视任务创建：${job.status}`,
        merge_request_id: job.merge_request_id,
        head_sha: job.head_sha,
        effort_level: job.requested_effort_level,
        priority: job.priority,
        attempt: job.attempt
      });
      if (job.updated_at) {
        items.push({
          kind: "review_job_status",
          id: job.id,
          timestamp: String(job.updated_at),
          status: job.status,
          summary: `检视任务状态更新：${job.status}`,
          locked_by: job.locked_by,
          heartbeat_at: job.heartbeat_at,
          error_message: job.error_message
        });
      }
    }

    if (selectedRun) {
      items.push({
        kind: "review_run",
        id: selectedRun.id,
        timestamp: String(selectedRun.started_at ?? ""),
        status: selectedRun.status,
        summary: `检视运行开始：${selectedRun.status}`,
        review_job_id: selectedRun.review_job_id,
        head_sha: selectedRun.head_sha,
        analysis_mode: selectedRun.analysis_mode,
        risk_snapshot_json: selectedRun.risk_snapshot_json
      });
      if (selectedRun.completed_at) {
        items.push({
          kind: "review_run_completed",
          id: selectedRun.id,
          timestamp: String(selectedRun.completed_at),
          status: selectedRun.status,
          summary: `检视运行结束：${selectedRun.status}`,
          report_summary: selectedRun.report_summary,
          budget_used_json: selectedRun.budget_used_json,
          quality_metrics_json: selectedRun.quality_metrics_json
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT e.*, s.span_key, s.agent_id, s.status AS span_status
        FROM agent_trace_events e
        JOIN agent_trace_spans s ON s.id = e.span_id
        WHERE s.review_run_id = $1
        ORDER BY e.created_at
      `, [selectedRun.id])) {
        items.push(normalizeLegacyEvidenceTraceRow({
          kind: "trace_event",
          id: row.id,
          timestamp: row.created_at,
          status: row.span_status,
          summary: row.summary,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          event_type: row.event_type,
          payload_json: row.payload_json
        }));
      }

      for (const row of normalizeSkillCalls(items.filter((item) => item.kind === "trace_event"))) {
        items.push({
          ...row,
          kind: "skill_call",
          timestamp: row.created_at,
          summary: `${row.agent_id || row.span_key || "agent"} ${row.status} ${row.skill_key}`
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT msg.*, s.span_key, s.agent_id
        FROM agent_messages msg
        JOIN agent_trace_spans s ON s.id = msg.span_id
        WHERE s.review_run_id = $1
        ORDER BY msg.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "agent_message",
          id: row.id,
          timestamp: row.created_at,
          status: "recorded",
          summary: row.content_summary,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          from_agent: row.from_agent,
          to_agent: row.to_agent,
          role: row.role,
          artifact_id: row.artifact_id
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT t.*, s.span_key, s.agent_id
        FROM tool_call_records t
        JOIN agent_trace_spans s ON s.id = t.span_id
        WHERE s.review_run_id = $1
        ORDER BY t.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "tool_call",
          id: row.id,
          timestamp: row.created_at,
          status: row.status,
          summary: row.output_summary || row.args_summary || row.tool_name,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          tool_name: row.tool_name,
          tool_version: row.tool_version,
          args_summary: row.args_summary,
          input_ref_json: row.input_ref_json,
          output_summary: row.output_summary,
          output_ref_json: row.output_ref_json,
          duration_ms: row.duration_ms
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT l.*, s.span_key, s.agent_id
        FROM llm_call_records l
        JOIN agent_trace_spans s ON s.id = l.span_id
        WHERE s.review_run_id = $1
        ORDER BY l.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "llm_call",
          id: row.id,
          timestamp: row.created_at,
          status: row.status,
          summary: `${row.provider}/${row.model} ${row.status}`,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          provider: row.provider,
          model: row.model,
          request_id: row.request_id,
          prompt_hash: row.prompt_hash,
          input_tokens: row.input_tokens,
          output_tokens: row.output_tokens,
          duration_ms: row.duration_ms
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT m.*, s.span_key, s.agent_id
        FROM mcp_call_records m
        JOIN agent_trace_spans s ON s.id = m.span_id
        WHERE s.review_run_id = $1
        ORDER BY m.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "mcp_call",
          id: row.id,
          timestamp: row.created_at,
          status: row.status,
          summary: row.response_summary || row.request_summary || `${row.server_name}.${row.tool_name}`,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          server_name: row.server_name,
          tool_name: row.tool_name,
          request_summary: row.request_summary,
          response_summary: row.response_summary,
          duration_ms: row.duration_ms
        });
      }

      for (const row of all<Record<string, any>>("SELECT * FROM review_artifacts WHERE review_run_id = $1 ORDER BY created_at", [selectedRun.id])) {
        items.push({
          kind: "artifact",
          id: row.id,
          timestamp: row.created_at,
          status: "recorded",
          summary: row.name,
          artifact_type: row.artifact_type,
          name: row.name,
          storage_uri: row.storage_uri,
          sha256: row.sha256,
          size_bytes: row.size_bytes,
          metadata_json: row.metadata_json
        });
      }
    }

    items.sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)) || String(left.kind).localeCompare(String(right.kind)));
    return {
      mr_id: mrId,
      run_id: selectedRun?.id ?? null,
      latest_job: jobs[0] ?? null,
      runs: runs.map((run) => ({
        id: run.id,
        review_job_id: run.review_job_id,
        status: run.status,
        started_at: run.started_at,
        completed_at: run.completed_at,
        analysis_mode: run.analysis_mode
      })),
      counts: countByKind(items),
      items
    };
  }

  function parseJsonValue(value: unknown): any {
    if (typeof value !== "string") return value;
    try { return JSON.parse(value); } catch { return value; }
  }

  function debugJobDetail(jobId: string | null | undefined) {
    if (!jobId) return null;
    const job = reviewJobRepository.findById(jobId) as Record<string, any> | undefined;
    if (!job) return null;
    const run = get<Record<string, any>>("SELECT * FROM review_runs WHERE review_job_id = $1 ORDER BY started_at DESC LIMIT 1", [jobId]);
    const runId = String(run?.id || "");
    const trace = runId ? all<Record<string, any>>(`SELECT e.*, s.span_key, s.agent_id FROM agent_trace_events e JOIN agent_trace_spans s ON s.id=e.span_id WHERE s.review_run_id=$1 ORDER BY e.created_at`, [runId]) : [];
    const llmCalls = runId ? all<Record<string, any>>(`SELECT l.*, s.span_key, s.agent_id FROM llm_call_records l JOIN agent_trace_spans s ON s.id=l.span_id WHERE s.review_run_id=$1 ORDER BY l.created_at`, [runId]) : [];
    const toolCalls = runId ? all<Record<string, any>>(`SELECT t.*, s.span_key, s.agent_id FROM tool_call_records t JOIN agent_trace_spans s ON s.id=t.span_id WHERE s.review_run_id=$1 ORDER BY t.created_at`, [runId]) : [];
    const findings = runId ? all<Record<string, any>>("SELECT * FROM review_findings WHERE review_run_id=$1 ORDER BY created_at", [runId]) : [];
    return {
      job: { ...job, debug_context_json: undefined },
      run: run || null,
      trace,
      llm_calls: llmCalls,
      tool_calls: toolCalls,
      findings,
      skill_trace: buildSkillTracePayload(run || {}, trace.map(normalizeLegacyEvidenceTraceRow), llmCalls)
    };
  }

  function debugSessionDetail(session: Record<string, any>) {
    const baseline: any = debugJobDetail(session.baseline_job_id);
    const candidate: any = debugJobDetail(session.candidate_job_id);
    const statuses = [baseline?.job?.status, candidate?.job?.status].filter(Boolean).map(String);
    const active = statuses.some((status) => ["queued", "fetching", "pre_scanning", "reviewing", "judging", "running"].includes(status));
    const failed = statuses.some((status) => ["failed", "dead_letter"].includes(status));
    const cancelled = statuses.length > 0 && statuses.every((status) => status === "cancelled");
    const preservedTerminalStatus = ["stale_head", "timed_out", "expired"].includes(String(session.status)) ? String(session.status) : null;
    let derivedStatus = session.status === "cancelled" ? "cancelled" : preservedTerminalStatus || (active ? "running" : failed ? "failed" : cancelled ? "cancelled" : statuses.length ? "completed" : session.status);
    const diagnostics = skillDebugDiagnosticService.build({ ...session, status: derivedStatus }, baseline, candidate);
    const validity = !active && derivedStatus === "completed"
      ? skillDebugValidityService.evaluate({ session, baseline, candidate, diagnostics })
      : parseJsonValue(session.validity_json);
    if (!active && derivedStatus === "completed" && validity.status) derivedStatus = String(validity.status);
    if (!active && ["completed", "degraded", "inconclusive"].includes(derivedStatus)) {
      skillDebugSessionRepository.updateValidity(session.id, derivedStatus, validity);
    } else if (derivedStatus !== session.status) {
      skillDebugSessionRepository.updateStatus(session.id, derivedStatus);
    }
    if (!active) skillDebugSessionRepository.updateComparison(session.id, diagnostics.comparison);
    return sensitiveDataRedactionService.redact({
      session: {
        ...session,
        status: derivedStatus,
        snapshot_json: undefined,
        snapshot: parseJsonValue(session.snapshot_json),
        comparison: parseJsonValue(session.comparison_json)
      },
      baseline,
      candidate,
      diagnostics,
      validity,
      publish_guard: "skill_debug.publish_forbidden"
    }) as Record<string, unknown>;
  }

  function ensureSkillDebugSessionAccess(session: Record<string, any>, actorId: string) {
    if (!ensureProjectRole(session.project_id, actorId, "project_admin")) return null;
    const denied = ensureProjectCapability(session.project_id, actorId, "run_skill_debug");
    if (denied) return denied;
    if (session.requested_by !== actorId) return { statusCode: 403, error: "forbidden", message: "Skill developers can only access their own debug sessions" };
    return null;
  }

  async function createSkillDebugSession(input: Record<string, unknown>, actorId: string, forcedProjectId?: string, frozenSnapshot?: Record<string, any>, frozenInputArtifact?: Record<string, any>) {
    skillDebugSessionRepository.expireDue();
    const mrId = String(input.mr_id || "").trim();
    const mr = mergeRequestRepository.findById(mrId) as Record<string, any> | undefined;
    if (!mr) return notFound();
    const repo = repositoryRepository.findById(mr.repository_id) as Record<string, any> | undefined;
    if (!repo || (forcedProjectId && repo.project_id !== forcedProjectId)) return notFound();
    const denied = ensureProjectCapability(repo.project_id, actorId, "run_skill_debug");
    if (denied) return denied;
    const skillKey = String(input.skill_key || frozenSnapshot?.skill?.skill_key || "").trim();
    const skillVersion = String(input.skill_version || frozenSnapshot?.skill?.version || "").trim();
    const agentKey = String(input.agent_key || frozenSnapshot?.agent?.agent_key || "").trim();
    const mode = String(input.mode || "targeted");
    const effortLevel = String(input.effort_level || "standard");
    if (!skillKey || !agentKey) return badRequest("skill_key and agent_key are required");
    if (!["targeted", "production_route"].includes(mode)) return badRequest("mode must be targeted or production_route");
    const projectEffectiveConfig = await effectiveConfig(repo.project_id);
    const policyDenied = skillDebugPolicyService.checkCreate(repo.project_id, actorId, projectEffectiveConfig);
    if (policyDenied) {
      auditLog({ userId: actorId, projectId: repo.project_id, action: "skill_debug.quota_rejected", resourceType: "skill_debug_session", summary: policyDenied.error });
      return policyDenied;
    }
    const debugPolicy = skillDebugPolicyService.resolve(projectEffectiveConfig);
    const sameInput = input.same_input === true;
    const requestedHeadSha = sameInput ? String(input.expected_head_sha || "") : String(mr.latest_head_sha || "");
    if (sameInput && (!requestedHeadSha || !frozenInputArtifact || !String(input.input_artifact_sha256 || ""))) {
      return badRequest("same_input rerun requires the frozen head and input artifact");
    }
    let snapshotResult: { snapshot: Record<string, unknown>; snapshot_sha256: string };
    try {
      snapshotResult = frozenSnapshot
        ? { snapshot: frozenSnapshot, snapshot_sha256: String(input.snapshot_sha256 || "") || sha1(JSON.stringify(frozenSnapshot)) }
        : skillDebugSnapshotService.build({
            projectId: repo.project_id,
            mergeRequest: mr,
            repository: repo,
            skillKey,
            skillVersion,
            agentKey,
            effectiveConfig: projectEffectiveConfig
          });
    } catch (error) {
      return badRequest((error as Error).message);
    }
    const sessionId = id("skill_debug");
    const expiresAt = new Date(Date.now() + debugPolicy.retention_days * 86400_000).toISOString();
    const session = skillDebugSessionRepository.create({
      id: sessionId,
      projectId: repo.project_id,
      repositoryId: repo.id,
      mergeRequestId: mr.id,
      headSha: requestedHeadSha,
      skillKey,
      skillVersion: String((snapshotResult.snapshot.skill as Record<string, any>)?.version || skillVersion),
      agentKey,
      mode: mode as "targeted" | "production_route",
      effortLevel,
      requestedBy: actorId,
      snapshot: snapshotResult.snapshot,
      snapshotSha256: snapshotResult.snapshot_sha256,
      bundleSha256: String((snapshotResult.snapshot.skill as Record<string, any>)?.bundle_sha256 || ""),
      inputArtifact: frozenInputArtifact || null,
      inputArtifactSha256: String(input.input_artifact_sha256 || ""),
      expiresAt
    }) as Record<string, any>;
    const baseContext = {
      kind: "skill_debug", mode, session_id: sessionId, project_id: repo.project_id,
      skill_key: skillKey, skill_version: session.skill_version, agent_key: agentKey,
      mr_id: mr.id, head_sha: requestedHeadSha, requested_by: actorId,
      publish_allowed: false, consistency_contract: "production_review_pipeline_v1",
      snapshot_sha256: snapshotResult.snapshot_sha256, snapshot: snapshotResult.snapshot,
      max_duration_seconds: debugPolicy.max_duration_seconds, replay_mode: sameInput ? "same_input" : "latest_head",
      snapshot_mode: "frozen", trace_level: "full", llm_replay: String(input.llm_replay || "record"),
      input_artifact_sha256: String(input.input_artifact_sha256 || ""),
      expires_at: expiresAt
    };
    const baseline = mode === "targeted" ? reviewQueueService.enqueueDebug({
      mergeRequestId: mr.id, headSha: requestedHeadSha, priority: Number(mr.risk_score || 0), effortLevel,
      requestedBy: actorId, debugSessionId: sessionId, debugVariant: "baseline", debugContext: { ...baseContext, variant: "baseline" }
    }) as Record<string, any> : null;
    const candidate = reviewQueueService.enqueueDebug({
      mergeRequestId: mr.id, headSha: requestedHeadSha, priority: Number(mr.risk_score || 0), effortLevel,
      requestedBy: actorId, debugSessionId: sessionId, debugVariant: "candidate", debugContext: { ...baseContext, variant: "candidate" }
    }) as Record<string, any>;
    skillDebugSessionRepository.attachJobs(sessionId, baseline?.id || null, candidate.id);
    auditLog({ userId: actorId, projectId: repo.project_id, action: "skill_debug.session_create", resourceType: "skill_debug_session", resourceId: sessionId, summary: `${mode} ${skillKey} ${session.skill_version}` });
    runWorkerOnce();
    return debugSessionDetail(skillDebugSessionRepository.findById(sessionId) as Record<string, any>);
  }

  const routes: Route[] = [
    route("POST", "/api/mr-review/projects/:projectId/skill-debug-sessions", async ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectCapability(params.projectId, actorId, "run_skill_debug");
      if (denied) return denied;
      return createSkillDebugSession((body || {}) as Record<string, unknown>, actorId, params.projectId);
    }),
    route("GET", "/api/mr-review/projects/:projectId/skill-debug-sessions", ({ params, req, url }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectCapability(params.projectId, actorId, "run_skill_debug");
      if (denied) return denied;
      skillDebugSessionRepository.expireDue();
      const limit = boundedQueryLimit(url, "limit", 50, 200);
      const isAdmin = !ensureProjectRole(params.projectId, actorId, "project_admin");
      return { items: skillDebugSessionRepository.listByProject(params.projectId, limit, isAdmin ? undefined : actorId) };
    }),
    route("GET", "/api/mr-review/skill-debug-sessions/:sessionId", ({ params, req }) => {
      const session = skillDebugSessionRepository.findById(params.sessionId) as Record<string, any> | undefined;
      if (!session) return notFound();
      const actorId = currentUserId(req);
      const denied = ensureSkillDebugSessionAccess(session, actorId);
      if (denied) return denied;
      auditLog({ userId: actorId, projectId: session.project_id, action: "skill_debug.session_view", resourceType: "skill_debug_session", resourceId: session.id, summary: "view skill debug session" });
      return debugSessionDetail(session);
    }),
    route("POST", "/api/mr-review/skill-debug-sessions/:sessionId/cancel", ({ params, req }) => {
      const session = skillDebugSessionRepository.findById(params.sessionId) as Record<string, any> | undefined;
      if (!session) return notFound();
      const actorId = currentUserId(req);
      const denied = ensureSkillDebugSessionAccess(session, actorId);
      if (denied) return denied;
      db.prepare(`
        UPDATE review_jobs SET status = 'cancelled', locked_at = NULL, locked_by = NULL, heartbeat_at = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE debug_session_id = $1 AND status IN ('queued', 'fetching', 'pre_scanning', 'reviewing', 'judging', 'running')
      `).run(session.id);
      const updated = skillDebugSessionRepository.updateStatus(session.id, "cancelled");
      auditLog({ userId: actorId, projectId: session.project_id, action: "skill_debug.session_cancel", resourceType: "skill_debug_session", resourceId: session.id, summary: "cancel skill debug session" });
      return debugSessionDetail(updated as Record<string, any>);
    }),
    route("POST", "/api/mr-review/skill-debug-sessions/:sessionId/rerun", async ({ params, req }) => {
      const session = skillDebugSessionRepository.findById(params.sessionId) as Record<string, any> | undefined;
      if (!session) return notFound();
      const actorId = currentUserId(req);
      const denied = ensureSkillDebugSessionAccess(session, actorId);
      if (denied) return denied;
      const snapshot = parseJsonValue(session.snapshot_json) as Record<string, any>;
      return createSkillDebugSession({
        mr_id: session.merge_request_id,
        skill_key: session.skill_key,
        skill_version: session.skill_version,
        agent_key: session.agent_key,
        mode: session.mode,
        effort_level: session.requested_effort_level,
        snapshot_sha256: session.snapshot_sha256,
        same_input: true,
        expected_head_sha: session.head_sha,
        input_artifact_sha256: session.input_artifact_sha256
      }, actorId, session.project_id, snapshot, parseJsonValue(session.input_artifact_json) as Record<string, any>);
    }),
    route("POST", "/api/mr-review/skill-debug-sessions/:sessionId/rerun-latest", async ({ params, req }) => {
      const session = skillDebugSessionRepository.findById(params.sessionId) as Record<string, any> | undefined;
      if (!session) return notFound();
      const actorId = currentUserId(req);
      const denied = ensureSkillDebugSessionAccess(session, actorId);
      if (denied) return denied;
      return createSkillDebugSession({
        mr_id: session.merge_request_id, skill_key: session.skill_key, skill_version: session.skill_version,
        agent_key: session.agent_key, mode: session.mode, effort_level: session.requested_effort_level,
        snapshot_sha256: session.snapshot_sha256, same_input: false
      }, actorId, session.project_id, parseJsonValue(session.snapshot_json) as Record<string, any>);
    }),
    route("GET", "/api/mr-review/skill-debug-sessions/:sessionId/export", ({ params, req }) => {
      const session = skillDebugSessionRepository.findById(params.sessionId) as Record<string, any> | undefined;
      if (!session) return notFound();
      const actorId = currentUserId(req);
      const denied = ensureSkillDebugSessionAccess(session, actorId);
      if (denied) return denied;
      const detail = sensitiveDataRedactionService.redact(debugSessionDetail(session));
      auditLog({ userId: actorId, projectId: session.project_id, action: "skill_debug.session_export", resourceType: "skill_debug_session", resourceId: session.id, summary: "export redacted skill debug diagnostics" });
      return { filename: `skill-debug-${session.id}.json`, content_type: "application/json; charset=utf-8", content: JSON.stringify(detail, null, 2) };
    }),
    route("GET", "/api/mr-review/projects/:projectId/merge-requests", async ({ params, req, url }) => {
      const denied = ensureProjectRead(params.projectId, req);
      if (denied) return denied;
      const requestedStatus = url.searchParams.get("status");
      const normalizedStatus = requestedStatus && requestedStatus !== "all" ? requestedStatus : null;
      const directDbStatuses = new Set(["queued", "paused", "waiting_confirmation", "submitted", "no_issue", "too_large", "cancelled", "merged", "closed"]);
      const dbStatus = normalizedStatus && directDbStatuses.has(normalizedStatus) ? normalizedStatus : null;
      const includeTerminal = truthyQuery(url.searchParams.get("include_terminal")) || normalizedStatus === "merged" || normalizedStatus === "closed";
      const activeJobStatuses = new Set(["fetching", "pre_scanning", "reviewing", "judging", "running"]);
      const activeProjectJobs = all<Record<string, any>>(`
        SELECT rj.id AS job_id, rj.status, mr.id AS merge_request_id, mr.number, mr.title
        FROM review_jobs rj
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = $1
          AND rj.execution_kind = 'production_review'
          AND rj.status IN ('fetching', 'pre_scanning', 'reviewing', 'judging', 'running')
          AND NULLIF(COALESCE(rj.heartbeat_at, rj.locked_at, rj.updated_at), '')::timestamptz >= CURRENT_TIMESTAMP - INTERVAL '60 seconds'
        ORDER BY rj.locked_at DESC, rj.updated_at DESC
      `, [params.projectId]);
      const projectEffectiveConfig = await effectiveConfig(params.projectId);
      const projectConcurrency = projectMrConcurrency(projectEffectiveConfig);
      const activeProjectJobIds = new Set(activeProjectJobs.map((job) => String(job.merge_request_id)));
      const rows = mergeRequestRepository.listByProject(params.projectId, dbStatus, { includeTerminal }).map((row: any) => {
        const terminalStatus = ["merged", "closed"].includes(String(row.review_status));
        const effectiveStatus = !terminalStatus && activeJobStatuses.has(String(row.latest_job_status)) ? String(row.latest_job_status) : String(row.review_status);
        const blockedByProject = effectiveStatus === "queued" && activeProjectJobs.length >= projectConcurrency && !activeProjectJobIds.has(String(row.id));
        const sizeHint = mrSizePolicyHint(row, projectEffectiveConfig);
        return {
          ...row,
          ...sizeHint,
          review_status: effectiveStatus,
          queue_blocked_by_project: Boolean(blockedByProject),
          queue_blocked_reason: blockedByProject
            ? `项目内已有 ${activeProjectJobs.length}/${projectConcurrency} 个 MR 正在检视，当前 MR 将排队等待`
            : "",
          active_project_review: blockedByProject ? activeProjectJobs[0] : null
        };
      });
      const filtered = normalizedStatus
        ? rows.filter((row: any) => {
            if (normalizedStatus === "reviewing") return activeJobStatuses.has(String(row.review_status));
            if (normalizedStatus === "high_risk") return Number(row.risk_score || 0) >= 70;
            return row.review_status === normalizedStatus;
          })
        : rows;
      return { items: filtered };
    }),
    route("POST", "/api/mr-review/projects/:projectId/sync", async ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "reviewer");
      if (denied) return denied;
      const result = await syncProject(params.projectId, actorId);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "mr_review.sync",
        resourceType: "project",
        resourceId: params.projectId,
        summary: `synced ${result.merge_requests} merge requests, queued ${result.jobs_created} jobs`,
        metadata: { repositories: result.repositories, repository_results: result.repository_results, errors: result.errors }
      });
      return result;
    }),
    route("POST", "/api/mr-review/projects/:projectId/merge-requests/status-refresh", async ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "reviewer");
      if (denied) return denied;
      const result = await mrSyncService.refreshProjectMergeRequestStatuses(params.projectId);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "mr_review.refresh_remote_status",
        resourceType: "project",
        resourceId: params.projectId,
        summary: `refreshed ${result.refreshed}/${result.checked} MR remote statuses, merged ${result.merged}, closed ${result.closed}`,
        metadata: { checked: result.checked, refreshed: result.refreshed, merged: result.merged, closed: result.closed, errors: result.errors }
      });
      return result;
    }),
    route("GET", "/api/mr-review/projects/:projectId/dead-letters", ({ params, req }) => {
      const denied = ensureProjectRead(params.projectId, req);
      if (denied) return denied;
      return {
        items: all<Record<string, any>>(`
        SELECT dl.*, r.name AS repository_name, mr.title AS merge_request_title, mr.number
        FROM review_jobs_dead_letter dl
        JOIN review_jobs rj ON rj.id = dl.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = $1
        ORDER BY dl.created_at DESC
      `, [params.projectId])
      };
    }),
    route("GET", "/api/mr-review/merge-requests/:mrId", ({ params, req, url }) => {
      const denied = ensureMrRead(params.mrId, req);
      if (denied) return denied;
      const logLimit = boundedQueryLimit(url, "log_limit", 240, 1000);
      const observationLimit = boundedQueryLimit(url, "observation_limit", 500, 2000);
      const artifactLimit = boundedQueryLimit(url, "artifact_limit", 80, 500);
      const findingLimit = boundedQueryLimit(url, "finding_limit", 200, 1000);
      const compareLimit = boundedQueryLimit(url, "compare_limit", 200, 1000);
      const runLimit = boundedQueryLimit(url, "run_limit", 20, 200);
      const jobLimit = boundedQueryLimit(url, "job_limit", 20, 200);
      const mr = mergeRequestRepository.findDetailById(params.mrId);
      if (!mr) return notFound();
      const jobs = all(`
        SELECT *
        FROM review_jobs
        WHERE merge_request_id = $1 AND execution_kind = 'production_review'
        ORDER BY created_at DESC
        LIMIT $2
      `, [params.mrId, jobLimit]);
      const runs = all(`
        SELECT rr.* FROM review_runs rr
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        WHERE rj.merge_request_id = $1 AND rj.execution_kind = 'production_review'
        ORDER BY rr.started_at DESC
        LIMIT $2
      `, [params.mrId, runLimit]);
      const latestRun = runs[0] as { id: string } | undefined;
      const findings = latestRun
        ? all("SELECT * FROM review_findings WHERE review_run_id = $1 ORDER BY severity DESC, confidence DESC LIMIT $2", [latestRun.id, findingLimit])
        : [];
      const toolObservations = latestRun
        ? all(`
            SELECT *
            FROM (
              SELECT *
              FROM tool_observations
              WHERE review_run_id = $1
              ORDER BY created_at DESC
              LIMIT $2
            ) recent_tool_observations
            ORDER BY created_at
          `, [latestRun.id, observationLimit])
        : [];
      const trace: Array<Record<string, any>> = latestRun
        ? all<Record<string, any>>(`
            SELECT *
            FROM (
              SELECT s.id AS span_id, s.span_key, s.agent_id, s.status, e.id AS event_id, e.event_type, e.summary, e.payload_json, e.created_at
              FROM agent_trace_spans s
              LEFT JOIN agent_trace_events e ON e.span_id = s.id
              WHERE s.review_run_id = $1
              ORDER BY e.created_at DESC NULLS LAST, s.started_at DESC
              LIMIT $2
            ) recent_trace
            ORDER BY created_at, span_key
          `, [latestRun.id, logLimit]).map(normalizeLegacyEvidenceTraceRow)
        : [];
      const sessionLogs = latestRun
        ? {
            messages: all(`
              SELECT *
              FROM (
                SELECT msg.*, s.span_key, s.agent_id
                FROM agent_messages msg
                JOIN agent_trace_spans s ON s.id = msg.span_id
                WHERE s.review_run_id = $1
                ORDER BY msg.created_at DESC
                LIMIT $2
              ) recent_messages
              ORDER BY created_at
            `, [latestRun.id, logLimit]),
            tool_calls: all(`
              SELECT *
              FROM (
                SELECT t.*, s.span_key, s.agent_id
                FROM tool_call_records t
                JOIN agent_trace_spans s ON s.id = t.span_id
                WHERE s.review_run_id = $1
                ORDER BY t.created_at DESC
                LIMIT $2
              ) recent_tool_calls
              ORDER BY created_at
            `, [latestRun.id, logLimit]),
            llm_calls: all(`
              SELECT *
              FROM (
                SELECT l.*, s.span_key, s.agent_id
                FROM llm_call_records l
                JOIN agent_trace_spans s ON s.id = l.span_id
                WHERE s.review_run_id = $1
                ORDER BY l.created_at DESC
                LIMIT $2
              ) recent_llm_calls
              ORDER BY created_at
            `, [latestRun.id, logLimit]),
            mcp_calls: all(`
              SELECT *
              FROM (
                SELECT m.*, s.span_key, s.agent_id
                FROM mcp_call_records m
                JOIN agent_trace_spans s ON s.id = m.span_id
                WHERE s.review_run_id = $1
                ORDER BY m.created_at DESC
                LIMIT $2
              ) recent_mcp_calls
              ORDER BY created_at
            `, [latestRun.id, logLimit]),
            skill_calls: normalizeSkillCalls(trace),
            artifacts: all(`
              SELECT *
              FROM (
                SELECT *
                FROM review_artifacts
                WHERE review_run_id = $1
                ORDER BY created_at DESC
                LIMIT $2
              ) recent_artifacts
              ORDER BY created_at
            `, [latestRun.id, artifactLimit])
          }
        : { messages: [], tool_calls: [], llm_calls: [], mcp_calls: [], skill_calls: [], artifacts: [] };
      return {
        mr,
        jobs,
        runs,
        findings,
        limits: {
          jobs: jobLimit,
          runs: runLimit,
          findings: findingLimit,
          logs: logLimit,
          observations: observationLimit,
          artifacts: artifactLimit
        },
        tool_observations: toolObservations,
        trace,
        session_logs: sessionLogs,
        compare: compareRunsForMr(params.mrId, compareLimit),
        quality: reviewQualityForRun(latestRun as Record<string, any> | undefined)
      };
    }),
    route("DELETE", "/api/mr-review/merge-requests/:mrId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const result = mergeRequestRepository.deleteById(params.mrId);
      if (!result.ok) return notFound();
      auditLog({
        userId: actorId,
        projectId: repo.project_id,
        action: "mr_review.delete",
        resourceType: "merge_request",
        resourceId: params.mrId,
        summary: `deleted local MR cache with ${result.deleted_jobs} jobs, ${result.deleted_runs} runs, ${result.deleted_findings} findings`,
        metadata: {
          repository_id: mr.repository_id,
          external_mr_id: mr.external_mr_id,
          deleted_related_rows: result.deleted_related_rows
        }
      });
      return { ...result, ok: true, mr_id: params.mrId };
    }),
    route("GET", "/api/mr-review/merge-requests/:mrId/logs", ({ params, req, url }) => {
      const mr = mergeRequestRepository.findDetailById(params.mrId) as any;
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id) as { project_id: string } | undefined;
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, currentUserId(req), "developer");
      if (denied) return denied;
      return unifiedReviewLogs(params.mrId, url.searchParams.get("run_id"));
    }),
    route("GET", "/api/mr-review/merge-requests/:mrId/export.md", ({ params, req }) => {
      const mr = mergeRequestRepository.findDetailById(params.mrId) as any;
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id) as { project_id: string } | undefined;
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, currentUserId(req), "developer");
      if (denied) return denied;
      const runs = all(`
        SELECT rr.* FROM review_runs rr
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        WHERE rj.merge_request_id = $1 AND rj.execution_kind = 'production_review'
        ORDER BY rr.started_at DESC
      `, [params.mrId]);
      const latestRun = runs[0] as { id: string } | undefined;
      const findings = latestRun
        ? all<FindingRow>("SELECT * FROM review_findings WHERE review_run_id = $1 ORDER BY severity DESC, confidence DESC", [latestRun.id])
        : [];
      const content = formatMrReviewMarkdown({ mr, run: latestRun as any, findings });
      auditLog({
        userId: currentUserId(req),
        projectId: repo.project_id,
        action: "mr_review.export_markdown",
        resourceType: "merge_request",
        resourceId: params.mrId,
        summary: `exported ${findings.length} findings as markdown`
      });
      return {
        filename: markdownFilename(mr),
        content_type: "text/markdown; charset=utf-8",
        content
      };
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/review-jobs", async ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findById(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const closed = await ensureMergeRequestOpenForAction(params.mrId, "开始检视");
      if (closed) return closed;
      const input = body as Record<string, unknown> | undefined;
      const projectEffectiveConfig = await effectiveConfig(repo.project_id);
      const sizeDecision = await evaluateMrSizeWithRemoteFiles(mr as unknown as Record<string, unknown>, repo as unknown as Record<string, unknown>, projectEffectiveConfig);
      if (!sizeDecision.allowed) {
        reviewQueueService.cancelQueued(params.mrId);
        mergeRequestRepository.updateReviewStatus(params.mrId, "too_large");
        const message = mrSizeBlockedMessage(sizeDecision);
        auditLog({
          userId: actorId,
          projectId: repo.project_id,
          action: "mr_review.too_large",
          resourceType: "merge_request",
          resourceId: params.mrId,
          summary: message,
          metadata: { added_lines: sizeDecision.addedLines, max_added_lines_per_mr: sizeDecision.maxAddedLines }
        });
        return {
          statusCode: 400,
          error: "mr_too_large",
          message,
          added_lines: sizeDecision.addedLines,
          max_added_lines_per_mr: sizeDecision.maxAddedLines
        };
      }
      const job = reviewQueueService.enqueueOrReset({
        mergeRequestId: params.mrId,
        headSha: mr.latest_head_sha,
        priority: mr.risk_score,
        effortLevel: String(input?.effort_level ?? "standard"),
        requestedBy: actorId
      });
      mergeRequestRepository.updateReviewStatus(params.mrId, "queued");
      auditLog({ userId: actorId, projectId: repo.project_id, action: "mr_review.enqueue", resourceType: "merge_request", resourceId: params.mrId, summary: `enqueue ${input?.effort_level ?? "standard"} review` });
      runWorkerOnce();
      return job;
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/skill-debug-runs", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId) as Record<string, any> | undefined;
      if (!mr) return notFound();
      const repo = repositoryRepository.findById(mr.repository_id) as Record<string, any> | undefined;
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "project_admin");
      if (denied) return denied;
      const input = (body || {}) as Record<string, unknown>;
      const skillKey = String(input.skill_key || "").trim();
      const agentKey = String(input.agent_key || "").trim();
      const mode = String(input.mode || "targeted");
      if (!skillKey || !agentKey) return badRequest("skill_key and agent_key are required");
      if (!["targeted", "production_route"].includes(mode)) return badRequest("mode must be targeted or production_route");
      const binding = get<Record<string, any>>(`
        SELECT esb.*, cs.version AS skill_version, cs.status AS skill_status
        FROM expert_skill_bindings esb
        JOIN custom_skills cs ON cs.project_id = esb.project_id AND cs.skill_key = esb.skill_key
        WHERE esb.project_id = $1 AND esb.agent_key = $2 AND esb.skill_key = $3 AND esb.enabled = 1
      `, [repo.project_id, agentKey, skillKey]);
      if (!binding || binding.skill_status !== "active") return badRequest("enabled active Skill binding not found");
      const debugContext = {
        kind: "skill_debug",
        mode,
        project_id: repo.project_id,
        skill_key: skillKey,
        skill_version: binding.skill_version,
        agent_key: agentKey,
        mr_id: params.mrId,
        head_sha: mr.latest_head_sha,
        requested_by: actorId,
        created_at: new Date().toISOString(),
        publish_allowed: false,
        consistency_contract: "production_review_pipeline_v1"
      };
      const job = reviewQueueService.enqueueOrReset({
        mergeRequestId: params.mrId,
        headSha: mr.latest_head_sha,
        priority: Number(mr.risk_score || 0),
        effortLevel: String(input.effort_level || "standard"),
        requestedBy: actorId,
        debugContext
      }) as Record<string, any>;
      mergeRequestRepository.updateReviewStatus(params.mrId, "queued");
      auditLog({ userId: actorId, projectId: repo.project_id, action: "skill_debug.enqueue", resourceType: "review_job", resourceId: String(job?.id || ""), summary: `debug ${skillKey} with ${mode}` });
      runWorkerOnce();
      return { ...job, debug_context: debugContext };
    }),
    route("GET", "/api/mr-review/projects/:projectId/skill-debug-runs", ({ params, req, url }) => {
      const denied = ensureProjectRole(params.projectId, currentUserId(req), "project_admin");
      if (denied) return denied;
      const limit = boundedQueryLimit(url, "limit", 50, 200);
      return { items: all(`
        SELECT rj.*, mr.title AS mr_title, rr.id AS review_run_id, rr.status AS run_status
        FROM review_jobs rj
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        LEFT JOIN review_runs rr ON rr.review_job_id = rj.id
        WHERE r.project_id = $1 AND rj.debug_context_json <> '{}'
        ORDER BY rj.updated_at DESC LIMIT $2
      `, [params.projectId, limit]) };
    }),
    route("GET", "/api/mr-review/skill-debug-runs/:jobId", ({ params, req }) => {
      const job = reviewJobRepository.findWithProject(params.jobId) as Record<string, any> | undefined;
      if (!job) return notFound();
      const denied = ensureProjectRole(String(job.project_id), currentUserId(req), "project_admin");
      if (denied) return denied;
      const run = get<Record<string, any>>("SELECT * FROM review_runs WHERE review_job_id = $1 ORDER BY started_at DESC LIMIT 1", [params.jobId]);
      const debugContext = parseRecord(job.debug_context_json);
      if (debugContext.kind !== "skill_debug") return notFound();
      const runId = String(run?.id || "");
      const trace = runId ? all<Record<string, any>>(`SELECT e.*, s.span_key, s.agent_id FROM agent_trace_events e JOIN agent_trace_spans s ON s.id=e.span_id WHERE s.review_run_id=$1 ORDER BY e.created_at`, [runId]) : [];
      const llmCalls = runId ? all<Record<string, any>>(`SELECT l.*, s.span_key, s.agent_id FROM llm_call_records l JOIN agent_trace_spans s ON s.id=l.span_id WHERE s.review_run_id=$1 ORDER BY l.created_at`, [runId]) : [];
      const toolCalls = runId ? all<Record<string, any>>(`SELECT t.*, s.span_key, s.agent_id FROM tool_call_records t JOIN agent_trace_spans s ON s.id=t.span_id WHERE s.review_run_id=$1 ORDER BY t.created_at`, [runId]) : [];
      const findings = runId ? all<Record<string, any>>("SELECT * FROM review_findings WHERE review_run_id=$1 ORDER BY created_at", [runId]) : [];
      return { job, run: run || null, debug_context: debugContext, trace, skill_trace: buildSkillTracePayload(run || {}, trace.map(normalizeLegacyEvidenceTraceRow), llmCalls), llm_calls: llmCalls, tool_calls: toolCalls, findings, publish_guard: "skill_debug.publish_forbidden" };
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/pause", ({ params, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findById(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const result = reviewQueueService.pauseByMergeRequest(params.mrId);
      mergeRequestRepository.updateReviewStatus(params.mrId, "paused");
      auditLog({ userId: actorId, projectId: repo.project_id, action: "mr_review.pause", resourceType: "merge_request", resourceId: params.mrId, summary: `paused ${result.changes} review jobs` });
      return { ok: true, paused_jobs: result.changes };
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/stop", ({ params, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findById(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const result = reviewQueueService.stopByMergeRequest(params.mrId);
      mergeRequestRepository.updateReviewStatus(params.mrId, "cancelled");
      auditLog({ userId: actorId, projectId: repo.project_id, action: "mr_review.stop", resourceType: "merge_request", resourceId: params.mrId, summary: `stopped ${result.changes} review jobs` });
      return { ok: true, stopped_jobs: result.changes };
    }),
    route("POST", "/api/mr-review/review-jobs/:jobId/retry", async ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const input = body as Record<string, unknown> | undefined;
      const job = reviewJobRepository.findWithProject(params.jobId) as { id: string; merge_request_id: string; requested_effort_level: string; project_id: string } | undefined;
      if (!job) return notFound();
      const denied = ensureProjectRole(job.project_id, actorId, "reviewer");
      if (denied) return denied;
      const mr = mergeRequestRepository.findById(job.merge_request_id);
      if (!mr) return notFound();
      const closed = await ensureMergeRequestOpenForAction(job.merge_request_id, "重新检视");
      if (closed) return closed;
      const projectEffectiveConfig = await effectiveConfig(job.project_id);
      const repository = repositoryRepository.findById(mr.repository_id);
      const sizeDecision = repository
        ? await evaluateMrSizeWithRemoteFiles(mr as unknown as Record<string, unknown>, repository as unknown as Record<string, unknown>, projectEffectiveConfig)
        : evaluateMrSizePolicy(mr as unknown as Record<string, unknown>, projectEffectiveConfig);
      if (!sizeDecision.allowed) {
        reviewQueueService.cancelQueued(job.merge_request_id);
        mergeRequestRepository.updateReviewStatus(job.merge_request_id, "too_large");
        const message = mrSizeBlockedMessage(sizeDecision);
        auditLog({
          userId: actorId,
          projectId: job.project_id,
          action: "mr_review.retry.too_large",
          resourceType: "review_job",
          resourceId: params.jobId,
          summary: message,
          metadata: { merge_request_id: job.merge_request_id, added_lines: sizeDecision.addedLines, max_added_lines_per_mr: sizeDecision.maxAddedLines }
        });
        return {
          statusCode: 400,
          error: "mr_too_large",
          message,
          added_lines: sizeDecision.addedLines,
          max_added_lines_per_mr: sizeDecision.maxAddedLines
        };
      }
      const updated = reviewQueueService.retry(params.jobId, String(input?.effort_level ?? job.requested_effort_level ?? "standard"), actorId);
      mergeRequestRepository.updateReviewStatus(job.merge_request_id, "queued");
      auditLog({ userId: actorId, projectId: job.project_id, action: "mr_review.retry", resourceType: "review_job", resourceId: params.jobId, summary: `retry as ${input?.effort_level ?? job.requested_effort_level ?? "standard"}` });
      runWorkerOnce();
      return updated;
    }),
    route("GET", "/api/mr-review/review-runs/:runId", ({ params, req }) => {
      const denied = ensureRunRead(params.runId, req);
      if (denied) return denied;
      const run = get<Record<string, any>>("SELECT * FROM review_runs WHERE id = $1", [params.runId]);
      if (!run) return notFound();
      return {
        ...run,
        coverage: parseRecord(run.coverage_json),
        context_health: contextHealthFromRun(run),
        quality: reviewQualityForRun(run)
      };
    }),
    route("GET", "/api/mr-review/review-runs/:runId/trace", ({ params, req, url }) => {
      const denied = ensureRunRead(params.runId, req);
      if (denied) return denied;
      const limit = boundedQueryLimit(url, "limit", 240, 1000);
      const offset = boundedQueryOffset(url);
      return {
        items: all<Record<string, any>>(`
          SELECT *
          FROM (
            SELECT s.*, e.event_type, e.summary, e.payload_json, e.created_at AS event_created_at
            FROM agent_trace_spans s
            LEFT JOIN agent_trace_events e ON e.span_id = s.id
            WHERE s.review_run_id = $1
            ORDER BY e.created_at DESC NULLS LAST, s.started_at DESC
            LIMIT $2 OFFSET $3
          ) recent_trace
          ORDER BY event_created_at, started_at
        `, [params.runId, limit, offset]).map(normalizeLegacyEvidenceTraceRow),
        page: { limit, offset }
      };
    }),
    route("GET", "/api/mr-review/review-runs/:runId/session-logs", ({ params, req, url }) => {
      const denied = ensureRunRead(params.runId, req);
      if (denied) return denied;
      const limit = boundedQueryLimit(url, "limit", 240, 1000);
      const offset = boundedQueryOffset(url);
      const type = String(url.searchParams.get("type") || "all");
      const include = (name: string) => type === "all" || type === name;
      const spans = include("spans")
        ? all(`
            SELECT *
            FROM (
              SELECT *
              FROM agent_trace_spans
              WHERE review_run_id = $1
              ORDER BY started_at DESC
              LIMIT $2 OFFSET $3
            ) recent_spans
            ORDER BY started_at
          `, [params.runId, limit, offset])
        : [];
      const events = all<Record<string, any>>(`
        SELECT *
        FROM (
          SELECT e.*, s.span_key, s.agent_id
          FROM agent_trace_events e
          JOIN agent_trace_spans s ON s.id = e.span_id
          WHERE s.review_run_id = $1
          ORDER BY e.created_at DESC
          LIMIT $2 OFFSET $3
        ) recent_events
        ORDER BY created_at
      `, include("events") || include("skill_calls") ? [params.runId, limit, offset] : [params.runId, 0, 0]).map(normalizeLegacyEvidenceTraceRow);
      const llmCalls = include("llm_calls") ? all(`
        SELECT *
        FROM (
          SELECT l.*, s.span_key, s.agent_id
          FROM llm_call_records l
          JOIN agent_trace_spans s ON s.id = l.span_id
          WHERE s.review_run_id = $1
          ORDER BY l.created_at DESC
          LIMIT $2 OFFSET $3
        ) recent_llm_calls
        ORDER BY created_at
      `, [params.runId, limit, offset]) : [];
      const toolCalls = include("tool_calls") ? all(`
        SELECT *
        FROM (
          SELECT t.*, s.span_key, s.agent_id
          FROM tool_call_records t
          JOIN agent_trace_spans s ON s.id = t.span_id
          WHERE s.review_run_id = $1
          ORDER BY t.created_at DESC
          LIMIT $2 OFFSET $3
        ) recent_tool_calls
        ORDER BY created_at
      `, [params.runId, limit, offset]) : [];
      const mcpCalls = include("mcp_calls") ? all(`
        SELECT *
        FROM (
          SELECT m.*, s.span_key, s.agent_id
          FROM mcp_call_records m
          JOIN agent_trace_spans s ON s.id = m.span_id
          WHERE s.review_run_id = $1
          ORDER BY m.created_at DESC
          LIMIT $2 OFFSET $3
        ) recent_mcp_calls
        ORDER BY created_at
      `, [params.runId, limit, offset]) : [];
      const messages = include("messages") ? all(`
        SELECT *
        FROM (
          SELECT msg.*, s.span_key, s.agent_id
          FROM agent_messages msg
          JOIN agent_trace_spans s ON s.id = msg.span_id
          WHERE s.review_run_id = $1
          ORDER BY msg.created_at DESC
          LIMIT $2 OFFSET $3
        ) recent_messages
        ORDER BY created_at
      `, [params.runId, limit, offset]) : [];
      return { spans, events, messages, llm_calls: llmCalls, tool_calls: toolCalls, mcp_calls: mcpCalls, skill_calls: normalizeSkillCalls(events), page: { limit, offset, type } };
    }),
    route("GET", "/api/mr-review/review-runs/:runId/skill-trace", ({ params, req, url }) => {
      const projectId = projectIdForRun(params.runId);
      if (!projectId) return notFound();
      const denied = ensureProjectRole(projectId, currentUserId(req), "project_admin");
      if (denied) return denied;
      const limit = boundedQueryLimit(url, "limit", 500, 1000);
      const offset = boundedQueryOffset(url);
      const run = get<Record<string, any>>("SELECT id, coverage_json FROM review_runs WHERE id = $1", [params.runId]);
      if (!run) return notFound();
      const skillEventTypes = [
        "skill_context_loaded",
        "skill_deepagents_invoked",
        "skill_llm_context_used",
        "bound_skill_started",
        "bound_skill_checked",
        "bound_batch_findings_rejected",
        "bound_rule_coverage_low",
        "bound_rule_coverage_retry_completed"
      ];
      const events = all<Record<string, any>>(`
        SELECT *
        FROM (
          SELECT e.*, s.span_key, s.agent_id
          FROM agent_trace_events e
          JOIN agent_trace_spans s ON s.id = e.span_id
          WHERE s.review_run_id = $1
            AND e.event_type = ANY($2::text[])
          ORDER BY e.created_at DESC
          LIMIT $3 OFFSET $4
        ) recent_skill_events
        ORDER BY created_at
      `, [params.runId, skillEventTypes, limit, offset]).map(normalizeLegacyEvidenceTraceRow);
      const llmCalls = all<Record<string, any>>(`
        SELECT *
        FROM (
          SELECT l.id, l.span_id, s.span_key, s.agent_id, l.provider, l.model, l.status, l.duration_ms, l.input_tokens, l.output_tokens, l.request_id, l.created_at
          FROM llm_call_records l
          JOIN agent_trace_spans s ON s.id = l.span_id
          WHERE s.review_run_id = $1
          ORDER BY l.created_at DESC
          LIMIT $2 OFFSET $3
        ) recent_skill_llm_calls
        ORDER BY created_at
      `, [params.runId, limit, offset]);
      const coverage = parseRecord(run.coverage_json);
      const runtimeFacts = Array.isArray(coverage.skill_runtime_facts) ? coverage.skill_runtime_facts.map(parseRecord) : [];
      const skillCheckpointIds = new Set(runtimeFacts.flatMap((fact) => (
        Array.isArray(fact.checkpoints)
          ? fact.checkpoints.map(parseRecord).map((item) => String(item.checkpoint_id || "")).filter(Boolean)
          : []
      )));
      const judgeDecisions = all<Record<string, any>>(`
        SELECT id, dedupe_hash, status, agent_id, rule_id, title, file_path, line_start, line_end,
               rejected_reasons_json, decision_reason_json, decision_stage, decided_at, merged_into_candidate_id
        FROM candidate_findings
        WHERE review_run_id = $1 AND stage = 'judge' AND status IN ('rejected','merged')
        ORDER BY decided_at, updated_at
      `, [params.runId])
        .filter((row) => skillCheckpointIds.has(String(row.rule_id || "")))
        .map((row) => ({
          ...row,
          rejected_reasons: stringList(parseJsonValue(row.rejected_reasons_json)),
          decision_reasons: Array.isArray(parseJsonValue(row.decision_reason_json)) ? parseJsonValue(row.decision_reason_json) : []
        }));
      return { ...buildSkillTracePayload(run, events, llmCalls), judge_decisions: judgeDecisions, page: { limit, offset } };
    }),
    route("GET", "/api/mr-review/review-runs/:runId/artifacts", ({ params, req, url }) => {
      const denied = ensureRunRead(params.runId, req);
      if (denied) return denied;
      const limit = boundedQueryLimit(url, "limit", 100, 1000);
      const offset = boundedQueryOffset(url);
      return {
        items: all(`
          SELECT *
          FROM (
            SELECT *
            FROM review_artifacts
            WHERE review_run_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
          ) recent_artifacts
          ORDER BY created_at
        `, [params.runId, limit, offset]),
        page: { limit, offset }
      };
    }),
    route("GET", "/api/mr-review/merge-requests/:mrId/review-runs/compare", ({ params, req, url }) => {
      const denied = ensureMrRead(params.mrId, req);
      if (denied) return denied;
      return compareRunsForMr(params.mrId, boundedQueryLimit(url, "limit", 200, 1000));
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/external-reports", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const input = body as Record<string, unknown> | undefined;
      const reportType = String(input?.type ?? input?.report_type ?? "").trim();
      const reportFormat = String(input?.report_format ?? "").trim();
      const commitSha = String(input?.commit_sha ?? mr.latest_head_sha).trim();
      if (!reportType) return badRequest("type is required");
      if (!reportFormat) return badRequest("report_format is required");
      const reportId = id("ext_report");
      db.prepare(`
        INSERT INTO external_review_reports (
          id, merge_request_id, report_type, commit_sha, report_format, report_url,
          payload_json, metadata_json, status, created_by
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'received', $9)
      `).run(
        reportId,
        params.mrId,
        reportType,
        commitSha,
        reportFormat,
        input?.report_url ? String(input.report_url) : null,
        JSON.stringify(input?.payload ?? {}),
        JSON.stringify(input?.metadata ?? {}),
        actorId
      );
      auditLog({
        userId: actorId,
        projectId: repo.project_id,
        action: "mr_review.external_report.received",
        resourceType: "merge_request",
        resourceId: params.mrId,
        summary: `${reportType}:${reportFormat}`,
        metadata: { report_id: reportId, commit_sha: commitSha }
      });
      return get("SELECT * FROM external_review_reports WHERE id = $1", [reportId]);
    }),
    route("GET", "/api/mr-review/merge-requests/:mrId/external-reports", ({ params, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "observer");
      if (denied) return denied;
      return {
        items: all(
          "SELECT * FROM external_review_reports WHERE merge_request_id = $1 ORDER BY created_at DESC",
          [params.mrId]
        )
      };
    }),
    route("PATCH", "/api/mr-review/review-findings/:findingId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const input = body as Record<string, unknown>;
      const finding = get<FindingRow & { project_id: string; execution_kind: string }>(`
        SELECT rf.*, r.project_id, rj.execution_kind
        FROM review_findings rf
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE rf.id = $1
      `, [params.findingId]);
      if (!finding) return notFound();
      if (finding.execution_kind !== "production_review") return badRequest("Skill 调试问题不进入正式反馈学习");
      const denied = ensureProjectRole(finding.project_id, actorId, "developer");
      if (denied) return denied;
      if (typeof input.selected === "boolean") {
        db.prepare("UPDATE review_findings SET selected = $1 WHERE id = $2").run(input.selected ? 1 : 0, params.findingId);
        auditLog({ userId: actorId, projectId: finding.project_id, action: "finding.select", resourceType: "review_finding", resourceId: params.findingId, summary: `selected=${input.selected}` });
      }
      if (typeof input.lifecycle_state === "string") {
        db.prepare("UPDATE review_findings SET lifecycle_state = $1 WHERE id = $2").run(input.lifecycle_state, params.findingId);
        auditLog({ userId: actorId, projectId: finding.project_id, action: "finding.lifecycle", resourceType: "review_finding", resourceId: params.findingId, summary: String(input.lifecycle_state) });
      }
      return get("SELECT * FROM review_findings WHERE id = $1", [params.findingId]);
    }),
    route("POST", "/api/mr-review/review-findings/:findingId/feedback", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const input = body as Record<string, unknown>;
      const state = String(input.feedback_type ?? "dismissed");
      const finding = get<FindingRow & { project_id: string; execution_kind: string }>(`
        SELECT rf.*, r.project_id, rj.execution_kind
        FROM review_findings rf
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE rf.id = $1
      `, [params.findingId]);
      if (!finding) return notFound();
      if (finding.execution_kind !== "production_review") return badRequest("Skill 调试问题不进入正式反馈学习");
      const denied = ensureProjectRole(finding.project_id, actorId, "developer");
      if (denied) return denied;
      feedbackLearningService.markFindingFeedback(params.findingId, state);
      feedbackLearningService.recordFeedback({
        userId: actorId,
        finding,
        feedbackType: state,
        scope: String(input.scope ?? (state === "false_positive" ? "project" : "merge_request")),
        reason: input.reason ? String(input.reason) : null
      });
      auditLog({ userId: actorId, projectId: finding.project_id, action: "finding.feedback", resourceType: "review_finding", resourceId: params.findingId, summary: state, metadata: { scope: input.scope ?? null } });
      return get("SELECT * FROM review_findings WHERE id = $1", [params.findingId]);
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/publish", async ({ params, body, req }) => {
      const input = body as Record<string, unknown>;
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findById(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, currentUserId(req), "reviewer");
      if (denied) return denied;
      const closed = await ensureMergeRequestOpenForAction(params.mrId, "提交检视意见");
      if (closed) return closed;
      return publishFindings(params.mrId, (input.finding_ids as string[] | undefined) ?? [], Boolean(input.dry_run), currentUserId(req));
    }),
  ];
  return routes;
}
