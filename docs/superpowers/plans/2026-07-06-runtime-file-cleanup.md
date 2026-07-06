# Runtime File Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable runtime-file cleanup mechanism that removes MR/common service files older than one day without touching source, config, database, rule, or skill data.

**Architecture:** MR Backend owns cleanup for its API log, worker log, review-run file logs, and worker sandbox directories. Common Backend owns cleanup for its API logs. A root dry-run script exercises both service cleanup implementations with temporary fixtures.

**Tech Stack:** Node.js, TypeScript backend services, existing service `config.json` files, `npm run verify`.

---

### Task 1: Runtime Cleanup Verification

**Files:**
- Create: `scripts/verify-runtime-cleanup.mjs`
- Modify: `package.json`

- [x] Add a verification script that creates temporary service directories with old and fresh runtime files.
- [x] Assert that dry-run reports old files and directories without deleting them.
- [x] Assert that execution deletes only old allowlisted runtime files.
- [x] Add the script to `npm run verify`.

### Task 2: MR Backend Cleanup Service

**Files:**
- Create: `mr-backend/src/backend/services/RuntimeFileCleanupService.ts`
- Modify: `mr-backend/src/backend/config.ts`
- Modify: `mr-backend/src/backend/types.ts`
- Modify: `mr-backend/src/backend/mr-server.ts`
- Modify: `mr-backend/config.example.json`

- [x] Add a `cleanup_policy` default with one-day retention.
- [x] Clean `logs/review-runs`, `logs/*.log`, and `worker/data/sandboxes`.
- [x] Schedule periodic cleanup on service startup.
- [x] Keep deletion restricted to normalized allowlisted paths under the service root.

### Task 3: Common Backend Cleanup Service

**Files:**
- Create: `common-backend/src/backend/services/RuntimeFileCleanupService.ts`
- Modify: `common-backend/src/backend/config.ts`
- Modify: `common-backend/src/backend/types.ts`
- Modify: `common-backend/src/backend/common-server.ts`
- Modify: `common-backend/config.example.json`

- [x] Add a `cleanup_policy` default with one-day retention.
- [x] Clean only Common runtime logs.
- [x] Schedule periodic cleanup on service startup.

### Task 4: Verification

- [x] Run `node scripts/verify-runtime-cleanup.mjs` and confirm it passes.
- [x] Run `npm run verify` and confirm existing regression checks pass.
