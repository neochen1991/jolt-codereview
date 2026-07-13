import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

function option(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}
function percentile(values, percentileValue) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * percentileValue) - 1)];
}
function summarize(engine, rows) {
  const truth = rows.reduce((sum, row) => sum + Number(row.expected_count || 0), 0);
  const found = rows.reduce((sum, row) => sum + Number(row.true_positive_count || 0), 0);
  const output = rows.reduce((sum, row) => sum + Number(row.finding_count || 0), 0);
  const crossTruth = rows.reduce((sum, row) => sum + Number(row.cross_file_expected_count || 0), 0);
  const crossFound = rows.reduce((sum, row) => sum + Number(row.cross_file_true_positive_count || 0), 0);
  return {
    engine,
    sample_count: rows.length,
    precision: output ? found / output : null,
    recall: truth ? found / truth : null,
    cross_file_recall: crossTruth ? crossFound / crossTruth : null,
    critical_high_recall: (() => { const expected = rows.reduce((s, r) => s + Number(r.critical_high_expected_count || 0), 0); const hit = rows.reduce((s, r) => s + Number(r.critical_high_true_positive_count || 0), 0); return expected ? hit / expected : null; })(),
    negative_false_positive_count: rows.reduce((sum, row) => sum + Number(row.negative_false_positive_count || 0), 0),
    p95_tokens: percentile(rows.map((row) => Number(row.tokens || 0)), 0.95),
    p95_duration_ms: percentile(rows.map((row) => Number(row.duration_ms || 0)), 0.95),
    publish_attempt_count: rows.reduce((sum, row) => sum + Number(row.publish_attempt_count || 0), 0)
  };
}

const snapshotsPath = option("--snapshots");
const runner = option("--runner");
const stage = option("--stage") || "internal_10";
const allowedStages = ["internal_10", "internal_30", "internal_100", "external_10", "full"];
if (!allowedStages.includes(stage)) throw new Error(`unsupported rollout stage: ${stage}`);
const outputPath = resolve(option("--output") || "review-quality-shadow-report.json");
if (!snapshotsPath || !runner) throw new Error("usage: --snapshots frozen.jsonl --runner <command> [--output report.json]");
const snapshots = readFileSync(resolve(snapshotsPath), "utf8").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
const results = { v1: [], v2: [] };
for (const snapshot of snapshots) {
  if (!snapshot.head_sha || !snapshot.input_artifact_sha256) throw new Error("every shadow case requires frozen head_sha and input_artifact_sha256");
  for (const engine of ["v1", "v2"]) {
    const input = JSON.stringify({ ...snapshot, execution_kind: "quality_shadow", context_engine: engine, publish_allowed: false });
    const child = spawnSync(runner, { shell: true, input, encoding: "utf8", env: { ...process.env, JOLT_QUALITY_SHADOW: "1", JOLT_CONTEXT_ENGINE: engine, JOLT_PUBLISH_ALLOWED: "0" } });
    if (child.status !== 0) throw new Error(`${engine} shadow runner failed: ${child.stderr || child.stdout}`);
    const row = JSON.parse(String(child.stdout || "{}").trim());
    if (Number(row.publish_attempt_count || 0) !== 0) throw new Error(`${engine} shadow run attempted a production publish`);
    results[engine].push({ ...row, snapshot_sha256: createHash("sha256").update(input).digest("hex") });
  }
}
const report = { schema_version: "review_quality_shadow_v1", rollout_stage: stage, minimum_valid_mrs: 30, stage_ready_for_gate: snapshots.length >= 30, generated_at: new Date().toISOString(), baseline: summarize("v1", results.v1), candidate: summarize("v2", results.v2), cases: results };
writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ ok: true, output: outputPath, sample_count: snapshots.length }));
