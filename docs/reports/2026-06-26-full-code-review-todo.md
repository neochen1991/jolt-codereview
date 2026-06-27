# 2026-06-26 Full Code Review Todo

Branch: `codex/three-service-split`

Scope reviewed so far:

- `common-backend/src`
- `mr-backend/src`
- `mr-backend/worker`
- `frontend/src`
- `scripts`

Excluded from code review scope: generated `build/` output, logs, image/report artifacts under `outputs/`, static third-party rule assets under `mr-backend/config/static-rules/`, package lockfiles, and historical benchmark data.

## P0

### TODO-001 MR review read APIs lack resource authorization

- Status: fixed
- Owner: MR backend
- Evidence:
  - `mr-backend/src/backend/routes/mr-review.routes.ts:490` wraps all MR handlers with Common introspection only.
  - `mr-backend/src/backend/routes/review.routes.ts:388` lists project MR data without calling `currentUserId` or `ensureProjectRole`.
  - `mr-backend/src/backend/routes/review.routes.ts:455` exposes project dead letters without authorization.
  - `mr-backend/src/backend/routes/review.routes.ts:466` exposes MR detail, jobs, runs, findings, tool observations, trace, and logs without authorization.
  - `mr-backend/src/backend/routes/review.routes.ts:708` exposes review run detail, trace, session logs, artifacts, and compare without authorization.
- Impact: unauthenticated or unauthorized callers can read review results, source-related findings, traces, tool outputs, LLM call metadata, artifacts, and session logs for known or guessable IDs.
- Fix:
  - Add helpers that resolve `project_id` from `projectId`, `mrId`, `runId`, `findingId`, or `jobId`.
  - Enforce at least `observer` for read endpoints and stricter roles for write endpoints.
  - Add negative tests proving anonymous and cross-project users receive 401/403.

### TODO-002 VCS proxy is a public backdoor to repository content and remote mutations

- Status: fixed
- Owner: MR backend / Worker
- Evidence:
  - `mr-backend/src/backend/routes/vcs-proxy.routes.ts:55` exposes capabilities without authorization.
  - `mr-backend/src/backend/routes/vcs-proxy.routes.ts:66` exposes diff/files/file content without authorization.
  - `mr-backend/src/backend/routes/vcs-proxy.routes.ts:88` can post comments without authorization.
  - `mr-backend/src/backend/routes/vcs-proxy.routes.ts:100` can update remote VCS status without authorization.
  - `mr-backend/worker/review_runtime.py:943` and `mr-backend/worker/review_runtime.py:979` call these endpoints without an internal service token.
- Impact: if VCS tokens are configured, unauthenticated callers can read private file contents and potentially comment/update status on remote MRs. Fixing the route alone will break Worker unless Worker sends an internal token.
- Fix:
  - Require user project role for browser-facing VCS routes.
  - Add an internal-only service authentication path/header for Worker.
  - Update Worker calls to include `x-internal-service-token`.
  - Add tests for anonymous denial and Worker internal access.

### TODO-015 Common always seeds a fixed root account with a public default password

- Status: fixed
- Owner: Common backend / deployment security
- Evidence:
  - `common-backend/src/backend/db/connection.ts:15` through `:16` run `migrate(db)` and then `seed(db)` for every Common database open.
  - `common-backend/src/backend/db/seed.ts:5` through `:8` hard-code the `admin123` password hash material.
  - `common-backend/src/backend/db/seed.ts:11` through `:15` creates `local-admin` as `root` with that fixed password.
  - `common-backend/src/backend/db/seed.ts:17` through `:22` keeps the user as `root` and fills the default password when the password fields are empty.
  - `common-backend/src/backend/common-server.ts:10` calls `openDatabase(config)` during normal service startup.
- Impact: any environment that starts Common against an empty or partially migrated database gets a known root credential. This can become a production backdoor if seed execution is not explicitly disabled or if a deployment reuses the documented default account.
- Fix:
  - Gate development seed data behind an explicit flag such as `JOLT_SEED_DEV_DATA=1`.
  - Require first root bootstrap through a one-time setup command or environment-provided initial password.
  - Fail production startup when the default `local-admin/admin123` credential is still active.
  - Update docs to label sample credentials as local-only and never valid for production.

