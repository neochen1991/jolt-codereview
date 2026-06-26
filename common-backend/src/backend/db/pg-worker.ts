import { parentPort } from "node:worker_threads";
import { Client } from "pg";
import { writeFileSync } from "node:fs";
import { preparePostgresSql } from "./pg-sql.js";

type PgWorkerRequest = {
  id: string;
  shared: SharedArrayBuffer;
  responsePath: string;
  config: {
    connectionString: string;
    user?: string;
    password?: string;
  };
  operation: "query" | "close";
  sql?: string;
  params?: unknown[];
};

let client: Client | null = null;
let connectedKey = "";

async function getClient(config: PgWorkerRequest["config"]) {
  const nextKey = JSON.stringify(config);
  if (client && connectedKey === nextKey) return client;
  if (client) {
    await client.end().catch(() => undefined);
    client = null;
  }
  const nextClient = new Client({
    connectionString: config.connectionString,
    user: config.user || undefined,
    password: config.password || undefined
  });
  await nextClient.connect();
  client = nextClient;
  connectedKey = nextKey;
  return client;
}

async function handleRequest(request: PgWorkerRequest) {
  if (request.operation === "close") {
    if (client) await client.end();
    client = null;
    return { rows: [], rowCount: 0 };
  }
  const activeClient = await getClient(request.config);
  const sql = request.sql || "";
  const result = await activeClient.query(preparePostgresSql(sql), request.params || []);
  return { rows: result.rows, rowCount: result.rowCount ?? 0 };
}

parentPort?.on("message", (request: PgWorkerRequest) => {
  const shared = new Int32Array(request.shared);
  handleRequest(request)
    .then((response) => {
      writeFileSync(request.responsePath, JSON.stringify({ ok: true, ...response }), "utf8");
    })
    .catch((error) => {
      writeFileSync(
        request.responsePath,
        JSON.stringify({
          ok: false,
          error: error instanceof Error ? error.message : String(error)
        }),
        "utf8"
      );
    })
    .finally(() => {
      Atomics.store(shared, 0, 1);
      Atomics.notify(shared, 0, 1);
    });
});
