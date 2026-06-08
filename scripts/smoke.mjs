const API = process.env.API_BASE || "http://127.0.0.1:8011";

async function get(path) {
  const response = await fetch(`${API}${path}`);
  const json = await response.json();
  if (!response.ok) throw new Error(`${path} failed: ${JSON.stringify(json)}`);
  return json;
}

const health = await get("/api/health");
const me = await get("/api/me");
const projects = await get("/api/projects");
const mrs = await get("/api/mr-review/projects/project_default/merge-requests");

console.log(JSON.stringify({
  health,
  user: me.user?.username,
  project_count: projects.length,
  mr_count: mrs.items.length
}, null, 2));
