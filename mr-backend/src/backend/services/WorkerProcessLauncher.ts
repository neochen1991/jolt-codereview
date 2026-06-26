import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";

export interface WorkerProcessLogger {
  log(event: string, fields?: Record<string, unknown>, level?: "info" | "warn" | "error"): void;
  error?(event: string, error: unknown, fields?: Record<string, unknown>): void;
}

export function spawnWorkerOnce(logger?: WorkerProcessLogger) {
  const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
  const command = "npm run worker:once";
  const detached = process.platform !== "win32";
  const child = spawn(npmCommand, ["run", "worker:once"], {
    cwd: process.cwd(),
    env: { ...process.env, JOLT_SKIP_LOG_CLEANUP: "1" },
    stdio: "ignore",
    detached,
    windowsHide: true
  });

  const fields = {
    pid: child.pid ?? null,
    command,
    platform: process.platform,
    detached
  };
  logger?.log("worker_spawned", fields);

  child.on("error", (error) => {
    if (logger?.error) {
      logger.error("worker_spawn_failed", error, { command, platform: process.platform, detached });
      return;
    }
    logger?.log("worker_spawn_failed", {
      command,
      platform: process.platform,
      detached,
      error_message: error.message
    }, "error");
  });

  child.on("exit", (code, signal) => {
    if ((code ?? 0) === 0 && !signal) return;
    logger?.log("worker_process_exited", {
      command,
      platform: process.platform,
      detached,
      code,
      signal
    }, "warn");
  });

  if (detached) {
    child.unref();
  }
}

export function spawnWorkerLoop(logger?: WorkerProcessLogger): ChildProcess {
  const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
  const command = "npm run worker";
  const child = spawn(npmCommand, ["run", "worker"], {
    cwd: process.cwd(),
    env: { ...process.env, JOLT_SKIP_LOG_CLEANUP: "1" },
    stdio: "ignore",
    windowsHide: true
  });

  logger?.log("worker_loop_spawned", {
    pid: child.pid ?? null,
    command,
    platform: process.platform
  });

  child.on("error", (error) => {
    if (logger?.error) {
      logger.error("worker_loop_spawn_failed", error, { command, platform: process.platform });
      return;
    }
    logger?.log("worker_loop_spawn_failed", {
      command,
      platform: process.platform,
      error_message: error.message
    }, "error");
  });

  return child;
}