## P1

### TODO-003 Project quality APIs lack authorization

- Status: fixed
- Owner: MR backend
- Evidence:
  - `mr-backend/src/backend/routes/quality.routes.ts:12` only reads `all/get` from context.
  - `mr-backend/src/backend/routes/quality.routes.ts:14` exposes review-quality summary without authorization.
  - `mr-backend/src/backend/routes/quality.routes.ts:65` exposes evaluation reports without authorization.
  - `mr-backend/src/backend/routes/quality.routes.ts:113` exposes rule-health data without authorization.
- Impact: project quality metrics, feedback precision, stored evaluation reports, and rule health data can be read without project membership.
- Fix:
  - Require `observer` or `project_admin` depending on intended visibility.
  - Add auth regression tests for all three endpoints.

### TODO-004 Publish endpoint accepts finding IDs from other MRs or projects

- Status: fixed
- Owner: MR backend
- Evidence:
  - `mr-backend/src/backend/routes/mr-review.routes.ts:345` checks permission only on the target MR project.
  - `mr-backend/src/backend/routes/mr-review.routes.ts:363` accepts caller-supplied `findingIds`.
  - `mr-backend/src/backend/routes/mr-review.routes.ts:366` fetches findings by ID only, without joining back to the target MR.
  - `mr-backend/src/backend/routes/mr-review.routes.ts:393` then writes publish records and mutates finding lifecycle state.
- Impact: a reviewer with access to one MR can publish and mutate findings from another MR/project if they know finding IDs.
- Fix:
  - Select findings by joining `review_findings -> review_runs -> review_jobs -> merge_requests`.
  - Require `merge_requests.id = targetMrId`.
  - Reject any requested finding IDs not returned by the scoped query.
  - Add cross-MR and cross-project tests.

### TODO-005 `@jolt` comment webhook can explain or dismiss findings outside the target MR

- Status: fixed
- Owner: MR backend
- Evidence:
  - `mr-backend/src/backend/routes/webhooks.routes.ts:76` authorizes the actor against the MR project.
  - `mr-backend/src/backend/routes/webhooks.routes.ts:80` fetches the finding by ID only for `explain`.
  - `mr-backend/src/backend/routes/webhooks.routes.ts:84` fetches the finding by ID only for `dismiss`.
  - `mr-backend/src/backend/routes/webhooks.routes.ts:86` updates that finding without verifying it belongs to the MR/project.
- Impact: a developer on Project A can explain or dismiss Project B findings if the finding ID is known.
- Fix:
  - Resolve findings through joins to the current MR and project.
  - Reject cross-MR/cross-project finding IDs.

### TODO-006 Common storage switch only updates Common config in a split deployment

- Status: fixed
- Owner: Common backend / deployment
- Evidence:
  - `common-backend/src/backend/routes/system.routes.ts:43` computes a config path from Common service runtime state.
  - `common-backend/src/backend/routes/system.routes.ts:62` writes only that service's `config.json`.
  - `common-backend/src/backend/routes/system.routes.ts:207` exposes this as the platform storage switch.
- Impact: after splitting service configs, switching storage in Common can leave MR backend on the old database after restart, creating split-brain state between auth/model config and review data.
- Fix:
  - Kept the endpoint as a Common-owned storage configuration API and made that service boundary explicit.
  - Common now returns `service_scope: "common-backend"` and audit logs the action as `common.storage.update`.
  - The frontend labels the page as Common database storage and tells operators MR backend and Worker use their own `config.json`.
  - The split regression test asserts the storage API scope is Common-only.

### TODO-007 Rule document binding can reference another project's rule document

- Status: fixed
- Owner: MR backend
- Evidence:
  - `mr-backend/src/backend/routes/rules.routes.ts:224` accepts `rule_document_id` from the caller.
  - `mr-backend/src/backend/repositories/RuleDocumentRepository.ts:63` inserts the binding without checking the document's project.
  - `mr-backend/src/backend/repositories/RuleDocumentRepository.ts:47` joins `rule_documents` by `rd.id = erb.rule_document_id` only.
