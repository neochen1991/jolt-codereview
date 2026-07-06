import { writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "pg";
import { loadConfig, root } from "./config-utils.mjs";

function parseArgs(argv) {
  const args = {
    configPath: process.env.CONFIG_PATH || process.env.MR_CONFIG_PATH || path.join(root, "mr-backend", "config.json"),
    out: path.join(root, "evaluation", "real_findings.jsonl"),
    projectId: process.env.PROJECT_ID || "",
    includeAllMrs: false,
    pretty: false
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--config") args.configPath = path.resolve(argv[++i]);
    else if (arg === "--out") args.out = path.resolve(argv[++i]);
    else if (arg === "--project-id") args.projectId = argv[++i];
    else if (arg === "--include-all-mrs") args.includeAllMrs = true;
    else if (arg === "--pretty") args.pretty = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function postgresConfig(config) {
  const server = config.server || {};
  const connectionString = process.env.POSTGRES_URL || process.env.DATABASE_URL || server.postgres_url || "";
  if (connectionString) return { connectionString };
  return {
    host: server.postgres_host || "127.0.0.1",
    port: Number(server.postgres_port || 5432),
    database: server.postgres_database || server.postgres_db || "jolt_codereview",
    user: process.env.POSTGRES_USER || server.postgres_user || "",
    password: process.env.POSTGRES_PASSWORD || server.postgres_password || ""
  };
}

function parseJson(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(String(value));
  } catch {
    return fallback;
  }
}

function arrayJson(value) {
  const parsed = parseJson(value, []);
  return Array.isArray(parsed) ? parsed : [];
}

function objectJson(value) {
  const parsed = parseJson(value, {});
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
}

function numberOrNull(value) {
  if (value === undefined || value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function normalizeFindingRow(row) {
  const qualityTrace = objectJson(row.quality_trace_json);
  const evidenceScore = objectJson(row.evidence_score_json || JSON.stringify(qualityTrace.evidence_score || {}));
  if (Object.keys(evidenceScore).length && !qualityTrace.evidence_score) {
    qualityTrace.evidence_score = evidenceScore;
  }
  if (!qualityTrace.consensus_agents && Array.isArray(evidenceScore.consensus_agents)) {
    qualityTrace.consensus_agents = evidenceScore.consensus_agents;
  }
  const toolProvenance = arrayJson(row.tool_provenance_json);
  const sourceObservations = arrayJson(row.source_observations_json);
  const coveredRules = arrayJson(row.covered_rules_json);
  return {
    mr_id: String(row.merge_request_id || row.mr_id || ""),
    merge_request_id: String(row.merge_request_id || row.mr_id || ""),
    review_run_id: String(row.review_run_id || ""),
    finding_id: String(row.finding_id || row.id || ""),
    agent_id: String(row.agent_id || ""),
    severity: String(row.severity || ""),
    confidence: Number(row.confidence ?? 0),
    file_path: String(row.file_path || ""),
    line_start: numberOrNull(row.line_start),
    line_end: numberOrNull(row.line_end),
    title: String(row.title || ""),
    problem_description: String(row.problem_description || ""),
    evidence: String(row.evidence || ""),
    recommendation: String(row.recommendation || ""),
    suggested_code: String(row.suggested_code || ""),
    covered_rules: coveredRules,
    skipped_rules: arrayJson(row.skipped_rules_json),
    tool_provenance: toolProvenance,
    source_observations: sourceObservations,
    quality_trace: qualityTrace,
    real_pr_fixture_id: objectJson(row.mr_metadata_json).real_pr_fixture_id || null
  };
}

function exportSql(includeAllMrs) {
  const realMrFilter = includeAllMrs ? "" : "AND mr.metadata_json LIKE '%real_pr_fixture_id%'";
  return `
    WITH candidate_mrs AS (
      SELECT mr.*, r.project_id
      FROM merge_requests mr
      JOIN repositories r ON r.id = mr.repository_id
      WHERE ($1::text = '' OR r.project_id = $1)
        ${realMrFilter}
    ),
    latest_runs AS (
      SELECT DISTINCT ON (rj.merge_request_id)
        rj.merge_request_id,
        rr.id AS review_run_id,
        rr.started_at
      FROM review_jobs rj
      JOIN review_runs rr ON rr.review_job_id = rj.id
      JOIN candidate_mrs cmr ON cmr.id = rj.merge_request_id
      WHERE rr.status IN ('completed', 'succeeded', 'success', 'done')
      ORDER BY rj.merge_request_id, rr.started_at DESC
    )
    SELECT
      rf.id AS finding_id,
      lr.merge_request_id,
      lr.review_run_id,
      cmr.metadata_json AS mr_metadata_json,
      rf.agent_id,
      rf.severity,
      rf.confidence,
      rf.file_path,
      rf.line_start,
      rf.line_end,
      rf.title,
      rf.problem_description,
      rf.evidence,
      rf.recommendation,
      rf.suggested_code,
      rf.covered_rules_json,
      rf.skipped_rules_json,
      rf.tool_provenance_json,
      rf.source_observations_json,
      rf.quality_trace_json,
      rf.evidence_score_json
    FROM latest_runs lr
    JOIN candidate_mrs cmr ON cmr.id = lr.merge_request_id
    JOIN review_findings rf ON rf.review_run_id = lr.review_run_id
    WHERE rf.selected = 1
      AND rf.lifecycle_state NOT IN ('dismissed', 'false_positive')
    ORDER BY lr.merge_request_id, rf.severity DESC, rf.confidence DESC, rf.created_at ASC
  `;
}

async function exportFindings(args) {
  const config = loadConfig(args.configPath);
  const client = new Client(postgresConfig(config));
  await client.connect();
  try {
    const result = await client.query(exportSql(args.includeAllMrs), [args.projectId || ""]);
    const items = result.rows.map(normalizeFindingRow);
    const jsonl = items.map((item) => JSON.stringify(item)).join("\n") + (items.length ? "\n" : "");
    writeFileSync(args.out, args.pretty ? items.map((item) => JSON.stringify(item, null, 2)).join("\n") + "\n" : jsonl);
    return { exported_findings: items.length, out: path.relative(root, args.out) };
  } finally {
    await client.end();
  }
}

async function main() {
  const result = await exportFindings(parseArgs(process.argv.slice(2)));
  console.log(JSON.stringify({ ok: true, ...result }, null, 2));
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isMain) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
