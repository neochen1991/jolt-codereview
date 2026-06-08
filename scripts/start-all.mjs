import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";

if (!existsSync(path.join(root, "node_modules"))) {
  console.error("node_modules not found. Run npm install first.");
  process.exit(1);
}

const env = {
  ...process.env,
  CONFIG_PATH: process.env.CONFIG_PATH || path.join(root, "config.json")
};

const children = [];

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
console.log("API:      http://127.0.0.1:8011");
console.log("Frontend: http://127.0.0.1:5173");
console.log("MR poller: built into API auto-sync scheduler");

start("API", ["run", "dev:api"]);
start("Worker", ["run", "worker"]);
if (process.env.JOLT_START_EXTERNAL_POLLER === "1") {
  start("Poller", ["run", "poll"]);
}
start("Frontend", ["run", "dev:web"]);
