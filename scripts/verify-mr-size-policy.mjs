import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const policyModule = await import(pathToFileURL(path.join(root, "build/backend/services/MrSizePolicy.js")));
const migrationsModule = await import(pathToFileURL(path.join(root, "build/backend/db/migrations.js")));
const mrRepoModule = await import(pathToFileURL(path.join(root, "build/backend/repositories/MergeRequestRepository.js")));
const repoRepoModule = await import(pathToFileURL(path.join(root, "build/backend/repositories/RepositoryRepository.js")));
const jobRepoModule = await import(pathToFileURL(path.join(root, "build/backend/repositories/ReviewJobRepository.js")));
const projectConfigModule = await import(pathToFileURL(path.join(root, "build/backend/services/ProjectConfigService.js")));
const queueModule = await import(pathToFileURL(path.join(root, "build/backend/services/ReviewQueueService.js")));
const syncModule = await import(pathToFileURL(path.join(root, "build/backend/services/MrSyncService.js")));
const {
  DEFAULT_MAX_ADDED_LINES_PER_MR,
  changedFileAdditions,
  evaluateMrSizePolicy,
  evaluateMrSizePolicyWithFiles,
  mergeRequestAdditions,
  mrSizeBlockedMessage
} = policyModule;
const { migrate } = migrationsModule;
const { MergeRequestRepository } = mrRepoModule;
const { RepositoryRepository } = repoRepoModule;
const { ReviewJobRepository } = jobRepoModule;
const { ProjectConfigService } = projectConfigModule;
const { ReviewQueueService } = queueModule;
const { MrSyncService } = syncModule;

assert.equal(DEFAULT_MAX_ADDED_LINES_PER_MR, 2000);

const defaultAllowed = evaluateMrSizePolicy(
  { additions: 2000, deletions: 10000, metadata: {} },
  {}
);
assert.equal(defaultAllowed.allowed, true, "default threshold should allow exactly 2000 added lines");
assert.equal(defaultAllowed.addedLines, 2000);
assert.equal(defaultAllowed.maxAddedLines, 2000);

const defaultBlocked = evaluateMrSizePolicy(
  { additions: 2001, deletions: 0, metadata: {} },
  {}
);
assert.equal(defaultBlocked.allowed, false, "default threshold should block more than 2000 added lines");
assert.match(mrSizeBlockedMessage(defaultBlocked), /新增代码行数 2001 行超过项目配置阈值 2000 行/);

const customAllowed = evaluateMrSizePolicy(
  { additions: 500, deletions: 0, metadata: {} },
  { review_policy: { max_added_lines_per_mr: 500 } }
);
assert.equal(customAllowed.allowed, true, "custom threshold should allow equal value");

const customBlocked = evaluateMrSizePolicy(
  { additions: 501, deletions: 0, metadata: {} },
  { review_policy: { max_added_lines_per_mr: 500 } }
);
assert.equal(customBlocked.allowed, false, "custom threshold should block larger values");
assert.equal(customBlocked.maxAddedLines, 500);

const deletionsOnly = evaluateMrSizePolicy(
  { additions: 0, deletions: 100000, metadata: {} },
  {}
);
assert.equal(deletionsOnly.allowed, true, "deletions should not count toward added line guard");

assert.equal(
  mergeRequestAdditions({ metadata_json: JSON.stringify({ additions: 2003, deletions: 9 }) }),
  2003,
  "repository row should derive additions from metadata_json"
);
assert.equal(
  changedFileAdditions([
    { filename: "src/A.java", additions: 1200 },
    { filename: "src/B.java", patch: "@@ -0,0 +1,3 @@\n+one\n+two\n+three" }
  ]),
  1203,
  "changed-file additions should combine file metadata and patch additions"
);
const filesBlocked = evaluateMrSizePolicyWithFiles(
  { additions: 0, metadata: { additions: 0 } },
  [
    { filename: "src/A.java", additions: 1500 },
    { filename: "src/B.java", patch: `@@ -0,0 +1,501 @@\n${Array.from({ length: 501 }, (_, index) => `+line ${index}`).join("\n")}` }
  ],
  {}
);
assert.equal(filesBlocked.addedLines, 2001, "files should provide exact additions when MR metadata is incomplete");
assert.equal(filesBlocked.allowed, false, "files-derived additions over threshold should block review");

const db = new DatabaseSync(":memory:");
migrate(db);
db.prepare("INSERT INTO projects (id, name) VALUES ('project_size', 'Size Guard Project')").run();
db.prepare(`
  INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
  VALUES ('repo_size', 'project_size', 'github', 'neochen1991/size-guard', 'size-guard', 'main', 'active', '{}')
`).run();

const mergeRequestRepository = new MergeRequestRepository(db);
const repositoryRepository = new RepositoryRepository(db);
const reviewJobRepository = new ReviewJobRepository(db);
const reviewQueueService = new ReviewQueueService(reviewJobRepository);
const projectConfigService = new ProjectConfigService(db);
const syncService = new MrSyncService({}, repositoryRepository, mergeRequestRepository, reviewQueueService, () => undefined, projectConfigService);
const repo = repositoryRepository.findById("repo_size");
const largeMr = {
  externalId: "101",
  number: 101,
  title: "Add too many generated files",
  author: "tester",
  sourceBranch: "feature/large",
  targetBranch: "main",
  headSha: "sha-large-1",
  htmlUrl: "https://github.example/pull/101",
  additions: 2001,
  deletions: 0,
  changedFiles: 4,
  metadata: { additions: 2001, deletions: 0, changed_files: 4 }
};
const syncedLargeMr = syncService.upsertAndEnqueue(repo, largeMr);
assert.equal(syncedLargeMr.jobCreated, true, "sync should still enqueue oversized MR for the pending list");
assert.equal(syncedLargeMr.skippedTooLarge, false, "sync should not apply the oversized MR guard");
const blockedMr = mergeRequestRepository.findByRepositoryAndExternalId("repo_size", "101");
assert.equal(blockedMr.review_status, "queued", "sync should keep oversized MR in the pending review list");
assert.equal(
  db.prepare("SELECT COUNT(*) AS count FROM review_jobs WHERE merge_request_id = ?").get(blockedMr.id).count,
  1,
  "sync should create a queued job without applying the size guard"
);

projectConfigService.upsertSetting("project_size", "review_policy", { max_added_lines_per_mr: 3000 });
const allowedSync = syncService.upsertAndEnqueue(repo, largeMr);
assert.equal(allowedSync.jobCreated, false, "re-syncing the same head should remain idempotent");
const allowedMr = mergeRequestRepository.findByRepositoryAndExternalId("repo_size", "101");
assert.equal(allowedMr.review_status, "queued", "MR should remain queued after threshold changes because sync does not block");
db.close();

console.log("MR size policy checks passed.");
