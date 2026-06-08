const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const REPO = process.env.GITHUB_REPO || "https://github.com/microsoft/vscode.git";

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

const repoName = REPO.replace(/\.git$/i, "").split("/").pop() || REPO;
const repository = await request(`/api/projects/${PROJECT_ID}/repositories`, {
  method: "POST",
  body: JSON.stringify({
    provider: "github",
    git_url: REPO,
    name: repoName,
    default_branch: "main"
  })
});

const sync = await request(`/api/mr-review/projects/${PROJECT_ID}/sync`, {
  method: "POST",
  body: "{}"
});

const list = await request(`/api/mr-review/projects/${PROJECT_ID}/merge-requests`);

console.log(JSON.stringify({
  repository: {
    id: repository.id,
    provider: repository.provider,
    external_repo_id: repository.external_repo_id
  },
  sync,
  mr_count: list.items.length,
  first_items: list.items.slice(0, 5).map((item) => ({
    id: item.id,
    number: item.number,
    title: item.title,
    status: item.review_status,
    risk_score: item.risk_score
  }))
}, null, 2));
