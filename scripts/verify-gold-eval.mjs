import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const root = path.resolve(import.meta.dirname, "..");
const tmp = mkdtempSync(path.join(tmpdir(), "jolt-gold-eval-"));

function run(args) {
  const result = spawnSync("python3", args, {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) {
    throw new Error(`python3 ${args.join(" ")} failed with exit ${result.status}`);
  }
}

const syntheticReport = path.join(tmp, "gold-report.json");
const realReport = path.join(tmp, "real-report.json");

run(["scripts/test_score_real_pr_reviews.py"]);
run(["evaluation/run_gold_eval.py", "--out", syntheticReport]);
run(["evaluation/check_thresholds.py", syntheticReport]);
run([
  "scripts/score_real_pr_reviews.py",
  "--gold",
  "evaluation/real_gold_set.jsonl",
  "--findings",
  "evaluation/real_findings.jsonl",
  "--out",
  realReport,
  "--min-precision",
  "0.70",
  "--min-recall",
  "0.60",
  "--max-negative-fp",
  "0",
]);

console.log(JSON.stringify({ ok: true, verified: "gold_eval", synthetic_report: syntheticReport, real_report: realReport }, null, 2));
