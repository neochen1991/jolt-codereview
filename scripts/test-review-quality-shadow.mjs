import { existsSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const output = resolve(tmpdir(), `jolt-shadow-${process.pid}.json`);
const child = spawnSync(process.execPath, [
  resolve(import.meta.dirname, "run-review-quality-shadow.mjs"),
  "--snapshots", resolve(import.meta.dirname, "fixtures/review-quality-shadow-snapshots.jsonl"),
  "--runner", `${process.execPath} ${resolve(import.meta.dirname, "fixtures/review-quality-shadow-runner.mjs")}`,
  "--output", output
], { encoding: "utf8" });
if (child.status !== 0) throw new Error(child.stderr || child.stdout);
if (!existsSync(output)) throw new Error("shadow report missing");
const report = JSON.parse(readFileSync(output, "utf8"));
rmSync(output, { force: true });
if (report.baseline.sample_count !== 2 || report.candidate.sample_count !== 2) throw new Error("shadow engines did not receive identical snapshots");
if (report.baseline.publish_attempt_count !== 0 || report.candidate.publish_attempt_count !== 0) throw new Error("shadow run published side effects");
if (report.candidate.recall <= report.baseline.recall) throw new Error("fixture must expose measurable uplift");
for (let index = 0; index < report.cases.v1.length; index += 1) {
  const baseline = report.cases.v1[index];
  const candidate = report.cases.v2[index];
  if (baseline.execution_kind !== "quality_shadow_v1" || baseline.context_engine !== "v1") throw new Error("baseline execution contract mismatch");
  if (candidate.execution_kind !== "quality_shadow_v2" || candidate.context_engine !== "v2") throw new Error("candidate execution contract mismatch");
  if (baseline.snapshot_sha256 !== candidate.snapshot_sha256) throw new Error("v1/v2 did not use the identical frozen case");
  if (baseline.input_artifact_sha256 !== candidate.input_artifact_sha256) throw new Error("v1/v2 input artifact hashes differ");
}
console.log(JSON.stringify({ ok: true, verified: "review_quality_shadow", sample_count: 2 }));
