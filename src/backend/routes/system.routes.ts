import { badRequest, id, route, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";
import { Client } from "pg";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { migrate } from "../db/migrations.js";
import { PostgresSyncDatabase } from "../db/pg-sync.js";

const STORAGE_SETTING_KEY = "storage";

function redactStorageConfig(value: Record<string, unknown>) {
  const password = String(value.postgres_password || "");
  return {
    ...value,
    postgres_password: "",
    postgres_password_has_value: Boolean(password),
    postgres_password_masked: password ? `****${password.slice(-4)}` : ""
  };
}

function storageSetting(ctx: BackendRouteContext) {
  const row = ctx.get<{ settings_json: string; updated_at: string }>(
    "SELECT settings_json, updated_at FROM system_settings WHERE settings_key = ?",
    [STORAGE_SETTING_KEY]
  );
  const saved = row ? JSON.parse(row.settings_json || "{}") as Record<string, unknown> : {};
  const currentDriver = "postgres";
  return {
    current_driver: currentDriver,
    active_postgres_url: ctx.config.server?.postgres_url || "",
    pg_runtime_enabled: true,
    switch_status: saved.switch_status || "not_enabled",
    updated_at: row?.updated_at || null,
    value: redactStorageConfig({
      driver: "postgres",
      postgres_url: saved.postgres_url || ctx.config.server?.postgres_url || "",
      postgres_user: saved.postgres_user || ctx.config.server?.postgres_user || "",
      postgres_password: saved.postgres_password || ctx.config.server?.postgres_password || ""
    })
  };
}

function persistStorageRuntimeConfig(ctx: BackendRouteContext, value: Record<string, unknown>) {
  const configPath = process.env.CONFIG_PATH
    ? path.resolve(process.env.CONFIG_PATH)
    : path.resolve(process.cwd(), "config.json");
  const current = existsSync(configPath)
    ? JSON.parse(readFileSync(configPath, "utf8")) as Record<string, unknown>
    : {};
  const currentServer = (typeof current.server === "object" && current.server ? current.server : {}) as Record<string, unknown>;
  const next = {
    ...current,
    server: {
      ...currentServer,
      database_driver: "postgres",
      postgres_url: value.postgres_url,
      postgres_user: value.postgres_user,
      postgres_password: value.postgres_password,
      postgres_query_timeout_seconds: ctx.config.server?.postgres_query_timeout_seconds ?? currentServer.postgres_query_timeout_seconds ?? 120
    }
  };
  writeFileSync(configPath, `${JSON.stringify(next, null, 2)}\n`, "utf8");
  return configPath;
}

function existingStorageValue(ctx: Pick<BackendRouteContext, "get">) {
  const row = ctx.get<{ settings_json: string }>(
    "SELECT settings_json FROM system_settings WHERE settings_key = ?",
    [STORAGE_SETTING_KEY]
  );
  return row ? JSON.parse(row.settings_json || "{}") as Record<string, unknown> : {};
}

function textValue(value: unknown) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

export function pgConnectionConfig(input: Record<string, unknown>) {
  const connectionString = textValue(input.postgres_url);
  const user = textValue(input.postgres_user);
  const password = textValue(input.postgres_password);
  return {
    ...(connectionString ? { connectionString } : {}),
    ...(user ? { user } : {}),
    ...(password ? { password } : {})
  };
}

export function effectivePostgresStorageInput(
  ctx: Pick<BackendRouteContext, "config" | "get">,
  input: Record<string, unknown>
) {
  const existing = existingStorageValue(ctx);
  const typedPassword = textValue(input.postgres_password);
  const maskedPassword = textValue(input.postgres_password_masked);
  const hasSavedPasswordMarker = Boolean(input.postgres_password_has_value);
  const savedPassword = textValue(existing.postgres_password) || textValue(ctx.config.server?.postgres_password);
  const passwordLooksMasked = Boolean(maskedPassword) && typedPassword === maskedPassword && hasSavedPasswordMarker;
  const postgresPassword = typedPassword && !passwordLooksMasked ? typedPassword : savedPassword;
  return {
    ...input,
    postgres_url: textValue(input.postgres_url),
    postgres_user: textValue(input.postgres_user),
    postgres_password: postgresPassword
  };
}

async function withPgClient<T>(input: Record<string, unknown>, fn: (client: Client) => Promise<T>) {
  const client = new Client(pgConnectionConfig(input));
  await client.connect();
  try {
    return await fn(client);
  } finally {
    await client.end().catch(() => undefined);
  }
}

async function initializePostgresSchema(ctx: BackendRouteContext, input: Record<string, unknown>) {
  const db = new PostgresSyncDatabase({
    ...ctx.config,
    server: {
      ...ctx.config.server,
      database_driver: "postgres",
      postgres_url: String(input.postgres_url || ""),
      postgres_user: String(input.postgres_user || ""),
      postgres_password: String(input.postgres_password || "")
    }
  });
  try {
    migrate(db);
    db.exec(`
      CREATE TABLE IF NOT EXISTS jolt_schema_migrations (
        id TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
      );
      INSERT INTO jolt_schema_migrations (id) VALUES ('postgres_schema_v1') ON CONFLICT (id) DO NOTHING;
    `);
    return { initialized: true };
  } finally {
    db.close();
  }
}

export function createSystemRoutes(ctx: BackendRouteContext): Route[] {
  const { auditLog, currentUserId, ensureRoot } = ctx;
  return [
    route("GET", "/api/system/storage", ({ req }) => {
      const actorId = currentUserId(req);
      const denied = ensureRoot(actorId);
      if (denied) return denied;
      return storageSetting(ctx);
    }),
    route("POST", "/api/system/storage/test", async ({ body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureRoot(actorId);
      if (denied) return denied;
      const input = (typeof body === "object" && body ? body : {}) as Record<string, unknown>;
      if (!String(input.postgres_url || "").trim()) {
        return { ok: false, driver: "postgres", status: "not_configured", message: "PostgreSQL 连接串不能为空" };
      }
      try {
        const effectiveInput = effectivePostgresStorageInput(ctx, input);
        const started = Date.now();
        await withPgClient(effectiveInput, async (client) => client.query("SELECT 1 AS ok"));
        return {
          ok: true,
          driver: "postgres",
          status: "available",
          latency_ms: Date.now() - started,
          message: "PostgreSQL 连接成功。"
        };
      } catch (error) {
        return {
          ok: false,
          driver: "postgres",
          status: "connection_failed",
          message: error instanceof Error ? error.message : String(error)
        };
      }
    }),
    route("POST", "/api/system/storage/init-postgres", async ({ body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureRoot(actorId);
      if (denied) return denied;
      const input = (typeof body === "object" && body ? body : {}) as Record<string, unknown>;
      if (!String(input.postgres_url || "").trim()) return badRequest("postgres_url is required");
      try {
        const result = await initializePostgresSchema(ctx, effectivePostgresStorageInput(ctx, input));
        auditLog({
          userId: actorId,
          action: "system.storage.init_postgres",
          resourceType: "system_settings",
          resourceId: STORAGE_SETTING_KEY,
          summary: "initialized PostgreSQL schema",
          metadata: result
        });
        return { ok: true, ...result, message: "PostgreSQL 表结构初始化完成。" };
      } catch (error) {
        return {
          ok: false,
          error: "postgres_init_failed",
          message: error instanceof Error ? error.message : String(error)
        };
      }
    }),
    route("POST", "/api/system/storage/switch", ({ body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureRoot(actorId);
      if (denied) return denied;
      const input = (typeof body === "object" && body ? body : {}) as Record<string, unknown>;
      const effectiveInput = effectivePostgresStorageInput(ctx, input);
      const value = {
        driver: "postgres",
        postgres_url: String(effectiveInput.postgres_url || "").trim(),
        postgres_user: String(effectiveInput.postgres_user || "").trim(),
        postgres_password: String(effectiveInput.postgres_password || "").trim(),
        switch_status: "pg_enabled_restart_required"
      };
      const persistedConfigPath = persistStorageRuntimeConfig(ctx, value);
      ctx.db.prepare(`
        INSERT INTO system_settings (id, settings_key, settings_json, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(settings_key) DO UPDATE SET
          settings_json = excluded.settings_json,
          updated_at = CURRENT_TIMESTAMP
      `).run(id("sys_setting"), STORAGE_SETTING_KEY, JSON.stringify(value));
      auditLog({
        userId: actorId,
        action: "system.storage.update",
        resourceType: "system_settings",
        resourceId: STORAGE_SETTING_KEY,
        summary: "storage target=postgres",
        metadata: { driver: "postgres", switch_status: value.switch_status, persisted_config_path: persistedConfigPath }
      });
      return { ...storageSetting(ctx), persisted_config_path: persistedConfigPath, message: "数据库目标配置已保存到 config.json，重启服务后生效。" };
    })
  ];
}
