import assert from "node:assert/strict";
import { normalizeFindingRow } from "./export-real-findings.mjs";

const row = {
  finding_id: "finding_real_1",
  merge_request_id: "mr_real_1",
  review_run_id: "run_real_1",
  mr_metadata_json: JSON.stringify({ real_pr_fixture_id: "spring-framework-12345" }),
  agent_id: "security_agent",
  severity: "high",
  confidence: "0.91",
  file_path: "src/main/java/demo/AuthController.java",
  line_start: "42",
  line_end: 42,
  title: "Missing authorization",
  problem_description: "Controller writes privileged state without auth check.",
  evidence: "adminService.update(request);",
  recommendation: "Add authorization before updating state.",
  suggested_code: "authz.requireAdmin(user);",
  covered_rules_json: JSON.stringify(["SEC-AUTH-001"]),
  skipped_rules_json: JSON.stringify(["SEC-SECRET-004"]),
  tool_provenance_json: JSON.stringify([{ tool_name: "semgrep", rule_id: "SEC-AUTH-001" }]),
  source_observations_json: JSON.stringify([{ file_path: "src/main/java/demo/AuthController.java", line_start: 42 }]),
  quality_trace_json: JSON.stringify({ consensus_agents: ["security_agent"], critic_verdict: { verdict: "real_bug" } }),
  evidence_score_json: JSON.stringify({ score: 0.72, components: { tool_backing: 0.3 }, consensus_agents: ["security_agent"] })
};

const normalized = normalizeFindingRow(row);
assert.equal(normalized.mr_id, "mr_real_1");
assert.equal(normalized.finding_id, "finding_real_1");
assert.equal(normalized.confidence, 0.91);
assert.equal(normalized.line_start, 42);
assert.deepEqual(normalized.covered_rules, ["SEC-AUTH-001"]);
assert.deepEqual(normalized.skipped_rules, ["SEC-SECRET-004"]);
assert.equal(normalized.tool_provenance[0].tool_name, "semgrep");
assert.equal(normalized.source_observations[0].line_start, 42);
assert.equal(normalized.quality_trace.evidence_score.score, 0.72);
assert.deepEqual(normalized.quality_trace.consensus_agents, ["security_agent"]);
assert.equal(normalized.quality_trace.critic_verdict.verdict, "real_bug");
assert.equal(normalized.real_pr_fixture_id, "spring-framework-12345");

console.log(JSON.stringify({ ok: true, verified: "real_findings_export" }));
