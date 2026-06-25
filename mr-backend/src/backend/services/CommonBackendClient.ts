import type { IncomingMessage } from "node:http";
import type { AppConfig } from "../types.js";

export type CommonMembership = {
  project_id: string;
  project_name?: string;
  role: string;
};

export type CommonAuthSnapshot = {
  active: boolean;
  user?: {
    id: string;
    username: string;
    global_role?: string;
    is_root?: boolean;
  };
  memberships: CommonMembership[];
  settings?: Record<string, Record<string, unknown>>;
};

export class CommonBackendClient {
  private readonly requestAuth = new WeakMap<IncomingMessage, CommonAuthSnapshot>();
  private readonly authByUserId = new Map<string, CommonAuthSnapshot>();

  constructor(private readonly config: AppConfig) {}

  commonBaseUrl() {
    const envBase = String(process.env.COMMON_API_BASE || process.env.VITE_COMMON_API_BASE || "").trim();
    if (envBase) return envBase.replace(/\/+$/, "");
    const host = this.config.server?.host ?? "127.0.0.1";
    const port = this.config.server?.common_port ?? 8010;
    return `http://${host}:${port}`;
  }

  internalToken() {
    return String(process.env.JOLT_INTERNAL_SERVICE_TOKEN || "").trim();
  }

  bearerToken(req: { headers: Record<string, any> }) {
    const value = Array.isArray(req.headers.authorization) ? req.headers.authorization[0] : req.headers.authorization;
    if (!value?.startsWith("Bearer ")) return null;
    return value.slice("Bearer ".length).trim();
  }

  async introspectRequest(req: IncomingMessage) {
    const token = this.bearerToken(req);
    if (!token) {
      const snapshot = { active: false, memberships: [] };
      this.requestAuth.set(req, snapshot);
      return snapshot;
    }
    const response = await fetch(`${this.commonBaseUrl()}/internal/auth/introspect`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "x-internal-service-token": this.internalToken()
      }
    });
    const json = await response.json().catch(() => ({}));
    const snapshot = response.ok
      ? json as CommonAuthSnapshot
      : { active: false, memberships: [] };
    this.requestAuth.set(req, snapshot);
    if (snapshot.active && snapshot.user?.id) {
      this.authByUserId.set(snapshot.user.id, snapshot);
    }
    return snapshot;
  }

  authForRequest(req: IncomingMessage) {
    return this.requestAuth.get(req) ?? { active: false, memberships: [] };
  }

  authForUser(userId: string) {
    return this.authByUserId.get(userId);
  }

  async effectiveConfig(projectId: string) {
    const url = new URL(`${this.commonBaseUrl()}/internal/models/effective-config`);
    url.searchParams.set("project_id", projectId);
    const response = await fetch(url, {
      headers: { "x-internal-service-token": this.internalToken() }
    });
    const json = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(`common effective config failed: ${response.status} ${JSON.stringify(json)}`);
    }
    return json as { project_id: string; effective_config?: AppConfig; llm?: Record<string, unknown> };
  }
}