- Impact: a project admin can bind a rule document from another project if they know its ID, causing cross-project rule reuse and metadata leakage.
- Fix:
  - Check `rule_documents.project_id = params.projectId` before binding.
  - Join on both `rd.id` and `rd.project_id = erb.project_id`.
  - Add a cross-project binding regression test.

### TODO-008 Common module config template still contains MR/Worker runtime defaults

- Status: fixed
- Owner: Common backend / configuration boundary
- Evidence:
  - `common-backend/config.example.json:10` through `:18` include GitHub/CodeHub runtime token defaults.
  - `common-backend/config.example.json:37` through `:56` include review, agent, and queue policy defaults.
  - `common-backend/config.example.json:57` through `:70` include token usage reporter and Worker runtime Python defaults.
  - `common-backend/src/backend/config.ts:5` through `:31` only defines Common's actual runtime defaults, so the extra template sections are not Common runtime needs.
- Impact: teams copying the Common config template will believe Common owns MR backend and Worker runtime behavior. This weakens the split boundary and can cause config drift when MR backend has its own `config.json`.
- Fix:
  - Keep Common's service config template limited to Common-owned runtime settings: server, PostgreSQL, logging, and platform-wide model defaults if required.
  - Move MR/Worker defaults to `mr-backend/config.example.json`.
  - Document project-level settings separately from Common service process config.

### TODO-024 Evidence-score `drop_below` policy does not actually remove final findings

- Status: fixed
- Owner: MR Worker review quality
- Evidence:
  - `mr-backend/worker/orchestration/judging/evidence_score.py:278` through `:290` sets `selected = 0` and `judge_adjustment = evidence_score_below_drop_threshold` when score is below `drop_below`.
  - `mr-backend/worker/orchestration/nodes/judge_findings.py:3684` applies that policy during final preparation.
  - `mr-backend/worker/orchestration/nodes/judge_findings.py:3725` through `:3738` keeps every post-critic finding whose severity is critical/high/medium; it does not check `selected` or `judge_adjustment`.
  - `mr-backend/worker/orchestration/nodes/judge_findings.py:3740` through `:3781` then inserts those findings into `review_findings`, with `selected` possibly stored as `0`.
- Impact: findings that the evidence policy explicitly intended to drop can still be persisted and make the run status `waiting_confirmation`. This weakens precision controls and can surface low-evidence issues to users.
- Fix:
  - After applying evidence-score policy and critic pass, reject findings with `selected = 0` or `judge_adjustment = evidence_score_below_drop_threshold`.
  - Record them as candidate rejections with a clear reason.
  - Add a unit test where a below-threshold finding is absent from final persisted findings.

### TODO-016 Permissions API bypasses root-only role promotion rules

- Status: fixed
- Owner: Common backend / authorization
- Evidence:
  - `common-backend/src/backend/routes/projects.routes.ts:150` through `:153` require `root` before adding a project member as `project_admin`.
  - `common-backend/src/backend/routes/projects.routes.ts:174` through `:177` require `root` before changing a member role to `project_admin`.
  - `common-backend/src/backend/routes/permissions.routes.ts:76` through `:83` let any current project admin update a member to any `validProjectRole`.
  - `common-backend/src/backend/routes/permissions.routes.ts:4` through `:10` include `system_admin` in valid project roles.
  - `common-backend/src/backend/routes/common.routes.ts:15` through `:17` rank `system_admin` above `project_admin` for project permission checks.
- Impact: project admins can bypass the root-only promotion rule by using the permissions endpoint instead of the project members endpoint. They can grant `project_admin` or `system_admin` inside the project, which changes authorization behavior and contradicts the stricter API path.
- Fix:
  - Apply the same root-only guard in `PATCH /api/permissions/projects/:projectId/members/:memberId`.
  - Remove `system_admin` from assignable project member roles unless it has a documented scoped meaning.
  - Add regression tests covering project-admin attempts to assign `project_admin` and `system_admin`.

