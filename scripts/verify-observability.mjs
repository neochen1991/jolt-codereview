import { authenticatedRequest } from "./api-auth.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";

const queue = await authenticatedRequest(`/api/projects/${PROJECT_ID}/queue/summary`);
const toolchain = await authenticatedRequest(`/api/projects/${PROJECT_ID}/toolchain/status`);
const agents = await authenticatedRequest(`/api/projects/${PROJECT_ID}/agents/quality`);
const quality = await authenticatedRequest(`/api/projects/${PROJECT_ID}/review-quality/summary`);

if (!Array.isArray(queue.by_status)) throw new Error("queue summary missing by_status");
if (!Array.isArray(queue.running)) throw new Error("queue summary missing running");
if (!Array.isArray(toolchain.tool_calls)) throw new Error("toolchain status missing tool_calls");
if (!Array.isArray(agents.items)) throw new Error("agent quality missing items");
if (!quality.llm_calls) throw new Error("review quality missing llm_calls");

console.log(JSON.stringify({
  queue: {
    statuses: queue.by_status,
    running_count: queue.running.length,
    dead_letter_count: queue.dead_letter_count
  },
  toolchain: {
    latest_run_id: toolchain.latest_run_id,
    tool_call_groups: toolchain.tool_calls.length
  },
  agents: {
    count: agents.items.length,
    top: agents.items[0] ?? null
  },
  review_quality: {
    llm_calls: quality.llm_calls
  }
}, null, 2));
