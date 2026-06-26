import { createApp } from "./app.js";
import { loadConfig } from "./config.js";
import { openDatabase } from "./db.js";
import { clearLogFiles, FileLogger } from "./logger.js";
import { MergeRequestRepository } from "./repositories/MergeRequestRepository.js";
import { RepositoryRepository } from "./repositories/RepositoryRepository.js";
import { ReviewJobRepository } from "./repositories/ReviewJobRepository.js";
import { createMrRoutes } from "./routes/mr-review.routes.js";
import { MrAutoSyncScheduler, shouldStartAutoSync } from "./services/MrAutoSyncScheduler.js";
import { MrSyncService } from "./services/MrSyncService.js";
import { ReviewQueueService } from "./services/ReviewQueueService.js";
import { queuedReviewWorkerCapacity } from "./services/WorkerLaunchPolicy.js";
import { spawnWorkerOnce } from "./services/WorkerProcessLauncher.js";
import { WorkerPoolManager } from "./services/WorkerPoolManager.js";
import { CommonBackendClient } from "./services/CommonBackendClient.js";

const config = loadConfig();
clearLogFiles(config);
const logger = new FileLogger(config);
const db = openDatabase(config);
const server = createApp(createMrRoutes(config, db, logger), logger);

const repositoryRepository = new RepositoryRepository(db);
const mergeRequestRepository = new MergeRequestRepository(db);
const reviewJobRepository = new ReviewJobRepository(db);
const commonClient = new CommonBackendClient(config);
const reviewQueueService = new ReviewQueueService(reviewJobRepository);
const workerPool = new WorkerPoolManager({ config, db, logger, effectiveConfig });

async function effectiveConfig(projectId: string) {
  return commonClient.projectEffectiveConfig(projectId);
}

function runWorkerOnce() {
  queuedReviewWorkerCapacity({ config, db, effectiveConfig })
    .then((count) => {
      const spawnCount = Math.max(1, count);
      for (let index = 0; index < spawnCount; index += 1) {
        spawnWorkerOnce(logger);
      }
    })
    .catch((error) => logger.error("worker_capacity_failed", error));
}

function runQueuedWorkersIfNeeded() {
  queuedReviewWorkerCapacity({ config, db, effectiveConfig })
    .then((count) => {
      for (let index = 0; index < count; index += 1) {
        spawnWorkerOnce(logger);
      }
    })
    .catch((error) => logger.error("worker_capacity_failed", error));
}

const mrSyncService = new MrSyncService(config, repositoryRepository, mergeRequestRepository, reviewQueueService, runWorkerOnce, effectiveConfig);
const autoSyncScheduler = new MrAutoSyncScheduler(
  config,
  () => db.prepare("SELECT DISTINCT project_id FROM repositories WHERE status = 'active'").all().map((row: any) => String(row.project_id)),
  effectiveConfig,
  mrSyncService,
  {
  logger: {
    log: (line: string) => logger.log("auto_sync", { message: line }),
    error: (line: string) => logger.log("auto_sync_failed", { message: line }, "error")
  }
  }
);

const host = config.server?.host ?? "127.0.0.1";
const port = config.server?.mr_port ?? config.server?.port ?? 9021;
server.listen(port, host, () => {
  console.log(`Jolt MR Backend listening on http://${host}:${port}`);
  logger.log("mr_api_started", { host, port });
  if (shouldStartAutoSync()) {
    autoSyncScheduler.start();
    console.log("MR auto-sync scheduler started");
    logger.log("auto_sync_scheduler_started");
  } else {
    console.log("MR auto-sync scheduler disabled");
    logger.log("auto_sync_scheduler_disabled");
  }
  workerPool.start();
  runQueuedWorkersIfNeeded();
});

function shutdown() {
  logger.log("mr_api_shutdown");
  autoSyncScheduler.stop();
  workerPool.stop();
  server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
