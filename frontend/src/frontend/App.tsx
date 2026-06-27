import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  RefreshCw,
  Search,
  UserRound
} from "lucide-react";
import {
  AuthPage,
  ProjectSelectionPage,
  Sidebar,
  ConfigWorkspace,
  PersonalSettingsWorkspace,
  SystemSettingsWorkspace,
  MrQueue,
  DetailPanel,
  MrPreviewModal,
  PublishResultModal,
  viewTitle
} from "./components/WorkspaceViews";
import {
  DEFAULT_PROJECT_ID,
  DEFAULT_WORKSPACE_MESSAGE,
  ViewKey,
  authToken,
  setApiToken,
  readWorkspaceRoute,
  writeWorkspaceRoute,
  User,
  Project,
  Repo,
  MergeRequest,
  Finding,
  MrActionState,
  Detail,
  MrChangedFile,
  PublishResultNotice,
  PublishApiResult,
  MarkdownExportResponse,
  api,
  normalizeMrChangedFiles,
  ACTIVE_REVIEW_STATUSES,
  isTerminalMrStatus,
  mrMatchesTimeFilter,
  hasNestedVerticalScrollRoom,
  repoNameFromGitUrl,
  isRootUser,
  isProjectAdminRole,
  canAccessProjectAdminView
} from "./shared";

