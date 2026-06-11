import { mkdirSync } from "node:fs";
import path from "node:path";
import { DatabaseSync, type SQLInputValue } from "node:sqlite";
import type { AppConfig } from "../types.js";
import { migrate } from "./migrations.js";
import type { Db, DbRunResult, DbStatement } from "./pg-sync.js";
import { PostgresSyncDatabase } from "./pg-sync.js";
import { seed } from "./seed.js";

class SqliteDatabase implements Db {
  constructor(private readonly db: DatabaseSync) {}

  exec(sql: string): void {
    this.db.exec(sql);
  }

  prepare(sql: string): DbStatement {
    const statement = this.db.prepare(sql);
    return {
      get: (...params: unknown[]) => statement.get(...(params as SQLInputValue[])),
      all: (...params: unknown[]) => statement.all(...(params as SQLInputValue[])),
      run: (...params: unknown[]) => statement.run(...(params as SQLInputValue[])) as DbRunResult
    };
  }

  close(): void {
    this.db.close();
  }
}

export type { Db } from "./pg-sync.js";

export function openDatabase(config: AppConfig): Db {
  const driver = String(config.server?.database_driver || "sqlite").trim().toLowerCase();
  if (driver === "postgres") {
    const db = new PostgresSyncDatabase(config);
    migrate(db);
    seed(db);
    return db;
  }
  if (driver && driver !== "sqlite") {
    throw new Error(`Unsupported database driver: ${driver}`);
  }
  const dbPath = path.resolve(process.cwd(), config.server?.database_path ?? "data/jolt-codereview.sqlite");
  mkdirSync(path.dirname(dbPath), { recursive: true });
  const sqlite = new SqliteDatabase(new DatabaseSync(dbPath));
  sqlite.exec("PRAGMA journal_mode = WAL");
  sqlite.exec("PRAGMA busy_timeout = 5000");
  migrate(sqlite);
  seed(sqlite);
  return sqlite;
}
