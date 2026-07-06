import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { FeedbackLearningService } from "../mr-backend/build/backend/services/FeedbackLearningService.js";

class FakeDb {
  constructor() {
    this.feedback = new Map();
    this.hints = new Map();
    this.precisionRows = [];
  }

  prepare(sql) {
    const normalized = sql.replace(/\s+/g, " ").trim().toLowerCase();
    if (normalized.startsWith("insert into user_feedback")) {
      return {
        run: (id, userId, findingId, dedupeHash, feedbackType, scope, reason) => {
          this.feedback.set(id, { id, user_id: userId, finding_id: findingId, dedupe_hash: dedupeHash, feedback_type: feedbackType, scope, reason });
          return { changes: 1 };
        }
      };
    }
    if (normalized.startsWith("select * from user_feedback")) {
      return { get: (id) => this.feedback.get(id) };
    }
    if (normalized.startsWith("insert into rule_precision_history")) {
      return {
        run: (...params) => {
          this.precisionRows.push(params);
          return { changes: 1 };
        }
      };
    }
    if (normalized.startsWith("insert into rule_suppression_hints")) {
      return {
        run: (projectId, ruleId, fileGlob, snippetHash, snippetExcerpt) => {
          const key = `${projectId}\u0000${ruleId}\u0000${fileGlob}\u0000${snippetHash}`;
          const existing = this.hints.get(key);
          this.hints.set(key, {
            project_id: projectId,
            rule_id: ruleId,
            file_glob: fileGlob,
            snippet_hash: snippetHash,
            snippet_excerpt: snippetExcerpt,
            count: existing ? existing.count + 1 : 1
          });
          return { changes: 1 };
        }
      };
    }
    throw new Error(`Unexpected SQL in fake DB: ${sql}`);
  }
}

function normalizedSnippet(value) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, 500);
}

function snippetHash(value) {
  return createHash("sha1").update(normalizedSnippet(value), "utf8").digest("hex");
}

const db = new FakeDb();
const service = new FeedbackLearningService(db);
const finding = {
  id: "finding_1",
  project_id: "project_q10",
  review_run_id: "run_1",
  severity: "high",
  confidence: 0.9,
  agent_id: "security_agent",
  dedupe_hash: "hash_1",
  file_path: "src/main/java/demo/PaymentRepository.java",
  line_start: 42,
  line_end: 42,
  title: "SQL 注入",
  problem_description: "用户输入拼接 SQL",
  evidence: "String sql = \"select *\" + userId;\nstatement.executeQuery(sql);",
  recommendation: "使用参数绑定",
  suggested_code: "statement.setString(1, userId);",
  covered_rules_json: JSON.stringify(["SEC-INJECT-003"])
};

service.recordFeedback({ userId: "u1", finding, feedbackType: "false_positive", scope: "project" });
service.recordFeedback({ userId: "u1", finding, feedbackType: "false_positive", scope: "project" });

assert.equal(db.hints.size, 1, "same FP pattern should upsert one suppression hint");
const hint = [...db.hints.values()][0];
assert.equal(hint.project_id, "project_q10");
assert.equal(hint.rule_id, "SEC-INJECT-003");
assert.equal(hint.file_glob, "src/main/**");
assert.equal(hint.snippet_hash, snippetHash(finding.evidence));
assert.equal(hint.snippet_excerpt, normalizedSnippet(finding.evidence).slice(0, 240));
assert.equal(hint.count, 2, "repeated FP feedback should increment suppression hint count");

const hintCountBeforeAccepted = db.hints.size;
service.recordFeedback({ userId: "u1", finding: { ...finding, id: "finding_2", dedupe_hash: "hash_2" }, feedbackType: "accepted", scope: "merge_request" });
assert.equal(db.hints.size, hintCountBeforeAccepted, "accepted feedback must not create suppression hints");
assert.ok(db.precisionRows.length >= 3, "feedback should still update rule precision history");

console.log(JSON.stringify({ ok: true, verified: "feedback_suppression_hints", hints: db.hints.size, count: hint.count }));
