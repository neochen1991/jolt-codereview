import { existsSync, readFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const scriptArgs = process.argv.slice(2);
const configPath = process.env.CONFIG_PATH || path.join(root, "config.json");

function configuredPythonBin() {
  if (!existsSync(configPath)) return null;
  try {
    const config = JSON.parse(readFileSync(configPath, "utf8"));
    return config?.runtime?.python_bin || null;
  } catch {
    return null;
  }
}

function candidateCommands() {
  if (process.env.PYTHON_BIN) {
    return [{ command: process.env.PYTHON_BIN, prefixArgs: [] }];
  }
  const configured = configuredPythonBin();
  if (configured) {
    return [{ command: configured, prefixArgs: [] }];
  }
  const localVenvPython = process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
  if (existsSync(localVenvPython)) {
    return [{ command: localVenvPython, prefixArgs: [] }];
  }
  if (process.platform === "win32") {
    return [
      { command: "py", prefixArgs: ["-3"] },
      { command: "python", prefixArgs: [] },
      { command: "python3", prefixArgs: [] }
    ];
  }
  return [
    { command: "python3", prefixArgs: [] },
    { command: "python", prefixArgs: [] }
  ];
}

function findPython() {
  for (const candidate of candidateCommands()) {
    const probe = spawnSync(candidate.command, [...candidate.prefixArgs, "--version"], {
      cwd: root,
      encoding: "utf8",
      shell: false
    });
    if (probe.status === 0) {
      return candidate;
    }
  }
  return null;
}

const python = findPython();
if (!python) {
  console.error("Python 3 was not found. Set PYTHON_BIN to your Python executable path.");
  process.exit(1);
}

const childEnv = {
  ...process.env,
  PYTHONUTF8: process.env.PYTHONUTF8 || "1",
  PYTHONIOENCODING: process.env.PYTHONIOENCODING || "utf-8"
};

const child = spawn(python.command, [...python.prefixArgs, ...scriptArgs], {
  cwd: root,
  stdio: "inherit",
  env: childEnv,
  shell: false
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  }
  process.exit(code ?? 0);
});
