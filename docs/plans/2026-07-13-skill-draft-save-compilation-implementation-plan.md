# Skill Draft Save Compilation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Recompile and persist the complete checkpoint manifest whenever a versioned Skill draft resource is saved.

**Architecture:** Keep `validateSkillBundlePayload` and `SkillCheckpointCompiler` as the only compilation path. After a draft asset mutation, compile the returned full version bundle and atomically persist validation, manifest, compiler version, and canonical bundle hash; expose the refreshed result to the UI while retaining activation-time recompilation.

**Tech Stack:** TypeScript, PostgreSQL-compatible repository wrapper, React, Node verification scripts.

---

### Task 1: Add the save-time compilation contract

**Files:**
- Create: `scripts/verify-skill-draft-save-compilation.mjs`
- Modify: `package.json`

**Step 1:** Write a source and behavior contract that requires versioned asset saves to compile the complete updated Bundle and persist validation plus Manifest.

**Step 2:** Run `node scripts/verify-skill-draft-save-compilation.mjs` and confirm it fails because save-time recompilation is absent.

### Task 2: Persist the refreshed draft compilation

**Files:**
- Modify: `mr-backend/src/backend/routes/rules.routes.ts`
- Modify: `mr-backend/src/backend/repositories/RuleDocumentRepository.ts`

**Step 1:** Add a helper that reconstructs the complete selected version Bundle.

**Step 2:** Save the resource, compile that complete Bundle with `validateSkillBundlePayload`, and persist compilation fields before returning the refreshed row.

**Step 3:** Ensure the repository update refreshes the canonical hash in the same transaction and never mutates an active version.

**Step 4:** Run the new verifier and backend build; expect both to pass.

### Task 3: Surface the result and document behavior

**Files:**
- Modify: `frontend/src/frontend/components/ConfigViews.tsx`
- Modify: `README.md`

**Step 1:** Consume the refreshed version response and show whether save-time compilation succeeded or has concrete validation failures.

**Step 2:** Document create/upload, individual draft save, debug, and activation compilation timing.

**Step 3:** Run the frontend build and Skill-specific verification.

### Task 4: Verify the complete change

**Files:**
- Modify: `package.json`

**Step 1:** Add the new verifier to `npm run verify`.

**Step 2:** Run `npm run verify` and require exit code 0.

**Step 3:** Review `git diff --check`, `git diff`, and `git status --short` before committing.
