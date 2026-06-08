import { MrAutoSyncScheduler, shouldStartAutoSync } from "../build/backend/services/MrAutoSyncScheduler.js";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitFor(condition, message) {
  const started = Date.now();
  while (Date.now() - started < 1000) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(message);
}

const calls = [];
const projectRepository = {
  listProjects() {
    return [{ id: "project_a" }, { id: "project_b" }];
  }
};
const projectConfigService = {
  effectiveConfig(projectId) {
    return {
      effective_config: {
        queue_policy: {
          poll_interval_seconds: projectId === "project_a" ? 20 : 30
        }
      }
    };
  }
};
const mrSyncService = {
  async syncProject(projectId) {
    calls.push(projectId);
    return { repositories: 1, merge_requests: 1, jobs_created: 1, errors: [] };
  }
};

const logs = [];
const scheduler = new MrAutoSyncScheduler(
  {},
  projectRepository,
  projectConfigService,
  mrSyncService,
  { logger: { log: (line) => logs.push(line), error: (line) => logs.push(line) } }
);

scheduler.start();
scheduler.start();
await waitFor(() => calls.length === 2, "scheduler did not immediately sync both projects");
assert(calls.join(",") === "project_a,project_b", `unexpected sync order: ${calls.join(",")}`);
assert(scheduler.timers.size === 2, "scheduler should create one timer per project");
assert(logs.length === 2, "scheduler should log sync result per project");

scheduler.stop();
assert(scheduler.timers.size === 0, "scheduler.stop should clear timers");

const previousNodeEnv = process.env.NODE_ENV;
const previousDisabled = process.env.JOLT_AUTO_SYNC_DISABLED;
process.env.NODE_ENV = "test";
delete process.env.JOLT_AUTO_SYNC_DISABLED;
assert(shouldStartAutoSync() === false, "NODE_ENV=test should disable auto sync");
process.env.NODE_ENV = "development";
process.env.JOLT_AUTO_SYNC_DISABLED = "1";
assert(shouldStartAutoSync() === false, "JOLT_AUTO_SYNC_DISABLED=1 should disable auto sync");
process.env.JOLT_AUTO_SYNC_DISABLED = "true";
assert(shouldStartAutoSync() === false, "JOLT_AUTO_SYNC_DISABLED=true should disable auto sync");
delete process.env.JOLT_AUTO_SYNC_DISABLED;
assert(shouldStartAutoSync() === true, "development without disable flag should enable auto sync");
if (previousNodeEnv === undefined) delete process.env.NODE_ENV;
else process.env.NODE_ENV = previousNodeEnv;
if (previousDisabled === undefined) delete process.env.JOLT_AUTO_SYNC_DISABLED;
else process.env.JOLT_AUTO_SYNC_DISABLED = previousDisabled;

console.log(JSON.stringify({
  immediate_sync_projects: calls,
  timer_count_after_start: 2,
  timer_count_after_stop: scheduler.timers.size,
  logs
}, null, 2));
