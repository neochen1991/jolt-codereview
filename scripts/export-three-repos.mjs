import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = new Set(process.argv.slice(2));
const outputArg = process.argv.find((arg) => arg.startsWith("--out="));
const outputRoot = path.resolve(root, outputArg ? outputArg.slice("--out=".length) : "split-repos");
const force = args.has("--force");
const initGit = args.has("--init-git");

const rootPkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));

function cleanDir(dir) {
  if (existsSync(dir)) {
    if (!force) {
      throw new Error(`${dir} already exists. Re-run with --force to replace it.`);
    }
    rmSync(dir, { recursive: true, force: true });
  }
  mkdirSync(dir, { recursive: true });
}

function copyIfExists(from, to) {
  const source = path.join(root, from);
  if (!existsSync(source)) return;
  const target = path.join(to, from);
  mkdirSync(path.dirname(target), { recursive: true });
  cpSync(source, target, {
    recursive: true,
    filter: (item) => {
      const relative = path.relative(root, item);
      return ![
        "node_modules",
        "build",
        "dist",
        "data",
        "logs",
        "output",
        "split-repos",
        ".git"
      ].some((blocked) => relative === blocked || relative.startsWith(`${blocked}${path.sep}`));
    }
  });
}

function writeJson(file, value) {
  writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function writeText(file, value) {
  writeFileSync(file, value, "utf8");
}

function backendTsconfig() {
  return {
    extends: "./tsconfig.json",
    compilerOptions: {
      noEmit: false,
      outDir: "build",
      rootDir: "src",
      module: "NodeNext",
      moduleResolution: "NodeNext",
      lib: ["ES2022"],
      jsx: "react-jsx"
    },
    include: ["src/backend/**/*.ts"]
  };
}

function backendBasePackage(name, description, entrypoint, extraScripts = {}) {
  return {
    name,
    version: rootPkg.version,
    private: true,
    type: "module",
    description,
    scripts: {
      build: "tsc -p tsconfig.backend.json",
      dev: `npm run build && node build/backend/${entrypoint}`,
      start: `node build/backend/${entrypoint}`,
      verify: "npm run build",
      ...extraScripts
    },
    dependencies: rootPkg.dependencies,
    devDependencies: {
      "@types/node": rootPkg.devDependencies["@types/node"],
      typescript: rootPkg.devDependencies.typescript
    }
  };
}

function frontendPackage() {
  return {
    name: "@jolt/frontend",
    version: rootPkg.version,
    private: true,
    type: "module",
    scripts: {
      dev: "vite --host 127.0.0.1",
      build: "tsc --noEmit && vite build",
      start: "vite --host 127.0.0.1",
      verify: "npm run build"
    },
    dependencies: {
      "lucide-react": rootPkg.dependencies["lucide-react"],
      react: rootPkg.dependencies.react,
      "react-dom": rootPkg.dependencies["react-dom"],
      vite: rootPkg.dependencies.vite
    },
    devDependencies: {
      "@types/node": rootPkg.devDependencies["@types/node"],
      "@types/react": rootPkg.devDependencies["@types/react"],
      "@types/react-dom": rootPkg.devDependencies["@types/react-dom"],
      typescript: rootPkg.devDependencies.typescript
    }
  };
}

function commonBackendRepo(dir) {
  cleanDir(dir);
  for (const item of ["src/backend", "config.example.json", "tsconfig.json"]) copyIfExists(item, dir);
  writeJson(path.join(dir, "package.json"), backendBasePackage(
    "@jolt/common-backend",
    "Jolt public platform backend for users, permissions, system settings, and model management.",
    "common-server.js"
  ));
  writeJson(path.join(dir, "tsconfig.backend.json"), backendTsconfig());
  writeText(path.join(dir, ".gitignore"), "node_modules/\nbuild/\ndata/\nlogs/\n.env\n.env.*\n!.env.example\n");
  writeText(path.join(dir, "README.md"), `# Jolt Common Backend

公共模块后端，负责用户管理、权限管理、系统设置和模型管理。

## Start

\`\`\`bash
npm install
npm run dev
\`\`\`

默认监听 \`127.0.0.1:8010\`，可通过 \`config.json\` 的 \`server.common_port\` 调整。

## Owned Routes

- \`/api/auth/*\`
- \`/api/me/*\`
- \`/api/permissions/*\`
- \`/api/models/*\`
- \`/api/system/*\`
- \`/internal/auth/introspect\`
- \`/internal/models/effective-config\`
`);
}

function mrBackendRepo(dir) {
  cleanDir(dir);
  for (const item of ["src/backend", "worker", "scripts", "config", "docs/nfr-and-slo.md", "config.example.json", "requirements.txt", "tsconfig.json"]) {
    copyIfExists(item, dir);
  }
  writeJson(path.join(dir, "package.json"), backendBasePackage(
    "@jolt/mr-backend",
    "Jolt MR review backend for repositories, merge requests, review jobs, quality, webhooks, and worker orchestration.",
    "mr-server.js",
    {
      worker: "node scripts/run-python.mjs worker/review_worker.py --loop",
      "worker:once": "node scripts/run-python.mjs worker/review_worker.py --once",
      "verify:worker-orchestration": "node scripts/run-python.mjs scripts/verify_worker_orchestration_nodes.py"
    }
  ));
  writeJson(path.join(dir, "tsconfig.backend.json"), backendTsconfig());
  writeText(path.join(dir, ".gitignore"), "node_modules/\nbuild/\ndata/\nlogs/\noutput/\n.venv/\n.env\n.env.*\n!.env.example\n");
  writeText(path.join(dir, "README.md"), `# Jolt MR Backend

MR 主后端，负责仓库、MR 同步、评审任务、规则、专家 Agent、质量观测、Webhook、VCS 代理和 Python Worker。

## Start

\`\`\`bash
npm install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm run dev
npm run worker
\`\`\`

默认监听 \`127.0.0.1:8011\`，可通过 \`config.json\` 的 \`server.mr_port\` 调整。

## Owned Routes

- \`/api/projects/*\`
- \`/api/mr-review/*\`
- \`/api/full-review/*\`
- \`/api/vcs/*\`
- \`/api/webhooks/*\`
- \`/api/observability/*\`
- \`/api/quality/*\`
`);
}

function frontendRepo(dir) {
  cleanDir(dir);
  for (const item of ["src/frontend", "index.html", "tsconfig.json"]) copyIfExists(item, dir);
  writeJson(path.join(dir, "package.json"), frontendPackage());
  writeText(path.join(dir, ".gitignore"), "node_modules/\ndist/\n.env\n.env.*\n!.env.example\n");
  writeText(path.join(dir, ".env.example"), [
    "VITE_COMMON_API_BASE=http://127.0.0.1:8010",
    "VITE_MR_API_BASE=http://127.0.0.1:8011",
    "VITE_API_BASE=http://127.0.0.1:8011",
    ""
  ].join("\n"));
  writeText(path.join(dir, "README.md"), `# Jolt Frontend

独立前端项目，通过路径路由同时访问 Common Backend 和 MR Backend。

## Start

\`\`\`bash
npm install
npm run dev
\`\`\`

默认监听 \`127.0.0.1:5173\`。

## API Environment

- \`VITE_COMMON_API_BASE\`: 公共模块后端，默认 \`http://127.0.0.1:8010\`
- \`VITE_MR_API_BASE\`: MR 主后端，默认 \`http://127.0.0.1:8011\`
- \`VITE_API_BASE\`: 兼容旧单后端模式
`);
}

cleanDir(outputRoot);
const repos = {
  "common-backend": path.join(outputRoot, "common-backend"),
  "mr-backend": path.join(outputRoot, "mr-backend"),
  frontend: path.join(outputRoot, "frontend")
};

commonBackendRepo(repos["common-backend"]);
mrBackendRepo(repos["mr-backend"]);
frontendRepo(repos.frontend);

if (initGit) {
  for (const dir of Object.values(repos)) {
    const result = spawnSync("git", ["init"], { cwd: dir, encoding: "utf8", stdio: "pipe" });
    if (result.status !== 0) {
      throw new Error(`git init failed in ${dir}\n${result.stdout}\n${result.stderr}`);
    }
  }
}

writeText(path.join(outputRoot, "README.md"), `# Jolt Three Repository Export

Generated from ${root}.

- common-backend: public platform backend
- mr-backend: MR review backend and worker
- frontend: React/Vite frontend

Regenerate:

\`\`\`bash
node scripts/export-three-repos.mjs --force
\`\`\`
`);

console.log(JSON.stringify({ ok: true, output_root: outputRoot, repos }, null, 2));
