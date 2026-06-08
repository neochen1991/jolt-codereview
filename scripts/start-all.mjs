import { existsSync } from "node:fs";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";
import { loadConfig } from "./config-utils.mjs";

const root = path.resolve(import.meta.dirname, "..");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const config = loadConfig();
const apiHost = config.server?.host || "127.0.0.1";
const apiPort = Number(config.server?.port || 8011);
const frontendHost = process.env.JOLT_FRONTEND_HOST || "127.0.0.1";
const frontendPort = Number(process.env.JOLT_FRONTEND_PORT || 5173);

if (!existsSync(path.join(root, "node_modules"))) {
  console.error("node_modules not found. Run npm install first.");
  process.exit(1);
}

const env = {
  ...process.env,
  CONFIG_PATH: process.env.CONFIG_PATH || path.join(root, "config.json")
};

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

function start(label, args) {
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
console.log(`API:      http://${apiHost}:${apiPort}`);
console.log(`Frontend: http://${frontendHost}:${frontendPort}`);
console.log("MR poller: built into API auto-sync scheduler");

await releasePort("API", apiPort);
await releasePort("Frontend", frontendPort);

start("API", ["run", "dev:api"]);
start("Worker", ["run", "worker"]);
if (process.env.JOLT_START_EXTERNAL_POLLER === "1") {
  start("Poller", ["run", "poll"]);
}
start("Frontend", ["run", "dev:web", "--", "--host", frontendHost, "--port", String(frontendPort), "--strictPort"]);