## P2

### TODO-009 MR backend startup clears Worker logs and review-run logs

- Status: fixed
- Owner: MR backend / observability
- Evidence:
  - `mr-backend/src/backend/mr-server.ts:18` calls `clearLogFiles(config)` on MR backend startup.
  - `mr-backend/src/backend/logger.ts:30` deletes API log, Worker log, and review-run directory.
  - `mr-backend/worker/review_runtime.py:4897` skips Worker-side cleanup when `JOLT_SKIP_LOG_CLEANUP=1`, but MR backend startup still removes Worker logs.
- Impact: restarting MR backend erases Worker diagnostics and review-run traces, which makes production incident analysis and local verification harder.
- Fix:
  - Separate API log cleanup from Worker/review-run cleanup.
  - Default to log rotation or append-only logs instead of deletion on service startup.

### TODO-010 HTTP body parsing has no size limit

- Status: fixed
- Owner: Common backend / MR backend
- Evidence:
  - `common-backend/src/backend/http.ts:33` reads request chunks until EOF and buffers the full body.
  - `mr-backend/src/backend/http.ts` has the same implementation.
- Impact: large request bodies can exhaust memory on both services. This is especially relevant for custom skills, rule documents, reports, settings, and webhook payloads.
- Fix:
  - Enforce a configurable request body limit.
  - Return HTTP 413 when exceeded.
  - Add tests for oversized payload rejection.

### TODO-011 Shared script API router does not match frontend split routing

- Status: fixed
- Owner: scripts / verification
- Evidence:
  - `frontend/src/frontend/apiRouting.ts:18` routes Common project APIs such as members, settings, effective-config, join requests, invitations, and audit logs to Common.
  - `scripts/api-auth.mjs:5` only routes auth/me/users/permissions/models/system/internal paths to Common.
  - `scripts/api-auth.mjs:5` through `:14` also omit the base `/api/projects` Common route.
  - `scripts/smoke.mjs:5` calls `/api/projects`, which the script router sends to MR backend by default.
  - `scripts/verify-local.mjs:11` calls `/api/projects/:projectId/members`.
  - `scripts/verify-local.mjs:17` calls `/api/projects/:projectId/audit-logs`.
- Impact: verification scripts can call Common-owned project APIs against MR backend in a three-port deployment, causing false 404 failures or reducing confidence in split validation.
- Fix:
  - Reuse the same route patterns as `frontend/src/frontend/apiRouting.ts`, or move shared API routing rules into a common script module.
  - Add a script-level routing verifier mirroring frontend cases.

### TODO-012 Production baseline verifier still assumes one backend API base

- Status: fixed
- Owner: scripts / verification
- Evidence:
  - `scripts/verify-production-baseline.mjs:4` defaults `API_BASE` to `http://127.0.0.1:9021`.
  - `scripts/verify-production-baseline.mjs:33` logs in through `/api/auth/login` on that single API base.
  - `scripts/verify-production-baseline.mjs:43` calls `/api/me` on the same base.
  - `scripts/verify-production-baseline.mjs:47` calls `/api/projects` on the same base.
  - `scripts/verify-production-baseline.mjs:54` then calls MR-owned repository APIs through the same helper.
- Impact: this baseline cannot validate the split deployment topology because Common-owned auth/project APIs and MR-owned review APIs are all sent to one service. On the new default ports it will either fail against MR with 404s or encourage running an obsolete single-backend compatibility shape.
- Fix:
  - Replace the single `API` helper with Common/MR routing rules.
  - Prefer importing the same path classifier used by `scripts/api-auth.mjs` after TODO-011 is fixed.
  - Add an assertion that `/api/auth/*` hits Common and MR-owned review APIs hit MR.

### TODO-013 Legacy verification scripts still read removed root `src/` and `build/backend` paths

