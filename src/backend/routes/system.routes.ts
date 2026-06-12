import { badRequest, id, route, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";
import { Client } from "pg";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { translateSqliteSchemaToPostgres } from "../db/pg-sql.js";

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
  const currentDriver = ctx.config.server?.database_driver || "sqlite";
  return {
    current_driver: currentDriver,
    active_database_path: ctx.config.server?.database_path || "data/jolt-codereview.sqlite",
    pg_runtime_enabled: true,
    switch_status: saved.switch_status || "not_enabled",
    updated_at: row?.updated_at || null,
    value: redactStorageConfig({
      driver: saved.driver || currentDriver,
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
      database_driver: value.driver,
      postgres_url: value.postgres_url,
      postgres_user: value.postgres_user,
      postgres_password: value.postgres_password,
      postgres_query_timeout_seconds: ctx.config.server?.postgres_query_timeout_seconds ?? currentServer.postgres_query_timeout_seconds ?? 120
    }
  };
  writeFileSync(configPath, `${JSON.stringify(next, null, 2)}\n`, "utf8");
  return configPath;
}

function existingStorageValue(ctx: BackendRouteContext) {
  const row = ctx.get<{ settings_json: string }>(
    "SELECT settings_json FROM system_settings WHERE settings_key = ?",
    [STORAGE_SETTING_KEY]
  );
  return row ? JSON.parse(row.settings_json || "{}") as Record<string, unknown> : {};
}

function pgConnectionConfig(input: Record<string, unknown>) {
  const connectionString = String(input.postgres_url || "").trim();
  const user = String(input.postgres_user || "").trim();
  const password = String(input.postgres_password || "").trim();
  return {
    ...(connectionString ? { connectionString } : {}),
    ...(user ? { user } : {}),
    ...(password ? { password } : {})
  };
}

function sqliteSchemaStatements(ctx: BackendRouteContext) {
  const tables = ctx.all<{ name: string; sql: string }>(`
    SELECT name, sql
    FROM sqlite_master
    WHERE type = 'table'
      AND name NOT LIKE 'sqlite_%'
      AND sql IS NOT NULL
    ORDER BY name
  `);
  const indexes = ctx.all<{ name: string; sql: string }>(`
    SELECT name, sql
    FROM sqlite_master
    WHERE type = 'index'
      AND name NOT LIKE 'sqlite_%'
      AND sql IS NOT NULL
    ORDER BY name
  `);
  return [...tables, ...indexes].map((row) => translateSqliteSchemaToPostgres(row.sql));
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
  const statements = sqliteSchemaStatements(ctx);
  return withPgClient(input, async (client) => {
    await client.query("BEGIN");
    try {
      for (const statement of statements) {
        await client.query(statement);
      }
      await client.query(`
        CREATE TABLE IF NOT EXISTS jolt_schema_migrations (
          id TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
      `);
      await client.query(
        "INSERT INTO jolt_schema_migrations (id) VALUES ($1) ON CONFLICT (id) DO NOTHING",
        ["sqlite_schema_snapshot_v1"]
      );
      await client.query("COMMIT");
      return { initialized_tables: statements.filter((item) => /^CREATE TABLE/i.test(item)).length, initialized_indexes: statements.filter((item) => /^CREATE .*INDEX/i.test(item)).length };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    }
  });
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
      const driver = String(input.driver || "sqlite");
      if (!["sqlite", "postgres"].includes(driver)) return badRequest("driver must be sqlite or postgres");
      if (driver === "postgres" && !String(input.postgres_url || "").trim()) {
        return { ok: false, driver, status: "not_configured", message: "PostgreSQL 连接串不能为空" };
      }
      if (driver === "postgres") {
        try {
          const started = Date.now();
          await withPgClient(input, async (client) => client.query("SELECT 1 AS ok"));
          return {
            ok: true,
            driver,
            status: "available",
            latency_ms: Date.now() - started,
            message: "PostgreSQL 连接成功。"
          };
        } catch (error) {
          return {
            ok: false,
            driver,
            status: "connection_failed",
            message: error instanceof Error ? error.message : String(error)
          };
        }
      }
      return {
        ok: driver === "sqlite",
        driver,
        status: "available",
        message: "当前运行时使用 SQLite，可继续运行。"
      };
    }),
    route("POST", "/api/system/storage/init-postgres", async ({ body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureRoot(actorId);
      if (denied) return denied;
      const input = (typeof body === "object" && body ? body : {}) as Record<string, unknown>;
      if (!String(input.postgres_url || "").trim()) return badRequest("postgres_url is required");
      try {
        const result = await initializePostgresSchema(ctx, input);
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
      const existing = existingStorageValue(ctx);
      const driver = String(input.driver || "sqlite");
      if (!["sqlite", "postgres"].includes(driver)) return badRequest("driver must be sqlite or postgres");
      const value = {
        driver,
        postgres_url: String(input.postgres_url || "").trim(),
        postgres_user: String(input.postgres_user || "").trim(),
        postgres_password: String(input.postgres_password || "").trim() || String(existing.postgres_password || ""),
        switch_status: driver === "postgres" ? "pg_enabled_restart_required" : "sqlite_enabled_restart_required"
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
        summary: `storage target=${driver}`,
        metadata: { driver, switch_status: value.switch_status, persisted_config_path: persistedConfigPath }
      });
      return { ...storageSetting(ctx), persisted_config_path: persistedConfigPath, message: "数据库目标配置已保存到 config.json，重启服务后生效。" };
    })
  ];
}
