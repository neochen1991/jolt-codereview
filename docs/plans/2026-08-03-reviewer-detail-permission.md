# Reviewer Detail Permission Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow self-registration as a global `project_admin` that can create new projects, and ensure reviewer users see only MR findings and normal review actions while diagnostic data remains administrator-only.

**Architecture:** Centralize account-role policy in the Common Backend and keep project membership as the only non-root authorization source for existing projects. Compute review diagnostic visibility in the MR Backend, avoid querying or returning diagnostic payloads for non-admin users, protect direct diagnostic endpoints, and mirror the same decision in the frontend presentation.

**Tech Stack:** TypeScript, Node.js route services, PostgreSQL repositories, React, Vite, repository verification scripts, Playwright browser verification.

---

### Task 1: Define registration and project-creation role policy

**Files:**
- Create: `common-backend/src/backend/services/AccountRolePolicy.ts`
- Create: `scripts/test-account-role-policy.mjs`
- Modify: `package.json`

**Step 1: Write the failing policy test**

Create `scripts/test-account-role-policy.mjs` that imports the compiled policy and asserts:

```js
assert.equal(registrationGlobalRole("user", 1), "user");
assert.equal(registrationGlobalRole("project_admin", 1), "project_admin");
assert.equal(registrationGlobalRole("user", 0), "root");
assert.equal(canCreateProjectForGlobalRole("root"), true);
assert.equal(canCreateProjectForGlobalRole("project_admin"), true);
assert.equal(canCreateProjectForGlobalRole("user"), false);
assert.throws(() => registrationGlobalRole("system_admin", 1), /account_type/);
```

Add a temporary npm script command only after the test file exists:

```json
"verify:account-role-policy": "npm --prefix common-backend run build && node scripts/test-account-role-policy.mjs"
```

**Step 2: Run the test and verify RED**

Run:

```bash
npm run verify:account-role-policy
```

Expected: FAIL because `AccountRolePolicy` does not exist.

**Step 3: Implement the minimal policy**

Implement:

```ts
export type RegistrationAccountType = "user" | "project_admin";

export function registrationGlobalRole(value: unknown, userCount: number) {
  if (userCount === 0) return "root";
  const accountType = String(value || "user");
  if (accountType !== "user" && accountType !== "project_admin") {
    throw new Error("account_type must be user or project_admin");
  }
  return accountType;
}

export function canCreateProjectForGlobalRole(value: unknown) {
  return value === "root" || value === "project_admin";
}
```

**Step 4: Run the test and verify GREEN**

Run `npm run verify:account-role-policy` and expect all assertions to pass.

**Step 5: Commit**

```bash
git add common-backend/src/backend/services/AccountRolePolicy.ts scripts/test-account-role-policy.mjs package.json
git commit -m "feat: define project admin registration policy"
```

### Task 2: Apply registration and project creation authorization

**Files:**
- Modify: `common-backend/src/backend/routes/auth.routes.ts`
- Modify: `common-backend/src/backend/routes/projects.routes.ts`
- Create: `scripts/verify-project-admin-registration.mjs`
- Modify: `package.json`

**Step 1: Write the failing route contract test**

Create a source contract verification that requires:

- `/api/auth/register` reads `account_type` and calls `registrationGlobalRole`;
- invalid account types produce a `400 bad_request`, not a server error;
- `/api/projects` uses `canCreateProjectForGlobalRole` instead of `ensureRoot`;
- existing project routes continue to use `ensureProjectRole` and never use global `project_admin` as membership;
- `ProjectRepository.createProject` remains responsible for inserting the creator as member-level `project_admin`.

Add `verify:project-admin-registration` to `package.json`.

**Step 2: Run the test and verify RED**

Run:

```bash
npm run verify:project-admin-registration
```

Expected: FAIL because register ignores `account_type` and project creation is root-only.

**Step 3: Implement registration and project creation**

In `auth.routes.ts`, translate the requested account type with the policy and catch policy validation errors as `badRequest`.

