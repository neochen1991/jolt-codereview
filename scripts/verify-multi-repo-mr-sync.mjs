import { DatabaseSync } from "node:sqlite";
import { migrate } from "../build/backend/db/migrations.js";
import { MergeRequestRepository } from "../build/backend/repositories/MergeRequestRepository.js";
import { RepositoryRepository } from "../build/backend/repositories/RepositoryRepository.js";
import { ReviewJobRepository } from "../build/backend/repositories/ReviewJobRepository.js";
import { MrSyncService } from "../build/backend/services/MrSyncService.js";
import { ReviewQueueService } from "../build/backend/services/ReviewQueueService.js";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function openMr(repoName, number, headSha) {
  return {
    externalId: String(number),
    number,
    title: `${repoName} change ${number}`,
    author: "reviewer",
    sourceBranch: `feature/${repoName}-${number}`,
    targetBranch: "main",
    headSha,
    htmlUrl: `https://git.example.com/team/${repoName}/pull/${number}`,
    additions: 120,
    deletions: 30,
    changedFiles: 4,
    metadata: { repoName }
  };
}

const db = new DatabaseSync(":memory:");
migrate(db);

db.prepare("INSERT INTO projects (id, name) VALUES ('project_multi_repo', 'Multi Repo Project')").run();

const repositoryRepository = new RepositoryRepository(db);
const mergeRequestRepository = new MergeRequestRepository(db);
const reviewJobRepository = new ReviewJobRepository(db);
const reviewQueueService = new ReviewQueueService(reviewJobRepository);
let workerWakeups = 0;

repositoryRepository.upsert({
  id: "repo_alpha",
  projectId: "project_multi_repo",
  provider: "github",
  externalRepoId: "https://git.example.com/team/alpha.git",
  name: "alpha",
  defaultBranch: "main",
  providerConfig: { full_name: "team/alpha" }
});
repositoryRepository.upsert({
  id: "repo_beta",
  projectId: "project_multi_repo",
  provider: "github",
  externalRepoId: "https://git.example.com/team/beta.git",
  name: "beta",
  defaultBranch: "main",
  providerConfig: { full_name: "team/beta" }
});

const service = new MrSyncService(
  {},
  repositoryRepository,
  mergeRequestRepository,
  reviewQueueService,
  () => {
    workerWakeups += 1;
  }
);
service.providers.github = {
  async listOpenMergeRequests(repo) {
    if (repo.name === "alpha") return [openMr("alpha", 11, "sha-alpha-1")];
    if (repo.name === "beta") return [openMr("beta", 21, "sha-beta-1"), openMr("beta", 22, "sha-beta-2")];
    return [];
  }
};

const result = await service.syncProject("project_multi_repo");
assert(result.repositories === 2, `expected two configured repositories, got ${JSON.stringify(result)}`);
assert(result.merge_requests === 3, `expected three merge requests, got ${JSON.stringify(result)}`);
assert(result.jobs_created === 3, `expected three review jobs, got ${JSON.stringify(result)}`);
assert(workerWakeups === 1, `worker should be woken once, got ${workerWakeups}`);
assert(Array.isArray(result.repository_results), `sync result must expose per-repository details: ${JSON.stringify(result)}`);
assert(result.repository_results.length === 2, `expected two repository results, got ${JSON.stringify(result.repository_results)}`);

const summaryByName = Object.fromEntries(result.repository_results.map((item) => [item.name, item]));
assert(summaryByName.alpha?.merge_requests === 1, `alpha summary mismatch: ${JSON.stringify(result.repository_results)}`);
assert(summaryByName.beta?.merge_requests === 2, `beta summary mismatch: ${JSON.stringify(result.repository_results)}`);
assert(summaryByName.alpha?.jobs_created === 1, `alpha jobs mismatch: ${JSON.stringify(result.repository_results)}`);
assert(summaryByName.beta?.jobs_created === 2, `beta jobs mismatch: ${JSON.stringify(result.repository_results)}`);

const listed = mergeRequestRepository.listByProject("project_multi_repo", null);
assert(listed.length === 3, `project MR list should include all configured repositories, got ${listed.length}`);
assert(new Set(listed.map((item) => item.repository_name)).size === 2, `MR list should retain repository names: ${JSON.stringify(listed)}`);

const alphaMr = mergeRequestRepository.findByRepositoryAndExternalId("repo_alpha", "11");
assert(alphaMr, "alpha MR should be stored by repository/external id");
const deleted = mergeRequestRepository.deleteById(alphaMr.id);
assert(deleted.ok, `expected delete before repull to succeed: ${JSON.stringify(deleted)}`);

const repull = await service.syncProject("project_multi_repo");
assert(repull.repositories === 2, `repull should still cover both repositories: ${JSON.stringify(repull)}`);
assert(mergeRequestRepository.findByRepositoryAndExternalId("repo_alpha", "11"), "deleted MR should be recreated on multi-repo sync");

db.close();
console.log(JSON.stringify({ ok: true, result, repull }, null, 2));
