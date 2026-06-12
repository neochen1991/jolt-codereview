import assert from "node:assert/strict";
import { authenticatedRequest } from "./api-auth.mjs";

const suffix = `${Date.now().toString(36)}_${Math.random().toString(16).slice(2, 8)}`;
const displayName = `Profile Smoke ${suffix}`;
const email = `profile-${suffix}@example.com`;

const updated = await authenticatedRequest("/api/me/profile", {
  method: "PATCH",
  body: JSON.stringify({ display_name: displayName, email })
});
assert.equal(updated.user.display_name, displayName, "display name should update");
assert.equal(updated.user.email, email, "email should update");

const me = await authenticatedRequest("/api/me");
assert.equal(me.user.display_name, displayName, "updated display name should be returned by /api/me");
assert.equal(me.user.email, email, "updated email should be returned by /api/me");

await authenticatedRequest("/api/auth/logout", { method: "POST", body: "{}" });

console.log("User profile menu API checks passed.");