- Status: fixed
- Owner: scripts / verification cleanup
- Evidence:
  - `scripts/verify-real-tooling.mjs:11` reads `worker/review_runtime.py`, while the migrated file is under `mr-backend/worker/review_runtime.py`.
  - `scripts/verify-real-tooling.mjs:15` through `:21` read `src/backend/*` and `src/frontend/*`, which are no longer root-level module paths.
  - `scripts/verify-production-hardening.mjs:5` through `:10` scan `src/backend` and `worker/orchestration`.
  - `scripts/verify-finding-source-context.mjs:6` reads `src/frontend/main.tsx`.
  - `scripts/verify-mr-markdown-export.mjs:2`, `:84`, and `:89` import/read root `build/backend` and `src/*` paths.
  - `scripts/build_rule_registry.py:8`, `:94`, and `:103` still use root `worker` paths for imports, generated metadata, and output.
  - `scripts/maintenance/recalc-recent-precision.mjs:7` through `:9`, `scripts/verify-pg-storage-config.mjs:6`, `scripts/verify-auto-sync-scheduler.mjs:1`, and `scripts/verify-model-config-env-fallback.mjs:16` import from root `build/backend/*`.
  - `scripts/verify-three-project-boundary.mjs:77` calls `npm run build:api`, but the root `package.json` no longer defines that script.
  - `scripts/verify-three-project-boundary.mjs:81`, `:102`, and `:104` still import/start root `build/backend/*`.
  - `scripts/verify_quality_evidence_contract.py:103` reads root `src/frontend/main.tsx`.
- Impact: these scripts no longer verify the current repository layout. Some fail immediately; others silently stop covering the migrated Common/MR/frontend code, so future cleanup or regression claims can be based on stale checks.
- Fix:
  - Update each script to point at `common-backend`, `mr-backend`, or `frontend` explicitly.
  - Delete scripts that are no longer part of the supported verification contract.
  - Add a root script that fails if verification code references root `src/`, root `worker/`, or root `build/backend` after the split.

### TODO-014 Runtime dependency check uses the wrong Python environment and requirements path

- Status: fixed
- Owner: scripts / local startup
- Evidence:
  - `scripts/check-runtime-deps.mjs:64` through `:67` use root `.venv`.
  - `scripts/check-runtime-deps.mjs:101` creates root `.venv`.
  - `scripts/check-runtime-deps.mjs:133` runs `pip install -r requirements.txt` from the repository root.
  - `scripts/start-windows.ps1:11` sets `$VenvPython` to root `.venv\Scripts\python.exe`.
  - `scripts/start-windows.ps1:40` through `:53` creates root `.venv` and installs root `requirements.txt`.
  - The repository root has no `requirements.txt`; the Worker dependencies live at `mr-backend/requirements.txt`.
  - `scripts/run-python.mjs:30` through `:31` and `scripts/verify-split-full-regression.mjs:347` through `:351` use `mr-backend/.venv` and install from `mr-backend/requirements.txt`.
- Impact: `npm run dev` can fail during dependency repair, or report success/failure for a different Python environment than the one actually used by the MR Worker.
- Fix:
  - Make `check-runtime-deps.mjs` use `mr-backend/.venv` and `mr-backend/requirements.txt`.
  - Keep the same Python selection logic as `scripts/run-python.mjs`.
  - Add a startup check that verifies `psycopg` imports from the exact Worker Python executable.

### TODO-017 LLM connectivity test can make server-side requests to arbitrary hosts

- Status: fixed
- Owner: Common backend / security
- Evidence:
  - `common-backend/src/backend/routes/projects.routes.ts:231` through `:239` expose project-level LLM testing to project admins.
  - `common-backend/src/backend/services/LlmConnectivityService.ts:13` through `:16` builds the request URL directly from `default_base_url`.
  - `common-backend/src/backend/services/LlmConnectivityService.ts:77` through `:83` validate only that base URL, model, and API key are present.
  - `common-backend/src/backend/services/LlmConnectivityService.ts:92` sends a server-side `fetch` to that URL without protocol, host, private-network, or allowlist checks.
