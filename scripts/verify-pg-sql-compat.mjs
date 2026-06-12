import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const pgSqlModule = await import(pathToFileURL(path.join(root, "build/backend/db/pg-sql.js")));
const { translateSqliteSchemaToPostgres, translateSqliteToPostgres } = pgSqlModule;

function assertContains(actual, expected) {
  assert.ok(
    actual.includes(expected),
    `Expected SQL to contain:\n${expected}\n\nActual SQL:\n${actual}`
  );
}

const ddl = translateSqliteToPostgres(`
  CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );
`);
assertContains(ddl, "created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)");

const schemaOnly = translateSqliteSchemaToPostgres(`
  CREATE TABLE IF NOT EXISTS legacy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN NOT NULL DEFAULT 1
  );
`);
assertContains(schemaOnly, "id SERIAL PRIMARY KEY");
assertContains(schemaOnly, "occurred_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)");
assertContains(schemaOnly, "active INTEGER NOT NULL DEFAULT 1");

const sessionLookup = translateSqliteToPostgres(`
  SELECT user_id
  FROM auth_sessions
  WHERE token_hash = ?
    AND status = 'active'
    AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
`);
assertContains(sessionLookup, "token_hash = $1");
assertContains(sessionLookup, "expires_at::timestamptz > CURRENT_TIMESTAMP");

const reclaimQueue = translateSqliteToPostgres(`
  UPDATE review_jobs
  SET status = 'queued'
  WHERE status = 'reviewing'
    AND (heartbeat_at IS NULL OR heartbeat_at < datetime('now', ?))
`);
assertContains(reclaimQueue, "heartbeat_at::timestamptz < (CURRENT_TIMESTAMP + $1::interval)");

const healthQuery = translateSqliteToPostgres(`
  SELECT COUNT(*) AS active
  FROM review_jobs rj
  WHERE COALESCE(rj.heartbeat_at, rj.locked_at, rj.updated_at) >= datetime('now', '-60 seconds')
`);
assertContains(
  healthQuery,
  "(COALESCE(rj.heartbeat_at, rj.locked_at, rj.updated_at))::timestamptz >= (CURRENT_TIMESTAMP + INTERVAL '-60 seconds')"
);

const feedbackQuery = translateSqliteToPostgres(`
  SELECT uf.dedupe_hash
  FROM user_feedback uf
  WHERE uf.created_at >= datetime('now', '-90 days')
`);
assertContains(feedbackQuery, "uf.created_at::timestamptz >= (CURRENT_TIMESTAMP + INTERVAL '-90 days')");

console.log("PG SQL compatibility translation checks passed.");
