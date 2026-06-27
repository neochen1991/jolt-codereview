import { readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = path.resolve(import.meta.dirname, "..");
const sourcePath = path.join(root, "frontend", "src", "frontend", "skillUploadPaths.ts");
const source = readFileSync(sourcePath, "utf8");
const compiled = source
  .replace(/\bexport\s+type\s+[A-Za-z0-9_]+\s*=\s*\{[\s\S]*?\};/g, "")
  .replace(/:\s*SkillUploadFile\[\]/g, "")
  .replace(/:\s*SkillUploadFile/g, "")
  .replace(/:\s*string/g, "")
  .replace(/\bexport\s+(const|function)\s+/g, "$1 ")
  .concat("\nexport { cleanUploadPath, uploadRelativePath, normalizeSkillBundleAssetPath, isStandardSkillAssetPath, skillRootNameFromFiles };\n");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const {
  cleanUploadPath,
  uploadRelativePath,
  normalizeSkillBundleAssetPath,
  isStandardSkillAssetPath,
  skillRootNameFromFiles
} = await import(moduleUrl);

const cases = [
  [{ name: "SKILL.md", webkitRelativePath: "security-skill\\SKILL.md" }, "SKILL.md"],
  [{ name: "rules.md", webkitRelativePath: "security-skill\\references\\rules.md" }, "references/rules.md"],
  [{ name: "authz.md", webkitRelativePath: "security-skill\\References\\authz.md" }, "references/authz.md"],
  [{ name: "patterns.js", webkitRelativePath: "security-skill\\Scripts\\patterns.js" }, "scripts/patterns.js"],
  [{ name: "rule-map.json", webkitRelativePath: "security-skill\\Assets\\rule-map.json" }, "assets/rule-map.json"],
  [{ name: "SKILL.md" }, "SKILL.md"],
  [{ name: "authz-rules.md" }, "references/authz-rules.md"],
  [{ name: "security-patterns.js" }, "scripts/security-patterns.js"],
  [{ name: "sample-finding.json" }, "assets/sample-finding.json"]
];

const failures = [];
for (const [file, expected] of cases) {
  const actual = normalizeSkillBundleAssetPath(file);
  if (actual !== expected) failures.push({ file, expected, actual });
  if (!isStandardSkillAssetPath(actual)) failures.push({ file, expected: "standard skill asset path", actual });
}

const cleaned = cleanUploadPath("security-skill\\\\references\\\\rules.md");
if (cleaned !== "security-skill/references/rules.md") {
  failures.push({ case: "cleanUploadPath", expected: "security-skill/references/rules.md", actual: cleaned });
}

const relative = uploadRelativePath({ name: "rules.md", webkitRelativePath: "security-skill\\references\\rules.md" });
if (relative !== "security-skill/references/rules.md") {
  failures.push({ case: "uploadRelativePath", expected: "security-skill/references/rules.md", actual: relative });
}

const rootName = skillRootNameFromFiles([{ name: "SKILL.md", webkitRelativePath: "security-skill\\SKILL.md" }]);
if (rootName !== "security-skill") {
  failures.push({ case: "skillRootNameFromFiles", expected: "security-skill", actual: rootName });
}

if (failures.length) {
  throw new Error(`skill upload path normalization failed:\n${JSON.stringify(failures, null, 2)}\nsource=${pathToFileURL(sourcePath)}`);
}

console.log(JSON.stringify({ ok: true, cases: cases.length }, null, 2));