- Impact: a project admin can make the Common service initiate outbound requests to arbitrary hosts reachable from the server network. Even though `/chat/completions` is appended, this is still an SSRF surface against internal gateways, proxies, or metadata-like endpoints.
- Fix:
  - Restrict LLM base URLs to configured providers or an admin-managed allowlist.
  - Reject non-HTTPS URLs by default, and block loopback, link-local, and private network ranges unless explicitly allowed.
  - Apply the same validation when saving `llm_policy`, not only when testing it.

### TODO-018 MR deletion leaves candidate findings and token usage reports behind

- Status: fixed
- Owner: MR backend / data cleanup
- Evidence:
  - `mr-backend/src/backend/repositories/MergeRequestRepository.ts:201` through `:204` delete tool observations, review artifacts, code index snapshots, and review runs by `review_run_id`.
  - `mr-backend/src/backend/repositories/MergeRequestRepository.ts:206` through `:209` delete dead letters, jobs, reports, and finally the merge request.
  - `mr-backend/src/backend/db/migrations.ts:113` through `:144` define `candidate_findings` keyed by `review_run_id`, but `deleteById()` never deletes those rows.
  - `mr-backend/src/backend/db/migrations.ts:225` through `:250` define `token_usage_reports` keyed by project, MR, job, and run, but `deleteById()` never deletes those rows either.
- Impact: deleting a local MR can leave review-derived evidence and token usage payloads in the database after the user expects MR data to be gone. Those orphan rows can also skew metrics or future maintenance queries.
- Fix:
  - Delete `candidate_findings` by run ID before deleting `review_runs`.
  - Delete `token_usage_reports` by MR ID, job IDs, or run IDs before deleting the MR/job/run records.
  - Add a regression test that creates all review-derived rows and verifies `deleteById()` removes them.

### TODO-019 MR backend still carries local LLM defaults that can override the Common-only configuration boundary

- Status: fixed
- Owner: MR backend / service split cleanup
- Evidence:
  - `mr-backend/src/backend/config.ts:5` through `:14` define MR-local LLM defaults, including `default_api_key_env: "MINIMAX_API_KEY"`.
  - `mr-backend/config.example.json:2` through `:9` documents the same MR-local LLM settings.
  - `mr-backend/src/backend/services/CommonBackendClient.ts:129` through `:132` start the effective project config from `this.config` and merge Common's LLM response over `this.config.llm`, leaving MR defaults as fallback values.
  - `mr-backend/src/backend/services/LlmConnectivityService.ts:7` through `:22` still contains an MR-local LLM test implementation that ignores plaintext API keys and requires an environment variable, although current frontend routes use the Common endpoint.
  - `mr-backend/worker/config.py:14` through `:23` also define Worker-local LLM defaults, including `default_api_key_env: "MINIMAX_API_KEY"`.
  - `mr-backend/worker/config.py:207` through `:219` build the Worker effective project config from local defaults and then merge Common project settings, preserving local fallback values.
- Impact: model runtime configuration is not cleanly owned by Common. If Common omits a field or an old script calls MR-side logic, MR/Worker can fall back to local env-key defaults and reintroduce the behavior the split was meant to remove.
- Fix:
  - Remove MR-local LLM defaults from `mr-backend/src/backend/config.ts` and `mr-backend/config.example.json`, or keep only non-secret runtime limits that are explicitly MR-owned.
  - Make `CommonBackendClient.projectEffectiveConfig()` treat Common's effective config as authoritative for `llm`.
  - Make `worker/config.py` treat Common's effective model config as authoritative and fail closed when Common cannot provide it.
  - Delete the unused MR `LlmConnectivityService` or move all LLM testing through Common.
  - Add a regression check that no MR config example or MR default config contains `default_api_key_env` / provider model defaults.

### TODO-020 VCS repository endpoints are project-admin controlled server-side request targets