In `projects.routes.ts`, load the actor and allow project creation only when `canCreateProjectForGlobalRole(actor.global_role)` is true. Return `403 forbidden` for regular users. Do not change `ensureProjectRole` for existing-project routes.

**Step 4: Run tests and build**

Run:

```bash
npm run verify:account-role-policy
npm run verify:project-admin-registration
npm --prefix common-backend run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add common-backend/src/backend/routes/auth.routes.ts common-backend/src/backend/routes/projects.routes.ts scripts/verify-project-admin-registration.mjs package.json
git commit -m "feat: allow project admins to create projects"
```

### Task 3: Add registration account type to the frontend

**Files:**
- Modify: `frontend/src/frontend/components/AuthViews.tsx`
- Modify: `frontend/src/frontend/App.tsx`
- Modify: `frontend/src/frontend/components/ProjectViews.tsx`
- Modify: `frontend/src/frontend/shared.ts`
- Create: `scripts/verify-registration-account-type-ui.mjs`
- Modify: `package.json`

**Step 1: Write the failing UI contract test**

Require the frontend to:

- render account-type options `user` and `project_admin` only in registration mode;
- send `account_type` in `onRegister` and `/api/auth/register`;
- expose `canCreateProject(user)` returning true only for root or global `project_admin`;
- use that helper in `ProjectSelectionPage` rather than `isRootUser`.

**Step 2: Verify RED**

Run `npm run verify:registration-account-type-ui` and expect failure because the UI has no account type.

**Step 3: Implement the UI**

Add an account-type selection with a plain-language explanation:

- `普通用户`: cannot create projects;
- `项目管理员`: can create a new project and becomes its administrator, but does not join existing projects.

Default to `user`. Update TypeScript callback types and the registration request payload. Add `canCreateProject` to `shared.ts` and use it in `ProjectViews.tsx`.

**Step 4: Verify GREEN**

Run:

```bash
npm run verify:registration-account-type-ui
npm --prefix frontend run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/frontend/components/AuthViews.tsx frontend/src/frontend/App.tsx frontend/src/frontend/components/ProjectViews.tsx frontend/src/frontend/shared.ts scripts/verify-registration-account-type-ui.mjs package.json
git commit -m "feat: register project administrator accounts"
```

### Task 4: Enforce administrator-only review diagnostics in the backend

**Files:**
- Create: `mr-backend/src/backend/services/ReviewVisibilityPolicy.ts`
- Modify: `mr-backend/src/backend/routes/review.routes.ts`
- Create: `scripts/test-review-visibility-policy.mjs`
- Create: `scripts/verify-review-diagnostic-authorization.mjs`
- Modify: `package.json`

**Step 1: Write failing policy and route tests**

The pure policy test must assert:

```js
assert.equal(reviewDetailVisibility("project_admin", false), "full");
assert.equal(reviewDetailVisibility("reviewer", false), "findings_only");
assert.equal(reviewDetailVisibility("observer", false), "findings_only");
assert.equal(reviewDetailVisibility("", true), "full");
```

The route contract test must require:

- MR detail computes project membership and `diagnostics_visible` server-side;
- non-admin response has `jobs: []`, `runs: []`, `tool_observations: []`, `trace: []`, empty session logs, empty quality/compare, and `has_review_run` without exposing IDs;
- diagnostic database queries only execute for full visibility;
- review-run detail, trace, session logs, Skill trace, artifacts, MR logs, and run comparison require `project_admin`;
- reviewer mutation routes remain authorized at `reviewer`.

**Step 2: Verify RED**

Run:

```bash
npm run verify:review-diagnostic-authorization
```

Expected: FAIL because reviewer detail currently returns all diagnostics and diagnostic endpoints use read-level authorization.

**Step 3: Implement the visibility policy and route shaping**

Resolve project ID and member role for the current user. Root maps to full visibility. Existing project membership remains mandatory.

The detail route may query the latest run ID internally to fetch findings, but must not serialize that ID for findings-only users. Only full visibility executes trace, tool observation, session log, artifact, compare, coverage, and quality queries.

Add response fields:

```ts
diagnostics_visible: boolean;
has_review_run: boolean;
```

