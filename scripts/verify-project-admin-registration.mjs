import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const authRoutes = read("common-backend", "src", "backend", "routes", "auth.routes.ts");
const projectRoutes = read("common-backend", "src", "backend", "routes", "projects.routes.ts");
const projectRepository = read("common-backend", "src", "backend", "repositories", "ProjectRepository.ts");
const createProjectRoute = projectRoutes.slice(
  projectRoutes.indexOf('route("POST", "/api/projects"'),
  projectRoutes.indexOf('route("GET", "/api/projects/:projectId"')
);

assert.match(authRoutes, /account_type/);
assert.match(authRoutes, /registrationGlobalRole/);
assert.match(authRoutes, /badRequest\(error instanceof Error \? error\.message/);
assert.match(createProjectRoute, /canCreateProjectForGlobalRole/);
assert.doesNotMatch(createProjectRoute, /ensureRoot\(actorId\)/);
assert.match(projectRoutes, /ensureProjectRole\(params\.projectId/);
assert.doesNotMatch(projectRoutes, /ensureProjectRole[\s\S]{0,120}global_role/);
assert.match(projectRepository, /INSERT INTO project_members[\s\S]*'project_admin'/);

console.log(JSON.stringify({ ok: true, verified: "project_admin_registration" }, null, 2));
