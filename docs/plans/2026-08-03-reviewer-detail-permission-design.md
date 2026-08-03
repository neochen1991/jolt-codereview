# Reviewer Detail Permission Design

## Goal

Add account-type selection during registration and reduce the MR review detail shown to reviewer users to business-facing findings and actions. Internal execution identifiers, tool activity, traces, coverage, and quality diagnostics remain available only to project administrators and root users.

## Registration and project administration

The registration form offers two account types:

- regular user, stored with `global_role = user`;
- project administrator, stored with `global_role = project_admin`.

No new role is introduced. A global `project_admin` may create a new project. Project creation also inserts a `project_members` record for the creator with role `project_admin`.

The global role does not grant access to existing projects. All reads and mutations for an existing project continue to require a matching `project_members` record, except for root users. This prevents self-registration from becoming an elevation path into an existing project.

The first registered account retains the existing root bootstrap behavior.

## MR review detail visibility

The backend determines diagnostic visibility from the authenticated user's membership in the MR's project:

- root or project member role `project_admin`: full review detail and diagnostic endpoints;
- reviewer: business-facing review detail only.

For reviewer responses, the MR detail contains the MR summary, business status/progress, findings, and data required by normal reviewer actions. It does not expose:

- Job or Run identifiers and records;
- tool observations and tool calls;
- LLM calls, Skill calls, Agent messages, or trace events;
- coverage data, quality dashboards, artifacts, or Skill trace data.

Dedicated trace, session-log, artifact, and Skill-trace endpoints require project administrator access. Reviewer operations such as selecting findings, marking false positives, exporting Markdown, rerunning review, and publishing selected findings retain their current authorization.

## Frontend behavior

The MR detail receives an explicit diagnostic-visibility decision derived from the active project role and current user.

For reviewers, the page keeps:

- MR title and basic metadata;
- business review status/progress without Job, Run, tool, LLM, Skill, or Agent metadata;
- the findings list and finding detail;
- selection, false-positive, export, rerun, and publish actions.

It removes:

- the `检视过程` tab;
- the `工具结果` tab;
- the `检视覆盖情况` card;
- the `真实任务质量仪表盘` card;
- all internal execution metadata rows.

Project administrators and root users retain the existing full presentation.

If a user changes project or role while a hidden diagnostic tab is active, the detail view resets to the findings tab.

## Security and error handling

Registration validates the requested account type against `user` and `project_admin`; arbitrary global roles are rejected. The server, not the browser, decides the stored global role.

Project creation allows root and global `project_admin` accounts. Existing-project authorization does not treat the global role as project membership.

Diagnostic endpoints return `403` for reviewers. Reviewer detail responses are shaped server-side so hidden diagnostic data is not delivered to the browser.

## Verification

Automated verification covers:

- regular registration stores `user` and cannot create projects;
- project-administrator registration stores `project_admin` and can create a new project;
- the creator becomes that project's member-level `project_admin`;
- a global `project_admin` cannot access an existing project without membership;
- reviewer MR detail responses omit diagnostics and dedicated diagnostic endpoints return `403`;
- project administrators retain full detail and diagnostic access;
- reviewer UI renders only findings and normal review actions;
- administrator UI retains process, tools, coverage, quality, Job, and Run information.

Browser verification uses separate reviewer and project-administrator accounts against the same MR fixture.
