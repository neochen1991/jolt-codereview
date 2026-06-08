import { existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const config = loadConfig();
const dbPath = path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
const mrId = process.env.MR_ID || "mr_repo_github_java_fixture_9101";
const out = path.join(root, "evaluation", "pipeline-report.json");

if (!existsSync(dbPath)) throw new Error(`database not found: ${dbPath}`);
const db = new DatabaseSync(dbPath);
const run = db.prepare(`
  SELECT rr.id
  FROM review_runs rr
  JOIN review_jobs rj ON rj.id = rr.review_job_id
  WHERE rj.merge_request_id = ?
  ORDER BY rr.started_at DESC
  LIMIT 1
`).get(mrId);
db.close();
if (!run) throw new Error(`no pipeline run found for ${mrId}; seed and run worker before pipeline eval`);

execFileSync(
  "python3",
  [
    "evaluation/run_pipeline_eval.py",
    "--db",
    dbPath,
    "--mr-id",
    mrId,
    "--negative",
    "evaluation/negative_gold_set.jsonl",
    "--out",
    out
  ],
  { cwd: root, stdio: "inherit" }
);

const report = JSON.parse(await import("node:fs").then((fs) => fs.readFileSync(out, "utf8")));
if (report.recall < 0.9) throw new Error(`pipeline recall below production target 0.90: ${report.recall}`);
if (report.fp_rate > 0.1) throw new Error(`pipeline fp_rate above production target 0.10: ${report.fp_rate}`);
console.log(JSON.stringify({ ok: true, report_path: out, recall: report.recall, fp_rate: report.fp_rate, agreement_at_5: report.agreement_at_5 }, null, 2));
