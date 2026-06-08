const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const INTERVAL_MS = Number(process.env.POLL_INTERVAL_MS || 5 * 60 * 1000);

async function request(path, init) {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  const json = await response.json();
  if (!response.ok) {
    throw new Error(`${path} failed: ${JSON.stringify(json)}`);
  }
  return json;
}

async function waitForApi() {
  for (let attempt = 1; attempt <= 60; attempt += 1) {
    try {
      await request("/api/health");
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  throw new Error("API did not become ready within 60 seconds");
}

async function syncOnce() {
  const result = await request(`/api/mr-review/projects/${PROJECT_ID}/sync`, {
    method: "POST",
    body: "{}"
  });
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] poll sync`, JSON.stringify(result));
}

await waitForApi();
await syncOnce().catch((error) => console.error("initial poll sync failed:", error.message));

setInterval(() => {
  syncOnce().catch((error) => console.error("poll sync failed:", error.message));
}, INTERVAL_MS);

