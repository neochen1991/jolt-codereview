import { createApp } from "./app.js";
import { loadConfig } from "./config.js";
import { openDatabase } from "./db.js";
import { clearLogFiles, FileLogger } from "./logger.js";
import { createCommonRoutes } from "./routes/common.routes.js";
import { startRuntimeFileCleanup } from "./services/RuntimeFileCleanupService.js";

const config = loadConfig();
clearLogFiles(config);
const logger = new FileLogger(config);
const db = openDatabase(config);
const server = createApp(createCommonRoutes(config, db), logger);
const stopRuntimeFileCleanup = startRuntimeFileCleanup(config, logger);

const host = config.server?.host ?? "127.0.0.1";
const port = config.server?.common_port ?? 9022;
server.listen(port, host, () => {
  console.log(`Jolt Common Backend listening on http://${host}:${port}`);
  logger.log("common_api_started", { host, port });
});

function shutdown() {
  logger.log("common_api_shutdown");
  stopRuntimeFileCleanup();
  server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
