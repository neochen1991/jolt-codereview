import assert from "node:assert/strict";

const { reviewDetailVisibility } = await import(
  "../mr-backend/build/backend/services/ReviewVisibilityPolicy.js"
);

assert.equal(reviewDetailVisibility("project_admin", false), "full");
assert.equal(reviewDetailVisibility("system_admin", false), "full");
assert.equal(reviewDetailVisibility("reviewer", false), "findings_only");
assert.equal(reviewDetailVisibility("observer", false), "findings_only");
assert.equal(reviewDetailVisibility("", true), "full");

console.log(JSON.stringify({ ok: true, verified: "review_visibility_policy" }, null, 2));
