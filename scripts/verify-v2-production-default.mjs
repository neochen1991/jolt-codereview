import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (path) => readFileSync(resolve(path), "utf8");
const example = JSON.parse(read("mr-backend/config.example.json"));
const backendConfig = read("mr-backend/src/backend/config.ts");
const backendTypes = read("mr-backend/src/backend/types.ts");
const commonSettings = read("common-backend/src/backend/services/ProjectConfigService.ts");

const quality = example.review_quality || {};
const failures = [];
if (quality.context_engine !== "v2") failures.push("config example context_engine is not v2");
if (quality.quality_shadow_mode !== true) failures.push("config example does not capture real inputs");
if (quality.auto_shadow_baseline !== true) failures.push("config example does not auto-run v1 baseline");
if (quality.auto_rollback_enabled !== true) failures.push("config example does not auto rollback");
if (quality.minimum_distinct_mrs !== 30) failures.push("config example minimum distinct MR count is not 30");
for (const snippet of ["context_engine: \"v2\"", "auto_shadow_baseline: true", "auto_rollback_enabled: true", "minimum_distinct_mrs: 30"]) {
  if (!backendConfig.includes(snippet)) failures.push(`backend default missing ${snippet}`);
}
for (const snippet of ["auto_shadow_baseline?: boolean", "auto_rollback_enabled?: boolean", "minimum_distinct_mrs?: number", "gold_dataset_path?: string"]) {
  if (!backendTypes.includes(snippet)) failures.push(`backend type missing ${snippet}`);
}
if (!commonSettings.includes('"review_quality"')) failures.push("Common project settings do not allow review_quality");
if (failures.length) throw new Error(`v2 production default verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "v2_production_default", quality }));
