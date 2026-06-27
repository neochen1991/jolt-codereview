import { badRequest, route, sha1, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";

const PROJECT_ROLES = [
  { key: "observer", rank: 1, label: "Observer" },
  { key: "developer", rank: 2, label: "Developer" },
  { key: "reviewer", rank: 3, label: "Reviewer" },
  { key: "project_admin", rank: 4, label: "Project Admin" }
];

const GLOBAL_ROLES = [
  { key: "user", rank: 1, label: "User" },
  { key: "root", rank: 10, label: "Root" }
];

function validProjectRole(role: string) {
  return PROJECT_ROLES.some((item) => item.key === role);
}

export function createPermissionRoutes(ctx: BackendRouteContext): Route[] {
  const { bearerToken, currentUserId, ensureRoot, ensureProjectRole, projectRepository, auditLog } = ctx;

  function userMemberships(userId: string) {
    return projectRepository.isRoot(userId)
      ? projectRepository.listProjects().map((project: any) => ({ project_id: project.id, project_name: project.name, role: "system_admin" }))
      : projectRepository.listProjectsForUser(userId).map((project: any) => ({ project_id: project.id, project_name: project.name, role: project.role }));
  }

  function publicAuthUser(userId: string) {
    const user = projectRepository.findUserById(userId) as { id: string; username: string; global_role?: string; status?: string } | undefined;
    if (!user || user.status !== "active") return null;
    return {
      id: user.id,
      username: user.username,
      global_role: user.global_role ?? "user",
      is_root: projectRepository.isRoot(userId)
    };
  }

  function userSettings(userId: string) {
    const rows = projectRepository.listUserSettings(userId) as Array<{ settings_key: string; settings_json: string }>;
    return Object.fromEntries(rows.map((row) => [
      row.settings_key,
      JSON.parse(row.settings_json || "{}")
    ]));
  }

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
      const memberships = userMemberships(userId);
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
      if (!validProjectRole(roleValue)) return badRequest("role must be one of observer, developer, reviewer, project_admin");
      if (roleValue === "project_admin") {
        const rootDenied = ensureRoot(actorId);
        if (rootDenied) return rootDenied;
      }
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
      let userId = url.searchParams.get("user_id") || "";
      const token = bearerToken(req);
      if (token) {
        const session = projectRepository.findSessionUserId(sha1(token)) as { user_id: string } | undefined;
        userId = session?.user_id ?? "";
      }
      if (!userId) return { active: false };
      const user = publicAuthUser(userId);
      if (!user) return { active: false };
      const memberships = userMemberships(userId).map((item: any) => ({ project_id: item.project_id, role: item.role }));
      return {
        active: true,
        user,
        memberships,
        settings: userSettings(userId)
      };
    })
  ];
}
