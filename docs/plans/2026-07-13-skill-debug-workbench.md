# Skill Debug Workbench Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real-MR Skill debugging workbench that uses the production review execution path and exposes complete Skill execution evidence.

**Architecture:** Add immutable Skill debug context to normal review jobs, consume it through the existing worker graph, and expose an aggregate debug API over existing run, trace, LLM, tool, checkpoint, and finding records. Add the entry and workbench to the existing agent binding UI; do not create a second Skill runner.

**Tech Stack:** TypeScript, React, Node HTTP routes, PostgreSQL repositories, Python review worker, existing verification scripts.

---

### Task 1: Define the debug API contract

**Files:**
- Create: `scripts/verify-skill-debug-workbench.mjs`
- Modify: `package.json`

1. Write a failing verifier requiring the create/history/detail routes, `targeted` and `production_route` modes, immutable debug context, publish protection, and frontend entry/workbench labels.
2. Run `node scripts/verify-skill-debug-workbench.mjs` and confirm it fails because the routes do not exist.
3. Add the verification command to `package.json` only after the feature passes.

### Task 2: Persist Skill debug context on the normal queue

**Files:**
- Modify: `mr-backend/src/backend/db/migrations.ts`
- Modify: `mr-backend/src/backend/repositories/ReviewJobRepository.ts`
- Modify: `mr-backend/src/backend/services/ReviewQueueService.ts`
- Test: `scripts/verify-skill-debug-workbench.mjs`

1. Extend `review_jobs` with a JSON debug-context column using an additive migration.
2. Accept debug context in the existing enqueue/reset contract.
3. Preserve normal jobs with an empty context.
4. Re-run the verifier and TypeScript build.

### Task 3: Add creation, history, and aggregate detail APIs

**Files:**
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Modify: `mr-backend/src/backend/repositories/AgentRepository.ts` if binding lookup cannot reuse current helpers.
- Test: `scripts/verify-skill-debug-workbench.mjs`

1. Add `POST /api/mr-review/merge-requests/:mrId/skill-debug-runs`.
2. Validate project ownership, reviewer permission, enabled binding and allowed mode.
3. Enqueue through `ReviewQueueService`, snapshotting Skill, Agent, mode, MR SHA and project.
4. Add project/Skill debug history and aggregate detail endpoints.
5. Aggregate existing trace, skill trace, LLM, tool and Finding records rather than duplicating storage.

### Task 4: Feed debug context into the production worker graph

**Files:**
- Modify: `mr-backend/worker/db_helpers.py`
- Modify: `mr-backend/worker/review_runtime.py`
- Modify: `mr-backend/worker/orchestration/nodes/route_agents.py`
- Modify: `mr-backend/worker/orchestration/nodes/finalize.py`
- Test: `mr-backend/worker/tests/test_skill_debug_mode.py`

1. Write a failing test showing `production_route` leaves routing unchanged and `targeted` adds only the bound target Agent.
2. Load the immutable debug context with the normal job.
3. Pass it through the existing graph state.
4. Apply the targeted override only after normal routing and emit an explicit trace event.
5. Mark debug runs in coverage metadata and prohibit publish eligibility.

### Task 5: Build the agent-binding entry and workbench

**Files:**
- Modify: `frontend/src/frontend/components/ConfigViews.tsx`
- Modify: `frontend/src/frontend/shared.ts`
- Modify: `frontend/src/frontend/styles.css`
- Test: `scripts/verify-skill-debug-workbench.mjs`

1. Add “调试 Skill” beside each bound Skill.
2. Load real MRs for the current project and present the two modes with unambiguous explanations.
3. Create the debug task and poll its normal review job/run status.
4. Render overview, binding/load, routing, Prompt, LLM, tools, checkpoints, Findings and raw log sections from the aggregate API.
5. Show missing evidence as “待验证”, never as a successful consistency check.

### Task 6: Verify production-path equivalence and regressions

**Files:**
- Modify: `scripts/verify-skill-debug-workbench.mjs`
- Modify: `package.json`

1. Verify no independent Skill runner or duplicate Prompt builder was introduced.
2. Verify `production_route` does not override routing and `targeted` emits its override.
3. Verify debug runs cannot be published.
4. Run the focused verifier, worker tests, all three builds, and the repository verification suite.
5. Audit the implementation against every item in the design document before completion.

