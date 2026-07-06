import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const root = path.resolve(import.meta.dirname, "..");
const tmp = mkdtempSync(path.join(tmpdir(), "jolt-real-pr-seed-"));
const manifestDir = path.join(tmp, "manifests");
const cacheDir = path.join(tmp, "cache");
const fixtureId = "octocat-hello-world-1347";
mkdirSync(manifestDir, { recursive: true });
mkdirSync(path.join(cacheDir, fixtureId), { recursive: true });

writeFileSync(
  path.join(manifestDir, "octocat-hello-world-1347.json"),
  JSON.stringify(
    {
      id: fixtureId,
      repository: { owner: "octocat", repo: "Hello-World", default_branch: "master" },
      pull_number: 1347,
      expected_gold_ids: ["gold-demo-001"],
      tags: ["offline-test"]
    },
    null,
    2
  )
);

writeFileSync(
  path.join(cacheDir, fixtureId, "pull.json"),
  JSON.stringify(
    {
      id: 1347,
      number: 1347,
      title: "Offline fixture PR",
      html_url: "https://github.com/octocat/Hello-World/pull/1347",
      user: { login: "fixture-user" },
      head: { ref: "feature/offline", sha: "abcdef1234567890" },
      base: { ref: "master", sha: "0123456789abcdef" }
    },
    null,
    2
  )
);
writeFileSync(
  path.join(cacheDir, fixtureId, "files.json"),
  JSON.stringify([{ filename: "README.md", additions: 3, deletions: 1, changes: 4, patch: "@@ -1 +1 @@" }], null, 2)
);
writeFileSync(path.join(cacheDir, fixtureId, "pull.diff"), "diff --git a/README.md b/README.md\n");

const result = spawnSync(
  "node",
  [
    "scripts/seed-real-prs.mjs",
    "--offline",
    "--manifest-dir",
    manifestDir,
    "--cache-dir",
    cacheDir,
    "--project-id",
    "project_real_pr_seed_test"
  ],
  { cwd: root, encoding: "utf8" }
);

if (result.stderr) process.stderr.write(result.stderr);
assert.equal(result.status, 0, result.stdout || result.stderr);
const parsed = JSON.parse(result.stdout);
assert.equal(parsed.ok, true);
assert.equal(parsed.seeded, 1);
assert.equal(parsed.write_db, false);
assert.equal(parsed.rows[0].id, fixtureId);
assert.equal(parsed.rows[0].repository, "octocat/Hello-World");
assert.equal(parsed.rows[0].pull_number, 1347);
assert.equal(parsed.rows[0].cached, true);

console.log(JSON.stringify({ ok: true, verified: "real_pr_seed_tool", fixtures: parsed.seeded }));
