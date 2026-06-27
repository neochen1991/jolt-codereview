# Three Repository Split Design

## Goal

Split the current single Jolt CodeReview project into two independently started backends and one independently started frontend, while keeping the first migration stage safe inside the current repository before moving the directories into separate Git repositories.

## Target Projects

- `common-backend`: public platform backend for users, authentication, authorization, system settings, and model management.
- `mr-backend`: MR review backend for repositories, MR sync, review jobs, rules, agents, quality, observability, webhooks, VCS proxy, and the Python worker.
- `frontend`: React/Vite frontend configured to call both backend APIs.

## Migration Approach

Use a two-stage migration.

Stage 1 keeps one Git repository but creates separate runtime entrypoints, route groups, configuration, and verification scripts. This lets us verify the three-process shape without losing existing tests, scripts, and historical fixtures.

Stage 2 keeps the current repository root shaped like the future split: `common-backend`, `mr-backend`, and `frontend` are the three module roots. If a one-time export is needed for repository creation, run `npm run export:repos`; the export output is a temporary artifact and must not be treated as the source layout.

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

Model configuration is managed by common backend. The settings page can submit a project API key to common backend, and public APIs only return masked key metadata. Internal model-config calls are service-to-service calls protected by `JOLT_INTERNAL_SERVICE_TOKEN`.

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

- Common backend: `127.0.0.1:9022`
- MR backend: `127.0.0.1:9021`
- Frontend: `127.0.0.1:9020`

## Verification Gates

- `npm run verify`
- `npm run verify:frontend-api-routing`
- `npm run verify:postgres-only-runtime`
- `node scripts/verify-real-tooling.mjs`
- `python3 -m compileall mr-backend/worker scripts`
- `env PYTHONPATH=mr-backend/worker mr-backend/.venv/bin/python scripts/verify_skill_layers.py`
- `npm run export:repos`
- `npm --prefix common-backend run build`
- `npm --prefix mr-backend run build`
- `npm --prefix frontend run build`

Full LLM e2e remains conditional on a valid model key being available through an environment variable referenced by model configuration.

## Complex MR Verification

After exporting the three repositories, run the current split-service regression from the repository root:

- `npm run verify:split-full-regression`

The verification covers repository/MR/job seeding, worker orchestration, static tool observations, findings persistence, and quality reporting in the split MR backend.
