# Multi-User And PostgreSQL Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add production-oriented multi-user isolation, user login/register, project membership workflows, user/project/root settings boundaries, and a path to PostgreSQL storage.

**Architecture:** Use project membership as the primary tenant boundary. Store MR sync credentials, LLM configuration, review policy, static tooling and expert/rule configuration at project scope so all users in the same project see the same MR queue, statuses and findings. Store only submit-time personal VCS tokens and UI preferences at user scope. PostgreSQL support is implemented through a database adapter layer shared by the Node API and Python worker.

**Tech Stack:** React, TypeScript Node API, Python worker, SQLite first, PostgreSQL adapter in phase 2.

---

## Permission Model

### Global Roles

- `root`: platform administrator. Can change storage backend, PostgreSQL connection, system defaults, logging, token reporting, and global fallback settings.
- `user`: normal account. Can manage personal settings and operate projects where it is a member.

### Project Roles

- `project_admin`: manages project repositories, project LLM defaults, static tool policy, expert agents, rule documents, skills, members, and join requests.
- `reviewer`: can start review jobs, confirm findings, export reports, and submit selected comments.
- `developer`: can view MR queue and review results, and can start review when project policy allows.
- `observer`: read-only.

## User Join Project Flow

1. Admin add member: project admin adds a username/email/employee number and assigns role.
2. Invitation: project admin creates an invite code with role, expiry, and max use count. User joins using the code.
3. Join request: user searches or enters project code, submits request, project admin approves or rejects.

Required tables:

- `project_invitations`
- `project_join_requests`

## Settings Scope

### Personal Settings

Visible to every logged-in user:

- Personal CodeHub/GitHub token used only when the user manually submits confirmed review comments.
- Default project and UI preferences.

Review and sync credential precedence:

```text
repository credential > project credential > system fallback
```

Personal VCS tokens are not used for MR sync, diff fetch, AI review, worker execution, or static tooling. This avoids duplicate or divergent review results across users.

### Project Settings

Visible and writable only to `project_admin` or `root`:

- Project default LLM and service account token.
- CodeHub/GitHub repositories and project-level tokens used for MR sync and diff/file fetching.
- Review policy and queue policy.
- Static tool switches and custom rule paths.
- Expert agents, rule documents, skill packages, bindings.
- Project members, invitations, and join requests.

### System Settings

Visible and writable only to `root`:

- SQLite/PostgreSQL backend switch.
- PostgreSQL connection string or host/port/database/user/password.
- Global fallback LLM.
- Token usage report API.
- Logging and system runtime settings.

## Implementation Phases

### Phase 1: Auth And Tenant Boundary

- Add password fields and `global_role` to `users`.
- Add register/login/logout/session endpoints.
- Stop frontend auto-login.
- Filter project listing by current user.
- Enforce project read/write permissions on all project-scoped routes.
- Add project invitations and join requests.

### Phase 2: Settings Scope

- Add `user_settings`.
- Store submit-time personal VCS tokens under `user_settings`.
- Store LLM and MR sync VCS credentials under project settings.
- Keep project LLM, repository, static tool, expert agent, rule, and skill configuration under project scope.
- Add frontend sections: My Settings, Project Settings, System Settings.
- Hide static tools and expert/rule pages from non-admin project members.

### Phase 3: PostgreSQL Backend

- Add a DB adapter interface for `prepare().get/all/run` and transaction helpers.
- Keep SQLite adapter for local mode.
- Add PostgreSQL adapter and SQL dialect compatibility layer.
- Add root-only API to test PostgreSQL connection and initialize schema.
- Update Python worker to support SQLite and PostgreSQL using the same config.
- Add setting page storage backend card.

Current implementation status:

- Root-only System Settings can test a PostgreSQL connection.
- Root-only System Settings can initialize PostgreSQL tables/indexes from the current SQLite schema snapshot.
- Storage target config is persisted in `system_settings` and written back to `config.json` so restart can activate the selected backend.
- Node API supports `server.database_driver=sqlite|postgres` through a DB adapter that preserves the existing `prepare().get/all/run` repository contract.
- Python Worker supports the same switch through a DB-API compatibility layer, including queue selection, heartbeat, tool observations, candidate findings, final findings, LLM logs and token usage reporting.
- SQLite-specific SQL used by the current codebase (`PRAGMA`, `sqlite_master`, `datetime('now', ...)`, `INSERT OR IGNORE`) is translated at the database boundary for PG runtime.

### Phase 4: Verification

- Verify login/register/session.
- Verify project membership filtering.
- Verify role restrictions for static tools and expert/rule pages.
- Verify project-level LLM/VCS precedence for review and sync, and personal VCS token usage only for submit.
- Verify root-only database config visibility and API protection.
- Verify PostgreSQL initialization in an integration environment.