- Status: fixed
- Owner: MR backend / VCS integration security
- Evidence:
  - `mr-backend/src/backend/routes/repositories.routes.ts:59` accepts arbitrary `provider_config` from the project repository creation body.
  - `mr-backend/src/backend/repositoryIdentity.ts:72` through `:80` and `:84` through `:93` spread `providerInput` after default GitHub/CodeHub values, so `endpoint` and path templates can be overridden.
  - `mr-backend/src/backend/github.ts:40` through `:42` build the GitHub API base from `repoConfig.endpoint`, and `github.ts:55` through `:157` use that base for server-side fetches.
  - `mr-backend/src/backend/codehub.ts:22` through `:25` build the CodeHub API base from `repoConfig.endpoint`, and `codehub.ts:68` through `:176` use that base for server-side fetches.
- Impact: a project admin can configure the MR backend to make outbound HTTP requests to arbitrary hosts reachable from the service network during sync, file fetch, comment publish, or status update. Custom enterprise VCS endpoints are useful, but without an allowlist this is an SSRF surface.
- Fix:
  - Restrict VCS endpoints to a system-admin managed allowlist or predefined provider profiles stored in Common.
  - Reject loopback, link-local, and private network ranges unless explicitly allowed for the deployment.
  - Validate and persist sanitized endpoint/profile IDs instead of raw project-provided endpoint URLs.

### TODO-021 LLM response cache is global and not project-isolated

- Status: fixed
- Owner: MR Worker / data isolation
- Evidence:
  - `mr-backend/src/backend/db/migrations.ts:491` through `:500` define `llm_response_cache` with only `cache_key`, provider/model/schema/seed/prompt hash, and response JSON; there is no `project_id`.
  - `mr-backend/worker/llm/client.py:260` through `:271` builds `cache_key` from provider, model, prompt, seed, and schema name only.
  - `mr-backend/worker/llm/client.py:292` through `:304` reads cached responses by `cache_key` only.
  - `mr-backend/worker/llm/client.py:315` through `:352` writes cached responses without project context.
- Impact: LLM output generated while reviewing one project can be reused in another project if the prompt/model tuple matches. Even when exact prompt collisions are uncommon, the cache also stores review response JSON in a global table without project ownership, weakening project data isolation and retention semantics.
- Fix:
  - Add `project_id` to `llm_response_cache`.
  - Include `project_id` in the cache key or query predicate.
  - Thread `project_id` through `_read_cached_llm_response()` and `_write_cached_llm_response()`.
  - Add a regression test that two projects with the same prompt do not share cached responses unless an explicit system-level shared-cache policy is enabled.

### TODO-022 Project-level token usage endpoint is an unrestricted outbound request target

- Status: fixed
- Owner: Common config / MR Worker telemetry
- Evidence:
  - `common-backend/src/backend/services/ProjectConfigService.ts:4` through `:15` include `token_usage` in project-level settings keys.
  - `common-backend/src/backend/routes/projects.routes.ts:207` through `:220` let a project admin update any allowed settings key, including `token_usage`.
  - `mr-backend/worker/token_usage_reporter.py:246` through `:284` reads `token_usage.endpoint` from effective config and builds a server-side `urllib.request.Request` to that endpoint.
  - `mr-backend/worker/token_usage_reporter.py:138` through `:182` includes review run, project, repository, merge request, reporter, and token usage metadata in the outbound payload.
- Impact: a project admin can make the Worker send server-side HTTP requests to arbitrary URLs and can exfiltrate MR metadata/token usage details to an attacker-controlled endpoint. This is another SSRF and data egress surface.
- Fix:
  - Move telemetry endpoint configuration to a root/system-admin-only Common setting, or restrict it to a system-managed allowlist.
  - Block loopback, link-local, and private network ranges by default.
  - Consider per-project enablement flags that reference a preapproved endpoint profile instead of accepting raw endpoint URLs.

### TODO-023 PR Summary node always returns the disabled fallback, leaving the configured summary implementation unreachable

- Status: fixed
- Owner: MR Worker orchestration
- Evidence:
  - `mr-backend/worker/orchestration/nodes/summarize_pr.py:28` through `:42` builds a hard-coded disabled summary, persists it, and returns immediately.
  - `mr-backend/worker/orchestration/nodes/summarize_pr.py:44` through `:94` contains the intended effort-aware fallback and `summarize_pr(...)` execution path, but this block is unreachable after the earlier return.
