import { createHash } from "node:crypto";
import { id } from "../http.js";
import type { Db } from "../db.js";
import type { FindingRow } from "../types.js";

export class FeedbackLearningService {
  constructor(private readonly db: Db) {}

  private ruleIdsFromJson(raw: unknown) {
    try {
      const parsed = JSON.parse(String(raw || "[]"));
      if (Array.isArray(parsed)) return parsed.map((item) => String(item)).filter(Boolean);
    } catch {
      // ignore malformed historical data
    }
    return [];
  }

  private ruleIds(finding: FindingRow) {
    return this.ruleIdsFromJson(finding.covered_rules_json);
  }

  private updateRulePrecision(projectId: string | undefined, finding: FindingRow, feedbackType: string) {
    if (!projectId) return;
    const ruleIds = this.ruleIds(finding);
    if (!ruleIds.length) return;
    const acceptedDelta = feedbackType === "accepted" ? 1 : 0;
    const rejectedDelta = feedbackType === "false_positive" || feedbackType === "dismissed" ? 1 : 0;
    if (!acceptedDelta && !rejectedDelta) return;
    for (const ruleId of ruleIds) {
      const historyId = id("rph");
      this.db.prepare(`
        INSERT INTO rule_precision_history (
          id, project_id, agent_id, rule_id, accepted_count, rejected_count,
          recent_accepted_count, recent_rejected_count, auto_suppress
        )
        VALUES ($1, $2, $3, $4, $5, $6, 0, 0, 0)
        ON CONFLICT(project_id, agent_id, rule_id) DO UPDATE SET
          accepted_count = rule_precision_history.accepted_count + excluded.accepted_count,
          rejected_count = rule_precision_history.rejected_count + excluded.rejected_count,
          last_updated = CURRENT_TIMESTAMP
      `).run(historyId, projectId, finding.agent_id, ruleId, acceptedDelta, rejectedDelta);
    }
  }

  private fileGlob(filePath: string) {
    const parts = String(filePath || "").replace(/\\/g, "/").split("/").filter(Boolean);
    if (!parts.length) return "**/*";
    return `${parts.slice(0, 2).join("/")}/**`;
  }

