import { mkdirSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const tmpRoot = path.join(root, "data", "tmp", "model-config-env-fallback");
const dbPath = path.join(tmpRoot, "model.sqlite");

rmSync(tmpRoot, { recursive: true, force: true });
mkdirSync(tmpRoot, { recursive: true });

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed\n${result.stdout}\n${result.stderr}`);
  }
}

run("npm", ["run", "build:api"]);

const { openDatabase } = await import("../build/backend/db.js");
const { ProjectConfigService } = await import("../build/backend/services/ProjectConfigService.js");

const config = {
  llm: {
    default_provider: "dashscope-openai-compatible",
    default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
    default_model: "MiniMax-M2.7",
    default_api_key_env: "MINIMAX_API_KEY",
    request_timeout_seconds: 120
  },
  server: {
    database_path: dbPath,
    database_driver: "sqlite"
  }
};
const db = openDatabase(config);
const service = new ProjectConfigService(db);
service.upsertSetting("project_default", "llm_policy", {
  default_provider: "dashscope-openai-compatible",
  default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
  default_model: "MiniMax-M2.7",
  default_api_key_env: null,
  default_api_key: "plaintext-should-not-be-runtime"
});

const effective = service.effectiveConfig("project_default", config).effective_config;
db.close?.();

if (effective.llm?.default_api_key_env !== "MINIMAX_API_KEY") {
  throw new Error(`default_api_key_env fallback failed: ${JSON.stringify(effective.llm)}`);
}
if ("default_api_key" in (effective.llm ?? {})) {
  throw new Error(`plaintext default_api_key leaked into effective runtime config: ${JSON.stringify(effective.llm)}`);
}

console.log(JSON.stringify({ ok: true, llm: effective.llm }, null, 2));