- Impact: project configuration and the injected `summarize_pr` implementation cannot enable PR summary generation. The file appears to support LLM/fallback summary behavior, but runtime always stores the disabled summary.
- Fix:
  - Either remove the unreachable implementation and make the product-level disabled state explicit, or gate the early disabled return behind a config flag.
  - Add a focused test proving the chosen behavior.

### TODO-025 New project creation silently drops the initial repository binding

- Status: fixed
- Owner: Frontend / Common backend / MR backend integration
- Evidence:
  - `frontend/src/frontend/main.tsx:2349` through `:2362` sends an optional `repository` object when creating a project.
  - `common-backend/src/backend/routes/projects.routes.ts:87` through `:113` creates the project in Common but ignores `input.repository` and returns `repository: null`.
  - `mr-backend/src/backend/routes/repositories.routes.ts:42` through `:71` owns the actual repository binding endpoint under `/api/projects/:projectId/repositories`.
- Impact: root users can enter a repository URL during new project creation and see the project created successfully, but no repository is bound in MR backend. The new project then has an empty MR queue until the user binds the repository again from the project maintenance UI.
- Fix:
  - Either remove the initial repository fields from the Common project creation form, or
  - After Common creates the project, call the MR backend repository binding endpoint with the new project ID.
  - Add a smoke case that creates a project with a repository and verifies the repository appears in `/api/projects/:projectId/repositories`.

### TODO-026 Backend module packages still carry frontend runtime dependencies

- Status: fixed
- Owner: module packaging
- Evidence:
  - `common-backend/package.json:15` through `:21` includes `@vitejs/plugin-react`, `vite`, `react`, `react-dom`, and `lucide-react`.
  - `mr-backend/package.json:17` through `:23` includes the same frontend packages.
  - `frontend/package.json:13` through `:17` is already the correct owner of those frontend dependencies.
- Impact: installing a backend module pulls frontend toolchain and UI dependencies, which makes the service boundary look less clean and increases deployment surface for Common and MR backend.
- Fix:
  - Remove frontend-only dependencies from `common-backend/package.json` and `mr-backend/package.json`.
  - Keep backend packages limited to runtime/database dependencies and TypeScript build dependencies.
  - Verify each backend still builds from its own package manifest.

## Verification gaps

- Code review coverage:
  - Reviewed the split service source tree and operational scripts across 213 code files under `common-backend`, `mr-backend`, `frontend`, `scripts`, `evaluation`, and root runtime helpers.
  - Excluded generated/build/runtime artifacts such as `outputs`, `build`, `dist`, `node_modules`, `.venv`, and `__pycache__` from source-review scope.
- Completed on 2026-06-26:
  - `npm run build`
  - `python3 -m compileall mr-backend/worker scripts`
  - `npm run verify`
  - `npm run verify:frontend-api-routing`
  - `npm run verify:postgres-only-runtime`
  - `node scripts/verify-real-tooling.mjs`
  - `node scripts/verify-production-hardening.mjs`
  - `node scripts/verify-auto-sync-scheduler.mjs`
  - `node scripts/verify-model-config-env-fallback.mjs`
  - `node scripts/verify-finding-source-context.mjs`
  - `node scripts/verify-mr-markdown-export.mjs`
  - `node scripts/verify-pg-storage-config.mjs`
  - `python3 scripts/verify_quality_evidence_contract.py`
  - `node scripts/verify-split-full-regression.mjs`
- Full split regression result:
  - Started temporary PostgreSQL plus Common, MR backend, frontend, and MR Worker.
  - Verified Common/MR route boundary, Common-only storage config scope, internal model config service-token access, login/session, anonymous request rejection, cross-project non-member rejection, project creation with repository binding, MR/review job/run flow, Worker execution, and PostgreSQL persistence.
  - Final fixture produced one MR, one review job, one review run, and three findings.
- Remaining test gap:
  - None known from this review pass.
