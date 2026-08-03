import assert from "node:assert/strict";

const {
  registrationGlobalRole,
  canCreateProjectForGlobalRole
} = await import("../common-backend/build/backend/services/AccountRolePolicy.js");

assert.equal(registrationGlobalRole("user", 1), "user");
assert.equal(registrationGlobalRole("project_admin", 1), "project_admin");
assert.equal(registrationGlobalRole("user", 0), "root");
assert.equal(canCreateProjectForGlobalRole("root"), true);
assert.equal(canCreateProjectForGlobalRole("project_admin"), true);
assert.equal(canCreateProjectForGlobalRole("user"), false);
assert.throws(() => registrationGlobalRole("system_admin", 1), /account_type/);

console.log(JSON.stringify({ ok: true, verified: "account_role_policy" }, null, 2));
