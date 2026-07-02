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

export type CommonEffectiveConfigResponse = {
  project_id: string;
  effective_config?: AppConfig & { vcs_policy?: Record<string, unknown> };
  llm?: Record<string, unknown>;
  source?: {
    project_settings?: Record<string, Record<string, unknown>>;
  };
};

function mergeObject<T extends Record<string, unknown>>(base: T | undefined, override: Record<string, unknown> | undefined): T | undefined {
  if (!override || Object.keys(override).length === 0) return base;
  return { ...(base ?? {}), ...override } as T;
}

function applyVcsPolicy(config: AppConfig, vcsPolicy: Record<string, unknown>) {
  const next: AppConfig = { ...config };
  if (vcsPolicy.github_token || vcsPolicy.github_token_env || vcsPolicy.github_endpoint) {
    next.github = {
      ...(next.github ?? {}),
      ...(vcsPolicy.github_token ? { default_token: vcsPolicy.github_token as string } : {}),
      ...(vcsPolicy.github_token_env ? { default_token_env: vcsPolicy.github_token_env as string } : {}),
      ...(vcsPolicy.github_endpoint ? { default_endpoint: vcsPolicy.github_endpoint as string } : {})
    };
  }
  if (vcsPolicy.codehub_token || vcsPolicy.codehub_token_env || vcsPolicy.codehub_endpoint) {
    next.codehub = {
      ...(next.codehub ?? {}),
      ...(vcsPolicy.codehub_token ? { default_token: vcsPolicy.codehub_token as string } : {}),
      ...(vcsPolicy.codehub_token_env ? { default_token_env: vcsPolicy.codehub_token_env as string } : {}),
      ...(vcsPolicy.codehub_endpoint ? { default_endpoint: vcsPolicy.codehub_endpoint as string } : {})
    };
  }
  return next;
}

export class CommonBackendClient {
  private readonly requestAuth = new WeakMap<IncomingMessage, CommonAuthSnapshot>();
  private readonly authByUserId = new Map<string, CommonAuthSnapshot>();
  private readonly effectiveConfigCache = new Map<string, { expiresAt: number; value: AppConfig }>();

  constructor(private readonly config: AppConfig) {}

  commonBaseUrl() {
    const envBase = String(process.env.COMMON_API_BASE || process.env.VITE_COMMON_API_BASE || "").trim();
    if (envBase) return envBase.replace(/\/+$/, "");
    const host = this.config.server?.host ?? "127.0.0.1";
    const port = this.config.server?.common_port ?? 9022;
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
    return json as CommonEffectiveConfigResponse;
  }

  async projectEffectiveConfig(projectId: string) {
    const cacheKey = projectId || "project_default";
    const cached = this.effectiveConfigCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.value;
    }
    const response = await this.effectiveConfig(projectId);
    const settings = response.source?.project_settings ?? {};
    let next: AppConfig = {
      ...this.config,
      llm: mergeObject(this.config.llm, response.llm ?? response.effective_config?.llm)
    };
    for (const [key, value] of Object.entries(settings)) {
      if (!value || Object.keys(value).length === 0) continue;
      if (key === "llm_policy") {
        next = { ...next, llm: mergeObject(next.llm, value) };
      } else if (key === "vcs_policy") {
        next = applyVcsPolicy(next, value);
      } else {
        const current = (next as Record<string, unknown>)[key];
        (next as Record<string, unknown>)[key] =
          current && typeof current === "object" && !Array.isArray(current)
            ? { ...(current as Record<string, unknown>), ...value }
            : value;
      }
    }
    this.effectiveConfigCache.set(cacheKey, { expiresAt: Date.now() + 30000, value: next });
    return next;
  }
}
