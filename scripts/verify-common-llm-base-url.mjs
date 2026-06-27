import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const source = readFileSync(path.join(root, "common-backend/src/backend/services/LlmConnectivityService.ts"), "utf8");

const forbidden = [
  "LLM base url must use https",
  "LLM base url cannot target localhost or private network hosts",
  "JOLT_ALLOW_PRIVATE_LLM_BASE_URLS",
  "isPrivateIpv4("
];

const required = [
  'parsed.protocol !== "http:" && parsed.protocol !== "https:"',
  "LLM base url must use http or https"
];

const failures = [
  ...forbidden.filter((pattern) => source.includes(pattern)).map((pattern) => ({ forbidden: pattern })),
  ...required.filter((pattern) => !source.includes(pattern)).map((pattern) => ({ missing: pattern }))
];

if (failures.length) {
  throw new Error(`Common LLM base URL verification failed:\n${JSON.stringify(failures, null, 2)}`);
}

console.log(JSON.stringify({ ok: true }, null, 2));
