# Three Repository Split Design

## Goal

Split the current single Jolt CodeReview project into two independently started backends and one independently started frontend, while keeping the first migration stage safe inside the current repository before moving the directories into separate Git repositories.

## Target Projects

- `apps/common-backend`: public platform backend for users, authentication, authorization, system settings, and model management.
- `apps/mr-backend`: MR review backend for repositories, MR sync, review jobs, rules, agents, quality, observability, webhooks, VCS proxy, and the Python worker.
- `apps/frontend`: React/Vite frontend configured to call both backend APIs.

## Migration Approach

Use a two-stage migration.

Stage 1 keeps one Git repository but creates separate runtime entrypoints, route groups, configuration, and verification scripts. This lets us verify the three-process shape without losing existing tests, scripts, and historical fixtures.

Stage 2 exports `common-backend`, `mr-backend`, and `frontend` into three Git repositories under `split-repos/` with `npm run export:repos`. These exported repositories are local migration artifacts and can be pushed to separate remotes when repository names and access control are ready.

## API Boundary

Common backend owns:

- `/api/auth/*`
- `/api/me/*`
- `/api/users/*`
- `/api/permissions/*`
- `/api/models/*`
- `/api/system/*`
- `/internal/auth/introspect`
- `/internal/models/effective-config`

MR backend owns:

- `/api/projects/*` for MR business configuration in stage 1, with permission checks moving to common introspection over time.
- `/api/mr-review/*`
- `/api/full-review/*`
- `/api/vcs/*`
- `/api/webhooks/*`
- `/api/observability/*`
- `/api/projects/:projectId/repositories`
- `/api/projects/:projectId/rule-*`
- `/api/projects/:projectId/agents`
- `/api/projects/:projectId/review-*`

Both backends expose `/api/health` with different service names.

## Backend-To-Backend Protocol

MR backend calls common backend for identity and model configuration:

- `POST /internal/auth/introspect`: validates a user bearer token and returns user identity plus global and project roles.
- `GET /internal/models/effective-config?project_id=...`: returns the model runtime config for a project.

Internal routes require `JOLT_INTERNAL_SERVICE_TOKEN`. Frontend user requests continue to use session bearer tokens.

Model configuration must return environment variable names or secret references, not plaintext keys. Worker runtime continues to read real keys from environment variables.

## Data Ownership

Common backend owns:

- `users`
- `auth_sessions`
- `user_settings`
- public portions of `system_settings`
- `project_members`
- `project_invitations`
- `project_join_requests`
- future `model_providers`
- future `model_profiles`
- future `model_project_bindings`

MR backend owns:

- `projects`
- MR-business portions of `project_settings`
- `repositories`
- `merge_requests`
- `review_jobs`
- `review_runs`
- `review_findings`
- `candidate_findings`
- `mr_finding_history`
- `rule_sets`
- `rule_documents`
- `custom_skills`
- `agent_configs`
- `expert_profiles`
- `expert_*_bindings`
- `tool_*`
- `llm_call_records`
- `review_artifacts`
- `full_review_*`
- `evaluation_*`
- `vcs_publish_records`
- `webhook_dead_letter`

Stage 1 uses PostgreSQL as the only service database. Code treats the table groups below as owned by separate services even when both backends point at the same PG database during local development.

## Frontend Routing

Frontend keeps a single API helper but resolves the base URL by path:

- auth, profile, users, permissions, models, and system routes use `VITE_COMMON_API_BASE`.
- MR review, repositories, rules, agents, VCS, webhooks, full review, quality, and observability routes use `VITE_MR_API_BASE`.

If the split variables are not set, the frontend falls back to the legacy `VITE_API_BASE` value.

## Local Ports

- Common backend: `127.0.0.1:8010`
- MR backend: `127.0.0.1:8011`
- Frontend: `127.0.0.1:5173`

## Verification Gates

- `npm run build`
- `npm run verify:three-project-boundary`
- `npm run verify:frontend-api-routing`
- `npm run smoke`
- `npm run verify:no-db-foreign-keys`
- `npm run verify:pg-sql-compat`
- `npm run verify:worker-orchestration`
- `npm run export:repos`
- `npm --prefix split-repos/common-backend run build`
- `npm --prefix split-repos/mr-backend run build`
- `npm --prefix split-repos/frontend run build`

Full LLM e2e remains conditional on a valid model key being available through an environment variable referenced by model configuration.

## Complex MR Verification

After exporting the three repositories, run the current split-service regression from the repository root:

- `npm run verify:split-full-regression`

The verification covers repository/MR/job seeding, worker orchestration, static tool observations, findings persistence, and quality reporting in the split MR backend.