export function App() {
  const initialRoute = useMemo(() => readWorkspaceRoute(), []);
  const [repos, setRepos] = useState<Repo[]>([]);
  const [mrs, setMrs] = useState<MergeRequest[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [activeMrId, setActiveMrId] = useState<string | null>(initialRoute.mrId);
  const activeMrIdRef = useRef<string | null>(initialRoute.mrId);
  const [mrPreview, setMrPreview] = useState<Detail | null>(null);
  const [mrPreviewFiles, setMrPreviewFiles] = useState<MrChangedFile[]>([]);
  const [mrPreviewLoading, setMrPreviewLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [repoFilter, setRepoFilter] = useState("all");
  const [authorFilter, setAuthorFilter] = useState("all");
  const [timeFilter, setTimeFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingMrActions, setPendingMrActions] = useState<Record<string, MrActionState>>({});
  const [selectedMrIds, setSelectedMrIds] = useState<string[]>([]);
  const [repoInput, setRepoInput] = useState("");
  const [message, setMessage] = useState(DEFAULT_WORKSPACE_MESSAGE);
  const [authMessage, setAuthMessage] = useState("");
  const [publishNotice, setPublishNotice] = useState<PublishResultNotice | null>(null);
  const [activeView, setActiveView] = useState<ViewKey>(initialRoute.view);
  const [ready, setReady] = useState(false);
  const [authLanding, setAuthLanding] = useState(!authToken || initialRoute.screen === "login");
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState(initialRoute.projectId || DEFAULT_PROJECT_ID);
  const [projectChosen, setProjectChosen] = useState(Boolean(authToken && initialRoute.screen === "workspace"));
  const workspaceScrollRef = useRef<HTMLDivElement | null>(null);

  async function loadCurrentUser() {
    const me = await api<{ user: User | null; projects: Project[] }>("/api/me");
    if (!me.user) {
      setApiToken(null);
      setUser(null);
      setProjects([]);
      return;
    }
    setUser(me.user);
    setProjects(me.projects || []);
    if (!me.projects?.some((project) => project.id === activeProjectId) && me.projects?.[0]?.id) {
      setActiveProjectId(me.projects[0].id);
    }
  }

  async function loadAll(nextActiveId?: string | null) {
    const [repoData, mrData] = await Promise.all([
      api<Repo[]>(`/api/projects/${activeProjectId}/repositories`),
      api<{ items: MergeRequest[] }>(`/api/mr-review/projects/${activeProjectId}/merge-requests`)
    ]);
    setRepos(repoData);
    setMrs(mrData.items);
    setSelectedMrIds((previous) => previous.filter((id) => mrData.items.some((mr) => mr.id === id)));
    const requestedId = nextActiveId ?? activeMrIdRef.current ?? activeMrId ?? null;
    const selectedId = requestedId && mrData.items.some((mr) => mr.id === requestedId)
      ? requestedId
      : mrData.items[0]?.id ?? null;
    activeMrIdRef.current = selectedId;
    setActiveMrId(selectedId);
    if (selectedId) {
      setDetail(await api<Detail>(`/api/mr-review/merge-requests/${selectedId}`));
    } else {
      setDetail(null);
    }
  }

  async function refreshMrRemoteStatuses(showMessage = false) {
    const result = await api<{ checked: number; refreshed: number; merged: number; closed: number; errors: string[] }>(
      `/api/mr-review/projects/${activeProjectId}/merge-requests/status-refresh`,
      { method: "POST", body: "{}" }
    );
    if (result.merged || result.closed) {
      await loadAll(activeMrIdRef.current);
    }
    if (showMessage) {
      const terminalText = result.merged || result.closed ? `，发现已合入 ${result.merged} 个、已关闭 ${result.closed} 个` : "";
      setMessage(`已刷新 ${result.refreshed}/${result.checked} 个 MR 远端状态${terminalText}${result.errors.length ? `，失败 ${result.errors.length} 个` : ""}`);
    }
    return result;
  }

  useEffect(() => {
    async function bootstrapSession() {
      try {
        if (authToken) {
          const session = await api<{ authenticated: boolean; user: User | null }>("/api/auth/session");
          if (!session.authenticated || !session.user) {
            setApiToken(null);
            setUser(null);
            setProjects([]);
          } else {
            await loadCurrentUser();
          }
        }
        setReady(true);
      } catch (error) {
        setApiToken(null);
        setUser(null);
        setProjects([]);
        setAuthMessage((error as Error).message);
        setReady(true);
      }
    }
    bootstrapSession();
  }, []);

  useEffect(() => {
    if (!ready || !projectChosen) return;
    loadAll(null).catch((error) => setMessage(error.message));
    const timer = window.setInterval(() => loadAll().catch(() => undefined), 8000);
    const statusTimer = window.setInterval(() => refreshMrRemoteStatuses().catch(() => undefined), 60000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(statusTimer);
    };
  }, [ready, projectChosen, activeProjectId]);

  useEffect(() => {
    if (!ready) return;
    if (!user || authLanding) {
      writeWorkspaceRoute({ screen: "login", projectId: activeProjectId, view: activeView, mrId: activeMrId });
      return;
    }
    if (!projectChosen) {
      writeWorkspaceRoute({ screen: "projects", projectId: activeProjectId, view: activeView, mrId: null });
      return;
    }
    writeWorkspaceRoute({ screen: "workspace", projectId: activeProjectId, view: activeView, mrId: activeMrId });
  }, [activeMrId, activeProjectId, activeView, authLanding, projectChosen, ready, user]);

  async function sync() {
    setSyncing(true);
    setMessage("正在同步项目已绑定代码仓的 MR...");
    try {
      const result = await api<{
        repositories: number;
        merge_requests: number;
        jobs_created: number;
        errors: string[];
        repository_results?: Array<{ name: string; merge_requests: number; jobs_created: number; error?: string }>;
      }>(
        `/api/mr-review/projects/${activeProjectId}/sync`,
        { method: "POST", body: "{}" }
      );
      await loadAll(activeMrId);
      const repoSummary = (result.repository_results || [])
        .slice(0, 4)
        .map((repo) => `${repo.name}:${repo.merge_requests}${repo.error ? "!" : ""}`)
        .join("，");
      const suffix = repoSummary ? ` · ${repoSummary}${(result.repository_results?.length || 0) > 4 ? "…" : ""}` : "";
      setMessage(`已同步 ${result.repositories} 个代码仓 · ${result.merge_requests} 个 MR · 新增 ${result.jobs_created} 个任务${suffix}`);
      if (result.errors.length) setMessage(`同步完成，但有错误：${result.errors.join("; ")}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setSyncing(false);
    }
  }

  async function bindRepo() {
    const gitUrl = repoInput.trim();
    if (!gitUrl.includes("/") || !gitUrl.includes(".git")) {
      setMessage("请输入 Git 仓库链接，例如 https://codehub.example.com/team/repo.git");
      return;
    }
    setBusy(true);
    try {
      await api(`/api/projects/${activeProjectId}/repositories`, {
        method: "POST",
        body: JSON.stringify({
          provider: "codehub",
          git_url: gitUrl,
          name: repoNameFromGitUrl(gitUrl),
          default_branch: "main"
        })
      });
      setRepoInput("");
      await loadAll(activeMrId);
      setMessage(`已绑定仓库 ${gitUrl}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function optimisticMrStatus(mrId: string, status: string) {
    const updatedAt = new Date().toISOString();
    setMrs((previous) => previous.map((mr) => (
      mr.id === mrId ? { ...mr, review_status: status, updated_at: updatedAt } : mr
    )));
    setDetail((previous) => (
      previous?.mr.id === mrId
        ? { ...previous, mr: { ...previous.mr, review_status: status, updated_at: updatedAt } }
        : previous
    ));
  }

  function beginMrAction(mrId: string, action: MrActionState, status: string) {
    setPendingMrActions((previous) => ({ ...previous, [mrId]: action }));
    optimisticMrStatus(mrId, status);
  }

  function endMrAction(mrId: string) {
    setPendingMrActions((previous) => {
      const next = { ...previous };
      delete next[mrId];
      return next;
    });
  }

  async function openMr(id: string, showPreview = false) {
    activeMrIdRef.current = id;
    setActiveMrId(id);
    const nextDetail = await api<Detail>(`/api/mr-review/merge-requests/${id}`);
    setDetail(nextDetail);
    if (showPreview) {
      setMrPreview(nextDetail);
      setMrPreviewFiles([]);
      setMrPreviewLoading(true);
      try {
        const files = await api<unknown>(`/api/vcs/${activeProjectId}/merge-requests/${id}/files`);
        setMrPreviewFiles(normalizeMrChangedFiles(files));
      } catch (error) {
        setMessage(`MR diff 加载失败：${(error as Error).message}`);
        setMrPreviewFiles([]);
      } finally {
        setMrPreviewLoading(false);
      }
    }
  }

  async function rerunReview(mrId = detail?.mr.id) {
    if (!mrId) return;
    beginMrAction(mrId, "rerun", "reviewing");
    setBusy(true);
    try {
      await api(`/api/mr-review/merge-requests/${mrId}/review-jobs`, {
        method: "POST",
        body: JSON.stringify({ effort_level: "standard", reason: "manual_retry" })
      });
      await loadAll(mrId);
      setMessage("已提交重新检视请求，系统正在处理");
    } catch (error) {
      setMessage((error as Error).message);
      await loadAll(mrId);
    } finally {
      endMrAction(mrId);
      setBusy(false);
    }
  }

  async function startReview(mrId: string) {
    beginMrAction(mrId, "start", "reviewing");
    setBusy(true);
    try {
      await api(`/api/mr-review/merge-requests/${mrId}/review-jobs`, {
        method: "POST",
        body: JSON.stringify({ effort_level: "standard", reason: "manual_start" })
      });
      await loadAll(mrId);
      setMessage("已提交开始请求，系统正在处理");
    } catch (error) {
      setMessage((error as Error).message);
      await loadAll(mrId);
    } finally {
      endMrAction(mrId);
      setBusy(false);
    }
  }

  async function pauseReview(mrId: string) {
    beginMrAction(mrId, "pause", "paused");
    setBusy(true);
    try {
      await api(`/api/mr-review/merge-requests/${mrId}/pause`, { method: "POST", body: "{}" });
      await loadAll(mrId);
      setMessage("已暂停该 MR 的检视任务");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      endMrAction(mrId);
      setBusy(false);
    }
  }

  async function stopReview(mrId: string) {
    beginMrAction(mrId, "stop", "cancelled");
    setBusy(true);
    try {
      await api(`/api/mr-review/merge-requests/${mrId}/stop`, { method: "POST", body: "{}" });
      await loadAll(mrId);
      setMessage("已停止该 MR 的检视任务");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      endMrAction(mrId);
      setBusy(false);
    }
  }

  function workflowStatusForMr(mr: MergeRequest, action?: MrActionState) {
    return action === "pause" ? "paused" : action === "stop" ? "cancelled" : action ? "reviewing" : mr.review_status;
  }

  function mrSupportsBatchAction(mr: MergeRequest, action: "start" | "pause" | "stop" | "delete") {
    const workflowStatus = workflowStatusForMr(mr, pendingMrActions[mr.id]);
    const queueBlocked = mr.queue_blocked_by_project && mr.review_status === "queued";
    const terminal = isTerminalMrStatus(workflowStatus);
    if (pendingMrActions[mr.id]) return false;
    if (action === "start") return !terminal && !queueBlocked && !["too_large", ...ACTIVE_REVIEW_STATUSES].includes(workflowStatus);
    if (action === "pause") return !terminal && ["queued", ...ACTIVE_REVIEW_STATUSES].includes(workflowStatus);
    if (action === "stop") return !terminal && !["waiting_confirmation", "submitted", "no_issue", "too_large", "cancelled"].includes(workflowStatus);
    if (action === "delete") return !ACTIVE_REVIEW_STATUSES.includes(workflowStatus);
    return false;
  }

  function toggleMrSelection(mrId: string, selected: boolean) {
    setSelectedMrIds((previous) => {
      const next = new Set(previous);
      if (selected) next.add(mrId);
      else next.delete(mrId);
      return Array.from(next);
    });
  }

  function setVisibleMrSelection(ids: string[], selected: boolean) {
    setSelectedMrIds((previous) => {
      const next = new Set(previous);
      for (const id of ids) {
        if (selected) next.add(id);
        else next.delete(id);
      }
      return Array.from(next);
    });
  }

  async function bulkMrAction(action: "start" | "pause" | "stop" | "delete") {
    const selected = selectedMrIds
      .map((id) => mrs.find((mr) => mr.id === id))
      .filter((mr): mr is MergeRequest => Boolean(mr));
    const targets = selected.filter((mr) => mrSupportsBatchAction(mr, action));
    const skipped = selected.length - targets.length;
    if (!selected.length) {
      setMessage("请先选择 MR");
      return;
    }
    if (!targets.length) {
      setMessage(`选中的 MR 当前都不适合执行${bulkActionLabel(action)}`);
      return;
    }
    if (action === "delete" && !window.confirm(`删除选中的 ${targets.length} 个本地 MR？删除后可通过重新同步再次拉取。${skipped ? `\n已自动跳过 ${skipped} 个正在运行或不可删除的 MR。` : ""}`)) {
      return;
    }

    const actionState: MrActionState = action === "delete" ? "stop" : action;
    const optimisticStatus = action === "pause" ? "paused" : action === "stop" || action === "delete" ? "cancelled" : "reviewing";
    const ids = targets.map((mr) => mr.id);
    setBusy(true);
    setPendingMrActions((previous) => ({ ...previous, ...Object.fromEntries(ids.map((id) => [id, actionState])) }));
    for (const id of ids) optimisticMrStatus(id, optimisticStatus);
    try {
      const results = await Promise.allSettled(targets.map((mr) => {
        if (action === "start") {
          return api(`/api/mr-review/merge-requests/${mr.id}/review-jobs`, {
            method: "POST",
            body: JSON.stringify({ effort_level: "standard", reason: "manual_bulk_start" })
          });
        }
        if (action === "pause") return api(`/api/mr-review/merge-requests/${mr.id}/pause`, { method: "POST", body: "{}" });
        if (action === "stop") return api(`/api/mr-review/merge-requests/${mr.id}/stop`, { method: "POST", body: "{}" });
        return api(`/api/mr-review/merge-requests/${mr.id}`, { method: "DELETE" });
      }));
      const failed = results.filter((result): result is PromiseRejectedResult => result.status === "rejected");
      if (action === "delete") {
        setSelectedMrIds((previous) => previous.filter((id) => !ids.includes(id)));
        if (activeMrIdRef.current && ids.includes(activeMrIdRef.current)) {
          activeMrIdRef.current = null;
          setActiveMrId(null);
          setDetail(null);
        }
      }
      await loadAll(activeMrIdRef.current);
      const firstFailure = failed[0]?.reason instanceof Error ? failed[0].reason.message : "";
      setMessage(`已对 ${targets.length - failed.length}/${targets.length} 个 MR 执行${bulkActionLabel(action)}${skipped ? `，跳过 ${skipped} 个` : ""}${failed.length ? `，失败 ${failed.length} 个${firstFailure ? `：${firstFailure}` : ""}` : ""}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setPendingMrActions((previous) => {
        const next = { ...previous };
        for (const id of ids) delete next[id];
        return next;
      });
      setBusy(false);
    }
  }

  function bulkActionLabel(action: "start" | "pause" | "stop" | "delete") {
    return action === "start" ? "开始" : action === "pause" ? "暂停" : action === "stop" ? "停止" : "删除";
  }

  async function deleteMr(mr: MergeRequest) {
    if (!window.confirm(`删除本地 MR !${mr.number}？删除后可通过重新同步再次拉取。`)) return;
    setBusy(true);
    try {
      const result = await api<{ deleted_jobs: number; deleted_runs: number; deleted_findings: number }>(
        `/api/mr-review/merge-requests/${mr.id}`,
        { method: "DELETE" }
      );
      if (activeMrIdRef.current === mr.id) {
        activeMrIdRef.current = null;
        setActiveMrId(null);
        setDetail(null);
      }
      await loadAll(activeMrIdRef.current);
      setMessage(`已删除 MR !${mr.number}，清理 ${result.deleted_jobs} 个任务、${result.deleted_runs} 次运行、${result.deleted_findings} 条 finding；重新同步可再次拉取`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleFinding(finding: Finding) {
    await api(`/api/mr-review/review-findings/${finding.id}`, {
      method: "PATCH",
      body: JSON.stringify({ selected: !finding.selected })
    });
    if (detail) await openMr(detail.mr.id);
  }

  async function setAllFindingsSelected(selected: boolean) {
    if (!detail) return;
    const targets = detail.findings.filter((finding) => Boolean(finding.selected) !== selected);
    if (!targets.length) return;
    setBusy(true);
    try {
      await Promise.all(targets.map((finding) =>
        api(`/api/mr-review/review-findings/${finding.id}`, {
          method: "PATCH",
          body: JSON.stringify({ selected })
        })
      ));
      await loadAll(detail.mr.id);
      setMessage(selected ? `已全选 ${detail.findings.length} 条检视意见` : "已取消全选检视意见");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function markFalsePositive(finding: Finding) {
    await api(`/api/mr-review/review-findings/${finding.id}/feedback`, {
      method: "POST",
      body: JSON.stringify({ feedback_type: "false_positive" })
    });
    if (detail) await openMr(detail.mr.id);
  }

  async function markSelectedFalsePositive() {
    if (!detail) return;
    const selected = detail.findings.filter((finding) => finding.selected);
    if (!selected.length) {
      setMessage("没有选中的 finding");
      return;
    }
    setBusy(true);
    try {
      for (const finding of selected) {
        await api(`/api/mr-review/review-findings/${finding.id}/feedback`, {
          method: "POST",
          body: JSON.stringify({ feedback_type: "false_positive", scope: "merge_request" })
        });
      }
      await loadAll(detail.mr.id);
      setMessage(`已标记 ${selected.length} 条误报`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function publish(dryRun = false) {
    if (!detail) return;
    const selectedFindings = detail.findings.filter((finding) => finding.selected);
    const findingIds = selectedFindings.map((finding) => finding.id);
    const requestedCount = findingIds.length;
    if (!findingIds.length) {
      setMessage("没有选中的 finding");
      return;
    }
    setBusy(true);
    try {
      const result = await api<PublishApiResult>(`/api/mr-review/merge-requests/${detail.mr.id}/publish`, {
        method: "POST",
        body: JSON.stringify({ finding_ids: findingIds, dry_run: dryRun })
      });
      await loadAll(detail.mr.id);
      const publishedCount = Number(result.published_count || 0);
      const skippedCount = Number(result.skipped_count || 0);
      const actionLabel = result.dry_run ? "生成 dry-run 发布记录" : "提交检视意见";
      const title = result.dry_run
        ? "发布预览已生成"
        : publishedCount === 0 && skippedCount > 0
          ? "所选问题已提交过"
          : publishedCount === requestedCount
          ? "检视意见提交成功"
          : "检视意见部分提交成功";
      const duplicateText = skippedCount > 0 ? `，${skippedCount} 条已提交过并已跳过` : "";
      const successMessage = result.dry_run
        ? `成功${actionLabel} ${publishedCount} / ${requestedCount} 条。`
        : `成功${actionLabel} ${publishedCount} / ${requestedCount} 条${duplicateText}。`;
      setMessage(result.dry_run ? `已生成 ${publishedCount} 条 dry-run 发布记录` : `已发布 ${publishedCount} 条意见${duplicateText}`);
      setPublishNotice({
        status: "success",
        title,
        message: successMessage,
        publishedCount,
        requestedCount,
        skippedCount,
        detail: result.dry_run
          ? "当前为 dry-run，仅生成发布记录，不会提交到代码平台。"
          : skippedCount > 0
            ? "已提交过的问题不会重复提交，系统已自动跳过这些问题。"
            : "已完成代码平台提交请求。"
      });
    } catch (error) {
      const errorMessage = (error as Error).message;
      setMessage(errorMessage);
      setPublishNotice({
        status: "failed",
        title: "检视意见提交失败",
        message: `成功提交 0 / ${requestedCount} 条。`,
        publishedCount: 0,
        requestedCount,
        detail: errorMessage
      });
    } finally {
      setBusy(false);
    }
  }

  async function exportMarkdown() {
    if (!detail) return;
    setBusy(true);
    try {
      const result = await api<MarkdownExportResponse>(`/api/mr-review/merge-requests/${detail.mr.id}/export.md`);
      const blob = new Blob([result.content], { type: result.content_type || "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const filename = result.filename || `jolt-mr-${detail.mr.number}-review.md`;
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setMessage(`已导出 ${filename}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const stats = useMemo(() => {
    const queued = mrs.filter((mr) => mr.review_status === "queued").length;
    const reviewing = mrs.filter((mr) => ["fetching", "pre_scanning", "reviewing", "judging", "running"].includes(mr.review_status)).length;
    const waiting = mrs.filter((mr) => mr.review_status === "waiting_confirmation").length;
    const highRisk = mrs.filter((mr) => mr.risk_score >= 70).length;
    const submitted = mrs.filter((mr) => mr.review_status === "submitted").length;
    const tooLarge = mrs.filter((mr) => mr.review_status === "too_large").length;
    const merged = mrs.filter((mr) => mr.review_status === "merged").length;
    const closed = mrs.filter((mr) => mr.review_status === "closed").length;
    return { all: mrs.length, queued, reviewing, waiting, highRisk, submitted, tooLarge, merged, closed };
  }, [mrs]);

  const filteredMrs = useMemo(() => {
    return mrs.filter((mr) => {
      const statusOk =
        statusFilter === "all" ||
        (statusFilter === "reviewing" && ["fetching", "pre_scanning", "reviewing", "judging", "running"].includes(mr.review_status)) ||
        (statusFilter === "high_risk" && mr.risk_score >= 70) ||
        mr.review_status === statusFilter;
      const repoOk = repoFilter === "all" || mr.repository_id === repoFilter || mr.repository_name === repoFilter;
      const authorOk = authorFilter === "all" || mr.author === authorFilter;
      const timeOk = mrMatchesTimeFilter(mr.review_started_at || mr.updated_at, timeFilter);
      const text = `${mr.title} ${mr.repository_name} ${mr.author} ${mr.number}`.toLowerCase();
      return statusOk && repoOk && authorOk && timeOk && text.includes(query.toLowerCase());
    });
  }, [authorFilter, mrs, query, repoFilter, statusFilter, timeFilter]);

  const activeProject = projects.find((project) => project.id === activeProjectId) ?? projects[0];
  const activeProjectRole = String(activeProject?.role || "");
  const canManageProject = isProjectAdminRole(activeProjectRole, user);
  const canManageSystem = isRootUser(user);

  useEffect(() => {
    if (!user) return;
    if (activeView === "system" && !canManageSystem) setActiveView("personal");
    if (canAccessProjectAdminView(activeView) && !canManageProject) setActiveView("mr");
  }, [activeView, canManageProject, canManageSystem, user]);

  async function login(username: string, password: string) {
    const result = await api<{ token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
    setApiToken(result.token);
    await loadCurrentUser();
    setProjectChosen(false);
    setAuthLanding(false);
    setAuthMessage("");
    setMessage("登录成功");
  }

  async function register(input: { username: string; password: string; display_name: string; email: string }) {
    await api<{ user: User }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(input)
    });
    setAuthMessage("注册成功，请使用新账号登录");
  }

  async function changePassword(input: { current_password: string; new_password: string; confirm_password: string }) {
    await api<{ ok: boolean }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify(input)
    });
    setAuthMessage("密码已修改，下次登录请使用新密码");
  }

  async function logout() {
    await api("/api/auth/logout", { method: "POST", body: "{}" }).catch(() => undefined);
    setApiToken(null);
    setUser(null);
    setProjects([]);
    setRepos([]);
    setMrs([]);
    setDetail(null);
    activeMrIdRef.current = null;
    setActiveMrId(null);
    setSelectedMrIds([]);
    setProjectChosen(false);
    setAuthLanding(true);
    setActiveView("mr");
    setMessage(DEFAULT_WORKSPACE_MESSAGE);
    setAuthMessage("已退出登录");
  }

  async function updateMyProfile(input: { display_name: string; email: string }) {
    const result = await api<{ user: User }>("/api/me/profile", {
      method: "PATCH",
      body: JSON.stringify(input)
    });
    setUser(result.user);
    setMessage("个人信息已更新");
    return result.user;
  }

  function handleWorkspaceWheel(event: React.WheelEvent<HTMLDivElement>) {
    const node = event.currentTarget;
    if (node.scrollWidth <= node.clientWidth) return;
    const target = event.target instanceof HTMLElement ? event.target : null;
    if (hasNestedVerticalScrollRoom(target, node, event.deltaY)) return;

    const horizontalDelta = Math.abs(event.deltaX) > 0 ? event.deltaX : 0;
    const verticalAsHorizontal = horizontalDelta === 0 ? event.deltaY : 0;
    const delta = horizontalDelta || verticalAsHorizontal;
    if (!delta) return;
    const before = node.scrollLeft;
    node.scrollLeft += delta;
    if (node.scrollLeft !== before) event.preventDefault();
  }

  function handleWorkspaceKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const node = workspaceScrollRef.current;
    if (!node || node.scrollWidth <= node.clientWidth) return;
    if (event.target instanceof HTMLElement) {
      const tagName = event.target.tagName.toLowerCase();
      if (["input", "textarea", "select", "button"].includes(tagName)) return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    node.scrollBy({ left: event.key === "ArrowRight" ? 240 : -240, behavior: "smooth" });
    event.preventDefault();
  }

  async function refreshProjects() {
    const me = await api<{ user: User; projects: Project[] }>("/api/me");
    setUser(me.user);
    setProjects(me.projects);
    if (!me.projects.some((project) => project.id === activeProjectId) && me.projects[0]?.id) {
      setActiveProjectId(me.projects[0].id);
    }
  }

  async function enterProject(projectId: string) {
    setActiveProjectId(projectId);
    setProjectChosen(true);
    setActiveView("mr");
    activeMrIdRef.current = null;
    setActiveMrId(null);
    setDetail(null);
  }

  function switchWorkspaceProject(projectId: string) {
    setActiveProjectId(projectId);
    activeMrIdRef.current = null;
    setActiveMrId(null);
    setDetail(null);
    setSelectedMrIds([]);
  }

  if (!ready) {
    return (
      <main className="auth-shell">
        <section className="auth-card compact">
          <Loader2 className="spin" size={24} />
          <strong>正在加载会话</strong>
        </section>
      </main>
    );
  }

  if (authLanding || !user) {
    return (
      <AuthPage
        currentUser={user}
        onContinue={() => {
          setAuthLanding(false);
          setAuthMessage("");
        }}
        onLogin={login}
        onRegister={register}
        onChangePassword={changePassword}
        onLogout={logout}
        message={authMessage}
      />
    );
  }

  if (ready && !projectChosen) {
    return (
      <ProjectSelectionPage
        user={user}
        projects={projects}
        refreshProjects={refreshProjects}
        enterProject={enterProject}
        logout={logout}
        updateProfile={updateMyProfile}
      />
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        projects={projects}
        activeProjectId={activeProjectId}
        setActiveProjectId={switchWorkspaceProject}
        repos={repos}
        repoInput={repoInput}
        setRepoInput={setRepoInput}
        bindRepo={bindRepo}
        busy={busy}
        activeView={activeView}
        setActiveView={setActiveView}
        backToProjects={() => setProjectChosen(false)}
        user={user}
        activeProjectRole={activeProjectRole}
      />
      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <strong>{activeProject?.name || "默认项目"}</strong>
            <span>/</span>
            <strong>{viewTitle(activeView)}</strong>
          </div>
          <div className="global-search">
            <Search size={18} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 MR、仓库、作者" />
            <kbd>/</kbd>
          </div>
          <div className="top-actions">
            <span className="sync-state">
              <CheckCircle2 size={18} />
              {message}
            </span>
            <button className="user-chip" type="button" onClick={logout}>
              <UserRound size={17} />
              {user?.display_name || user?.username || "local-admin"}
            </button>
            <button className="square-button" type="button" onClick={sync} aria-label="刷新" disabled={syncing}>
              {syncing ? <Loader2 className="spin" size={19} /> : <RefreshCw size={19} />}
              <span className="tooltip">刷新</span>
            </button>
          </div>
        </header>

        {activeView === "mr" ? (
          <div
            ref={workspaceScrollRef}
            className="workspace-scroll"
            tabIndex={0}
            aria-label="MR 工作台横向滚动区域"
            onWheel={handleWorkspaceWheel}
            onKeyDown={handleWorkspaceKeyDown}
          >
            <section className="content-grid">
              <MrQueue
                items={filteredMrs}
                activeMrId={activeMrId}
                openMr={(id) => openMr(id)}
                previewMr={(id) => openMr(id, true)}
                statusFilter={statusFilter}
                setStatusFilter={setStatusFilter}
                repoFilter={repoFilter}
                setRepoFilter={setRepoFilter}
                authorFilter={authorFilter}
                setAuthorFilter={setAuthorFilter}
                timeFilter={timeFilter}
                setTimeFilter={setTimeFilter}
                repos={repos}
                authors={Array.from(new Set(mrs.map((mr) => mr.author).filter(Boolean))).sort()}
                stats={stats}
                sync={sync}
                syncing={syncing}
                busy={busy}
                pendingMrActions={pendingMrActions}
                selectedMrIds={selectedMrIds}
                toggleMrSelection={toggleMrSelection}
                setVisibleMrSelection={setVisibleMrSelection}
                bulkMrAction={bulkMrAction}
                startReview={startReview}
                pauseReview={pauseReview}
                stopReview={stopReview}
                rerunReview={rerunReview}
                deleteMr={deleteMr}
              />
              <DetailPanel
                detail={detail}
                busy={busy}
                onRerun={rerunReview}
                onToggleFinding={toggleFinding}
                onToggleAllFindings={setAllFindingsSelected}
                onFalsePositive={markFalsePositive}
                onBulkFalsePositive={markSelectedFalsePositive}
                onExportMarkdown={exportMarkdown}
                onPublish={() => publish(false)}
                projectId={activeProjectId}
              />
            </section>
          </div>
        ) : (
          activeView === "personal" ? (
            <PersonalSettingsWorkspace user={user} setMessage={setMessage} />
          ) : activeView === "system" ? (
            <SystemSettingsWorkspace setMessage={setMessage} canEdit={canManageSystem} />
          ) : (
            <ConfigWorkspace
              view={activeView}
              projectId={activeProjectId}
              repos={repos}
              reload={loadAll}
              setMessage={setMessage}
              canEdit={canManageProject}
              canManageSystem={canManageSystem}
            />
          )
        )}
        {mrPreview && (
          <MrPreviewModal
            detail={mrPreview}
            files={mrPreviewFiles}
            loading={mrPreviewLoading}
            onClose={() => {
              setMrPreview(null);
              setMrPreviewFiles([]);
            }}
          />
        )}
        {publishNotice && <PublishResultModal notice={publishNotice} onClose={() => setPublishNotice(null)} />}
      </main>
    </div>
  );
}
