import { randomBytes } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";

const PROJECT_MEMBER_ROLES = new Set(["observer", "developer", "reviewer", "project_admin"]);

export function createProjectRoutes(ctx: BackendRouteContext): Route[] {
  const { config, get, currentUserId, ensureRoot, ensureProjectRole, projectRepository, auditRepository, projectConfigService, auditLog } = ctx;
  return [
    route("GET", "/api/projects", ({ req }) => {
      const actorId = currentUserId(req);
      if (!actorId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      return projectRepository.isRoot(actorId) ? projectRepository.listProjects() : projectRepository.listProjectsForUser(actorId);
    }),
    route("GET", "/api/projects/discover", ({ req }) => {
      const actorId = currentUserId(req);
      if (!actorId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      return { items: projectRepository.listDiscoverableProjects(actorId) };
    }),
    route("POST", "/api/projects", ({ body, req }) => {
      const actorId = currentUserId(req);
      if (!actorId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const denied = ensureRoot(actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const name = String(input.name || "").trim();
      if (!name) return badRequest("project name is required");
      const projectId = id("project");
      const project = projectRepository.createProject({
        id: projectId,
        name,
        description: String(input.description || "").trim(),
        ownerUserId: actorId,
        memberId: `member_${sha1(`${projectId}:${actorId}`).slice(0, 12)}`,
        cloneFromProjectId: "project_default"
      });
      auditLog({
        userId: actorId,
        projectId,
        action: "projects.create",
        resourceType: "project",
        resourceId: projectId,
        summary: "created project"
      });
      return { project, repository: null };
    }),
    route("GET", "/api/projects/:projectId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "observer");
      if (denied) return denied;
      return projectRepository.findProjectById(params.projectId) ?? notFound();
    }),
    route("PATCH", "/api/projects/:projectId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      if (input.name !== undefined && !String(input.name).trim()) return badRequest("project name is required");
      const project = projectRepository.updateProject(params.projectId, {
        name: input.name !== undefined ? String(input.name).trim() : undefined,
        description: input.description !== undefined ? String(input.description) : undefined,
        data_policy: input.data_policy
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "projects.update", resourceType: "project", resourceId: params.projectId, summary: "updated project profile" });
      return project ?? notFound();
    }),
    route("GET", "/api/projects/:projectId/members", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return projectRepository.listMembers(params.projectId);
    }),
    route("POST", "/api/projects/:projectId/members", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const username = String(input.username ?? "").trim();
      const displayName = String(input.display_name ?? username);
      const role = String(input.role ?? "developer");
      if (!username) return badRequest("username is required");
      if (!PROJECT_MEMBER_ROLES.has(role)) return badRequest("role is invalid");
      if (role === "project_admin") {
        const rootDenied = ensureRoot(actorId);
        if (rootDenied) return rootDenied;
      }
      const userId = String(input.user_id ?? `user_${sha1(username).slice(0, 12)}`);
      const memberId = String(input.member_id ?? `member_${sha1(`${params.projectId}:${userId}`).slice(0, 12)}`);
      const member = projectRepository.upsertMember({
        userId,
        username,
        displayName,
        email: input.email ? String(input.email) : null,
        memberId,
        projectId: params.projectId,
        role
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "project.members.upsert", resourceType: "project_member", resourceId: memberId, summary: `upsert member ${username} as ${role}` });
      return member;
    }),
    route("PATCH", "/api/projects/:projectId/members/:memberId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const role = String((body as Record<string, unknown>)?.role ?? "");
      if (!PROJECT_MEMBER_ROLES.has(role)) return badRequest("role is invalid");
      if (role === "project_admin") {
        const rootDenied = ensureRoot(actorId);
        if (rootDenied) return rootDenied;
      }
      projectRepository.updateMemberRole(params.projectId, params.memberId, role);
      auditLog({ userId: actorId, projectId: params.projectId, action: "project.members.update_role", resourceType: "project_member", resourceId: params.memberId, summary: `role=${role}` });
      return projectRepository.findMember(params.projectId, params.memberId) ?? notFound();
    }),
    route("DELETE", "/api/projects/:projectId/members/:memberId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      projectRepository.deleteMember(params.projectId, params.memberId);
      auditLog({ userId: actorId, projectId: params.projectId, action: "project.members.remove", resourceType: "project_member", resourceId: params.memberId });
      return { ok: true };
    }),
    route("GET", "/api/projects/:projectId/settings", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "observer");
      if (denied) return denied;
      return projectConfigService.listSettings(params.projectId);
    }),
    route("GET", "/api/projects/:projectId/effective-config", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "observer");
      if (denied) return denied;
      return projectConfigService.effectiveConfig(params.projectId, config);
    }),
    route("PATCH", "/api/projects/:projectId/settings/:key", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      if (!projectConfigService.isAllowedKey(params.key)) {
        return badRequest(`settings key must be one of: ${projectConfigService.allowedKeys().join(", ")}`);
      }
      const input = (body as Record<string, unknown> | undefined) ?? {};
      const value = (typeof input.value === "object" && input.value ? input.value : input) as Record<string, unknown>;
      const row = projectConfigService.upsertSetting(params.projectId, params.key, value);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "project.settings.update",
        resourceType: "project_settings",
        resourceId: params.key,
        summary: `updated ${params.key}`
      });
      return row ? { key: row.key, value: JSON.parse(row.settings_json || "{}"), updated_at: row.updated_at } : notFound();
    }),
    route("GET", "/api/projects/:projectId/join-requests", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return { items: projectRepository.listJoinRequests(params.projectId) };
    }),
    route("POST", "/api/projects/:projectId/join-requests", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      if (!actorId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const input = body as Record<string, unknown>;
      const requestedRole = String(input.requested_role ?? "developer");
      if (!PROJECT_MEMBER_ROLES.has(requestedRole)) return badRequest("requested_role is invalid");
      const request = projectRepository.createJoinRequest({
        id: id("join"),
        projectId: params.projectId,
        userId: actorId,
        requestedRole,
        reason: String(input.reason ?? "")
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "project.join_request.create", resourceType: "project_join_request", resourceId: String((request as { id?: string })?.id ?? ""), summary: `requested ${requestedRole}` });
      return request;
    }),
    route("PATCH", "/api/projects/:projectId/join-requests/:requestId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const status = String((body as Record<string, unknown>)?.status ?? "");
      if (!["approved", "rejected"].includes(status)) return badRequest("status must be approved or rejected");
      if (status === "approved") {
        const request = get<{ requested_role?: string }>(
          "SELECT requested_role FROM project_join_requests WHERE id = $1 AND project_id = $2",
          [params.requestId, params.projectId]
        );
        if (request?.requested_role === "project_admin") {
          const rootDenied = ensureRoot(actorId);
          if (rootDenied) return rootDenied;
        }
      }
      const request = projectRepository.reviewJoinRequest({
        projectId: params.projectId,
        requestId: params.requestId,
        reviewerId: actorId,
        status: status as "approved" | "rejected"
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: `project.join_request.${status}`, resourceType: "project_join_request", resourceId: params.requestId });
      return request ?? notFound();
    }),
    route("GET", "/api/projects/:projectId/invitations", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return { items: projectRepository.listInvitations(params.projectId) };
    }),
    route("POST", "/api/projects/:projectId/invitations", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const role = String(input.role || "developer");
      if (!PROJECT_MEMBER_ROLES.has(role)) return badRequest("role is invalid");
      if (role === "project_admin") {
        const rootDenied = ensureRoot(actorId);
        if (rootDenied) return rootDenied;
      }
      const inviteCode = `jolt-${randomBytes(9).toString("base64url")}`;
      const invitation = projectRepository.createInvitation({
        id: id("invite"),
        projectId: params.projectId,
        inviteCodeHash: sha1(inviteCode),
        role,
        createdBy: actorId,
        expiresAt: String(input.expires_at || "").trim() || null,
        maxUses: 0
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "project.invitation.create", resourceType: "project_invitation", resourceId: String((invitation as { id?: string })?.id || ""), summary: `created invitation role=${role}` });
      return { invitation, invite_code: inviteCode };
    }),
    route("POST", "/api/projects/join-by-invite", ({ body, req }) => {
      const actorId = currentUserId(req);
      if (!actorId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const inviteCode = String((body as Record<string, unknown>)?.invite_code || "").trim();
      if (!inviteCode) return badRequest("invite_code is required");
      const project = projectRepository.redeemInvitation({ inviteCodeHash: sha1(inviteCode), userId: actorId });
      if (!project) return { statusCode: 404, error: "invite_not_found", message: "邀请码无效、已过期或已使用完" };
      auditLog({ userId: actorId, projectId: String((project as { id?: string }).id || ""), action: "project.invitation.redeem", resourceType: "project_invitation", summary: "redeemed project invitation" });
      return { project };
    }),
    route("GET", "/api/projects/:projectId/audit-logs", ({ params, url, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const limit = Math.min(100, Math.max(1, Number(url.searchParams.get("limit") ?? 50)));
      return {
        items: auditRepository.listForProject(params.projectId, limit)
      };
    })
  ];
}
