import { createApp } from "./app.js";
import { loadConfig } from "./config.js";
import { openDatabase } from "./db.js";
import { clearLogFiles, FileLogger } from "./logger.js";
import { MergeRequestRepository } from "./repositories/MergeRequestRepository.js";
import { ProjectRepository } from "./repositories/ProjectRepository.js";
import { RepositoryRepository } from "./repositories/RepositoryRepository.js";
import { ReviewJobRepository } from "./repositories/ReviewJobRepository.js";
import { createRoutes } from "./routes/mr-review.routes.js";
import { MrAutoSyncScheduler, shouldStartAutoSync } from "./services/MrAutoSyncScheduler.js";
import { MrSyncService } from "./services/MrSyncService.js";
import { ProjectConfigService } from "./services/ProjectConfigService.js";
import { ReviewQueueService } from "./services/ReviewQueueService.js";
import { queuedReviewWorkerCapacity } from "./services/WorkerLaunchPolicy.js";
import { spawnWorkerOnce } from "./services/WorkerProcessLauncher.js";

const config = loadConfig();
clearLogFiles(config);
const logger = new FileLogger(config);
const db = openDatabase(config);
const server = createApp(createRoutes(config, db, logger), logger);

function runWorkerOnce() {
  const count = queuedReviewWorkerCapacity({ config, db, projectConfigService });
  const spawnCount = Math.max(1, count);
  for (let index = 0; index < spawnCount; index += 1) {
    spawnWorkerOnce(logger);
  }
}

function runQueuedWorkersIfNeeded() {
  const count = queuedReviewWorkerCapacity({ config, db, projectConfigService });
  for (let index = 0; index < count; index += 1) {
    spawnWorkerOnce(logger);
  }
}

const projectRepository = new ProjectRepository(db);
const repositoryRepository = new RepositoryRepository(db);
const mergeRequestRepository = new MergeRequestRepository(db);
const reviewJobRepository = new ReviewJobRepository(db);
const projectConfigService = new ProjectConfigService(db);
const reviewQueueService = new ReviewQueueService(reviewJobRepository);
const mrSyncService = new MrSyncService(config, repositoryRepository, mergeRequestRepository, reviewQueueService, runWorkerOnce, projectConfigService);
const autoSyncScheduler = new MrAutoSyncScheduler(config, projectRepository, projectConfigService, mrSyncService, {
  logger: {
    log: (line: string) => logger.log("auto_sync", { message: line }),
    error: (line: string) => logger.log("auto_sync_failed", { message: line }, "error")
  }
});

const host = config.server?.host ?? "127.0.0.1";
const port = config.server?.port ?? 8011;
server.listen(port, host, () => {
  console.log(`Jolt CodeReview API listening on http://${host}:${port}`);
  logger.log("api_started", { host, port });
  if (shouldStartAutoSync()) {
    autoSyncScheduler.start();
    console.log("MR auto-sync scheduler started");
    logger.log("auto_sync_scheduler_started");
  } else {
    console.log("MR auto-sync scheduler disabled");
    logger.log("auto_sync_scheduler_disabled");
  }
  runQueuedWorkersIfNeeded();
});

function shutdown() {
  logger.log("api_shutdown");
  autoSyncScheduler.stop();
  server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
