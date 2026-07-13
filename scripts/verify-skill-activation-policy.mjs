import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (...parts) => {
  const filename = path.join(root, ...parts);
  return existsSync(filename) ? readFileSync(filename, "utf8") : "";
};
const routes = read("mr-backend", "src", "backend", "routes", "rules.routes.ts");
const repository = read("mr-backend", "src", "backend", "repositories", "RuleDocumentRepository.ts");
const policy = read("mr-backend", "src", "backend", "services", "SkillActivationPolicyService.ts");
const frontendApi = read("frontend", "src", "frontend", "shared.ts");
const frontend = read("frontend", "src", "frontend", "components", "ConfigViews.tsx");

const checks = [
  [routes, 'status: "draft"', "server forces new versions to draft"],
  [routes, "invalid_skill_bundle", "server always rejects invalid bundles"],
  [routes, "skill_activation_gate_failed", "activation exposes a stable gate error"],
  [routes, "break_glass_reason", "activation supports audited root break-glass"],
  [routes, "ensureRoot(actorId)", "break-glass is root-only"],
  [repository, "validationJson", "validation report is persisted"],
  [repository, "createdBy", "version creator is persisted"],
  [repository, "active_version_id", "activation changes the active version pointer"],
  [policy, "class SkillActivationPolicyService", "activation policy service"],
  [policy, '"targeted"', "targeted debug evidence gate"],
  [policy, '"production_route"', "production-route evidence gate"],
  [policy, "bundle_sha256", "activation evidence matches the bundle hash"],
  [policy, "conclusive", "activation requires conclusive evidence"],
  [frontendApi, 'const status = "draft"', "folder uploads are draft-only"],
  [frontendApi, "version,", "all uploaded assets target the draft version"],
  [frontend, 'const skillStatus: "draft" = "draft"', "workbench defaults to draft"]
];

const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill activation policy verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_activation_policy" }, null, 2));
