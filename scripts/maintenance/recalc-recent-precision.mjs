import path from "node:path";

if (!process.env.CONFIG_PATH) {
  process.env.CONFIG_PATH = process.env.MR_CONFIG_PATH || path.resolve(process.cwd(), "mr-backend", "config.json");
}

const { loadConfig } = await import("../../mr-backend/build/backend/config.js");
const { openDatabase } = await import("../../mr-backend/build/backend/db.js");
const { FeedbackLearningService } = await import("../../mr-backend/build/backend/services/FeedbackLearningService.js");

function argValue(name) {
  const prefix = `${name}=`;
  const item = process.argv.slice(2).find((arg) => arg === name || arg.startsWith(prefix));
  if (!item || item === name) return item === name ? "true" : "";
  return item.slice(prefix.length);
}

const projectId = argValue("--project-id") || undefined;
const windowDays = Number(argValue("--window-days") || 90);
const dryRun = argValue("--dry-run") === "true";

const config = loadConfig();
const db = openDatabase(config);
try {
  if (dryRun) {
    console.log(JSON.stringify({ dry_run: true, project_id: projectId ?? null, window_days: windowDays }, null, 2));
  } else {
    const service = new FeedbackLearningService(db);
    const result = service.recalculateRecentPrecision({ projectId, windowDays });
    console.log(JSON.stringify({ ok: true, ...result }, null, 2));
  }
} finally {
  db.close?.();
}
