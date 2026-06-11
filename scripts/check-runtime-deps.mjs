import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const requireFromRoot = createRequire(path.join(root, "package.json"));
const args = new Set(process.argv.slice(2));
const installMissing = args.has("--install") || process.env.JOLT_INSTALL_MISSING_DEPS === "1";
const skipNode = args.has("--python-only");
const skipPython = args.has("--node-only");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const configPath = process.env.CONFIG_PATH || path.join(root, "config.json");

const nodePackages = ["pg", "@types/pg"];
const pythonModules = [{ module: "psycopg", package: "psycopg[binary]>=3.2.0" }];

function readConfig() {
  if (!existsSync(configPath)) return {};
  try {
    return JSON.parse(readFileSync(configPath, "utf8"));
  } catch {
    return {};
  }
}

function nodePackageInstalled(packageName) {
  try {
    requireFromRoot.resolve(`${packageName}/package.json`);
    return true;
  } catch {
    return false;
  }
}

function run(command, commandArgs, label) {
  const result = spawnSync(command, commandArgs, {
    cwd: root,
    stdio: "inherit",
    shell: false
  });
  if (result.status !== 0) {
    throw new Error(`${label} failed with exit code ${result.status ?? "unknown"}`);
  }
}

function commandWorks(command, prefixArgs = []) {
  const result = spawnSync(command, [...prefixArgs, "--version"], {
    cwd: root,
    encoding: "utf8",
    shell: false,
    stdio: ["ignore", "pipe", "ignore"]
  });
  return result.status === 0;
}

function configuredPythonBin() {
  const config = readConfig();
  return config?.runtime?.python_bin || null;
}

function localVenvPython() {
  return process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
}

function pythonCandidates() {
  const configured = configuredPythonBin();
  const candidates = [];
  if (process.env.PYTHON_BIN) candidates.push({ command: process.env.PYTHON_BIN, prefixArgs: [] });
  if (configured) candidates.push({ command: configured, prefixArgs: [] });
  const venvPython = localVenvPython();
  if (existsSync(venvPython)) candidates.push({ command: venvPython, prefixArgs: [] });
  if (process.platform === "win32") {
    candidates.push({ command: "py", prefixArgs: ["-3"] });
    candidates.push({ command: "python", prefixArgs: [] });
  } else {
    candidates.push({ command: "python3", prefixArgs: [] });
    candidates.push({ command: "python", prefixArgs: [] });
  }
  return candidates;
}

function findPython() {
  for (const candidate of pythonCandidates()) {
    if (commandWorks(candidate.command, candidate.prefixArgs)) return candidate;
  }
  return null;
}

function ensureVenv() {
  const venvPython = localVenvPython();
  if (existsSync(venvPython)) return { command: venvPython, prefixArgs: [] };
  const systemPython = findPython();
  if (!systemPython) {
    throw new Error("Python 3 was not found. Install Python 3.10+ first or set PYTHON_BIN.");
  }
  console.log("Creating Python virtual environment .venv");
  run(systemPython.command, [...systemPython.prefixArgs, "-m", "venv", ".venv"], "python -m venv .venv");
  return { command: venvPython, prefixArgs: [] };
}

function pythonModuleInstalled(python, moduleName) {
  const result = spawnSync(python.command, [...python.prefixArgs, "-c", `import ${moduleName}`], {
    cwd: root,
    encoding: "utf8",
    shell: false,
    stdio: ["ignore", "pipe", "pipe"]
  });
  return result.status === 0;
}

function checkNodeDependencies() {
  const missing = nodePackages.filter((packageName) => !nodePackageInstalled(packageName));
  if (!missing.length) return [];
  if (!installMissing) return missing.map((item) => `Node package missing: ${item}`);
  console.log(`Installing missing Node runtime packages via npm install: ${missing.join(", ")}`);
  run(npmCommand, ["install"], "npm install");
  return nodePackages.filter((packageName) => !nodePackageInstalled(packageName)).map((item) => `Node package still missing after npm install: ${item}`);
}

function checkPythonDependencies() {
  let python = installMissing ? ensureVenv() : findPython();
  if (!python) return ["Python 3 was not found. Install Python 3.10+ or set PYTHON_BIN."];
  const missing = pythonModules.filter((item) => !pythonModuleInstalled(python, item.module));
  if (!missing.length) return [];
  if (!installMissing) return missing.map((item) => `Python package missing: ${item.module}`);
  console.log(`Installing missing Python runtime packages via requirements.txt: ${missing.map((item) => item.package).join(", ")}`);
  run(python.command, [...python.prefixArgs, "-m", "pip", "install", "--upgrade", "pip"], "pip install --upgrade pip");
  run(python.command, [...python.prefixArgs, "-m", "pip", "install", "-r", "requirements.txt"], "pip install -r requirements.txt");
  python = { command: localVenvPython(), prefixArgs: [] };
  return pythonModules.filter((item) => !pythonModuleInstalled(python, item.module)).map((item) => `Python package still missing after pip install: ${item.module}`);
}

const errors = [
  ...(skipNode ? [] : checkNodeDependencies()),
  ...(skipPython ? [] : checkPythonDependencies())
];

if (errors.length) {
  console.error("Runtime dependency check failed:");
  for (const error of errors) console.error(`- ${error}`);
  console.error("");
  console.error("Fix:");
  console.error("- Run `npm install` to install Node packages including `pg`.");
  console.error("- Run `.venv/bin/python -m pip install -r requirements.txt` on Linux/macOS, or `.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt` on Windows.");
  console.error("- Or start with dependency repair enabled: `JOLT_INSTALL_MISSING_DEPS=1 npm run dev` / `powershell -File scripts/start-windows.ps1 -InstallIfMissing`.");
  process.exit(1);
}

console.log("Runtime dependency check passed.");
