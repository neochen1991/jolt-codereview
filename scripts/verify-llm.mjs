import { chatCompletionsUrl, loadConfig, redact, resolveLlmApiKey } from "./config-utils.mjs";

const config = loadConfig();
const llm = config.llm || {};
const apiKey = resolveLlmApiKey(config);

if (!apiKey) {
  throw new Error("No LLM API key configured. Set llm.default_api_key or llm.default_api_key_env.");
}

const started = Date.now();
const response = await fetch(chatCompletionsUrl(llm.default_base_url), {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${apiKey}`
  },
  body: JSON.stringify({
    model: llm.default_model,
    messages: [
      {
        role: "system",
        content: "你是一个代码检视系统的连通性检查器，只输出 JSON。"
      },
      {
        role: "user",
        content: "返回 {\"ok\": true, \"purpose\": \"code_review_connectivity\"}"
      }
    ],
    temperature: 0
  })
});

const text = await response.text();
let json;
try {
  json = JSON.parse(text);
} catch {
  json = { raw: text.slice(0, 500) };
}

if (!response.ok) {
  console.log(JSON.stringify({
    ok: false,
    provider: llm.default_provider,
    model: llm.default_model,
    base_url: llm.default_base_url,
    api_key: redact(apiKey),
    status: response.status,
    duration_ms: Date.now() - started,
    response: json
  }, null, 2));
  process.exit(1);
}

const content = json?.choices?.[0]?.message?.content ?? "";
console.log(JSON.stringify({
  ok: true,
  provider: llm.default_provider,
  model: llm.default_model,
  base_url: llm.default_base_url,
  api_key: redact(apiKey),
  status: response.status,
  duration_ms: Date.now() - started,
  request_id: json?.id || null,
  usage: json?.usage || null,
  content_preview: String(content).slice(0, 300)
}, null, 2));
