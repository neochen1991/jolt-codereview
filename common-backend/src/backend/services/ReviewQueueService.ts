import { id } from "../http.js";
import type { ReviewJobRepository } from "../repositories/ReviewJobRepository.js";

export interface EnqueueReviewJobInput {
  mergeRequestId: string;
  headSha: string;
  priority: number;
  effortLevel?: string;
  requestedBy?: string | null;
}

export class ReviewQueueService {
  constructor(private readonly reviewJobRepository: ReviewJobRepository) {}

  enqueueIdempotent(input: EnqueueReviewJobInput) {
    const result = this.reviewJobRepository.enqueueIgnore({
      id: id("job"),
      mergeRequestId: input.mergeRequestId,
      headSha: input.headSha,
      priority: input.priority,
      effortLevel: input.effortLevel ?? "standard",
      requestedBy: input.requestedBy ?? null
    });
    return {
      job: this.reviewJobRepository.findByMergeRequestAndHead(input.mergeRequestId, input.headSha),
      created: result.changes > 0
    };
  }

  enqueueOrReset(input: EnqueueReviewJobInput) {
    this.reviewJobRepository.enqueueOrReset({
      id: id("job"),
      mergeRequestId: input.mergeRequestId,
      headSha: input.headSha,
      priority: input.priority,
      effortLevel: input.effortLevel ?? "standard",
      requestedBy: input.requestedBy ?? null
    });
    return this.reviewJobRepository.findByMergeRequestAndHead(input.mergeRequestId, input.headSha);
  }

  supersedeQueued(mergeRequestId: string) {
    return this.reviewJobRepository.supersedeQueued(mergeRequestId);
  }

  cancelQueued(mergeRequestId: string) {
    return this.reviewJobRepository.cancelQueued(mergeRequestId);
  }

  pauseByMergeRequest(mergeRequestId: string) {
    return this.reviewJobRepository.pauseByMergeRequest(mergeRequestId);
  }

  stopByMergeRequest(mergeRequestId: string) {
    return this.reviewJobRepository.stopByMergeRequest(mergeRequestId);
  }

  retry(jobId: string, effortLevel: string, requestedBy?: string | null) {
    this.reviewJobRepository.retry(jobId, effortLevel, requestedBy ?? null);
    return this.reviewJobRepository.findById(jobId);
  }

  deadLetter(jobId: string, reason: string, finalAttempt: number) {
    this.reviewJobRepository.deadLetter(jobId, reason, finalAttempt, id("dead"));
    return this.reviewJobRepository.findById(jobId);
  }

  reclaimStale(seconds = 60) {
    return this.reviewJobRepository.reclaimStale(seconds);
  }
}
