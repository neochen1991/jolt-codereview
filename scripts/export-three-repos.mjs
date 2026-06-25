import { cpSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = new Set(process.argv.slice(2));
const outputArg = process.argv.find((arg) => arg.startsWith("--out="));
const outputRoot = outputArg ? path.resolve(root, outputArg.slice("--out=".length)) : root;
const force = args.has("--force");
const initGit = args.has("--init-git");
const moduleNames = ["common-backend", "mr-backend", "frontend"];

function cleanDir(dir) {
  if (existsSync(dir)) {
    if (!force) {
      throw new Error(`${dir} already exists. Re-run with --force to replace it.`);
    }
    rmSync(dir, { recursive: true, force: true });
  }
  mkdirSync(dir, { recursive: true });
}

function shouldCopy(item) {
  const basename = path.basename(item);
  if (basename === ".DS_Store") return false;
  const relative = path.relative(root, item);
  return ![
    "node_modules",
    "build",
    "dist",
    "data",
    "logs",
    "output",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".git"
  ].some((blocked) => relative === blocked || relative.includes(`${path.sep}${blocked}${path.sep}`) || relative.endsWith(`${path.sep}${blocked}`));
}

function copyModule(moduleName) {
  const source = path.join(root, moduleName);
  const target = path.join(outputRoot, moduleName);
  if (!existsSync(source)) {
    throw new Error(`Missing root module: ${source}`);
  }
  if (source === target) {
    return target;
  }
  cleanDir(target);
  cpSync(source, target, { recursive: true, filter: shouldCopy });
  return target;
}

if (outputRoot !== root) {
  cleanDir(outputRoot);
}

const repos = Object.fromEntries(moduleNames.map((moduleName) => [moduleName, copyModule(moduleName)]));

if (initGit && outputRoot !== root) {
  for (const dir of Object.values(repos)) {
    const result = spawnSync("git", ["init"], { cwd: dir, encoding: "utf8", stdio: "pipe" });
    if (result.status !== 0) {
      throw new Error(`git init failed in ${dir}\n${result.stdout}\n${result.stderr}`);
    }
  }
}

if (outputRoot !== root) {
  writeFileSync(path.join(outputRoot, "README.md"), `# Jolt Three Module Export

Generated from ${root}.

- common-backend: public platform backend. See \`common-backend/README.md\`.
- mr-backend: MR review backend and worker. See \`mr-backend/README.md\`.
- frontend: React/Vite frontend. See \`frontend/README.md\`.

Regenerate from the repository root:

\`\`\`bash
node scripts/export-three-repos.mjs --force --out=/path/to/output
\`\`\`
`, "utf8");
}

console.log(JSON.stringify({ ok: true, output_root: outputRoot, repos }, null, 2));
