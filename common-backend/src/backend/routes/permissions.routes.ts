import { badRequest, route, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";

const PROJECT_ROLES = [
  { key: "observer", rank: 1, label: "Observer" },
  { key: "developer", rank: 2, label: "Developer" },
  { key: "reviewer", rank: 3, label: "Reviewer" },
  { key: "project_admin", rank: 4, label: "Project Admin" },
  { key: "system_admin", rank: 5, label: "System Admin" }
];

const GLOBAL_ROLES = [
  { key: "user", rank: 1, label: "User" },
  { key: "root", rank: 10, label: "Root" }
];

function validProjectRole(role: string) {
  return PROJECT_ROLES.some((item) => item.key === role);
}

export function createPermissionRoutes(ctx: BackendRouteContext): Route[] {
  const { currentUserId, ensureRoot, ensureProjectRole, projectRepository, auditLog } = ctx;
  return [
    route("GET", "/api/permissions/roles", () => ({
      global_roles: GLOBAL_ROLES,
      project_roles: PROJECT_ROLES
    })),
    route("GET", "/api/permissions/me", ({ req }) => {
      const userId = currentUserId(req);
      if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const user = projectRepository.findUserById(userId) as { id: string; username: string; global_role?: string } | undefined;
      if (!user) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const memberships = projectRepository.isRoot(userId)
        ? projectRepository.listProjects().map((project: any) => ({ project_id: project.id, project_name: project.name, role: "system_admin" }))
        : projectRepository.listProjectsForUser(userId).map((project: any) => ({ project_id: project.id, project_name: project.name, role: project.role }));
      return {
        user: {
          id: user.id,
          username: user.username,
          global_role: user.global_role ?? "user",
          is_root: projectRepository.isRoot(userId)
        },
        memberships
      };
    }),
    route("GET", "/api/permissions/projects/:projectId/members", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = projectRepository.isRoot(actorId) ? null : ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return { items: projectRepository.listMembers(params.projectId) };
    }),
    route("PATCH", "/api/permissions/projects/:projectId/members/:memberId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = projectRepository.isRoot(actorId) ? null : ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const input = (typeof body === "object" && body ? body : {}) as Record<string, unknown>;
      const roleValue = String(input.role || "").trim();
      if (!validProjectRole(roleValue)) return badRequest("role must be one of observer, developer, reviewer, project_admin, system_admin");
      projectRepository.updateMemberRole(params.projectId, params.memberId, roleValue);
      const member = projectRepository.findMember(params.projectId, params.memberId);
      if (!member) return { statusCode: 404, error: "not_found" };
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "permissions.member.update",
        resourceType: "project_member",
        resourceId: params.memberId,
        summary: `updated member role to ${roleValue}`
      });
      return { member };
    }),
    route("GET", "/internal/auth/introspect", ({ req, url }) => {
      const expected = String(process.env.JOLT_INTERNAL_SERVICE_TOKEN || "").trim();
      const actual = String(req.headers["x-internal-service-token"] || "").trim();
      if (!expected || actual !== expected) {
        return { statusCode: 401, error: "unauthorized", message: "internal service token is required" };
      }
      const userId = url.searchParams.get("user_id") || "";
      if (!userId) return badRequest("user_id is required");
      const user = projectRepository.findUserById(userId) as { id: string; username: string; global_role?: string; status?: string } | undefined;
      if (!user || user.status !== "active") return { active: false };
      const memberships = projectRepository.isRoot(userId)
        ? projectRepository.listProjects().map((project: any) => ({ project_id: project.id, role: "system_admin" }))
        : projectRepository.listProjectsForUser(userId).map((project: any) => ({ project_id: project.id, role: project.role }));
      return {
        active: true,
        user: {
          id: user.id,
          username: user.username,
          global_role: user.global_role ?? "user",
          is_root: projectRepository.isRoot(userId)
        },
        memberships
      };
    })
  ];
}