  private normalizedSnippet(value: string) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, 500);
  }

  private snippetHash(value: string) {
    return createHash("sha1").update(this.normalizedSnippet(value), "utf8").digest("hex");
  }

  private recordSuppressionHints(projectId: string | undefined, finding: FindingRow, feedbackType: string) {
    if (!projectId || feedbackType !== "false_positive") return;
    const ruleIds = this.ruleIds(finding);
    if (!ruleIds.length) return;
    const snippet = this.normalizedSnippet(finding.evidence || finding.problem_description || finding.title || finding.file_path);
    if (!snippet) return;
    const fileGlob = this.fileGlob(finding.file_path);
    const snippetHash = this.snippetHash(snippet);
    const snippetExcerpt = snippet.slice(0, 240);
    for (const ruleId of ruleIds) {
      this.db.prepare(`
        INSERT INTO rule_suppression_hints (
          project_id, rule_id, file_glob, snippet_hash, snippet_excerpt, count, last_marked_at
        )
        VALUES ($1, $2, $3, $4, $5, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(project_id, rule_id, file_glob, snippet_hash) DO UPDATE SET
          count = rule_suppression_hints.count + 1,
          snippet_excerpt = excluded.snippet_excerpt,
          last_marked_at = CURRENT_TIMESTAMP
      `).run(projectId, ruleId, fileGlob, snippetHash, snippetExcerpt);
    }
  }

  recalculateRecentPrecision(input: { projectId?: string; windowDays?: number; now?: Date; minSamples?: number; suppressPrecision?: number } = {}) {
    const windowDays = Math.max(1, Number(input.windowDays ?? 90));
    const now = input.now ?? new Date();
    const cutoffMs = now.getTime() - windowDays * 24 * 60 * 60 * 1000;
    const minSamples = Math.max(1, Number(input.minSamples ?? 5));
    const suppressPrecision = Math.max(0, Math.min(1, Number(input.suppressPrecision ?? 0.3)));
    const params = input.projectId ? [input.projectId] : [];
    const rows = this.db.prepare(`
      SELECT rf.agent_id, rf.covered_rules_json, uf.feedback_type, uf.created_at, r.project_id
      FROM user_feedback uf
      JOIN review_findings rf ON rf.id = uf.finding_id
      JOIN review_runs rr ON rr.id = rf.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      ${input.projectId ? "WHERE r.project_id = $1" : ""}
    `).all(...params) as Array<{
      project_id: string;
      agent_id: string;
      covered_rules_json: string;
      feedback_type: string;
      created_at: string;
    }>;

    const aggregates = new Map<string, { projectId: string; agentId: string; ruleId: string; accepted: number; rejected: number }>();
    for (const row of rows) {
      const createdAt = Date.parse(String(row.created_at || ""));
      if (!Number.isFinite(createdAt) || createdAt < cutoffMs) continue;
      const accepted = row.feedback_type === "accepted" ? 1 : 0;
      const rejected = row.feedback_type === "false_positive" || row.feedback_type === "dismissed" ? 1 : 0;
      if (!accepted && !rejected) continue;
      for (const ruleId of this.ruleIdsFromJson(row.covered_rules_json)) {
        const key = `${row.project_id}\u0000${row.agent_id}\u0000${ruleId}`;
        const aggregate = aggregates.get(key) ?? { projectId: row.project_id, agentId: row.agent_id, ruleId, accepted: 0, rejected: 0 };
        aggregate.accepted += accepted;
        aggregate.rejected += rejected;
        aggregates.set(key, aggregate);
      }
    }

    if (input.projectId) {
      this.db.prepare(`
        UPDATE rule_precision_history
        SET recent_accepted_count = 0,
            recent_rejected_count = 0,
            auto_suppress = 0,
            last_updated = CURRENT_TIMESTAMP
        WHERE project_id = $1
      `).run(input.projectId);
    } else {
      this.db.prepare(`
        UPDATE rule_precision_history
        SET recent_accepted_count = 0,
            recent_rejected_count = 0,
            auto_suppress = 0,
            last_updated = CURRENT_TIMESTAMP
      `).run();
    }

    for (const aggregate of aggregates.values()) {
      const total = aggregate.accepted + aggregate.rejected;
      const precision = total ? aggregate.accepted / total : 1;
      const autoSuppress = total >= minSamples && precision < suppressPrecision ? 1 : 0;
      this.db.prepare(`
        INSERT INTO rule_precision_history (
          id, project_id, agent_id, rule_id, accepted_count, rejected_count,
          recent_accepted_count, recent_rejected_count, auto_suppress
        )
        VALUES ($1, $2, $3, $4, 0, 0, $5, $6, $7)
        ON CONFLICT(project_id, agent_id, rule_id) DO UPDATE SET
          recent_accepted_count = excluded.recent_accepted_count,
          recent_rejected_count = excluded.recent_rejected_count,
          auto_suppress = excluded.auto_suppress,
          last_updated = CURRENT_TIMESTAMP
      `).run(id("rph"), aggregate.projectId, aggregate.agentId, aggregate.ruleId, aggregate.accepted, aggregate.rejected, autoSuppress);
    }

    return {
      project_id: input.projectId ?? null,
      window_days: windowDays,
      cutoff_at: new Date(cutoffMs).toISOString(),
      recalculated_rules: aggregates.size,
      feedback_rows_scanned: rows.length
    };
  }

  recordFeedback(input: {
    userId: string;
    finding: FindingRow & { project_id?: string };
    feedbackType: string;
    scope: string;
    reason?: string | null;
  }) {
    const feedbackId = id("feedback");
    this.db.prepare(`
      INSERT INTO user_feedback (id, user_id, finding_id, dedupe_hash, feedback_type, scope, reason)
      VALUES ($1, $2, $3, $4, $5, $6, $7)
    `).run(
      feedbackId,
      input.userId,
      input.finding.id,
      input.finding.dedupe_hash,
      input.feedbackType,
      input.scope,
      input.reason ?? null
    );
    this.updateRulePrecision(input.finding.project_id, input.finding, input.feedbackType);
    this.recordSuppressionHints(input.finding.project_id, input.finding, input.feedbackType);
    return this.db.prepare("SELECT * FROM user_feedback WHERE id = $1").get(feedbackId);
  }

  markFindingFeedback(findingId: string, lifecycleState: string) {
    const selected = lifecycleState === "accepted" ? 1 : 0;
    this.db.prepare("UPDATE review_findings SET lifecycle_state = $1, selected = $2 WHERE id = $3").run(lifecycleState, selected, findingId);
    return this.db.prepare("SELECT * FROM review_findings WHERE id = $1").get(findingId);
  }
}
