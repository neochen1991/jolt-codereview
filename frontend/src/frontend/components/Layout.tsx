import React from "react";
import {
  Bot,
  ChevronDown,
  ChevronLeft,
  Clock3,
  Database,
  GitBranch,
  LockKeyhole,
  Settings,
  UserRound,
  Zap
} from "lucide-react";
import {
  ViewKey,
  User,
  Project,
  Repo,
  isRootUser,
  isProjectAdminRole
} from "../shared";

export function viewTitle(view: ViewKey) {
  const map: Record<ViewKey, string> = {
    mr: "MR 队列",
    full: "全量检视",
    issues: "问题总览",
    rules: "规则库",
    agents: "专家与规则",
    repos: "代码仓库",
    policy: "检视策略",
    users: "用户权限",
    tools: "工具链",
    queue: "队列运维",
    personal: "个人设置",
    settings: "项目设置",
    system: "系统设置"
  };
  return map[view];
}

export function Sidebar({
  projects,
  activeProjectId,
  setActiveProjectId,
  repos,
  repoInput,
  setRepoInput,
  bindRepo,
  busy,
  activeView,
  setActiveView,
  backToProjects,
  user,
  activeProjectRole
}: {
  projects: Project[];
  activeProjectId: string;
  setActiveProjectId: (value: string) => void;
  repos: Repo[];
  repoInput: string;
  setRepoInput: (value: string) => void;
  bindRepo: () => void;
  busy: boolean;
  activeView: ViewKey;
  setActiveView: (view: ViewKey) => void;
  backToProjects: () => void;
  user: User | null;
  activeProjectRole: string;
}) {
  const canManageProject = isProjectAdminRole(activeProjectRole, user);
  const canDevelopSkills = activeProjectRole === "skill_developer";
  const canManageSystem = isRootUser(user);
  return (
    <aside className="sidebar">
      <div className="brand">
        <Zap className="brand-icon" size={30} fill="currentColor" />
        <strong>Jolt CodeReview</strong>
      </div>
      <label className="project-select">
        <select value={activeProjectId} onChange={(event) => setActiveProjectId(event.target.value)}>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>{project.name}</option>
          ))}
          {!projects.length && <option value={activeProjectId}>默认项目</option>}
        </select>
        <ChevronDown size={18} />
      </label>
      <nav className="nav">
        <NavItem icon={<GitBranch />} label="MR 队列" active={activeView === "mr"} onClick={() => setActiveView("mr")} />
        <NavItem icon={<UserRound />} label="个人设置" active={activeView === "personal"} onClick={() => setActiveView("personal")} />
        {(canManageProject || canDevelopSkills) && <NavItem icon={<Bot />} label={canDevelopSkills ? "Skill 开发" : "专家与规则"} active={activeView === "agents"} onClick={() => setActiveView("agents")} />}
        {canManageProject && <NavItem icon={<Clock3 />} label="队列运维" active={activeView === "queue"} onClick={() => setActiveView("queue")} />}
        {canManageProject && <NavItem icon={<LockKeyhole />} label="用户权限" active={activeView === "users"} onClick={() => setActiveView("users")} />}
        {canManageProject && <NavItem icon={<Settings />} label="项目设置" active={activeView === "settings"} onClick={() => setActiveView("settings")} />}
        {canManageSystem && <NavItem icon={<Database />} label="系统设置" active={activeView === "system"} onClick={() => setActiveView("system")} />}
      </nav>
      <button className="collapse-button" type="button" onClick={backToProjects}>
        <ChevronLeft size={16} />
        返回项目
      </button>
    </aside>
  );
}

export function NavItem({ icon, label, active, muted, onClick }: { icon: React.ReactElement<{ size?: number }>; label: string; active?: boolean; muted?: boolean; onClick?: () => void }) {
  return (
    <button type="button" className={`nav-item ${active ? "active" : ""} ${muted ? "muted" : ""}`} onClick={onClick}>
      {React.cloneElement(icon, { size: 21 })}
      <span>{label}</span>
    </button>
  );
}
