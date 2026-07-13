import assert from "node:assert/strict";

const { summarizeSkillRuntimeDashboard } = await import("../mr-backend/build/backend/services/ObservabilityService.js");

const coverage = (executionKind, facts) => JSON.stringify({
  execution_kind: executionKind,
  skill_runtime_schema: "skill_runtime_facts_v1",
  skill_runtime_facts: facts
});

const runs = [
  {
    id: "run-1",
    started_at: "2026-07-13T08:00:00Z",
    execution_kind: "production_review",
    coverage_json: coverage("production_review", [{
      skill_key: "secure-review",
      skill_version: "v2",
      agent_id: "security_agent",
      model: "model-a",
      applicable: true,
      routed: true,
      loaded: true,
      required_checkpoint_count: 2,
      completed_checkpoint_count: 2,
      unresolved_checkpoint_count: 0,
      judge_hit_checkpoint_count: 1,
      judge_unclassified_deletion_count: 0,
      checkpoints: [{ checkpoint_id: "SEC-001" }, { checkpoint_id: "SEC-002" }]
    }])
  },
  {
    id: "run-2",
    started_at: "2026-07-13T09:00:00Z",
    execution_kind: "production_review",
    coverage_json: coverage("production_review", [{
      skill_key: "secure-review",
      skill_version: "v2",
      agent_id: "security_agent",
      model: "model-a",
      applicable: true,
      routed: false,
      loaded: false,
      required_checkpoint_count: 0,
      completed_checkpoint_count: 0,
      unresolved_checkpoint_count: 0,
      judge_hit_checkpoint_count: 0,
      judge_unclassified_deletion_count: 0,
      checkpoints: []
    }])
  },
  {
    id: "run-3",
    started_at: "2026-07-13T10:00:00Z",
    execution_kind: "production_review",
    coverage_json: coverage("production_review", [{
      skill_key: "secure-review",
      skill_version: "v2",
      agent_id: "security_agent",
      model: "model-a",
      applicable: false,
      routed: true,
      loaded: false,
      required_checkpoint_count: 1,
      completed_checkpoint_count: 0,
      unresolved_checkpoint_count: 1,
      judge_hit_checkpoint_count: 0,
      judge_unclassified_deletion_count: 1,
      checkpoints: [{ checkpoint_id: "SEC-001" }]
    }])
  },
  {
    id: "debug-1",
    started_at: "2026-07-13T11:00:00Z",
    execution_kind: "skill_debug",
    coverage_json: coverage("skill_debug", [{ skill_key: "secure-review", applicable: true, routed: true, loaded: true }])
  }
];

const findings = [
  { id: "f1", run_id: "run-1", agent_id: "security_agent", covered_rules: ["SEC-001"], feedback: "accepted" },
  { id: "f2", run_id: "run-1", agent_id: "security_agent", covered_rules: ["SEC-002"], feedback: "false_positive" },
  { id: "f3", run_id: "run-1", agent_id: "security_agent", covered_rules: ["SEC-001"], feedback: null },
  { id: "debug-f", run_id: "debug-1", agent_id: "security_agent", covered_rules: ["SEC-001"], feedback: "false_positive" }
];

const dashboard = summarizeSkillRuntimeDashboard("project-1", runs, findings);
assert.equal(dashboard.totals.production_run_count, 3);
assert.equal(dashboard.totals.skill_opportunity_count, 3);
assert.equal(dashboard.totals.routed_count, 2);
assert.equal(dashboard.totals.applicable_count, 2);
assert.equal(dashboard.totals.applicable_routed_count, 1);
assert.equal(dashboard.totals.loaded_count, 1);
assert.equal(dashboard.totals.required_checkpoint_count, 3);
assert.equal(dashboard.totals.completed_checkpoint_count, 2);
assert.equal(dashboard.totals.unresolved_checkpoint_count, 1);
assert.equal(dashboard.totals.judge_hit_checkpoint_count, 1);
assert.equal(dashboard.totals.feedback_eligible_count, 3);
assert.equal(dashboard.totals.feedback_labeled_count, 2);
assert.equal(dashboard.totals.false_positive_count, 1);
assert.equal(dashboard.totals.all_route_rate, 0.6667);
assert.equal(dashboard.totals.applicable_route_rate, 0.5);
assert.equal(dashboard.totals.load_rate, 0.5);
assert.equal(dashboard.totals.checkpoint_completion_rate, 0.6667);
assert.equal(dashboard.totals.unresolved_rate, 0.3333);
assert.equal(dashboard.totals.hit_rate, 0.5);
assert.equal(dashboard.totals.false_positive_rate, 0.5);
assert.equal(dashboard.totals.feedback_coverage_rate, 0.6667);
assert.equal(dashboard.totals.judge_unclassified_deletion_count, 1);
assert.equal(dashboard.items[0].model, "model-a");

const empty = summarizeSkillRuntimeDashboard("project-1", [], []);
for (const key of ["all_route_rate", "applicable_route_rate", "load_rate", "checkpoint_completion_rate", "unresolved_rate", "hit_rate", "false_positive_rate", "feedback_coverage_rate"]) {
  assert.equal(empty.totals[key], null, `${key} should be null`);
}

console.log(JSON.stringify({ ok: true, verified: "skill_runtime_dashboard" }, null, 2));
