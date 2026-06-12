import { id } from "../http.js";
import type { Db } from "../db.js";
import type { FindingRow } from "../types.js";

export class FeedbackLearningService {
  constructor(private readonly db: Db) {}

  private ruleIds(finding: FindingRow) {
    try {
      const parsed = JSON.parse(String(finding.covered_rules_json || "[]"));
      if (Array.isArray(parsed)) return parsed.map((item) => String(item)).filter(Boolean);
    } catch {
      // ignore malformed historical data
    }
    return [];
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
          id, project_id, agent_id, rule_id, accepted_count, rejected_count, auto_suppress
        )
        VALUES (?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(project_id, agent_id, rule_id) DO UPDATE SET
          accepted_count = rule_precision_history.accepted_count + excluded.accepted_count,
          rejected_count = rule_precision_history.rejected_count + excluded.rejected_count,
          auto_suppress = CASE
            WHEN rule_precision_history.accepted_count + excluded.accepted_count + rule_precision_history.rejected_count + excluded.rejected_count >= 10
             AND 1.0 * (rule_precision_history.accepted_count + excluded.accepted_count)
                 / (rule_precision_history.accepted_count + excluded.accepted_count + rule_precision_history.rejected_count + excluded.rejected_count) < 0.4
            THEN 1 ELSE rule_precision_history.auto_suppress END,
          last_updated = CURRENT_TIMESTAMP
      `).run(historyId, projectId, finding.agent_id, ruleId, acceptedDelta, rejectedDelta);
    }
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
      VALUES (?, ?, ?, ?, ?, ?, ?)
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
    return this.db.prepare("SELECT * FROM user_feedback WHERE id = ?").get(feedbackId);
  }

  markFindingFeedback(findingId: string, lifecycleState: string) {
    const selected = lifecycleState === "accepted" ? 1 : 0;
    this.db.prepare("UPDATE review_findings SET lifecycle_state = ?, selected = ? WHERE id = ?").run(lifecycleState, selected, findingId);
    return this.db.prepare("SELECT * FROM review_findings WHERE id = ?").get(findingId);
  }
}
