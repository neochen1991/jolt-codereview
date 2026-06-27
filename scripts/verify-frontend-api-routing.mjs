import { readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = path.resolve(import.meta.dirname, "..");
const sourcePath = path.join(root, "frontend", "src", "frontend", "apiRouting.ts");
const source = readFileSync(sourcePath, "utf8");
const compiled = source
  .replace(/\bexport\s+type\s+[A-Za-z0-9_]+\s*=\s*\{[\s\S]*?\};/g, "")
  .replace(/:\s*ApiBaseConfig/g, "")
  .replace(/:\s*string/g, "")
  .replace(/([A-Za-z0-9_]+)\?/g, "$1")
  .replace(/\bexport\s+(const|function)\s+/g, "$1 ")
  .concat("\nexport { resolveApiBase, COMMON_API_PATH_PATTERNS };\n");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { resolveApiBase, COMMON_API_PATH_PATTERNS } = await import(moduleUrl);

const bases = {
  legacyBase: "http://legacy.example",
  commonBase: "http://common.example",
  mrBase: "http://mr.example"
};

const cases = [
  ["/api/auth/login", bases.commonBase],
  ["/api/auth/session", bases.commonBase],
  ["/api/me", bases.commonBase],
  ["/api/me/settings", bases.commonBase],
  ["/api/system/storage", bases.commonBase],
  ["/api/models/effective-config", bases.commonBase],
  ["/internal/models/effective-config", bases.commonBase],
  ["/api/projects", bases.commonBase],
  ["/api/projects/discover", bases.commonBase],
  ["/api/projects/project_default", bases.commonBase],
  ["/api/projects/project_default/members", bases.commonBase],
  ["/api/projects/project_default/settings", bases.commonBase],
  ["/api/projects/project_default/settings/llm/test", bases.commonBase],
  ["/api/projects/project_default/effective-config", bases.commonBase],
  ["/api/projects/project_default/invitations", bases.commonBase],
  ["/api/mr-review/projects/project_default/merge-requests", bases.mrBase],
  ["/api/full-review/projects/project_default/jobs", bases.mrBase],
  ["/api/vcs/project_default/capabilities", bases.mrBase],
  ["/api/projects/project_default/repositories", bases.mrBase],
  ["/api/projects/project_default/agents", bases.mrBase],
  ["/api/projects/project_default/expert-skill-bindings", bases.mrBase],
  ["/api/projects/project_default/expert-skill-bindings/skill_binding_123", bases.mrBase]
];

const failures = [];
for (const [apiPath, expected] of cases) {
  const actual = resolveApiBase(apiPath, bases);
  if (actual !== expected) failures.push({ apiPath, expected, actual });
}

const legacyFallback = resolveApiBase("/api/auth/login", { legacyBase: bases.legacyBase });
if (legacyFallback !== bases.legacyBase) {
  failures.push({ apiPath: "legacy fallback", expected: bases.legacyBase, actual: legacyFallback });
}

if (!Array.isArray(COMMON_API_PATH_PATTERNS) || COMMON_API_PATH_PATTERNS.length === 0) {
  failures.push({ apiPath: "COMMON_API_PATH_PATTERNS", expected: "non-empty array", actual: COMMON_API_PATH_PATTERNS });
}

if (failures.length) {
  throw new Error(`frontend API routing failed:\n${JSON.stringify(failures, null, 2)}\nsource=${pathToFileURL(sourcePath)}`);
}

console.log(JSON.stringify({ ok: true, cases: cases.length, common_patterns: COMMON_API_PATH_PATTERNS.length }, null, 2));
