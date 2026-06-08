import { execFileSync } from "node:child_process";
import fs from "node:fs";
import https from "node:https";
import os from "node:os";
import path from "node:path";

const root = path.resolve(new URL("..", import.meta.url).pathname);
const rulesRoot = path.join(root, "config", "static-rules");
const manifestPath = path.join(rulesRoot, "manifest.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function download(url, target) {
  ensureDir(path.dirname(target));
  return new Promise((resolve, reject) => {
    let request;
    const timeout = setTimeout(() => {
      if (request) request.destroy();
      reject(new Error(`download timeout: ${url}`));
    }, 45000);
    request = https.get(url, { headers: { "User-Agent": "jolt-codereview-rule-sync" } }, (response) => {
      if ([301, 302, 307, 308].includes(response.statusCode ?? 0) && response.headers.location) {
        response.resume();
        clearTimeout(timeout);
        download(response.headers.location, target).then(resolve, reject);
        return;
      }
      if ((response.statusCode ?? 0) >= 400) {
        response.resume();
        clearTimeout(timeout);
        reject(new Error(`download failed ${response.statusCode}: ${url}`));
        return;
      }
      const stream = fs.createWriteStream(target);
      response.pipe(stream);
      stream.on("finish", () => {
        clearTimeout(timeout);
        stream.close(resolve);
      });
      stream.on("error", (error) => {
        clearTimeout(timeout);
        reject(error);
      });
    });
    request.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
  });
}

function copyDir(src, dest) {
  fs.rmSync(dest, { recursive: true, force: true });
  ensureDir(path.dirname(dest));
  fs.cpSync(src, dest, { recursive: true });
}

function hasExistingBundle(name) {
  const dest = path.join(rulesRoot, name);
  if (!fs.existsSync(dest)) return false;
  const stack = [dest];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const child = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(child);
      else if (!entry.name.startsWith(".")) return true;
    }
  }
  return false;
}

function walkFiles(dir, visitor) {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const child = path.join(dir, entry.name);
    if (entry.isDirectory()) walkFiles(child, visitor);
    else visitor(child);
  }
}

function prunePushProtectionFixtures() {
  const removed = [];
  const kicsRoot = path.join(rulesRoot, "kics");
  if (fs.existsSync(kicsRoot)) {
    const stack = [kicsRoot];
    while (stack.length) {
      const current = stack.pop();
      for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
        const child = path.join(current, entry.name);
        if (!entry.isDirectory()) continue;
        if (entry.name === "test") {
          fs.rmSync(child, { recursive: true, force: true });
          removed.push(path.relative(root, child));
        } else {
          stack.push(child);
        }
      }
    }
  }
  const semgrepRoot = path.join(rulesRoot, "semgrep");
  const semgrepSecretFixtures = path.join(semgrepRoot, "generic", "secrets");
  if (fs.existsSync(semgrepSecretFixtures)) {
    fs.rmSync(semgrepSecretFixtures, { recursive: true, force: true });
    removed.push(path.relative(root, semgrepSecretFixtures));
  }
  walkFiles(semgrepRoot, (file) => {
    if (/\.(fixed\.)?test\./.test(path.basename(file))) {
      fs.rmSync(file, { force: true });
      removed.push(path.relative(root, file));
    }
  });
  return removed;
}

function gitSparseCheckout(source, dest) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "jolt-static-rules-"));
  try {
    execFileSync("git", ["clone", "--depth", "1", "--filter=blob:none", "--sparse", "--branch", source.ref, source.repository, tmp], { stdio: "inherit", timeout: Number(process.env.STATIC_RULE_SYNC_GIT_TIMEOUT_MS || 120000) });
    execFileSync("git", ["-C", tmp, "sparse-checkout", "set", ...source.paths], { stdio: "inherit", timeout: Number(process.env.STATIC_RULE_SYNC_GIT_TIMEOUT_MS || 120000) });
    for (const sparsePath of source.paths) {
      const src = path.join(tmp, sparsePath);
      const target = path.join(dest, sparsePath.replace(/^assets\//, ""));
      if (fs.existsSync(src)) copyDir(src, target);
    }
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

async function downloadRawFiles(source, dest) {
  for (const sourcePath of source.paths) {
    const fileName = path.basename(sourcePath);
    const rawUrl = `${source.repository.replace("github.com", "raw.githubusercontent.com")}/${source.ref}/${sourcePath}`;
    await download(rawUrl, path.join(dest, fileName));
  }
}

async function main() {
  ensureDir(rulesRoot);
  const results = [];
  for (const [name, source] of Object.entries(manifest.sources)) {
    const dest = path.join(rulesRoot, name);
    ensureDir(dest);
    try {
      if (source.kind === "git_sparse") gitSparseCheckout(source, dest);
      else if (source.kind === "raw") await downloadRawFiles(source, dest);
      else throw new Error(`unsupported source kind: ${source.kind}`);
      results.push({ name, status: "synced", dest: path.relative(root, dest) });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (hasExistingBundle(name)) {
        results.push({ name, status: "synced", dest: path.relative(root, dest), warning: `kept existing cached rules after sync error: ${message}` });
      } else {
        results.push({ name, status: "failed", error: message });
      }
    }
  }
  const pruned = prunePushProtectionFixtures();
  const syncedManifest = {
    ...manifest,
    updated_at: new Date().toISOString(),
    sync_results: results,
    pruned_push_protection_fixtures: pruned.length,
  };
  fs.writeFileSync(manifestPath, JSON.stringify(syncedManifest, null, 2) + "\n");
  console.log(JSON.stringify({ ok: results.every((item) => item.status === "synced"), results }, null, 2));
  if (results.some((item) => item.status !== "synced")) process.exitCode = 1;
}

main();
