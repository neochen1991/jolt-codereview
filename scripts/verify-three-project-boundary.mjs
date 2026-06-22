import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const runId = `${process.pid}_${Date.now()}`;
const tmpRoot = path.join(root, "data", "tmp", `three-project-boundary-${runId}`);
const configPath = path.join(tmpRoot, "config.json");
const commonPort = Number(process.env.THREE_PROJECT_COMMON_PORT || 18110);
const mrPort = Number(process.env.THREE_PROJECT_MR_PORT || 18111);
const host = "127.0.0.1";

rmSync(tmpRoot, { recursive: true, force: true });
mkdirSync(tmpRoot, { recursive: true });
writeFileSync(
  configPath,
  JSON.stringify(
    {
      server: {
        host,
        port: mrPort,
        common_port: commonPort,
        mr_port: mrPort,
        database_path: path.join(tmpRoot, "boundary.sqlite")
      },
      logging: {
        enabled: false
      }
    },
    null,
    2
  ),
  "utf8"
);

function run(command, args, extraEnv = {}) {
  const result = spawnSync(command, args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, ...extraEnv } });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed\n${result.stdout}\n${result.stderr}`);
  }
}

async function waitForJson(url, attempts = 80) {
  let lastError;
  for (let index = 0; index < attempts; index += 1) {
    try {
      const response = await fetch(url);
      const json = await response.json();
      return { status: response.status, json };
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  throw lastError ?? new Error(`Timed out waiting for ${url}`);
}

async function jsonStatus(url) {
  const response = await fetch(url);
  let json = {};
  try {
    json = await response.json();
  } catch {
    json = {};
  }
  return { status: response.status, json };
}

run("npm", ["run", "build:api"]);
run(process.execPath, [
  "--input-type=module",
  "-e",
  "const { loadConfig } = await import('./build/backend/config.js'); const { openDatabase } = await import('./build/backend/db.js'); const db = openDatabase(loadConfig()); db.close?.();"
], { CONFIG_PATH: configPath });

const env = {
  ...process.env,
  CONFIG_PATH: configPath,
  JOLT_INTERNAL_SERVICE_TOKEN: "boundary-test-token"
};
const children = [];

const output = [];

function startServer(entrypoint) {
  const child = spawn(process.execPath, [entrypoint], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
  children.push(child);
  child.stdout.on("data", (chunk) => output.push(String(chunk)));
  child.stderr.on("data", (chunk) => output.push(String(chunk)));
  return child;
}

try {
  startServer("build/backend/common-server.js");
  const commonHealth = await waitForJson(`http://${host}:${commonPort}/api/health`);
  startServer("build/backend/mr-server.js");
  const mrHealth = await waitForJson(`http://${host}:${mrPort}/api/health`);
  if (commonHealth.json.service !== "jolt-common-backend") {
    throw new Error(`common health service mismatch: ${JSON.stringify(commonHealth.json)}`);
  }
  if (mrHealth.json.service !== "jolt-mr-backend") {
    throw new Error(`mr health service mismatch: ${JSON.stringify(mrHealth.json)}`);
  }

  const commonSession = await jsonStatus(`http://${host}:${commonPort}/api/auth/session`);
  if (commonSession.status !== 200) throw new Error(`common auth session failed: ${commonSession.status}`);

  const commonPermissions = await jsonStatus(`http://${host}:${commonPort}/api/permissions/roles`);
  if (commonPermissions.status !== 200) throw new Error(`common permissions roles failed: ${commonPermissions.status}`);
  if (!Array.isArray(commonPermissions.json.project_roles)) {
    throw new Error(`common permissions roles contract mismatch: ${JSON.stringify(commonPermissions.json)}`);
  }

  const commonMr = await jsonStatus(`http://${host}:${commonPort}/api/mr-review/projects/project_default/merge-requests`);
  if (commonMr.status !== 404) throw new Error(`common backend should not expose mr-review routes: ${commonMr.status}`);

  const mrSession = await jsonStatus(`http://${host}:${mrPort}/api/auth/session`);
  if (mrSession.status !== 404) throw new Error(`mr backend should not expose auth routes: ${mrSession.status}`);

  const mrPermissions = await jsonStatus(`http://${host}:${mrPort}/api/permissions/roles`);
  if (mrPermissions.status !== 404) throw new Error(`mr backend should not expose permissions routes: ${mrPermissions.status}`);

  const mrList = await jsonStatus(`http://${host}:${mrPort}/api/mr-review/projects/project_default/merge-requests`);
  if (mrList.status !== 200) throw new Error(`mr backend list route failed: ${mrList.status}`);

  const modelConfig = await jsonStatus(`http://${host}:${commonPort}/internal/models/effective-config?project_id=project_default`);
  if (modelConfig.status !== 401) throw new Error(`internal model route should require service token: ${modelConfig.status}`);

  const authedModelConfig = await fetch(`http://${host}:${commonPort}/internal/models/effective-config?project_id=project_default`, {
    headers: { "x-internal-service-token": "boundary-test-token" }
  });
  const modelJson = await authedModelConfig.json();
  if (!authedModelConfig.ok) throw new Error(`internal model route failed: ${JSON.stringify(modelJson)}`);
  if ("default_api_key" in (modelJson.llm ?? {})) throw new Error("internal model route leaked default_api_key");

  console.log(JSON.stringify({
    common: commonHealth.json,
    mr: mrHealth.json,
    route_boundary: "ok",
    permissions_contract: commonPermissions.json,
    model_contract: modelJson
  }, null, 2));
} finally {
  for (const child of children) {
    if (!child.killed) child.kill();
  }
  await new Promise((resolve) => setTimeout(resolve, 150));
  if (process.env.DEBUG_THREE_PROJECT_BOUNDARY) {
    console.error(output.join(""));
  }
}
