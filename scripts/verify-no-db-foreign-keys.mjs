import { readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { relative, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";

const root = resolve(import.meta.dirname, "..");
const targets = ["src", "worker", "scripts", "package.json", "README.md", "config.json"];
const files = execFileSync("rg", ["--files", ...targets], { cwd: root, encoding: "utf8" })
  .split(/\r?\n/)
  .filter(Boolean)
  .filter((file) => file !== "scripts/verify-no-db-foreign-keys.mjs");

const patterns = [
  /\b(TEXT|INTEGER|REAL|BLOB|NUMERIC)\b[^;\n,]*\bREFERENCES\b/i,
  /\bFOREIGN\s+KEY\b/i,
  /PRAGMA\s+foreign_keys/i,
];

const violations = [];
for (const file of files) {
  const text = readFileSync(resolve(root, file), "utf8");
  const lines = text.split(/\r?\n/);
  lines.forEach((line, index) => {
    if (patterns.some((pattern) => pattern.test(line))) {
      violations.push(`${relative(root, resolve(root, file))}:${index + 1}: ${line.trim()}`);
    }
  });
}

if (violations.length) {
  throw new Error(`Database foreign key dependencies are not allowed:\n${violations.join("\n")}`);
}

const { migrate } = await import("../build/backend/db/migrations.js");
const db = new DatabaseSync(resolve(tmpdir(), `jolt-no-fk-${process.pid}.sqlite`));
db.exec(`
  CREATE TABLE legacy_parent (id TEXT PRIMARY KEY);
  CREATE TABLE legacy_child (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES legacy_parent(id),
    value TEXT NOT NULL
  );
  CREATE INDEX idx_legacy_child_value ON legacy_child(value);
  INSERT INTO legacy_parent (id) VALUES ('p1');
  INSERT INTO legacy_child (id, parent_id, value) VALUES ('c1', 'p1', 'kept');
`);
migrate(db);
const legacyForeignKeys = db.prepare("PRAGMA foreign_key_list(legacy_child)").all();
const legacyRow = db.prepare("SELECT value FROM legacy_child WHERE id = 'c1'").get();
const legacyIndex = db.prepare("SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_legacy_child_value'").get();
db.close();

if (legacyForeignKeys.length) {
  throw new Error(`Legacy table still has foreign keys: ${JSON.stringify(legacyForeignKeys)}`);
}
if (!legacyRow || legacyRow.value !== "kept") {
  throw new Error("Legacy table rebuild did not preserve data");
}
if (!legacyIndex) {
  throw new Error("Legacy table rebuild did not preserve explicit indexes");
}

console.log("database foreign key dependency scan passed");
