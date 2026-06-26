import type { Db } from "../db.js";

export interface RepositoryRow {
  id: string;
  project_id: string;
  provider: string;
  external_repo_id: string;
  name: string;
  default_branch: string;
  status: string;
  provider_config_json: string;
}

export class RepositoryRepository {
  constructor(private readonly db: Db) {}

  listByProject(projectId: string) {
    return this.db.prepare("SELECT * FROM repositories WHERE project_id = $1 AND status = 'active' ORDER BY created_at DESC").all(projectId) as unknown as RepositoryRow[];
  }

  listActiveByProject(projectId: string) {
    return this.db.prepare("SELECT * FROM repositories WHERE project_id = $1 AND status = 'active'").all(projectId) as unknown as RepositoryRow[];
  }

  listActiveByProjectAndProvider(projectId: string, provider: string) {
    return this.db.prepare("SELECT * FROM repositories WHERE project_id = $1 AND provider = $2 AND status = 'active'").all(projectId, provider) as unknown as RepositoryRow[];
  }

  findById(repositoryId: string) {
    return this.db.prepare("SELECT * FROM repositories WHERE id = $1").get(repositoryId) as RepositoryRow | undefined;
  }

  findProjectByRepositoryId(repositoryId: string) {
    return this.db.prepare("SELECT project_id FROM repositories WHERE id = $1").get(repositoryId) as { project_id: string } | undefined;
  }

  findByProjectProviderExternal(projectId: string, provider: string, externalRepoId: string) {
    return this.db.prepare("SELECT * FROM repositories WHERE project_id = $1 AND provider = $2 AND external_repo_id = $3").get(projectId, provider, externalRepoId) as RepositoryRow | undefined;
  }

  softDelete(projectId: string, repositoryId: string) {
    return this.db.prepare(`
      UPDATE repositories
      SET status = 'deleted',
          updated_at = CURRENT_TIMESTAMP
      WHERE id = $1 AND project_id = $2 AND status = 'active'
    `).run(repositoryId, projectId);
  }

  upsert(input: {
    id: string;
    projectId: string;
    provider: string;
    externalRepoId: string;
    name: string;
    defaultBranch: string;
    providerConfig: Record<string, unknown>;
  }) {
    this.db.prepare(`
      INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
      VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
      ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
        name = excluded.name,
        default_branch = excluded.default_branch,
        provider_config_json = excluded.provider_config_json,
        status = 'active',
        updated_at = CURRENT_TIMESTAMP
    `).run(
      input.id,
      input.projectId,
      input.provider,
      input.externalRepoId,
      input.name,
      input.defaultBranch,
      JSON.stringify(input.providerConfig)
    );
    return this.findByProjectProviderExternal(input.projectId, input.provider, input.externalRepoId);
  }
}
