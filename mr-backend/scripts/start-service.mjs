import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const nodeCommand = process.execPath;
const children = [];
let shuttingDown = false;

function start(label, args, extraEnv = {}) {
  console.log(`Starting ${label}: node ${args.join(" ")}`);
  const child = spawn(nodeCommand, args, {
    cwd: root,
    env: { ...process.env, ...extraEnv },
    stdio: "inherit",
    shell: false
  });
  children.push({ label, child });
  child.on("exit", (code, signal) => {
    if (shuttingDown) return;
    const exitCode = code ?? 0;
    if (exitCode !== 0 || signal) {
      console.error(`${label} exited with ${signal ? `signal ${signal}` : `code ${exitCode}`}`);
      shutdown(exitCode || 1);
      return;
    }
    console.log(`${label} exited`);
    shutdown(0);
  });
}

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const { child } of children) {
    if (!child.killed) child.kill();
  }
  setTimeout(() => process.exit(code), 200);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

if (!existsSync(path.join(root, "build", "backend", "mr-server.js"))) {
  console.error("MR Backend build output not found. Run `npm run build` first.");
  process.exit(1);
}

console.log("Jolt MR Backend service");
console.log("MR API and review worker will run in the same service boundary.");

start("MR API", ["build/backend/mr-server.js"]);
start("Worker", ["scripts/run-python.mjs", "worker/review_worker.py", "--loop"], {
  JOLT_SKIP_LOG_CLEANUP: process.env.JOLT_SKIP_LOG_CLEANUP || "1"
});
