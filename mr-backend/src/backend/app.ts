import { createServer } from "node:http";
import { URL } from "node:url";
import { PayloadTooLargeError, notFound, parseBody, sendJson, type Route } from "./http.js";
import type { FileLogger } from "./logger.js";

function slowRequestThresholdMs() {
  const configured = Number(process.env.JOLT_SLOW_REQUEST_MS || "");
  return Number.isFinite(configured) && configured > 0 ? configured : 1000;
}

export function createApp(routes: Route[], logger?: FileLogger) {
  return createServer(async (req, res) => {
    const startedAt = Date.now();
    const logRequest = (event: string, fields: Record<string, unknown>, level: "info" | "warn" | "error" = "info") => {
      logger?.log(event, fields, level);
      const durationMs = Number(fields.duration_ms || 0);
      if (durationMs >= slowRequestThresholdMs()) {
        logger?.log("http_slow_request", fields, "warn");
      }
    };
    if (req.method === "OPTIONS") {
      sendJson(res, 200, { ok: true });
      logRequest("http_request", { method: req.method, path: req.url ?? "/", status: 200, duration_ms: Date.now() - startedAt });
      return;
    }
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
    const matched = routes.find((candidate) => candidate.method === req.method && candidate.pattern.test(url.pathname));
    if (!matched) {
      sendJson(res, 404, notFound());
      logRequest("http_request", { method: req.method, path: url.pathname, status: 404, duration_ms: Date.now() - startedAt }, "warn");
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
        logRequest("http_request", { method: req.method, path: url.pathname, status, duration_ms: Date.now() - startedAt });
      } else {
        sendJson(res, 200, result ?? { ok: true });
        logRequest("http_request", { method: req.method, path: url.pathname, status: 200, duration_ms: Date.now() - startedAt });
      }
    } catch (error) {
      if (error instanceof PayloadTooLargeError) {
        sendJson(res, error.statusCode, { error: "payload_too_large", message: error.message, limit_bytes: error.limitBytes });
        logRequest("http_request", { method: req.method, path: url.pathname, status: error.statusCode, duration_ms: Date.now() - startedAt }, "warn");
        return;
      }
      sendJson(res, 500, { error: "internal_error", message: (error as Error).message });
      logger?.error("http_request_failed", error, { method: req.method, path: url.pathname, status: 500, duration_ms: Date.now() - startedAt });
    }
  });
}
