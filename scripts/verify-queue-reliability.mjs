import { DatabaseSync } from "node:sqlite";
import { ReviewJobRepository } from "../build/backend/repositories/ReviewJobRepository.js";
import { ReviewQueueService } from "../build/backend/services/ReviewQueueService.js";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const db = new DatabaseSync(":memory:");
db.exec(`
  CREATE TABLE review_jobs (
    id TEXT PRIMARY KEY,
    merge_request_id TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    requested_effort_level TEXT NOT NULL DEFAULT 'standard',
    attempt INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT,
    locked_by TEXT,
    heartbeat_at TEXT,
    requested_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(merge_request_id, head_sha)
  );

  CREATE TABLE review_jobs_dead_letter (
    id TEXT PRIMARY KEY,
    review_job_id TEXT NOT NULL,
    failure_reason TEXT NOT NULL,
    final_attempt INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );
`);

const repository = new ReviewJobRepository(db);
const queue = new ReviewQueueService(repository);

const first = queue.enqueueIdempotent({ mergeRequestId: "mr_1", headSha: "sha_1", priority: 80 });
const duplicate = queue.enqueueIdempotent({ mergeRequestId: "mr_1", headSha: "sha_1", priority: 80 });
const duplicateCount = db.prepare("SELECT COUNT(*) AS count FROM review_jobs WHERE merge_request_id = ? AND head_sha = ?").get("mr_1", "sha_1").count;
assert(first.created === true, "first enqueue should create a job");
assert(duplicate.created === false, "duplicate enqueue should be idempotent");
assert(duplicateCount === 1, "duplicate enqueue should leave one job");

queue.supersedeQueued("mr_1");
queue.enqueueIdempotent({ mergeRequestId: "mr_1", headSha: "sha_2", priority: 90 });
const oldHead = repository.findByMergeRequestAndHead("mr_1", "sha_1");
const newHead = repository.findByMergeRequestAndHead("mr_1", "sha_2");
assert(oldHead.status === "superseded", "old queued head should be superseded");
assert(newHead.status === "queued", "new head should be queued");

queue.enqueueIdempotent({ mergeRequestId: "mr_cancel", headSha: "sha_cancel", priority: 10 });
queue.cancelQueued("mr_cancel");
const cancelled = repository.findByMergeRequestAndHead("mr_cancel", "sha_cancel");
assert(cancelled.status === "cancelled", "closed MR should cancel queued job");

queue.enqueueIdempotent({ mergeRequestId: "mr_retry", headSha: "sha_retry", priority: 30 });
const retryJob = repository.findByMergeRequestAndHead("mr_retry", "sha_retry");
db.prepare("UPDATE review_jobs SET status = 'failed', attempt = 2, locked_at = CURRENT_TIMESTAMP, heartbeat_at = CURRENT_TIMESTAMP WHERE id = ?").run(retryJob.id);
const retried = queue.retry(retryJob.id, "deep");
assert(retried.status === "queued", "retry should return job to queued");
assert(retried.attempt === 0, "manual retry should reset attempt");
assert(retried.requested_effort_level === "deep", "retry should update effort level");

queue.enqueueIdempotent({ mergeRequestId: "mr_dead", headSha: "sha_dead", priority: 5 });
const deadJob = repository.findByMergeRequestAndHead("mr_dead", "sha_dead");
const dead = queue.deadLetter(deadJob.id, "verification failure", 3);
const deadLetter = db.prepare("SELECT * FROM review_jobs_dead_letter WHERE review_job_id = ?").get(deadJob.id);
assert(dead.status === "dead_letter", "dead-lettered job should have dead_letter status");
assert(dead.attempt === 3, "dead-lettered job should record final attempt");
assert(deadLetter.failure_reason === "verification failure", "dead-letter should preserve reason");

queue.enqueueIdempotent({ mergeRequestId: "mr_stale", headSha: "sha_stale", priority: 20 });
const staleJob = repository.findByMergeRequestAndHead("mr_stale", "sha_stale");
db.prepare(`
  UPDATE review_jobs
  SET status = 'reviewing', locked_at = datetime('now', '-120 seconds'), heartbeat_at = datetime('now', '-120 seconds')
  WHERE id = ?
`).run(staleJob.id);
const reclaimed = queue.reclaimStale(60);
const staleAfter = repository.findById(staleJob.id);
assert(reclaimed.changes === 1, "stale running job should be reclaimed");
assert(staleAfter.status === "queued", "reclaimed job should return to queued");
assert(staleAfter.locked_at === null && staleAfter.locked_by === null, "reclaimed job should clear lock");

const summary = db.prepare(`
  SELECT status, COUNT(*) AS count
  FROM review_jobs
  GROUP BY status
  ORDER BY status
`).all();
db.close();

console.log(JSON.stringify({
  idempotent: { first_created: first.created, duplicate_created: duplicate.created, count: duplicateCount },
  supersede: { old_head_status: oldHead.status, new_head_status: newHead.status },
  cancel: { status: cancelled.status },
  retry: { status: retried.status, attempt: retried.attempt, effort: retried.requested_effort_level },
  dead_letter: { status: dead.status, final_attempt: dead.attempt },
  reclaim: { changes: reclaimed.changes, status: staleAfter.status },
  queue_summary: summary
}, null, 2));
