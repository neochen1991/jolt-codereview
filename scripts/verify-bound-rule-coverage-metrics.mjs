import assert from "node:assert/strict";
import { summarizeBoundRuleCoverage } from "../mr-backend/build/backend/services/ObservabilityService.js";

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
          hit_rate: 0.75,
          skip_rate: 0,
          rule_count: 2,
          skill_checkpoint_count: 2,
          rejected_count: 1,
          missed: [{ agent_id: "security_agent", rule_id: "SEC-AUTH-001" }]
        }
      }
    })
  },
  {
    coverage_json: JSON.stringify({
      candidate_quality: {
        bound_review_coverage: {
          required_count: 3,
          checked_count: 1,
          hit_count: 1,
          skipped_count: 1,
          missed_count: 2,
          coverage_rate: 0.3333,
          hit_rate: 0.3333,
          skip_rate: 0.3333,
          rule_count: 1,
          skill_checkpoint_count: 2,
          rejected_count: 0,
          missed: [{ agent_id: "redis_agent", checkpoint_id: "redis-ttl" }]
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
assert.equal(summary.checked_count, 5);
assert.equal(summary.hit_count, 4);
assert.equal(summary.skipped_count, 1);
assert.equal(summary.missed_count, 3);
assert.equal(summary.rule_count, 3);
assert.equal(summary.skill_checkpoint_count, 4);
assert.equal(summary.rejected_count, 1);
assert.equal(summary.low_coverage_run_count, 1);
assert.equal(summary.coverage_rate, 0.7143);
assert.equal(summary.hit_rate, 0.5714);
assert.equal(summary.skip_rate, 0.1429);
assert.deepEqual(summary.missed.map((item) => item.agent_id), ["security_agent", "redis_agent"]);

console.log(JSON.stringify({ ok: true, verified: "bound_rule_coverage_metrics", summary }));
