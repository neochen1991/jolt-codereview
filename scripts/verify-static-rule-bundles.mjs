import fs from "node:fs";
import path from "node:path";

const root = path.resolve(new URL("..", import.meta.url).pathname);
const rulesRoot = path.join(root, "config", "static-rules");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function exists(relativePath) {
  return fs.existsSync(path.join(rulesRoot, relativePath));
}

function countFiles(relativePath, predicate = () => true) {
  const target = path.join(rulesRoot, relativePath);
  if (!fs.existsSync(target)) return 0;
  let count = 0;
  for (const entry of fs.readdirSync(target, { withFileTypes: true })) {
    const child = path.join(relativePath, entry.name);
    if (entry.isDirectory()) count += countFiles(child, predicate);
    else if (predicate(entry.name)) count += 1;
  }
  return count;
}

const manifest = JSON.parse(fs.readFileSync(path.join(rulesRoot, "manifest.json"), "utf8"));

assert(exists("semgrep/java"), "Semgrep Java rule directory is missing");
assert(countFiles("semgrep/java", (name) => name.endsWith(".yaml") || name.endsWith(".yml")) > 0, "Semgrep Java rules are empty");
for (const name of ["bestpractices.xml", "errorprone.xml", "security.xml", "performance.xml"]) {
  assert(exists(`pmd/category/java/${name}`), `PMD ruleset missing: ${name}`);
}
for (const name of ["google_checks.xml", "sun_checks.xml"]) {
  assert(exists(`checkstyle/${name}`), `Checkstyle config missing: ${name}`);
}
assert(exists("gitleaks/gitleaks.toml"), "Gitleaks default config is missing");
assert(exists("kics/queries"), "KICS queries directory is missing");
assert(countFiles("kics/queries", (name) => name.endsWith(".json")) > 0, "KICS queries are empty");
assert(Object.values(manifest.sync_results ?? {}).length || Array.isArray(manifest.sync_results), "Manifest sync results missing");

console.log(JSON.stringify({
  ok: true,
  semgrep_java_rules: countFiles("semgrep/java", (name) => name.endsWith(".yaml") || name.endsWith(".yml")),
  kics_query_files: countFiles("kics/queries", (name) => name.endsWith(".json")),
  updated_at: manifest.updated_at
}, null, 2));
