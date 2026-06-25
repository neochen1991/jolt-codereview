import type { AppConfig } from "../types.js";
import { migrate } from "./migrations.js";
import type { Db } from "./pg-sync.js";
import { PostgresSyncDatabase } from "./pg-sync.js";
import { seed } from "./seed.js";

export type { Db } from "./pg-sync.js";

export function openDatabase(config: AppConfig): Db {
  const driver = String(config.server?.database_driver || "postgres").trim().toLowerCase();
  if (driver && driver !== "postgres") {
    throw new Error(`Unsupported database driver: ${driver}. Jolt services are PostgreSQL-only.`);
  }
  const db = new PostgresSyncDatabase(config);
  migrate(db);
  seed(db);
  return db;
}
