import { badRequest } from "../http.js";

export type LlmTestInput = {
  default_provider?: string;
  default_base_url?: string;
  default_model?: string;
  default_api_key_env?: string | null;
  default_api_key?: string | null;
  request_timeout_seconds?: number;
  enable_stream?: boolean;
};

function openAiCompatibleChatUrl(baseUrl: string) {
  const normalized = baseUrl.trim().replace(/\/+$/, "");
  return `${normalized}/chat/completions`;
}

function resolveLlmApiKey(input: LlmTestInput) {
  const envName = typeof input.default_api_key_env === "string" ? input.default_api_key_env.trim() : "";
  if (envName && process.env[envName]) return process.env[envName] ?? "";
  return typeof input.default_api_key === "string" ? input.default_api_key.trim() : "";
}

export function compactLlmTestInput(input: LlmTestInput) {
  const compacted: LlmTestInput = {};
  for (const [key, rawValue] of Object.entries(input) as Array<[keyof LlmTestInput, unknown]>) {
    if (rawValue === null || rawValue === undefined) continue;
    if (typeof rawValue === "string" && rawValue.trim() === "") continue;
    (compacted as Record<string, unknown>)[key] = rawValue;
  }
  return compacted;
}

function parseOpenAiLikeResponse(text: string, stream: boolean) {
  if (!stream) {
    try {
      return text ? JSON.parse(text) as Record<string, unknown> : null;
    } catch {
      return null;
    }
  }
  let sample = "";
  let chunkCount = 0;
  let parsedStatus: Record<string, unknown> | null = null;
  if (!text.split(/\r?\n/).some((line) => line.trim().startsWith("data:"))) {
    try {
      return text ? JSON.parse(text) as Record<string, unknown> : null;
    } catch {
      return null;
    }
  }
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (!payload || payload === "[DONE]") continue;
    try {
      const chunk = JSON.parse(payload) as Record<string, unknown>;
      parsedStatus = chunk;
      chunkCount += 1;
      const choices = Array.isArray(chunk.choices) ? chunk.choices as Array<Record<string, unknown>> : [];
      const delta = choices[0]?.delta as Record<string, unknown> | undefined;
      if (typeof delta?.content === "string") sample += delta.content;
    } catch {
      continue;
    }
  }
  return {
    choices: [{ message: { content: sample } }],
    stream: { enabled: true, chunk_count: chunkCount },
    last_chunk: parsedStatus
  };
}

export async function testOpenAiCompatibleLlm(input: LlmTestInput) {
  const baseUrl = String(input.default_base_url ?? "").trim();
  const model = String(input.default_model ?? "").trim();
  const apiKey = resolveLlmApiKey(input);
  if (!baseUrl) return badRequest("LLM base url is required");
  if (!model) return badRequest("LLM model is required");
  if (!apiKey) return badRequest("LLM api key or api key env is required");

  const started = Date.now();
  const controller = new AbortController();
  const configuredTimeout = Number(input.request_timeout_seconds ?? 120);
  const timeoutSeconds = Number.isFinite(configuredTimeout) ? Math.max(1, Math.min(600, configuredTimeout)) : 120;
  const enableStream = input.enable_stream !== false;
  const timer = setTimeout(() => controller.abort(), timeoutSeconds * 1000);
  try {
    const response = await fetch(openAiCompatibleChatUrl(baseUrl), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: enableStream ? "text/event-stream, application/json" : "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      signal: controller.signal,
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: "You are a connectivity checker. Reply with ok." },
          { role: "user", content: "ping" }
        ],
        temperature: 0,
        max_tokens: 8,
        stream: enableStream,
        ...(enableStream ? { stream_options: { include_usage: true } } : {})
      })
    });
    const text = await response.text();
    const parsed = parseOpenAiLikeResponse(text, enableStream);
    const choices = Array.isArray(parsed?.choices) ? parsed.choices as Array<Record<string, unknown>> : [];
    const firstMessage = choices[0]?.message as Record<string, unknown> | undefined;
    const sample = String(firstMessage?.content ?? "").slice(0, 80);
    return {
      ok: response.ok,
      provider: String(input.default_provider ?? ""),
      model,
      stream: enableStream,
      status: response.status,
      latency_ms: Date.now() - started,
      sample,
      error_preview: response.ok ? "" : text.slice(0, 300)
    };
  } catch (error) {
    return {
      ok: false,
      provider: String(input.default_provider ?? ""),
      model,
      status: 0,
      latency_ms: Date.now() - started,
      error_preview: error instanceof Error ? error.message : String(error)
    };
  } finally {
    clearTimeout(timer);
  }
}
