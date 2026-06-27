import { useEffect, useState } from "react";
import {
  ChevronDown,
  Database,
  GitBranch,
  Link2,
  Plus,
  Settings,
  Trash2,
  UserRound,
  Zap
} from "lucide-react";
import {
  User,
  Project,
  Repo,
  api,
  repoNameFromGitUrl,
  providerLabel,
  isRootUser,
  isProjectAdminRole
} from "../shared";

export function ProjectSelectionPage({
  user,
  projects,
  refreshProjects,
  enterProject,
  logout,
  updateProfile
}: {
  user: User | null;
  projects: Project[];
  refreshProjects: () => Promise<void>;
  enterProject: (projectId: string) => void;
  logout: () => void;
  updateProfile: (input: { display_name: string; email: string }) => Promise<User>;
}) {
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [createProvider, setCreateProvider] = useState("codehub");
  const [createRepoUrl, setCreateRepoUrl] = useState("");
  const [createRepoName, setCreateRepoName] = useState("");
  const [createError, setCreateError] = useState("");
  const [discoverProjects, setDiscoverProjects] = useState<Project[]>([]);
  const [joinReason, setJoinReason] = useState("");
  const [joiningProjectId, setJoiningProjectId] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const canCreateProject = isRootUser(user);

  async function loadDiscoverProjects() {
    const result = await api<{ items: Project[] }>("/api/projects/discover");
    setDiscoverProjects(result.items || []);
  }

  useEffect(() => {
    loadDiscoverProjects().catch(() => undefined);
  }, [projects.length]);

  async function createProject() {
    const name = createName.trim();
    const gitUrl = createRepoUrl.trim();
    if (!name) {
      setCreateError("请输入项目名称");
      return;
    }
    if (gitUrl && (!gitUrl.includes("/") || !gitUrl.includes(".git"))) {
      setCreateError("请输入有效的 Git 仓库链接，例如 https://git.example.com/team/repo.git");
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      const repositoryInput = gitUrl
        ? {
            provider: createProvider,
            git_url: gitUrl,
            name: createRepoName.trim() || repoNameFromGitUrl(gitUrl),
            default_branch: "main"
          }
        : null;
      const result = await api<{ project: Project }>("/api/projects", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: createDescription.trim(),
          repository: repositoryInput
        })
      });
      if (repositoryInput) {
        await api(`/api/projects/${result.project.id}/repositories`, {
          method: "POST",
          body: JSON.stringify(repositoryInput)
        });
      }
      await refreshProjects();
      await loadDiscoverProjects();
      setCreateOpen(false);
      setCreateName("");
      setCreateDescription("");
      setCreateRepoUrl("");
      setCreateRepoName("");
      enterProject(result.project.id);
    } catch (error) {
      setCreateError((error as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function requestJoin(projectId: string) {
    setJoiningProjectId(projectId);
    try {
      await api(`/api/projects/${projectId}/join-requests`, {
        method: "POST",
        body: JSON.stringify({ requested_role: "developer", reason: joinReason.trim() })
      });
      setJoinReason("");
      await loadDiscoverProjects();
    } finally {
      setJoiningProjectId("");
    }
  }

  async function redeemInvite() {
    const code = inviteCode.trim();
    if (!code) return;
    await api("/api/projects/join-by-invite", {
      method: "POST",
      body: JSON.stringify({ invite_code: code })
    });
    setInviteCode("");
    await refreshProjects();
    await loadDiscoverProjects();
  }

  return (
    <main className="project-home">
      <header className="project-home-top">
        <div className="brand">
          <Zap className="brand-icon" size={30} fill="currentColor" />
          <strong>Jolt CodeReview</strong>
        </div>
        <ProjectUserMenu user={user} logout={logout} updateProfile={updateProfile} />
      </header>
      <section className="project-home-heading">
        <h1>选择项目</h1>
        <p>项目隔离仓库、规则、专家 Agent、模型配置和检视队列。进入项目后只展示该项目的 MR 工作台。</p>
      </section>
      <section className="project-card-grid">
        {projects.map((project) => (
          <ProjectCard key={project.id} project={project} user={user} refreshProjects={refreshProjects} enterProject={enterProject} />
        ))}
        {canCreateProject && (
          <button className="project-create-card" type="button" onClick={() => setCreateOpen(true)}>
            <span><Plus size={22} /></span>
            <strong>新建项目</strong>
            <em>创建项目后可立即绑定 Git 仓库，并进入独立 MR 工作台。</em>
          </button>
        )}
        {!projects.length && <div className="config-table-empty">暂无可访问项目</div>}
      </section>
      {!isRootUser(user) && <section className="project-join-panel">
        <div>
          <strong>申请加入项目</strong>
          <span>提交申请后，由项目管理员在“用户权限”中审批。</span>
        </div>
        <div className="invite-redeem-row">
          <input value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="输入项目邀请码" />
          <button type="button" onClick={redeemInvite}>使用邀请码加入</button>
        </div>
        <textarea value={joinReason} onChange={(event) => setJoinReason(event.target.value)} placeholder="可选：说明加入原因或团队归属" />
        <div className="project-join-list">
          {discoverProjects.filter((project) => !project.role).map((project) => (
            <article key={project.id}>
              <div>
                <strong>{project.name}</strong>
                <span>{project.description || "未填写项目描述"}</span>
              </div>
              {project.join_request_status === "pending" ? (
                <em>申请待审批</em>
              ) : (
                <button type="button" onClick={() => requestJoin(project.id)} disabled={joiningProjectId === project.id}>
                  {joiningProjectId === project.id ? "提交中..." : "申请加入"}
                </button>
              )}
            </article>
          ))}
          {!discoverProjects.filter((project) => !project.role).length && <div className="config-table-empty">暂无可申请项目</div>}
        </div>
      </section>}
      {canCreateProject && createOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={() => setCreateOpen(false)}>
          <section className="project-maintenance-modal project-create-modal" onClick={(event) => event.stopPropagation()}>
            <header>
              <div>
                <span>新建项目</span>
                <strong>创建独立检视空间</strong>
                <p>项目会隔离仓库、规范、专家 Agent、模型配置和检视队列。可在创建时顺手绑定一个代码仓。</p>
              </div>
            </header>
            <div className="project-maintenance project-create-form">
              <section className="project-maintenance-section">
                <h3>项目信息</h3>
                <label>
                  <span>项目名称</span>
                  <input value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder="例如 支付交易中台" autoFocus />
                </label>
                <label>
                  <span>项目描述</span>
                  <textarea value={createDescription} onChange={(event) => setCreateDescription(event.target.value)} placeholder="说明这个项目覆盖的业务或团队范围" />
                </label>
              </section>
              <section className="project-maintenance-section">
                <h3>绑定代码仓（可选）</h3>
                <div className="project-repo-editor create">
                  <select value={createProvider} onChange={(event) => setCreateProvider(event.target.value)}>
                    <option value="codehub">CodeHub</option>
                    <option value="github">GitHub</option>
                  </select>
                  <input value={createRepoUrl} onChange={(event) => setCreateRepoUrl(event.target.value)} placeholder="Git 仓库链接，例如 https://git.example.com/team/repo.git" />
                  <input value={createRepoName} onChange={(event) => setCreateRepoName(event.target.value)} placeholder="仓库显示名，默认从链接识别" />
                </div>
                <p className="project-create-hint">也可以先创建项目，进入项目维护后再绑定多个代码仓。</p>
                {createError && <div className="form-error">{createError}</div>}
                <button type="button" onClick={createProject} disabled={creating}>
                  {creating ? "创建中..." : "创建并进入项目"}
                </button>
              </section>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export function ProjectUserMenu({
  user,
  logout,
  updateProfile
}: {
  user: User | null;
  logout: () => void;
  updateProfile: (input: { display_name: string; email: string }) => Promise<User>;
}) {
  const [open, setOpen] = useState(false);
  const [displayName, setDisplayName] = useState(user?.display_name || "");
  const [email, setEmail] = useState(user?.email || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setDisplayName(user?.display_name || "");
    setEmail(user?.email || "");
  }, [user?.display_name, user?.email]);

  async function saveProfile() {
    const nextDisplayName = displayName.trim();
    if (!nextDisplayName) {
      setError("显示名不能为空");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await updateProfile({ display_name: nextDisplayName, email: email.trim() });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="project-user-menu">
      <button className="user-chip" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <UserRound size={17} />
        {user?.display_name || user?.username || "用户"}
        <ChevronDown size={15} />
      </button>
      {open && (
        <section className="project-user-dropdown">
          <header>
            <strong>{user?.display_name || user?.username || "用户"}</strong>
            <span>{user?.username || "--"}</span>
          </header>
          <div className="project-user-profile-grid">
            <p><span>账号</span><strong>{user?.username || "--"}</strong></p>
            <p><span>邮箱</span><strong>{user?.email || "未填写"}</strong></p>
            <p><span>角色</span><strong>{user?.global_role === "root" ? "root 管理员" : "普通用户"}</strong></p>
            <p><span>状态</span><strong>{user?.status === "active" ? "有效" : user?.status || "--"}</strong></p>
          </div>
          <label>
            <span>显示名</span>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          </label>
          <label>
            <span>邮箱</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" />
          </label>
          {error && <div className="project-user-error">{error}</div>}
          <div className="project-user-actions">
            <button type="button" onClick={saveProfile} disabled={saving}>{saving ? "保存中..." : "保存个人信息"}</button>
            <button type="button" className="danger" onClick={logout}>登出</button>
          </div>
        </section>
      )}
    </div>
  );
}

export function ProjectCard({
  project,
  user,
  refreshProjects,
  enterProject
}: {
  project: Project;
  user: User | null;
  refreshProjects: () => Promise<void>;
  enterProject: (projectId: string) => void;
}) {
  const canEdit = isProjectAdminRole(String(project.role || ""), user);
  const roleLabel = isRootUser(user) ? "root" : project.role || "observer";
  const [repos, setRepos] = useState<Repo[]>([]);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description || "");
  const [provider, setProvider] = useState("codehub");
  const [repoId, setRepoId] = useState("");
  const [repoName, setRepoName] = useState("");
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function loadRepos() {
    setRepos(await api<Repo[]>(`/api/projects/${project.id}/repositories`));
  }

  useEffect(() => {
    loadRepos().catch(() => undefined);
  }, [project.id]);

  useEffect(() => {
    setName(project.name);
    setDescription(project.description || "");
  }, [project.id, project.name, project.description]);

  async function saveProject() {
    setBusy(true);
    try {
      await api(`/api/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, description })
      });
      await refreshProjects();
    } finally {
      setBusy(false);
    }
  }

  async function bindProjectRepo() {
    const gitUrl = repoId.trim();
    if (!gitUrl) return;
    setBusy(true);
    try {
      await api(`/api/projects/${project.id}/repositories`, {
        method: "POST",
        body: JSON.stringify({
          provider,
          git_url: gitUrl,
          name: repoName.trim() || repoNameFromGitUrl(gitUrl),
          default_branch: "main"
        })
      });
      setRepoId("");
      setRepoName("");
      await loadRepos();
    } finally {
      setBusy(false);
    }
  }

  async function deleteProjectRepo(repo: Repo) {
    if (!window.confirm(`删除已绑定代码仓 ${repo.name}？`)) return;
    setBusy(true);
    try {
      await api(`/api/projects/${project.id}/repositories/${repo.id}`, { method: "DELETE" });
      await loadRepos();
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="project-card">
      <div className="project-card-head">
        <div>
          <strong>{project.name}</strong>
          <span>{project.description || "未填写项目描述"}</span>
        </div>
        <div className="project-card-tools">
          <span className="state-pill on">{roleLabel}</span>
          <button
            className="project-settings-button"
            type="button"
            onClick={() => setMaintenanceOpen(true)}
            aria-label={`维护项目 ${project.name}`}
            title="维护项目"
          >
            <Settings size={17} />
          </button>
        </div>
      </div>
      <div className="project-card-metrics">
        <span>仓库 {repos.length}</span>
        <span>GitHub {repos.filter((repo) => repo.provider === "github").length}</span>
        <span>CodeHub {repos.filter((repo) => repo.provider === "codehub").length}</span>
      </div>
      <div className="project-card-actions">
        <button type="button" onClick={() => enterProject(project.id)}>进入工作台</button>
      </div>
      {maintenanceOpen && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby={`project-maintenance-${project.id}`}
          onClick={() => setMaintenanceOpen(false)}
        >
          <section className="project-maintenance-modal" onClick={(event) => event.stopPropagation()}>
            <header>
              <div>
                <span><Settings size={14} />项目维护</span>
                <strong id={`project-maintenance-${project.id}`}>{project.name}</strong>
                <p>维护项目基础信息和关联代码仓，进入工作台后系统会按这些仓库同步待检视 MR。</p>
              </div>
              <div className="project-maintenance-summary">
                <article>
                  <span>角色</span>
                  <strong>{roleLabel}</strong>
                </article>
                <article>
                  <span>代码仓</span>
                  <strong>{repos.length}</strong>
                </article>
                <article>
                  <span>默认来源</span>
                  <strong>CodeHub</strong>
                </article>
              </div>
            </header>
            <div className="project-maintenance">
              <section className="project-maintenance-section project-profile-panel">
                <div className="project-section-title">
                  <span><Database size={16} /></span>
                  <div>
                    <h3>项目档案</h3>
                    <p>这些信息用于团队识别项目边界。</p>
                  </div>
                </div>
                <label>
                  <span>项目名称</span>
                  <input value={name} onChange={(event) => setName(event.target.value)} disabled={!canEdit} />
                </label>
                <label>
                  <span>项目描述</span>
                  <textarea value={description} onChange={(event) => setDescription(event.target.value)} disabled={!canEdit} />
                </label>
                <div className="project-maintenance-actions">
                  <button type="button" onClick={saveProject} disabled={!canEdit || busy}>保存项目信息</button>
                </div>
              </section>
              <section className="project-maintenance-section project-repository-panel">
                <div className="project-section-title">
                  <span><GitBranch size={16} /></span>
                  <div>
                    <h3>代码仓接入</h3>
                    <p>以 Git 链接为准拉取 MR 和提交检视意见。</p>
                  </div>
                </div>
                <div className="project-repo-editor" aria-label="绑定代码仓">
                  <label>
                    <span>平台</span>
                    <select value={provider} onChange={(event) => setProvider(event.target.value)} disabled={!canEdit}>
                      <option value="codehub">CodeHub</option>
                      <option value="github">GitHub</option>
                    </select>
                  </label>
                  <label>
                    <span>Git 仓库链接</span>
                    <input value={repoId} onChange={(event) => setRepoId(event.target.value)} placeholder="https://git.example.com/team/repo.git" disabled={!canEdit} />
                  </label>
                  <label>
                    <span>显示名称</span>
                    <input value={repoName} onChange={(event) => setRepoName(event.target.value)} placeholder="默认从链接识别" disabled={!canEdit} />
                  </label>
                  <button type="button" onClick={bindProjectRepo} disabled={!canEdit || busy}>
                    <Link2 size={15} />
                    绑定仓库
                  </button>
                </div>
                <div className="project-repo-list" aria-label="已绑定代码仓">
                  <div className="project-repo-list-head">
                    <span>平台</span>
                    <span>仓库</span>
                    <span>Git 链接</span>
                    <span>操作</span>
                  </div>
                  {repos.map((repo) => (
                    <div className="project-repo-row" key={repo.id}>
                      <span className="repo-provider">{providerLabel(repo.provider)}</span>
                      <strong title={repo.name}>{repo.name}</strong>
                      <em title={repo.external_repo_id}>{repo.external_repo_id}</em>
                      <button
                        className="repo-delete-button"
                        type="button"
                        onClick={() => deleteProjectRepo(repo)}
                        disabled={!canEdit || busy}
                        aria-label={`删除代码仓 ${repo.name}`}
                        title="删除代码仓"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))}
                  {!repos.length && <div className="config-table-empty">暂无绑定仓库</div>}
                </div>
              </section>
            </div>
          </section>
        </div>
      )}
    </article>
  );
}

