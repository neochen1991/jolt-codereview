import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..", "..");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";

loadLocalEnv(path.join(frontendRoot, ".env"));

const devMode = process.argv.includes("--dev") || process.env.JOLT_FRONTEND_DEV === "1";
const host = process.env.JOLT_FRONTEND_HOST || "127.0.0.1";
const port = Number(process.env.JOLT_FRONTEND_PORT || 9020);
const vitePort = Number(process.env.JOLT_VITE_PORT || 9023);
const commonBase = cleanBase(process.env.COMMON_API_BASE || process.env.VITE_COMMON_API_BASE || "http://127.0.0.1:9022");
const mrBase = cleanBase(process.env.MR_API_BASE || process.env.VITE_MR_API_BASE || "http://127.0.0.1:9021");
const viteBase = `http://${host}:${vitePort}`;
const distDir = path.join(frontendRoot, "dist");

const commonApiPathPatterns = [
  /^\/api\/auth(?:\/|$)/,
  /^\/api\/me(?:\/|$)/,
  /^\/api\/users(?:\/|$)/,
  /^\/api\/permissions(?:\/|$)/,
  /^\/api\/models(?:\/|$)/,
  /^\/api\/system(?:\/|$)/,
  /^\/internal\/auth(?:\/|$)/,
  /^\/internal\/models(?:\/|$)/
];

const commonProjectPathPatterns = [
  /^\/api\/projects$/,
  /^\/api\/projects\/discover$/,
  /^\/api\/projects\/join-by-invite$/,
  /^\/api\/projects\/[^/]+$/,
  /^\/api\/projects\/[^/]+\/members(?:\/|$)/,
  /^\/api\/projects\/[^/]+\/repositories(?:\/|$)/,
  /^\/api\/projects\/[^/]+\/settings(?:\/|$)/,
  /^\/api\/projects\/[^/]+\/effective-config$/,
  /^\/api\/projects\/[^/]+\/join-requests(?:\/|$)/,
  /^\/api\/projects\/[^/]+\/invitations(?:\/|$)/,
  /^\/api\/projects\/[^/]+\/audit-logs$/
];

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".ico": "image/x-icon"
};

function loadLocalEnv(envPath) {
  if (!existsSync(envPath)) return;
  const lines = readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [rawKey, ...rawValueParts] = trimmed.split("=");
    const key = rawKey.trim();
    if (!key || process.env[key] !== undefined) continue;
    const rawValue = rawValueParts.join("=").trim();
    process.env[key] = rawValue.replace(/^['"]|['"]$/g, "");
  }
}

function cleanBase(value) {
  return String(value || "").replace(/\/+$/, "");
}

export function resolveGatewayTarget(pathname) {
  const normalizedPath = pathname.startsWith("/") ? pathname : `/${pathname}`;
  if (
    commonApiPathPatterns.some((pattern) => pattern.test(normalizedPath)) ||
    commonProjectPathPatterns.some((pattern) => pattern.test(normalizedPath))
  ) {
    return commonBase;
  }
  return mrBase;
}

function proxyRequest(req, res, targetBase) {
  const target = new URL(req.url || "/", targetBase);
  const headers = { ...req.headers, host: target.host };
  const client = target.protocol === "https:" ? httpsRequest : httpRequest;
  const upstream = client(
    target,
    {
      method: req.method,
      headers
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    }
  );
  upstream.on("error", (error) => {
    if (res.headersSent) {
      res.destroy(error);
      return;
    }
    res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ error: "bad_gateway", message: error.message, target: targetBase }));
  });
  req.pipe(upstream);
}

function serveStatic(req, res) {
  const url = new URL(req.url || "/", `http://${host}:${port}`);
  const decodedPath = decodeURIComponent(url.pathname);
  const safePath = path.normalize(decodedPath).replace(/^(\.\.[/\\])+/, "");
  let filePath = path.join(distDir, safePath);
  if (!filePath.startsWith(distDir)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }
  if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
    filePath = path.join(distDir, "index.html");
  }
  if (!existsSync(filePath)) {
    res.writeHead(404);
    res.end("Frontend dist not found. Run npm --prefix frontend run build first.");
    return;
  }
  const ext = path.extname(filePath).toLowerCase();
  res.writeHead(200, { "Content-Type": mimeTypes[ext] || "application/octet-stream" });
  createReadStream(filePath).pipe(res);
}

function startViteDevServer() {
  const child = spawn(
    npmCommand,
    ["run", "vite:dev", "--", "--host", host, "--port", String(vitePort), "--strictPort"],
    {
      cwd: frontendRoot,
      env: {
        ...process.env,
        VITE_API_BASE: process.env.VITE_API_BASE || "",
        VITE_COMMON_API_BASE: process.env.VITE_COMMON_API_BASE || "",
        VITE_MR_API_BASE: process.env.VITE_MR_API_BASE || ""
      },
      stdio: "inherit",
      shell: false
    }
  );
  child.on("exit", (code) => {
    if (code && code !== 0) {
      console.error(`Vite dev server exited with code ${code}`);
      process.exit(code);
    }
  });
  process.on("SIGINT", () => child.kill());
  process.on("SIGTERM", () => child.kill());
  return child;
}

export function createGatewayServer() {
  return createServer((req, res) => {
    const url = new URL(req.url || "/", `http://${host}:${port}`);
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/internal/")) {
      proxyRequest(req, res, resolveGatewayTarget(url.pathname));
      return;
    }
    if (devMode) {
      proxyRequest(req, res, viteBase);
      return;
    }
    serveStatic(req, res);
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (devMode) startViteDevServer();

  const server = createGatewayServer();
  server.listen(port, host, () => {
    console.log(`Jolt Frontend Gateway: http://${host}:${port}`);
    console.log(`Common Backend: ${commonBase}`);
    console.log(`MR Backend: ${mrBase}`);
    if (devMode) console.log(`Vite dev server: ${viteBase}`);
  });
}
