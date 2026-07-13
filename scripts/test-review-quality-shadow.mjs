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
console.log(JSON.stringify({ ok: true, verified: "review_quality_shadow", sample_count: 2 }));
