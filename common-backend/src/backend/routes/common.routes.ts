import { sha1, id, type Route } from "../http.js";
import type { AppConfig } from "../types.js";
import type { Db } from "../db.js";
import { AuditRepository } from "../repositories/AuditRepository.js";
import { ProjectRepository } from "../repositories/ProjectRepository.js";
import { ProjectConfigService } from "../services/ProjectConfigService.js";
import type { BackendRouteContext } from "./context.js";
import { createAuthRoutes } from "./auth.routes.js";
import { createHealthRoutes } from "./health.routes.js";
import { createModelRoutes } from "./models.routes.js";
import { createPermissionRoutes } from "./permissions.routes.js";
import { createProjectRoutes } from "./projects.routes.js";
import { createSystemRoutes } from "./system.routes.js";

function projectRoleRank(role: string): number {
  return { system_admin: 5, project_admin: 4, reviewer: 3, developer: 2, observer: 1 }[role] ?? 0;
}

export function createCommonRoutes(config: AppConfig, db: Db): Route[] {
  const projectRepository = new ProjectRepository(db);
  const auditRepository = new AuditRepository(db);
  const projectConfigService = new ProjectConfigService(db);

  function all<T>(sql: string, params: any[] = []): T[] {
    return db.prepare(sql).all(...params) as T[];
  }

  function get<T>(sql: string, params: any[] = []): T | undefined {
    return db.prepare(sql).get(...params) as T | undefined;
  }

  function bearerToken(req: { headers: Record<string, any> }) {
    const value = Array.isArray(req.headers.authorization) ? req.headers.authorization[0] : req.headers.authorization;
    if (!value?.startsWith("Bearer ")) return null;
    return value.slice("Bearer ".length).trim();
  }

  function currentUserId(req: { headers: Record<string, any> }) {
    const token = bearerToken(req);
    if (token) {
      const session = projectRepository.findSessionUserId(sha1(token)) as { user_id: string } | undefined;
      if (session) return session.user_id;
    }
    if (process.env.JOLT_TRUST_X_USER_ID === "1" || process.env.JOLT_TRUST_X_USER_ID === "true") {
      const headerUser = Array.isArray(req.headers["x-user-id"]) ? req.headers["x-user-id"][0] : req.headers["x-user-id"];
      return headerUser ? String(headerUser) : "";
    }
    return "";
  }

  function ensureProjectRole(projectId: string, userId: string, minRole: string) {
    if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
    if (projectRepository.isRoot(userId)) return null;
    const member = projectRepository.findMemberRole(projectId, userId) as { role: string } | undefined;
    if (!member || projectRoleRank(member.role) < projectRoleRank(minRole)) {
      return { statusCode: 403, error: "forbidden", message: `${minRole} permission is required` };
    }
    return null;
  }

  function ensureRoot(userId: string) {
    if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
    if (!projectRepository.isRoot(userId)) {
      return { statusCode: 403, error: "forbidden", message: "root permission is required" };
    }
    return null;
  }

  function auditLog(input: {
    userId?: string;
    projectId?: string;
    action: string;
    resourceType: string;
    resourceId?: string;
    summary?: string;
    metadata?: Record<string, unknown>;
  }) {
    auditRepository.record({
      id: id("audit"),
      userId: input.userId ?? null,
      projectId: input.projectId ?? null,
      action: input.action,
      resourceType: input.resourceType,
      resourceId: input.resourceId ?? null,
      summary: input.summary ?? "",
      metadata: input.metadata ?? {}
    });
  }

  const ctx: BackendRouteContext = {
    config,
    db,
    projectRepository,
    auditRepository,
    projectConfigService,
    all,
    get,
    bearerToken,
    currentUserId,
    ensureProjectRole,
    ensureRoot,
    auditLog
  };

  return [
    ...createHealthRoutes({ serviceName: "jolt-common-backend" }),
    ...createAuthRoutes(ctx),
    ...createPermissionRoutes(ctx),
    ...createProjectRoutes(ctx),
    ...createSystemRoutes(ctx),
    ...createModelRoutes(ctx)
  ];
}
