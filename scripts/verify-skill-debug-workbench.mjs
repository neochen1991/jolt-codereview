import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const routes = read("mr-backend", "src", "backend", "routes", "review.routes.ts");
const migrations = read("mr-backend", "src", "backend", "db", "migrations.ts");
const repository = read("mr-backend", "src", "backend", "repositories", "ReviewJobRepository.ts");
const sessionRepository = read("mr-backend", "src", "backend", "repositories", "SkillDebugSessionRepository.ts");
const skillRepository = read("mr-backend", "src", "backend", "repositories", "RuleDocumentRepository.ts");
const snapshotService = read("mr-backend", "src", "backend", "services", "SkillDebugSnapshotService.ts");
const ruleRoutes = read("mr-backend", "src", "backend", "routes", "rules.routes.ts");
const worker = read("mr-backend", "worker", "review_runtime.py");
const debugWorker = read("mr-backend", "worker", "skill_debug.py");
const router = read("mr-backend", "worker", "orchestration", "nodes", "route_agents.py");
const frontend = read("frontend", "src", "frontend", "components", "ConfigViews.tsx");

const checks = [
  [migrations, "debug_context_json", "review_jobs debug context migration"],
  [migrations, "skill_debug_sessions", "isolated debug session table"],
  [migrations, "execution_kind", "review job execution classification"],
  [migrations, "skill_debug_candidate", "candidate debug variant"],
  [migrations, "custom_skill_versions", "immutable skill version bundles"],
  [sessionRepository, "class SkillDebugSessionRepository", "debug session repository"],
  [repository, "debug_context_json", "queue persistence"],
  [repository, "enqueueDebug", "non-idempotent debug queue insertion"],
  [repository, "production_review", "production job isolation"],
  [skillRepository, "findCustomSkillVersion", "selectable skill versions"],
  [skillRepository, "activateCustomSkillVersion", "version activation projection"],
  [snapshotService, "class SkillDebugSnapshotService", "server-side snapshot builder"],
  [snapshotService, "snapshot_sha256", "deterministic snapshot hash"],
  [snapshotService, "stableStringify", "stable snapshot serialization"],
  [ruleRoutes, "/api/projects/:projectId/custom-skills/:skillKey/versions/:version/activate", "audited skill activation"],
  [routes, "/api/mr-review/projects/:projectId/skill-debug-sessions", "debug session create and history routes"],
  [routes, "/api/mr-review/skill-debug-sessions/:sessionId", "stable debug session detail route"],
  [routes, "/api/mr-review/skill-debug-sessions/:sessionId/cancel", "debug cancellation route"],
  [routes, "/api/mr-review/skill-debug-sessions/:sessionId/rerun", "debug rerun route"],
  [routes, "/api/mr-review/skill-debug-sessions/:sessionId/export", "redacted diagnostic export"],
  [routes, 'ensureProjectRole(params.projectId, actorId, "project_admin")', "administrator-only debug access"],
  [routes, "/api/mr-review/merge-requests/:mrId/skill-debug-runs", "debug creation route"],
  [routes, "/api/mr-review/projects/:projectId/skill-debug-runs", "debug history route"],
  [routes, "/api/mr-review/skill-debug-runs/:jobId", "debug detail route"],
  [routes, "production_route", "production routing mode"],
  [routes, "targeted", "targeted routing mode"],
  [routes, "skill_debug.publish_forbidden", "publish protection"],
  [routes, "execution_kind", "publish checks finding execution ownership"],
  [worker, "debug_context_json", "worker debug context loading"],
  [debugWorker, "production_side_effects_allowed", "debug side-effect isolation"],
  [debugWorker, "apply_debug_snapshot", "frozen snapshot execution"],
  [debugWorker, "redact_snapshot", "snapshot secret redaction"],
  [router, "skill_debug_targeted_override", "targeted override trace"],
  [frontend, "调试 Skill", "binding debug entry"],
  [frontend, "严格生产路由", "production route UI"],
  [frontend, "Skill 调试工作台", "workbench UI"],
  [frontend, "baseline", "A/B baseline view"],
  [frontend, "调试历史", "debug history"],
  [frontend, "取消调试", "debug cancellation action"],
  [frontend, "导出诊断包", "redacted export action"]
];

const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill debug workbench verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_debug_workbench" }, null, 2));
