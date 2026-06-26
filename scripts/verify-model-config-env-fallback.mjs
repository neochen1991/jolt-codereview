import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed\n${result.stdout}\n${result.stderr}`);
  }
}

run("npm", ["run", "build:api"]);

const { ProjectConfigService } = await import("../build/backend/services/ProjectConfigService.js");

const rows = new Map();
const fakeDb = {
  prepare(sql) {
    return {
      all(projectId) {
        if (!/FROM project_settings/i.test(sql)) return [];
        return [...rows.values()].filter((row) => row.project_id === projectId);
      },
      get(projectId, key) {
        if (!/FROM project_settings/i.test(sql)) return undefined;
        const row = rows.get(`${projectId}:${key}`);
        return row ? { key: row.settings_key, settings_json: row.settings_json, updated_at: row.updated_at } : undefined;
      },
      run(_settingId, projectId, key, value) {
        rows.set(`${projectId}:${key}`, {
          project_id: projectId,
          settings_key: key,
          settings_json: value,
          updated_at: "test"
        });
        return { changes: 1 };
      }
    };
  },
  exec() {}
};

const config = {
  llm: {
    default_provider: "dashscope-openai-compatible",
    default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
    default_model: "MiniMax-M2.7",
    default_api_key_env: "MINIMAX_API_KEY",
    request_timeout_seconds: 120
  },
  server: {
    database_driver: "postgres"
  }
};
const service = new ProjectConfigService(fakeDb);
service.upsertSetting("project_default", "llm_policy", {
  default_provider: "dashscope-openai-compatible",
  default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
  default_model: "MiniMax-M2.7",
  default_api_key_env: null,
  default_api_key: "plaintext-runtime-key"
});

const effective = service.effectiveConfig("project_default", config).effective_config;

if (effective.llm?.default_api_key_env !== "MINIMAX_API_KEY") {
  throw new Error(`default_api_key_env fallback failed: ${JSON.stringify(effective.llm)}`);
}
if (effective.llm?.default_api_key !== "plaintext-runtime-key") {
  throw new Error(`default_api_key runtime config failed: ${JSON.stringify(effective.llm)}`);
}

console.log(JSON.stringify({ ok: true, llm: effective.llm }, null, 2));
