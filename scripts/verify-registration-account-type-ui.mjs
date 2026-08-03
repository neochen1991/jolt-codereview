import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const authView = read("frontend", "src", "frontend", "components", "AuthViews.tsx");
const app = read("frontend", "src", "frontend", "App.tsx");
const projectView = read("frontend", "src", "frontend", "components", "ProjectViews.tsx");
const shared = read("frontend", "src", "frontend", "shared.ts");

assert.match(authView, /accountType/);
assert.match(authView, /value="user"/);
assert.match(authView, /value="project_admin"/);
assert.match(authView, /account_type: accountType/);
assert.match(app, /account_type: "user" \| "project_admin"/);
assert.match(app, /JSON\.stringify\(input\)/);
assert.match(shared, /export function canCreateProject\(user: User \| null\)/);
assert.match(shared, /user\?\.global_role === "project_admin"/);
assert.match(projectView, /canCreateProject\(user\)/);
assert.doesNotMatch(projectView, /const canCreateProject = isRootUser\(user\)/);

console.log(JSON.stringify({ ok: true, verified: "registration_account_type_ui" }, null, 2));
