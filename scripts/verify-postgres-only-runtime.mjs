import { readFileSync, statSync, readdirSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

const scanTargets = [
  "common-backend",
  "mr-backend",
  "frontend",
  "package.json",
  "package-lock.json",
  "common-backend/config.example.json",
  "mr-backend/config.example.json"
];

const ignoredPathParts = [
  `${path.sep}node_modules${path.sep}`,
  `${path.sep}.venv${path.sep}`,
  `${path.sep}__pycache__${path.sep}`,
  `${path.sep}build${path.sep}`,
  `${path.sep}dist${path.sep}`,
  `${path.sep}data${path.sep}`,
  `${path.sep}config${path.sep}static-rules${path.sep}`
];

const ignoredExtensions = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".ico",
  ".woff",
  ".woff2",
  ".pyc"
]);

const checks = [
  { name: "sqlite-name", pattern: /\bsqlite\b/i },
  { name: "node-sqlite", pattern: /node:sqlite/i },
  { name: "sqlite3", pattern: /\bsqlite3\b/i },
  { name: "database-sync", pattern: /\bDatabaseSync\b/ },
  { name: "sqlite-master", pattern: /\bsqlite_master\b/i },
  { name: "sqlite-insert-or-ignore", pattern: /\bINSERT\s+OR\s+IGNORE\b/i },
  { name: "sqlite-datetime-now", pattern: /datetime\s*\(\s*['"]now['"]/i },
  { name: "sqlite-strftime", pattern: /\bstrftime\s*\(/i },
  { name: "sqlite-julianday", pattern: /\bjulianday\s*\(/i },
  { name: "sqlite-pragma", pattern: /\bPRAGMA\b/ },
  { name: "sqlite-randomblob", pattern: /\brandomblob\s*\(/i },
  { name: "sqlite-lower-hex-random", pattern: /\blower\s*\(\s*hex\s*\(/i },
  { name: "sqlite-scalar-max", pattern: /\bMAX\s*\([^()\n]+,\s*[^()\n]+\)/ },
  { name: "sqlite-scalar-min", pattern: /\bMIN\s*\([^()\n]+,\s*[^()\n]+\)/ },
  { name: "legacy-sql-translator", pattern: /translate(?:Legacy|Sqlite|_sqlite).*Postgres/i },
  { name: "placeholder-translator", pattern: /replace(?:Qmark|_qmark|Placeholders)|escape_psycopg_percent_literals/i },
  { name: "compat-wrapper", pattern: /\bCompat(?:Row|Cursor|Connection)\b/ },
  { name: "database-path", pattern: /\bdatabase_path\b/i }
];

function shouldIgnore(filePath) {
  const normalized = filePath.split(path.sep).join(path.sep);
  if (ignoredPathParts.some((part) => normalized.includes(part))) return true;
  return ignoredExtensions.has(path.extname(filePath).toLowerCase());
}

function listFiles(target) {
  const absolute = path.join(root, target);
  const stat = statSync(absolute);
  if (stat.isFile()) return [absolute];
  const files = [];
  const stack = [absolute];
  while (stack.length) {
    const current = stack.pop();
    if (!current || shouldIgnore(current)) continue;
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const child = path.join(current, entry.name);
      if (shouldIgnore(child)) continue;
      if (entry.isDirectory()) stack.push(child);
      if (entry.isFile()) files.push(child);
    }
  }
  return files;
}

const violations = [];
for (const target of scanTargets) {
  for (const file of listFiles(target)) {
    const text = readFileSync(file, "utf8");
    const lines = text.split(/\r?\n/);
    for (const [index, line] of lines.entries()) {
      for (const check of checks) {
        if (check.pattern.test(line)) {
          violations.push({
            check: check.name,
            file: path.relative(root, file),
            line: index + 1,
            text: line.trim()
          });
        }
      }
    }
  }
}

if (violations.length) {
  console.error("SQLite runtime remnants found:");
  for (const item of violations) {
    console.error(`${item.file}:${item.line} [${item.check}] ${item.text}`);
  }
  process.exit(1);
}

console.log("No SQLite runtime remnants found.");
