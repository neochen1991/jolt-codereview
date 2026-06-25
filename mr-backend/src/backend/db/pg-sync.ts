import { mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Worker } from "node:worker_threads";
import type { AppConfig } from "../types.js";
import { splitSqlStatements } from "./pg-sql.js";

export type DbRunResult = {
  changes: number;
  lastInsertRowid?: number | bigint;
};

export type DbStatement = {
  get(...params: unknown[]): unknown;
  all(...params: unknown[]): unknown[];
  run(...params: unknown[]): DbRunResult;
};

export type Db = {
  exec(sql: string): void;
  prepare(sql: string): DbStatement;
  close?(): void;
};

type PgResponse = {
  ok: boolean;
  rows?: unknown[];
  rowCount?: number;
  error?: string;
};

export class PostgresSyncDatabase implements Db {
  private readonly worker: Worker;
  private readonly timeoutMs: number;
  private readonly connectionConfig: { connectionString: string; user?: string; password?: string };
  private readonly responseDir: string;

  constructor(config: AppConfig) {
    const serverConfig = config.server || {};
    const connectionString = String(serverConfig.postgres_url || "").trim();
    if (!connectionString) {
      throw new Error("PostgreSQL is enabled but server.postgres_url is empty.");
    }
    this.timeoutMs = Math.max(1, Number(serverConfig.postgres_query_timeout_seconds ?? 30)) * 1000;
    this.connectionConfig = {
      connectionString,
      user: serverConfig.postgres_user || undefined,
      password: serverConfig.postgres_password || undefined
    };
    this.responseDir = path.join(tmpdir(), "jolt-codereview-pg");
    mkdirSync(this.responseDir, { recursive: true });
    this.worker = new Worker(new URL("./pg-worker.js", import.meta.url));
  }

  exec(sql: string): void {
    for (const statement of splitSqlStatements(sql)) {
      this.query(statement, []);
    }
  }

  prepare(sql: string): DbStatement {
    return {
      get: (...params: unknown[]) => this.query(sql, params)[0],
      all: (...params: unknown[]) => this.query(sql, params),
      run: (...params: unknown[]) => {
        const response = this.queryWithMetadata(sql, params);
        return { changes: Number(response.rowCount || 0), lastInsertRowid: 0 };
      }
    };
  }

  close(): void {
    this.queryWithMetadata("SELECT 1", [], "close");
    this.worker.terminate();
  }

  private query(sql: string, params: unknown[]) {
    const response = this.queryWithMetadata(sql, params);
    return response.rows || [];
  }

  private queryWithMetadata(sql: string, params: unknown[], operation: "query" | "close" = "query"): PgResponse {
    const id = randomUUID();
    const shared = new SharedArrayBuffer(4);
    const state = new Int32Array(shared);
    const responsePath = path.join(this.responseDir, `${id}.json`);
    this.worker.postMessage({
      id,
      shared,
      responsePath,
      config: this.connectionConfig,
      operation,
      sql,
      params
    });
    const waitResult = Atomics.wait(state, 0, 0, this.timeoutMs);
    if (waitResult === "timed-out") {
      throw new Error(`PostgreSQL query timed out after ${this.timeoutMs}ms: ${sql.slice(0, 160)}`);
    }
    const response = JSON.parse(readFileSync(responsePath, "utf8")) as PgResponse;
    rmSync(responsePath, { force: true });
    if (!response.ok) {
      throw new Error(response.error || "PostgreSQL query failed");
    }
    return response;
  }
}
