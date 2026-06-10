import { mkdirSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { AppConfig } from "../types.js";
import { migrate } from "./migrations.js";
import { seed } from "./seed.js";

export type Db = DatabaseSync;

export function openDatabase(config: AppConfig): Db {
  const dbPath = path.resolve(process.cwd(), config.server?.database_path ?? "data/jolt-codereview.sqlite");
  mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec("PRAGMA journal_mode = WAL");
  db.exec("PRAGMA busy_timeout = 5000");
  migrate(db);
  seed(db);
  return db;
}
