import { existsSync } from "node:fs";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";
import { loadConfig } from "./config-utils.mjs";

const root = path.resolve(import.meta.dirname, "..");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const commonConfigPath = path.resolve(process.env.COMMON_CONFIG_PATH || path.join(root, "common-backend", "config.json"));
const mrConfigPath = path.resolve(process.env.MR_CONFIG_PATH || path.join(root, "mr-backend", "config.json"));
const commonExamplePath = path.join(root, "common-backend", "config.example.json");
const mrExamplePath = path.join(root, "mr-backend", "config.example.json");

function requireConfig(label, configPath, examplePath) {
  if (existsSync(configPath)) return;
  console.error(`${label} config not found: ${configPath}`);
  console.error(`Create it from the module template first: cp ${path.relative(root, examplePath)} ${path.relative(root, configPath)}`);
  process.exit(1);
}

requireConfig("Common Backend", commonConfigPath, commonExamplePath);
requireConfig("MR Backend", mrConfigPath, mrExamplePath);

const commonConfig = loadConfig(commonConfigPath, commonExamplePath);
const mrConfig = loadConfig(mrConfigPath, mrExamplePath);
const apiHost = commonConfig.server?.host || mrConfig.server?.host || "127.0.0.1";
const commonPort = Number(commonConfig.server?.common_port || commonConfig.server?.port || 9022);
const mrPort = Number(mrConfig.server?.mr_port || mrConfig.server?.port || 9021);
const frontendHost = process.env.JOLT_FRONTEND_HOST || "127.0.0.1";
const frontendPort = Number(process.env.JOLT_FRONTEND_PORT || 9020);

if (!existsSync(path.join(root, "node_modules"))) {
  console.error("node_modules not found. Run npm install first.");
  process.exit(1);
}

try {
  const dependencyCheck = execFileSync(
    process.execPath,
    ["scripts/check-runtime-deps.mjs"],
    {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"]
    }
  );
  process.stdout.write(dependencyCheck);
} catch (error) {
  if (error.stdout) process.stdout.write(error.stdout);
  if (error.stderr) process.stderr.write(error.stderr);
  process.exit(error.status || 1);
}

const baseEnv = {
  ...process.env,
  JOLT_INTERNAL_SERVICE_TOKEN: process.env.JOLT_INTERNAL_SERVICE_TOKEN || "jolt-local-internal-service-token",
  COMMON_API_BASE: process.env.COMMON_API_BASE || `http://${apiHost}:${commonPort}`,
  MR_API_BASE: process.env.MR_API_BASE || `http://${apiHost}:${mrPort}`,
  VITE_COMMON_API_BASE: process.env.VITE_COMMON_API_BASE || `http://${apiHost}:${commonPort}`,
  VITE_MR_API_BASE: process.env.VITE_MR_API_BASE || `http://${apiHost}:${mrPort}`,
  VITE_API_BASE: process.env.VITE_API_BASE || `http://${apiHost}:${mrPort}`
};
const commonEnv = { ...baseEnv, CONFIG_PATH: commonConfigPath };
const mrEnv = { ...baseEnv, CONFIG_PATH: mrConfigPath };
const frontendEnv = { ...baseEnv };

const children = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function parsePids(output) {
  return [...new Set(String(output || "")
    .split(/\r?\n/)
    .map((line) => Number(line.trim()))
    .filter((pid) => Number.isInteger(pid) && pid > 0 && pid !== process.pid))];
}

function pidsForPortWindows(port) {
  try {
    return parsePids(execFileSync("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Command",
      `Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique`
    ], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }));
  } catch {
    try {
      const output = execFileSync("netstat.exe", ["-ano", "-p", "tcp"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
      const pids = output
        .split(/\r?\n/)
        .filter((line) => line.includes("LISTENING") && new RegExp(`[:.]${port}\\s`).test(line))
        .map((line) => Number(line.trim().split(/\s+/).at(-1)))
        .filter((pid) => Number.isInteger(pid) && pid > 0 && pid !== process.pid);
      return [...new Set(pids)];
    } catch {
      return [];
    }
  }
}

function pidsForPortUnix(port) {
  try {
    return parsePids(execFileSync("lsof", [`-tiTCP:${port}`, "-sTCP:LISTEN"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }));
  } catch {
    try {
      return parsePids(execFileSync("fuser", ["-n", "tcp", String(port)], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }));
    } catch {
      return [];
    }
  }
}

function pidsForPort(port) {
  return process.platform === "win32" ? pidsForPortWindows(port) : pidsForPortUnix(port);
}

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function killPid(pid, label, port) {
  if (process.platform === "win32") {
    execFileSync("taskkill.exe", ["/PID", String(pid), "/T", "/F"], { stdio: ["ignore", "ignore", "ignore"] });
    return;
  }
  process.kill(pid, "SIGTERM");
  await sleep(800);
  if (isAlive(pid)) {
    console.warn(`${label} port ${port}: pid ${pid} did not exit after SIGTERM, sending SIGKILL`);
    process.kill(pid, "SIGKILL");
  }
}

async function releasePort(label, port) {
  if (!Number.isInteger(port) || port <= 0) return;
  const pids = pidsForPort(port);
  if (!pids.length) return;
  console.log(`${label} port ${port} is already in use by pid(s): ${pids.join(", ")}. Stopping old process(es)...`);
  for (const pid of pids) {
    try {
      await killPid(pid, label, port);
    } catch (error) {
      console.warn(`Failed to stop pid ${pid} on ${label} port ${port}: ${error.message}`);
    }
  }
  await sleep(300);
  const remaining = pidsForPort(port);
  if (remaining.length) {
    throw new Error(`${label} port ${port} is still in use by pid(s): ${remaining.join(", ")}`);
  }
}

function start(label, args, env = baseEnv) {
  console.log(`Starting ${label}: npm ${args.join(" ")}`);
  const child = spawn(npmCommand, args, {
    cwd: root,
    env,
    stdio: "inherit",
    shell: false
  });
  children.push(child);
  child.on("exit", (code) => {
    if (code && code !== 0) {
      console.error(`${label} exited with code ${code}`);
      shutdown(code);
    }
  });
}

function shutdown(code = 0) {
  for (const child of children) {
    if (!child.killed) child.kill();
  }
  process.exit(code);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

console.log("Jolt CodeReview local dev");
console.log(`Common:  http://${apiHost}:${commonPort}`);
console.log(`MR Backend: http://${apiHost}:${mrPort}`);
console.log(`Frontend: http://${frontendHost}:${frontendPort}`);
console.log("MR worker: managed by MR Backend");
console.log("MR poller: built into API auto-sync scheduler");

await releasePort("Common API", commonPort);
await releasePort("MR Backend", mrPort);
await releasePort("Frontend", frontendPort);

start("Common API", ["run", "dev:common"], commonEnv);
start("MR Backend", ["run", "dev:mr"], mrEnv);
if (process.env.JOLT_START_EXTERNAL_POLLER === "1") {
  start("Poller", ["run", "poll"], mrEnv);
}
start("Frontend", ["run", "dev:web"], {
  ...frontendEnv,
  JOLT_FRONTEND_HOST: frontendHost,
  JOLT_FRONTEND_PORT: String(frontendPort)
});
