import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const migrations = read("mr-backend", "src", "backend", "db", "migrations.ts");
const repository = read("mr-backend", "src", "backend", "repositories", "RuleDocumentRepository.ts");
const snapshot = read("mr-backend", "src", "backend", "services", "SkillDebugSnapshotService.ts");
const worker = read("mr-backend", "worker", "review_runtime.py");

const checks = [
  [migrations, "active_version_id", "custom_skills active version pointer"],
  [migrations, "bundle_sha256", "immutable bundle hash"],
  [migrations, "validation_json", "persisted validation report"],
  [migrations, "skill_debug_validity_v1", "debug validity schema marker"],
  [repository, "resolveCanonicalSkillVersion", "canonical TypeScript resolver"],
  [snapshot, "resolveCanonicalSkillVersion", "debug snapshot uses canonical resolver"],
  [snapshot, "bundle_sha256", "debug snapshot includes bundle hash"],
  [worker, "load_canonical_skill_version", "production worker canonical resolver"],
  [worker, "active_version_id", "production worker follows active version pointer"],
  [worker, "skill_version_legacy_fallback", "legacy fallback is observable"]
];

const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill version canonicalization verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_version_canonicalization" }, null, 2));
