import { createServer } from "node:http";
import { URL } from "node:url";
import { notFound, parseBody, sendJson, type Route } from "./http.js";
import type { FileLogger } from "./logger.js";

export function createApp(routes: Route[], logger?: FileLogger) {
  return createServer(async (req, res) => {
    const startedAt = Date.now();
    if (req.method === "OPTIONS") {
      sendJson(res, 200, { ok: true });
      logger?.log("http_request", { method: req.method, path: req.url ?? "/", status: 200, duration_ms: Date.now() - startedAt });
      return;
    }
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
    const matched = routes.find((candidate) => candidate.method === req.method && candidate.pattern.test(url.pathname));
    if (!matched) {
      sendJson(res, 404, notFound());
      logger?.log("http_request", { method: req.method, path: url.pathname, status: 404, duration_ms: Date.now() - startedAt }, "warn");
      return;
    }
    const match = matched.pattern.exec(url.pathname);
    const params: Record<string, string> = {};
    matched.keys.forEach((key, index) => {
      params[key] = decodeURIComponent(match?.[index + 1] ?? "");
    });

    try {
      const body = await parseBody(req);
      const result = await matched.handler({ req, res, url, params, body });
      if (typeof result === "object" && result && "statusCode" in result) {
        const status = Number((result as { statusCode: number }).statusCode);
        sendJson(res, status, result);
        logger?.log("http_request", { method: req.method, path: url.pathname, status, duration_ms: Date.now() - startedAt });
      } else {
        sendJson(res, 200, result ?? { ok: true });
        logger?.log("http_request", { method: req.method, path: url.pathname, status: 200, duration_ms: Date.now() - startedAt });
      }
    } catch (error) {
      sendJson(res, 500, { error: "internal_error", message: (error as Error).message });
      logger?.error("http_request_failed", error, { method: req.method, path: url.pathname, status: 500, duration_ms: Date.now() - startedAt });
    }
  });
}