Use an administrator authorization helper for all dedicated diagnostic endpoints. Leave rerun, feedback, export, and publish permissions unchanged.

**Step 4: Verify GREEN and build**

Run:

```bash
npm run verify:review-diagnostic-authorization
npm --prefix mr-backend run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add mr-backend/src/backend/services/ReviewVisibilityPolicy.ts mr-backend/src/backend/routes/review.routes.ts scripts/test-review-visibility-policy.mjs scripts/verify-review-diagnostic-authorization.mjs package.json
git commit -m "feat: protect review diagnostics from reviewers"
```

### Task 5: Render findings-only MR detail for reviewers

**Files:**
- Modify: `frontend/src/frontend/shared.ts`
- Modify: `frontend/src/frontend/App.tsx`
- Modify: `frontend/src/frontend/components/ReviewViews.tsx`
- Create: `scripts/verify-reviewer-detail-ui.mjs`
- Modify: `package.json`

**Step 1: Write the failing UI test**

Require:

- `Detail` supports `diagnostics_visible` and `has_review_run`;
- `DetailPanel` receives `canViewDiagnostics` from the active project role/root decision and also respects the backend flag;
- findings-only mode renders no process/tools tab, CoverageCard, ReviewQualityCard, Job, Run, tool/LLM/Skill/Agent counters;
- findings list and reviewer action handlers remain present;
- full mode retains all existing diagnostic components;
- changing to findings-only mode resets an active hidden tab to `findings`.

**Step 2: Verify RED**

Run `npm run verify:reviewer-detail-ui`; expect failure because `DetailPanel` always renders diagnostics.

**Step 3: Implement minimal conditional rendering**

In `App.tsx`, compute administrator visibility from `activeProjectRole` and root status, and pass it to `DetailPanel`.

In `ReviewViews.tsx`:

- derive `showDiagnostics = canViewDiagnostics && detail.diagnostics_visible !== false`;
- show only the findings tab when false;
- render coverage and quality cards only when true;
- update `ReviewProgressPanel` with `showDiagnostics` and omit the entire internal metadata block when false, including Job and Run;
- retain findings, finding modal, selection, false-positive, export, rerun, and publish controls;
- use `has_review_run` for business empty/pending state without requiring serialized run records.

**Step 4: Verify GREEN and build**

Run:

```bash
npm run verify:reviewer-detail-ui
npm --prefix frontend run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/frontend/shared.ts frontend/src/frontend/App.tsx frontend/src/frontend/components/ReviewViews.tsx scripts/verify-reviewer-detail-ui.mjs package.json
git commit -m "feat: show reviewers findings only"
```

### Task 6: Full regression and browser verification

**Files:**
- Modify only if a verified regression requires a focused correction.

**Step 1: Run automated verification**

Run:

```bash
npm run verify:account-role-policy
npm run verify:project-admin-registration
npm run verify:registration-account-type-ui
npm run verify:review-diagnostic-authorization
npm run verify:reviewer-detail-ui
npm run verify:frontend-api-routing
npm run build
git diff --check
```

Expected: all commands exit 0.

**Step 2: Run real authorization checks**

Against disposable test accounts and a test project:

- register a regular user and verify project creation returns 403;
- register a project administrator and verify project creation succeeds;
- verify the creator's new-project membership is `project_admin`;
- verify that account receives 403 for an existing project without membership;
- add a reviewer membership and verify MR detail contains findings but no diagnostic payload;
- verify direct diagnostic endpoints return 403 for the reviewer and succeed for the project administrator.

Do not alter production user roles or existing project membership for this check.

**Step 3: Verify in a real browser**

Use the reviewer account to confirm the MR detail contains only business progress, findings, finding detail, and normal reviewer actions. Confirm absence of Job, Run, internal call counters, process/tools tabs, coverage, and quality cards.

Use the project administrator account to confirm all existing diagnostics remain visible.

**Step 4: Inspect repository state**

Run:

```bash
git status --short
git log --oneline --decorate -8
```

Do not commit runtime databases, logs, screenshots, generated build output, or `evaluation/real_prs/cache/`.
