import assert from "node:assert/strict";
import { summarizeBoundRuleCoverage, summarizeBoundRuleCoverageByAgent } from "../mr-backend/build/backend/services/ObservabilityService.js";

const rows = [
  {
    coverage_json: JSON.stringify({
      candidate_quality: {
        bound_review_coverage: {
          required_count: 4,
          checked_count: 4,
          hit_count: 3,
          skipped_count: 0,
          missed_count: 1,
          coverage_rate: 1,
          resolved_count: 3,
          unresolved_count: 1,
          resolution_rate: 0.75,
          unresolved_rate: 0.25,
          hit_rate: 0.75,
          skip_rate: 0,
          rule_count: 2,
          skill_checkpoint_count: 2,
          rejected_count: 1,
          missed: [{ agent_id: "security_agent", rule_id: "SEC-AUTH-001" }],
          items: [
            { agent_id: "security_agent", type: "rule", checked: true, finding_count: 1, skipped: false, rejected_count: 0 },
            { agent_id: "security_agent", type: "skill_checkpoint", checked: true, finding_count: 0, skipped: false, rejected_count: 1 },
            { agent_id: "backend_agent", type: "rule", checked: true, finding_count: 1, skipped: false, rejected_count: 0 },
            { agent_id: "backend_agent", type: "skill_checkpoint", checked: true, finding_count: 1, skipped: false, rejected_count: 0 }
          ]
        }
      }
    })
  },
  {
    coverage_json: JSON.stringify({
      candidate_quality: {
        bound_review_coverage: {
          required_count: 3,
          checked_count: 3,
          hit_count: 1,
          skipped_count: 1,
          missed_count: 1,
          coverage_rate: 1,
          resolved_count: 2,
          unresolved_count: 1,
          resolution_rate: 0.6667,
          unresolved_rate: 0.3333,
          hit_rate: 0.3333,
          skip_rate: 0.3333,
          rule_count: 1,
          skill_checkpoint_count: 2,
          rejected_count: 0,
          missed: [{ agent_id: "redis_agent", checkpoint_id: "redis-ttl" }],
          items: [
            { agent_id: "redis_agent", type: "rule", checked: true, finding_count: 1, skipped: false, rejected_count: 0 },
            { agent_id: "redis_agent", type: "skill_checkpoint", checked: true, finding_count: 0, skipped: true, rejected_count: 0 },
            { agent_id: "redis_agent", type: "skill_checkpoint", checked: true, finding_count: 0, skipped: false, rejected_count: 0 }
          ]
        }
      }
    })
  },
  { coverage_json: "{}" },
  { coverage_json: "{bad-json" }
];

const summary = summarizeBoundRuleCoverage(rows);

assert.equal(summary.run_count, 2);
assert.equal(summary.required_count, 7);
assert.equal(summary.checked_count, 7);
assert.equal(summary.hit_count, 4);
assert.equal(summary.skipped_count, 1);
assert.equal(summary.missed_count, 2);
assert.equal(summary.resolved_count, 5);
assert.equal(summary.unresolved_count, 2);
assert.equal(summary.rule_count, 3);
assert.equal(summary.skill_checkpoint_count, 4);
assert.equal(summary.rejected_count, 1);
assert.equal(summary.low_coverage_run_count, 0);
assert.equal(summary.low_resolution_run_count, 1);
assert.equal(summary.coverage_rate, 1);
assert.equal(summary.resolution_rate, 0.7143);
assert.equal(summary.unresolved_rate, 0.2857);
assert.equal(summary.hit_rate, 0.5714);
assert.equal(summary.skip_rate, 0.1429);
assert.deepEqual(summary.missed.map((item) => item.agent_id), ["security_agent", "redis_agent"]);

const byAgent = summarizeBoundRuleCoverageByAgent(rows);
assert.deepEqual(byAgent.map((item) => item.agent_id), ["backend_agent", "redis_agent", "security_agent"]);
assert.equal(byAgent[0].required_count, 2);
assert.equal(byAgent[0].resolution_rate, 1);
assert.equal(byAgent[1].required_count, 3);
assert.equal(byAgent[1].resolved_count, 2);
assert.equal(byAgent[1].unresolved_count, 1);
assert.equal(byAgent[1].resolution_rate, 0.6667);
assert.equal(byAgent[2].required_count, 2);
assert.equal(byAgent[2].unresolved_count, 1);
assert.equal(byAgent[2].rejected_count, 1);

console.log(JSON.stringify({ ok: true, verified: "bound_rule_coverage_metrics", summary, by_agent: byAgent }));
