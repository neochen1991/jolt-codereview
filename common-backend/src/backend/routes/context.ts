import type { Db } from "../db.js";
import type { AppConfig } from "../types.js";
import type { AuditRepository } from "../repositories/AuditRepository.js";
import type { ProjectRepository } from "../repositories/ProjectRepository.js";
import type { ProjectConfigService } from "../services/ProjectConfigService.js";

export interface BackendRouteContext {
  config: AppConfig;
  db: Db;
  projectRepository: ProjectRepository;
  auditRepository: AuditRepository;
  projectConfigService: ProjectConfigService;
  all<T>(sql: string, params?: any[]): T[];
  get<T>(sql: string, params?: any[]): T | undefined;
  bearerToken(req: { headers: Record<string, any> }): string | null;
  currentUserId(req: { headers: Record<string, any> }): string;
  ensureProjectRole(projectId: string, userId: string, minRole: string): { statusCode: number; error: string; message: string } | null;
  ensureRoot(userId: string): { statusCode: number; error: string; message: string } | null;
  auditLog(input: {
    userId?: string;
    projectId?: string;
    action: string;
    resourceType: string;
    resourceId?: string;
    summary?: string;
    metadata?: Record<string, unknown>;
  }): void;
}
