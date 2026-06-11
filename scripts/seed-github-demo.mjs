import { authenticatedRequest } from "./api-auth.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const REPO = process.env.GITHUB_REPO || "https://github.com/microsoft/vscode.git";

const repoName = REPO.replace(/\.git$/i, "").split("/").pop() || REPO;
const repository = await authenticatedRequest(`/api/projects/${PROJECT_ID}/repositories`, {
  method: "POST",
  body: JSON.stringify({
    provider: "github",
    git_url: REPO,
    name: repoName,
    default_branch: "main"
  })
});

const sync = await authenticatedRequest(`/api/mr-review/projects/${PROJECT_ID}/sync`, {
  method: "POST",
  body: "{}"
});

const list = await authenticatedRequest(`/api/mr-review/projects/${PROJECT_ID}/merge-requests`);

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
