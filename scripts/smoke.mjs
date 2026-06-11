import { authenticatedRequest, request } from "./api-auth.mjs";

const health = await request("/api/health");
const me = await authenticatedRequest("/api/me");
const projects = await authenticatedRequest("/api/projects");
const mrs = await authenticatedRequest("/api/mr-review/projects/project_default/merge-requests");

console.log(JSON.stringify({
  health,
  user: me.user?.username,
  project_count: projects.length,
  mr_count: mrs.items.length
}, null, 2));
