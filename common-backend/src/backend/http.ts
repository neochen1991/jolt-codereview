import { createHash, randomUUID } from "node:crypto";
import { URL } from "node:url";
import type { IncomingMessage, ServerResponse } from "node:http";

export interface RequestContext {
  req: IncomingMessage;
  res: ServerResponse;
  url: URL;
  params: Record<string, string>;
  body: unknown;
}

export type Handler = (ctx: RequestContext) => Promise<unknown> | unknown;

export interface Route {
  method: string;
  pattern: RegExp;
  keys: string[];
  handler: Handler;
}

export class PayloadTooLargeError extends Error {
  statusCode = 413;
  constructor(public readonly limitBytes: number) {
    super(`request body exceeds ${limitBytes} bytes`);
    this.name = "PayloadTooLargeError";
  }
}

const DEFAULT_BODY_LIMIT_BYTES = 1024 * 1024;

function requestBodyLimitBytes() {
  const configured = Number(process.env.JOLT_HTTP_BODY_LIMIT_BYTES || "");
  return Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_BODY_LIMIT_BYTES;
}

export function route(method: string, template: string, handler: Handler): Route {
  const keys: string[] = [];
  const source = template
    .replace(/:[A-Za-z0-9_]+/g, (part) => {
      keys.push(part.slice(1));
      return "([^/]+)";
    })
    .replace(/\//g, "\\/");
  return { method, pattern: new RegExp(`^${source}$`), keys, handler };
}

export async function parseBody(req: IncomingMessage): Promise<unknown> {
  if (req.method === "GET" || req.method === "HEAD") return undefined;
  const limitBytes = requestBodyLimitBytes();
  const declaredLength = Number(req.headers["content-length"] || 0);
  if (declaredLength > limitBytes) throw new PayloadTooLargeError(limitBytes);
  const chunks: Buffer[] = [];
  let received = 0;
  for await (const chunk of req) {
    const buffer = Buffer.from(chunk);
    received += buffer.length;
    if (received > limitBytes) throw new PayloadTooLargeError(limitBytes);
    chunks.push(buffer);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return undefined;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

export function sendJson(res: ServerResponse, status: number, value: unknown) {
  const body = JSON.stringify(value, null, 2);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS"
  });
  res.end(body);
}

export function notFound() {
  return { statusCode: 404, error: "not_found" };
}

export function badRequest(message: string) {
  return { statusCode: 400, error: "bad_request", message };
}

export function sha1(input: string): string {
  return createHash("sha1").update(input).digest("hex");
}

export function id(prefix: string): string {
  return `${prefix}_${randomUUID().replace(/-/g, "").slice(0, 16)}`;
}
