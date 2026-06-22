# Three Repository Split Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a verified first-stage split where the current repository can run a common backend, an MR backend, and a frontend as separate projects before moving them into three Git repositories.

**Architecture:** Reuse existing route modules and database adapters, but introduce explicit route groups and independent server entrypoints. The frontend keeps one API helper with path-based backend routing. The MR worker remains attached to the MR backend and model configuration is treated as a common-backend-owned contract.

**Tech Stack:** TypeScript Node HTTP server, React/Vite, Python worker, SQLite/PostgreSQL adapter, existing npm verification scripts.

---

## Task 1: Add Boundary Verification Scripts

**Files:**
- Create: `scripts/verify-three-project-boundary.mjs`
- Create: `scripts/verify-frontend-api-routing.mjs`
- Modify: `package.json`

**Steps:**

1. Add a script that builds the backend, starts common and MR backend entrypoints on temporary ports, calls `/api/health`, and verifies route ownership.
2. Add a script that imports the frontend route resolver and verifies common paths route to the common API base while MR paths route to the MR API base.
3. Add npm script aliases.
4. Run both scripts and verify they fail before implementation because the new entrypoints and route resolver do not exist.

## Task 2: Split Backend Route Groups

**Files:**
- Modify: `src/backend/routes/mr-review.routes.ts`
- Create: `src/backend/routes/common.routes.ts`
- Create: `src/backend/routes/mr.routes.ts`

**Steps:**

1. Extract common route creation to include health, auth, system, and model-management routes.
2. Extract MR route creation to include health and MR-business route groups.
3. Keep the legacy `createRoutes()` export as a compatibility wrapper while the split is introduced.
4. Run backend build and boundary verification.

## Task 3: Add Independent Backend Entrypoints

**Files:**
- Create: `src/backend/common-server.ts`
- Create: `src/backend/mr-server.ts`
- Modify: `src/backend/server.ts`
- Modify: `src/backend/config.ts`

**Steps:**

1. Add config support for common and MR ports while preserving `server.port`.
2. Add common server startup on `server.common_port || 8010`.
3. Add MR server startup on `server.mr_port || server.port || 8011`.
4. Keep legacy `server.ts` pointing to MR server behavior for existing scripts.
5. Run `npm run build` and `npm run verify:three-project-boundary`.

## Task 4: Add Model Management Contract

**Files:**
- Create: `src/backend/routes/models.routes.ts`
- Modify: `src/backend/services/ProjectConfigService.ts`
- Modify: `src/backend/routes/common.routes.ts`

**Steps:**

1. Expose common model settings endpoints that store `default_api_key_env`, provider, base URL, and model.
2. Add internal effective model config route protected by `JOLT_INTERNAL_SERVICE_TOKEN`.
3. Explicitly omit plaintext `default_api_key` from runtime responses.
4. Add focused verification to the boundary script.

## Task 5: Split Frontend API Routing

**Files:**
- Create: `src/frontend/apiRouting.ts`
- Modify: `src/frontend/main.tsx`
- Modify: `package.json`

**Steps:**

1. Move API base resolution into `apiRouting.ts`.
2. Route common paths to `VITE_COMMON_API_BASE`.
3. Route MR paths to `VITE_MR_API_BASE`.
4. Preserve fallback to `VITE_API_BASE`.
5. Run `npm run verify:frontend-api-routing` and `npm run build`.

## Task 6: Add First-Stage App Project Layout

**Files:**
- Create: `apps/common-backend/package.json`
- Create: `apps/mr-backend/package.json`
- Create: `apps/frontend/package.json`
- Modify: `README.md`

**Steps:**

1. Add lightweight package files with scripts that delegate to the root build output during stage 1.
2. Document the local three-process startup commands.
3. Keep root `npm run dev` as a compatibility orchestrator.

## Task 7: Update Local Orchestration

**Files:**
- Modify: `scripts/start-all.mjs`
- Modify: `package.json`

**Steps:**

1. Start common backend, MR backend, worker, and frontend.
2. Release ports `8010`, `8011`, and `5173`.
3. Pass `COMMON_API_BASE`, `MR_API_BASE`, `VITE_COMMON_API_BASE`, and `VITE_MR_API_BASE` to child processes.
4. Run smoke and boundary verification.

## Task 8: Final Verification

**Files:**
- No new files.

**Steps:**

1. Run `npm run build`.
2. Run `npm run verify:three-project-boundary`.
3. Run `npm run verify:frontend-api-routing`.
4. Run `npm run smoke` against the running stack if an API is active.
5. Run `npm run verify:no-db-foreign-keys`.
6. Run `npm run verify:pg-sql-compat`.
7. Run `npm run verify:worker-orchestration`.
8. Report LLM e2e status separately because it requires an env-backed model key.
