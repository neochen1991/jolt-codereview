import React, { useEffect, useMemo, useState } from "react";
import {
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  Clock3,
  Code2,
  FileDown,
  FileCode2,
  Folder,
  AlertTriangle,
  Loader2,
  RefreshCw,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Users
} from "lucide-react";
import {
  Repo,
  MergeRequest,
  Finding,
  MrActionState,
  RuleDetail,
  Detail,
  MrChangedFile,
  ParsedDiffLine,
  api,
  normalizeMrChangedFiles,
  statusLabel,
  formatDurationMs,
  parseBackendTime,
  formatDateTime,
  formatElapsedSeconds,
  ACTIVE_REVIEW_STATUSES,
  REVIEW_STEPS,
  effectiveReviewStatus,
  isTerminalMrStatus,
  reviewStepIndex,
  severityText,
  publishStateLabel,
  isAlreadyPublishedFinding,
  sortFindingsBySeverity,
  findingSource,
  recordTimestamp,
  participatingAgentIds,
  riskLevel,
  shortTime,
  formatFindingLocation,
  formatFindingLineRange,
  shortPath,
  textCodeLines,
  sourceCodeWindow,
  diffCodeWindow,
  parseUnifiedPatch,
  buildFileTree,
  basename,
  normalizeRepositoryPath,
  matchRepositoryPath,
  readPathMap
} from "../shared";

function llmCallSucceeded(row: Record<string, unknown>) {
  const status = String(row.status || "").toLowerCase();
  return ["completed", "success", "ok"].includes(status);
}

function llmCallStats(rows: Array<Record<string, unknown>> | undefined) {
  const total = rows?.length || 0;
  const succeeded = (rows || []).filter(llmCallSucceeded).length;
  const successRate = total ? Math.round((succeeded / total) * 100) : null;
  return { total, succeeded, successRate };
}

function arrayStrings(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function skillCallRows(detail: Detail) {
  return detail.session_logs?.skill_calls || [];
}

function skillStageText(stage: unknown) {
  const value = String(stage || "");
  if (value === "loaded") return "加载";
  if (value === "deepagents") return "DeepAgents";
  if (value === "llm") return "LLM 检视";
  return value || "记录";
}

function skillStatusText(status: unknown) {
  const value = String(status || "");
  if (value === "called") return "已调用";
  if (value === "loaded") return "已加载";
  return value || "已记录";
}

function skillAssetSummary(row: Record<string, unknown>) {
  const paths = arrayStrings(row.asset_paths);
  if (paths.length) return paths.slice(0, 3).join(", ");
  const count = Number(row.asset_count || 0);
  return count ? `${count} 个资源文件` : "--";
}

export function MrQueue({
  items,
  activeMrId,
  openMr,
  previewMr,
  statusFilter,
  setStatusFilter,
  repoFilter,
  setRepoFilter,
  authorFilter,
  setAuthorFilter,
  timeFilter,
  setTimeFilter,
  repos,
  authors,
  stats,
  sync,
  syncing,
  busy,
  pendingMrActions,
  selectedMrIds,
  toggleMrSelection,
  setVisibleMrSelection,
  bulkMrAction,
  startReview,
  pauseReview,
  stopReview,
  rerunReview,
  deleteMr
}: {
  items: MergeRequest[];
  activeMrId: string | null;
  openMr: (id: string) => void;
  previewMr: (id: string) => void;
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  repoFilter: string;
  setRepoFilter: (value: string) => void;
  authorFilter: string;
  setAuthorFilter: (value: string) => void;
  timeFilter: string;
  setTimeFilter: (value: string) => void;
  repos: Repo[];
  authors: string[];
  stats: { all: number; queued: number; reviewing: number; waiting: number; highRisk: number; submitted: number; tooLarge: number; merged: number; closed: number };
  sync: () => void;
  syncing: boolean;
  busy: boolean;
  pendingMrActions: Record<string, MrActionState>;
  selectedMrIds: string[];
  toggleMrSelection: (mrId: string, selected: boolean) => void;
  setVisibleMrSelection: (ids: string[], selected: boolean) => void;
  bulkMrAction: (action: "start" | "pause" | "stop" | "delete") => void;
  startReview: (mrId: string) => void;
  pauseReview: (mrId: string) => void;
  stopReview: (mrId: string) => void;
  rerunReview: (mrId: string) => void;
  deleteMr: (mr: MergeRequest) => void;
}) {
  const tabs = [
    ["all", "全部", stats.all],
    ["queued", "待检视", stats.queued],
    ["reviewing", "检视中", stats.reviewing],
    ["waiting_confirmation", "待确认", stats.waiting],
    ["submitted", "已提交", stats.submitted],
    ["too_large", "MR 过大", stats.tooLarge],
    ["merged", "已合入", stats.merged],
    ["closed", "已关闭", stats.closed]
  ] as const;
  const visibleIds = items.map((mr) => mr.id);
  const selectedVisibleCount = visibleIds.filter((id) => selectedMrIds.includes(id)).length;
  const selectedCount = selectedMrIds.length;
  const allVisibleSelected = visibleIds.length > 0 && selectedVisibleCount === visibleIds.length;
  const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected;

  return (
    <section className="queue-panel">
      <div className="panel-heading">
        <h1>待检视 MR</h1>
        <div className="status-tabs-bar">
          <div className="segmented-tabs">
            {tabs.map(([key, label, count]) => (
              <button key={key} className={statusFilter === key ? "active" : ""} onClick={() => setStatusFilter(key)}>
                {label}
                <strong>{count}</strong>
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="filters">
        <FilterSelect
          label="状态"
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            ["all", "全部状态"],
            ["queued", "待检视"],
            ["reviewing", "检视中"],
            ["waiting_confirmation", "待确认"],
            ["submitted", "已提交"],
            ["too_large", "MR 过大"],
            ["merged", "已合入"],
            ["closed", "已关闭"]
          ]}
        />
        <FilterSelect
          label="作者"
          value={authorFilter}
          onChange={setAuthorFilter}
          options={[
            ["all", "全部作者"],
            ...authors.map((author) => [author, author] as [string, string])
          ]}
        />
        <FilterSelect
          label="时间"
          value={timeFilter}
          onChange={setTimeFilter}
          options={[
            ["all", "全部时间"],
            ["today", "今天"],
            ["7d", "近 7 天"],
            ["30d", "近 30 天"]
          ]}
        />
        <FilterSelect
          label="仓库"
          value={repoFilter}
          onChange={setRepoFilter}
          options={[
            ["all", "全部仓库"],
            ...repos.map((repo) => [repo.id, repo.name] as [string, string])
          ]}
        />
        <button className="filter-icon" type="button" onClick={sync} disabled={syncing}>
          {syncing ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
        </button>
      </div>
      <div className="mr-bulk-bar">
        <label className="mr-select-all">
          <input
            type="checkbox"
            checked={allVisibleSelected}
            ref={(input) => {
              if (input) input.indeterminate = someVisibleSelected;
            }}
            onChange={(event) => setVisibleMrSelection(visibleIds, event.target.checked)}
            disabled={!visibleIds.length || busy}
          />
          <span>{selectedCount ? `已选择 ${selectedCount} 个 MR` : "选择当前列表 MR"}</span>
        </label>
        <div className="mr-bulk-actions">
          <button type="button" onClick={() => bulkMrAction("start")} disabled={!selectedCount || busy}>批量开始</button>
          <button type="button" onClick={() => bulkMrAction("pause")} disabled={!selectedCount || busy}>批量暂停</button>
          <button type="button" onClick={() => bulkMrAction("stop")} disabled={!selectedCount || busy}>批量停止</button>
          <button className="danger" type="button" onClick={() => bulkMrAction("delete")} disabled={!selectedCount || busy}>批量删除</button>
        </div>
      </div>
      <div className="mr-table">
        <div className="mr-head">
          <span className="mr-select-cell">
            <input
              type="checkbox"
              checked={allVisibleSelected}
              ref={(input) => {
                if (input) input.indeterminate = someVisibleSelected;
              }}
              onChange={(event) => setVisibleMrSelection(visibleIds, event.target.checked)}
              disabled={!visibleIds.length || busy}
              aria-label="选择当前列表全部 MR"
            />
          </span>
          <span>MR</span>
          <span>仓库</span>
          <span>作者</span>
          <span>风险</span>
          <span>状态</span>
          <span>问题</span>
          <span>检视开始</span>
          <span>操作</span>
        </div>
        <div className="mr-body">
          {items.map((mr) => {
            const action = pendingMrActions[mr.id];
            const workflowStatus = action === "pause" ? "paused" : action === "stop" ? "cancelled" : action ? "reviewing" : mr.review_status;
            const queueBlocked = !action && mr.queue_blocked_by_project && mr.review_status === "queued";
            const displayStatus = queueBlocked ? "project_queued" : workflowStatus;
            const queueBlockedReason = mr.queue_blocked_reason || "项目内已有 MR 正在检视，当前 MR 将排队等待";
            const terminal = isTerminalMrStatus(workflowStatus);
            const terminalReason = workflowStatus === "merged" ? "该 MR 已合入，不能再检视或提交意见" : workflowStatus === "closed" ? "该 MR 已关闭，不能再检视或提交意见" : "";
            const rowBusy = Boolean(action);
            const selected = selectedMrIds.includes(mr.id);
            return (
              <div
                className={`mr-row ${activeMrId === mr.id ? "active" : ""} ${rowBusy ? "pending-action" : ""} ${queueBlocked ? "project-queued" : ""} ${selected ? "selected" : ""}`}
                key={mr.id}
                onClick={() => openMr(mr.id)}
              >
                <span className="mr-select-cell" onClick={(event) => event.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={(event) => toggleMrSelection(mr.id, event.target.checked)}
                    aria-label={`选择 MR !${mr.number}`}
                  />
                </span>
                <span className="mr-title">
                  <span>
                    {mr.html_url ? (
                      <a
                        className="mr-title-link"
                        href={mr.html_url}
                        target="_blank"
                        rel="noreferrer"
                        title={`打开远程 MR：${mr.title}`}
                        onClick={(event) => event.stopPropagation()}
                      >
                        <strong>!{mr.number}</strong>
                        <span>{mr.title}</span>
                      </a>
                    ) : (
                      <>
                        <strong>!{mr.number}</strong>
                        <span>{mr.title}</span>
                      </>
                    )}
                  </span>
                </span>
                <span>{mr.repository_name}</span>
                <span>{mr.author}</span>
                <RiskBadge score={mr.risk_score} />
                <StatusBadge status={displayStatus} title={terminalReason || (queueBlocked ? queueBlockedReason : undefined)} />
                <span>{mr.finding_count || (workflowStatus === "queued" ? "--" : 0)}</span>
                <span>{mr.review_started_at ? shortTime(mr.review_started_at) : "--"}</span>
                <span className="mr-actions">
                  <button
                    className="mr-action-button"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      startReview(mr.id);
                    }}
                    disabled={busy || rowBusy || terminal || queueBlocked || workflowStatus === "too_large" || ACTIVE_REVIEW_STATUSES.includes(workflowStatus)}
                    title={terminalReason || (queueBlocked ? queueBlockedReason : undefined)}
                  >
                    {action === "start" ? "启动中" : "开始"}
                  </button>
                  <button
                    className="mr-action-button"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      pauseReview(mr.id);
                    }}
                    disabled={busy || rowBusy || terminal || !["queued", ...ACTIVE_REVIEW_STATUSES].includes(workflowStatus)}
                  >
                    {action === "pause" ? "暂停中" : "暂停"}
                  </button>
                  <button
                    className="mr-action-button danger"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      stopReview(mr.id);
                    }}
                    disabled={busy || rowBusy || terminal || ["waiting_confirmation", "submitted", "no_issue", "too_large", "cancelled"].includes(workflowStatus)}
                  >
                    {action === "stop" ? "停止中" : "停止"}
                  </button>
                  <button
                    className="mr-action-button subtle"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      rerunReview(mr.id);
                    }}
                    disabled={busy || rowBusy || terminal || workflowStatus === "too_large" || ACTIVE_REVIEW_STATUSES.includes(workflowStatus)}
                  >
                    {action === "rerun" ? "提交中" : "重检"}
                  </button>
                  <button
                    className="mr-action-button subtle"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      previewMr(mr.id);
                    }}
                  >
                    Diff
                  </button>
                  <button
                    className="mr-action-button icon danger"
                    type="button"
                    title="删除本地 MR"
                    aria-label={`删除 MR !${mr.number}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      deleteMr(mr);
                    }}
                    disabled={busy || rowBusy || ACTIVE_REVIEW_STATUSES.includes(workflowStatus)}
                  >
                    <Trash2 size={15} />
                  </button>
                </span>
              </div>
            );
          })}
          {!items.length && <div className="table-empty">暂无 MR，请绑定 Git 仓库链接后同步。</div>}
        </div>
      </div>
      <div className="table-footer">
        <span>共 {items.length} 条</span>
        <div className="pager">
          <button disabled><ChevronLeft size={16} /></button>
          <button className="active">1</button>
          <button disabled><ChevronRight size={16} /></button>
        </div>
        <button className="page-size">20 条/页 <ChevronDown size={14} /></button>
      </div>
    </section>
  );
}

export function FilterSelect({
  label,
  value,
  options,
  onChange
}: {
  label: string;
  value: string;
  options: Array<[string, string]>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="filter-select">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>{optionLabel}</option>
        ))}
      </select>
    </label>
  );
}

export function RiskBadge({ score }: { score: number }) {
  const level = riskLevel(score);
  const text = level === "high" ? "高" : level === "medium" ? "中" : "低";
  return <span className={`risk-badge ${level}`}>{text}</span>;
}

export function StatusBadge({ status, title }: { status: string; title?: string }) {
  return <span className={`status-badge ${status}`} title={title || statusLabel(status)}>{statusLabel(status)}</span>;
}

export function DetailPanel({
  detail,
  busy,
  onRerun,
  onToggleFinding,
  onToggleAllFindings,
  onFalsePositive,
  onBulkFalsePositive,
  onExportMarkdown,
  onPublish,
  projectId
}: {
  detail: Detail | null;
  busy: boolean;
  onRerun: () => void;
  onToggleFinding: (finding: Finding) => void;
  onToggleAllFindings: (selected: boolean) => void;
  onFalsePositive: (finding: Finding) => void;
  onBulkFalsePositive: () => void;
  onExportMarkdown: () => void;
  onPublish: () => void;
  projectId: string;
}) {
  const [tab, setTab] = useState<"findings" | "process" | "tools">("findings");
  const [activeFinding, setActiveFinding] = useState<Finding | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const activeStatus = detail ? effectiveReviewStatus(detail) : "";
  useEffect(() => {
    if (!ACTIVE_REVIEW_STATUSES.includes(activeStatus)) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [activeStatus]);

  if (!detail) {
    return (
      <section className="detail-panel empty-detail">
        <Circle size={34} />
        <strong>选择一个 MR</strong>
        <span>右侧将展示检视进度、问题和提交操作。</span>
      </section>
    );
  }

  const hasRun = detail.runs.length > 0;
  const selectedCount = detail.findings.filter((finding) => finding.selected).length;
  const selectedAlreadyPublishedCount = detail.findings.filter((finding) => finding.selected && isAlreadyPublishedFinding(finding)).length;
  const allSelected = detail.findings.length > 0 && selectedCount === detail.findings.length;
  const highCount = detail.findings.filter((finding) => finding.severity === "high" || finding.severity === "critical").length;
  const agentCount = participatingAgentIds(detail).length;
  const duration = estimateDuration(detail, now);
  const currentStatus = effectiveReviewStatus(detail);
  const terminal = isTerminalMrStatus(currentStatus);
  const terminalReason = currentStatus === "merged" ? "该 MR 已合入，不能再重新检视或提交检视意见。" : currentStatus === "closed" ? "该 MR 已关闭，不能再重新检视或提交检视意见。" : "";
  const sortedFindings = sortFindingsBySeverity(detail.findings);

  return (
    <section className="detail-panel">
      <div className="detail-content">
        <div className="detail-title">
          <h2>!{detail.mr.number} {detail.mr.title}</h2>
          <p>
            <span>{detail.mr.source_branch}</span>
            <ChevronRight size={14} />
            <a href={detail.mr.html_url} target="_blank" rel="noreferrer">{detail.mr.target_branch}</a>
            <span>·</span>
            <span>{detail.mr.repository_name}</span>
            <span>·</span>
            <span>{detail.mr.author}</span>
            <span>· 风险分</span>
            <strong className={`risk-score ${riskLevel(detail.mr.risk_score)}`}>{detail.mr.risk_score}</strong>
          </p>
        </div>

        <ReviewProgressPanel detail={detail} status={currentStatus} />

        <div className="metric-row">
          <MetricCard icon={<Code2 />} value={detail.findings.length} label="个问题" sub="待确认问题" />
          <MetricCard icon={<ShieldCheck />} value={highCount} label="高危" sub="高危问题" danger />
          <MetricCard icon={<Users />} value={agentCount} label="个 Agent" sub="参与检视" />
          <MetricCard icon={<Clock3 />} value={duration} label="" sub="检视耗时" />
        </div>

        <div className="detail-tabs">
          {[
            ["findings", "检视问题"],
            ["process", "检视过程"],
            ["tools", `工具结果 (${detail.tool_observations?.length || 0})`]
          ].map(([key, label]) => (
            <button key={key} type="button" className={tab === key ? "active" : ""} onClick={() => setTab(key as typeof tab)}>
              {label}
            </button>
          ))}
        </div>

        {tab === "findings" && (
          <div className="findings-list">
            {sortedFindings.map((finding) => (
              <FindingRow
                key={finding.id}
                finding={finding}
                onToggle={() => onToggleFinding(finding)}
                onFalsePositive={() => onFalsePositive(finding)}
                onOpen={() => setActiveFinding(finding)}
              />
            ))}
            {hasRun && <CoverageCard run={detail.runs[0]} />}
            {!detail.findings.length && !hasRun && (
              <div className="empty-finding pending">
                <Loader2 className="spin" size={22} />
                <strong>检视任务尚未完成</strong>
                <span>该 MR 已提交检视，系统会先读取代码变更，再进行工具检查和 AI 专家分析。</span>
              </div>
            )}
          </div>
        )}

        {tab === "process" && <ProcessTimeline detail={detail} />}
        {tab === "tools" && <ToolResultsPanel detail={detail} onOpenFinding={setActiveFinding} />}
      </div>

      <div className="detail-actions">
        {terminalReason && (
          <div className="publish-duplicate-warning terminal" role="status">
            <AlertTriangle size={16} />
            <span>{terminalReason}</span>
          </div>
        )}
        {selectedAlreadyPublishedCount > 0 && (
          <div className="publish-duplicate-warning" role="status">
            <AlertTriangle size={16} />
            <span>已选 {selectedAlreadyPublishedCount} 条问题已提交过，本次提交会自动跳过，避免重复提交。</span>
          </div>
        )}
        <button type="button" onClick={() => onToggleAllFindings(!allSelected)} disabled={busy || !detail.findings.length}>
          <Check size={18} />
          {allSelected ? "取消全选" : "全选问题"}
        </button>
        <button type="button" onClick={onBulkFalsePositive} disabled={busy || !selectedCount}>标记误报</button>
        <button type="button" onClick={onExportMarkdown} disabled={busy || !detail.findings.length}>
          <FileDown size={18} />
          导出 MD
        </button>
        <button type="button" onClick={onRerun} disabled={busy || terminal}>重新检视</button>
        <button className="submit-button" type="button" onClick={onPublish} disabled={busy || terminal || !selectedCount}>
          <Send size={18} />
          提交选中意见到 CodeHub
        </button>
      </div>
      {activeFinding && (
        <FindingDetailModal
          finding={activeFinding}
          mr={detail.mr}
          projectId={projectId}
          onClose={() => setActiveFinding(null)}
        />
      )}
    </section>
  );
}

export function ReviewProgressPanel({ detail, status }: { detail: Detail; status: string }) {
  const index = reviewStepIndex(status);
  const latestJob = detail.jobs?.[0] || {};
  const latestRun = detail.runs?.[0] || {};
  const sessionLogs = detail.session_logs;
  const toolCount = sessionLogs?.tool_calls?.length || detail.tool_observations?.length || 0;
  const llmStats = llmCallStats(sessionLogs?.llm_calls);
  const skillCalls = skillCallRows(detail);
  const agentMessages = sessionLogs?.messages?.length || 0;
  const percent = Math.round((index / (REVIEW_STEPS.length - 1)) * 100);
  return (
    <section className="review-progress-card">
      <div className="review-progress-head">
        <div>
          <span>当前检视进度</span>
          <strong>{REVIEW_STEPS[index]?.label || statusLabel(status)}</strong>
          <p>{REVIEW_STEPS[index]?.description || statusLabel(status)}</p>
        </div>
        <StatusBadge status={status} />
      </div>
      <div className="review-progress-bar" aria-label={`检视进度 ${percent}%`}>
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="review-step-grid">
        {REVIEW_STEPS.map((step, stepIndex) => (
          <div className={`${stepIndex <= index ? "active" : ""} ${stepIndex === index ? "current" : ""}`} key={step.key}>
            <span>{stepIndex < index ? <Check size={13} /> : stepIndex + 1}</span>
            <strong>{step.label}</strong>
          </div>
        ))}
      </div>
      <div className="review-progress-meta">
        <p><strong>Job</strong><span>{String(latestJob.id || "--")}</span></p>
        <p><strong>Run</strong><span>{String(latestRun.id || "--")}</span></p>
        <p><strong>工具调用</strong><span>{toolCount}</span></p>
        <p><strong>LLM 调用</strong><span>{llmStats.total}</span></p>
        <p><strong>LLM 成功率</strong><span>{llmStats.successRate === null ? "--" : `${llmStats.succeeded}/${llmStats.total} · ${llmStats.successRate}%`}</span></p>
        <p><strong>Skill 调用</strong><span>{skillCalls.length}</span></p>
        <p><strong>Agent 消息</strong><span>{agentMessages}</span></p>
      </div>
    </section>
  );
}

function coverageNumber(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function coverageCount(value: unknown) {
  const parsed = coverageNumber(value);
  return parsed === null ? 0 : parsed;
}

function formatCoveragePercent(value: unknown) {
  const parsed = coverageNumber(value);
  return parsed === null ? "--" : `${Math.round(parsed * 100)}%`;
}

export function CoverageCard({ run }: { run?: Record<string, unknown> }) {
  const coverage = safeJson(String(run?.coverage_json || "{}"));
  const tools = Array.isArray(coverage.tools) ? coverage.tools as Array<Record<string, unknown>> : [];
  const agents = Array.isArray(coverage.agents_executed) ? coverage.agents_executed.map((item) => String(item)) : [];
  const candidateQuality = typeof coverage.candidate_quality === "object" && coverage.candidate_quality ? coverage.candidate_quality as Record<string, unknown> : {};
  const boundReviewCoverage = (
    typeof candidateQuality.bound_review_coverage === "object" && candidateQuality.bound_review_coverage
      ? candidateQuality.bound_review_coverage
      : coverage.bound_review_coverage
  ) as Record<string, unknown> | undefined;
  const requiredBoundRules = coverageCount(boundReviewCoverage?.required_count);
  const resolvedBoundRules = coverageCount(boundReviewCoverage?.resolved_count);
  const unresolvedBoundRules = coverageCount(boundReviewCoverage?.unresolved_count ?? boundReviewCoverage?.missed_count);
  const hasBoundCoverage = requiredBoundRules > 0;
  return (
    <div className="coverage-card">
      <div>
        <CheckCircle2 size={22} />
        <strong>检视覆盖情况</strong>
        <span>来自本次真实工具调用、工具观察和 Agent trace。</span>
      </div>
      {tools.slice(0, 8).map((tool) => (
        <p key={String(tool.id)}>
          <Check size={15} />
          <span>{String(tool.id)}</span>
          <em>{String(tool.completed_calls || 0)} completed · {String(tool.skipped_calls || 0)} skipped</em>
          <strong>{String(tool.hits || 0)} 命中</strong>
        </p>
      ))}
      {!tools.length && <p><Check size={15} /><span>暂无 coverage_json</span><em>等待检视完成</em><strong>--</strong></p>}
      {hasBoundCoverage && (
        <>
          <p>
            <ShieldCheck size={15} />
            <span>绑定规则闭环</span>
            <em>{resolvedBoundRules}/{requiredBoundRules} 已闭环 · 覆盖 {formatCoveragePercent(boundReviewCoverage?.coverage_rate)}</em>
            <strong>{formatCoveragePercent(boundReviewCoverage?.resolution_rate)}</strong>
          </p>
          <p>
            <AlertTriangle size={15} />
            <span>未闭环规则</span>
            <em>命中 {String(boundReviewCoverage?.hit_count || 0)} · 跳过 {String(boundReviewCoverage?.skipped_count || 0)}</em>
            <strong>{unresolvedBoundRules}</strong>
          </p>
        </>
      )}
      {agents.length > 0 && (
        <p>
          <Check size={15} />
          <span>专家 Agent</span>
          <em>{agents.slice(0, 4).map(agentLabel).join(", ")}</em>
          <strong>{agents.length} 个</strong>
        </p>
      )}
    </div>
  );
}

export function ReviewRunCompare({ compare }: { compare?: Detail["compare"] }) {
  if (!compare?.head_run) {
    return <div className="empty-finding">暂无可对比的检视记录</div>;
  }
  return (
    <div className="compare-grid">
      <CompareColumn title="新增问题" tone="danger" items={compare.added || []} />
      <CompareColumn title="已解决" tone="success" items={compare.resolved || []} />
      <CompareColumn title="仍存在" tone="muted" items={compare.retained || []} />
    </div>
  );
}

export function CompareColumn({ title, tone, items }: { title: string; tone: "danger" | "success" | "muted"; items: Finding[] }) {
  return (
    <section className={`compare-column ${tone}`}>
      <h3>{title}<strong>{items.length}</strong></h3>
      {items.slice(0, 12).map((finding) => (
        <article key={finding.id}>
          <SeverityBadge severity={finding.severity} />
          <strong>{finding.title}</strong>
          <span>{formatFindingLocation(finding)}</span>
        </article>
      ))}
      {!items.length && <p>无变化</p>}
    </section>
  );
}

export function ProcessTimeline({ detail }: { detail: Detail }) {
  const isSummaryNoise = (row: Record<string, unknown>) =>
    String(row.span_key || "").includes("summarize_pr") ||
    String(row.agent_id || "").includes("summary_agent");
  const trace = (detail.trace || []).filter((row) => !isSummaryNoise(row));
  const sessionLogs = detail.session_logs;
  const toolCalls = (sessionLogs?.tool_calls || []).filter((row) => !isSummaryNoise(row));
  const staticToolCalls = toolCalls.filter((row) => String(row.tool_name || "").startsWith("static."));
  const llmCalls = (sessionLogs?.llm_calls || []).filter((row) => !isSummaryNoise(row));
  const llmStats = llmCallStats(llmCalls);
  const skillCalls = skillCallRows(detail).filter((row) => !isSummaryNoise(row));
  const latestJob = detail.jobs?.[0] || {};
  const latestRun = detail.runs?.[0] || {};
  const status = effectiveReviewStatus(detail);
  const groups = [
    ["Agent 对话", (sessionLogs?.messages || []).filter((row) => !isSummaryNoise(row)), "content_summary"],
    ["工具调用", toolCalls, "output_summary"],
    ["LLM 调用", llmCalls, "status"],
    ["MCP 调用", (sessionLogs?.mcp_calls || []).filter((row) => !isSummaryNoise(row)), "status"],
    ["Artifacts", sessionLogs?.artifacts || [], "name"]
  ] as const;
  return (
    <div className="process-panel">
      <section className="process-overview">
        <div>
          <span>检视阶段</span>
          <strong>{statusLabel(status)}</strong>
          <p>{REVIEW_STEPS[reviewStepIndex(status)]?.description || "等待检视状态刷新"}</p>
        </div>
        <p><strong>Job 状态</strong><span>{String(latestJob.status || "--")}</span></p>
        <p><strong>Run 状态</strong><span>{String(latestRun.status || "--")}</span></p>
        <p><strong>Trace</strong><span>{trace.length} 条</span></p>
        <p><strong>Tool</strong><span>{sessionLogs?.tool_calls?.length || detail.tool_observations?.length || 0} 次</span></p>
        <p><strong>LLM</strong><span>{llmStats.total} 次 · 成功率 {llmStats.successRate === null ? "--" : `${llmStats.successRate}%`}</span></p>
        <p><strong>Skill</strong><span>{skillCalls.length} 次</span></p>
      </section>
      <div className="process-list">
        {trace.slice(0, 80).map((item, index) => (
          <article key={index}>
            <span />
            <div>
              <strong>{String(item.span_key || item.event_type || "trace")}</strong>
              <p>{String(item.summary || item.status || "执行记录")}</p>
              <small>
                <time>{formatDateTime(recordTimestamp(item))}</time>
                <em>{String(item.agent_id || item.event_type || "system")}</em>
              </small>
            </div>
          </article>
        ))}
        {!trace.length && <div className="process-empty">当前阶段尚未写入 trace，列表状态会随 Job 状态实时刷新。</div>}
      </div>
      <section className="static-tool-detail">
        <h4>静态工具调用明细<strong>{staticToolCalls.length}</strong></h4>
        <div className="static-tool-table">
          <div className="static-tool-head">
            <span>工具</span>
            <span>状态</span>
            <span>时间</span>
            <span>耗时</span>
            <span>输出</span>
            <span>Artifact</span>
          </div>
          {staticToolCalls.map((row, index) => {
            const outputRef = safeJson(String(row.output_ref_json || "{}"));
            const artifact = String(outputRef.path || outputRef.artifact || "--");
            return (
              <div className="static-tool-row" key={`${String(row.tool_name)}-${index}`}>
                <strong>{String(row.tool_name || "--")}</strong>
                <em className={`tool-run-status ${String(row.status || "").replace(/[^a-z0-9_-]/gi, "_")}`}>{String(row.status || "--")}</em>
                <time>{formatDateTime(recordTimestamp(row))}</time>
                <span>{formatDurationMs(row.duration_ms)}</span>
                <p>{String(row.output_summary || "--")}</p>
                <small title={artifact}>{artifact}</small>
              </div>
            );
          })}
          {!staticToolCalls.length && <div className="static-tool-empty">本次还没有静态工具调用记录</div>}
        </div>
      </section>
      <section className="skill-call-detail">
        <h4>Agent Skill 调用记录<strong>{skillCalls.length}</strong></h4>
        <div className="skill-call-list">
          {skillCalls.slice(0, 12).map((row, index) => (
            <article key={`${String(row.id || row.skill_key || "skill")}-${index}`}>
              <div>
                <strong>{agentLabel(String(row.agent_id || row.span_key || "agent"))}</strong>
                <span>{String(row.skill_key || "--")}</span>
              </div>
              <em className={`skill-stage ${String(row.stage || "recorded").replace(/[^a-z0-9_-]/gi, "_")}`}>{skillStageText(row.stage)}</em>
              <time>{formatDateTime(recordTimestamp(row))}</time>
              <p>{String(row.batch_label || row.summary || skillStatusText(row.status))}</p>
              <small title={skillAssetSummary(row)}>{skillAssetSummary(row)}</small>
            </article>
          ))}
          {!skillCalls.length && <div className="skill-call-empty">本次还没有 Agent 调用 Skill 的记录</div>}
        </div>
      </section>
      <div className="session-grid">
        {groups.map(([title, rows, summaryKey]) => (
          <section key={title}>
            <h4>{title}<strong>{rows.length}</strong></h4>
            {rows.slice(0, 4).map((row, index) => (
              <p key={index}>
                <span>{String(row.span_key || row.tool_name || row.model || row.artifact_type || row.from_agent || title)}</span>
                <time>{formatDateTime(recordTimestamp(row))}</time>
                <em>{String(row[summaryKey] || row.status || row.output_summary || row.storage_uri || "--")}</em>
              </p>
            ))}
            {!rows.length && <p><span>--</span><em>本次未调用</em></p>}
          </section>
        ))}
      </div>
    </div>
  );
}

export function ContextRules({ runs, mr }: { runs: Array<Record<string, unknown>>; mr: MergeRequest }) {
  const run = runs[0];
  const policy = safeJson(String(run?.data_policy_snapshot || "{}"));
  const budget = safeJson(String(run?.budget_json || "{}"));
  const budgetUsed = safeJson(String(run?.budget_used_json || "{}"));
  const budgetStatus = budgetUsed.truncated_reason
    ? `已截断 ${String(budgetUsed.truncated_reason)}`
    : "未截断";
  return (
    <div className="context-panel">
      <p><strong>规则来源</strong><span>{String(run?.rule_version_source || "target_branch")}</span></p>
      <p><strong>检视强度</strong><span>{String(run?.effort_level || "standard")}</span></p>
      <p><strong>Sandbox</strong><span>{String(run?.sandbox_uri || "--")}</span></p>
      <p><strong>数据策略</strong><span>{String(policy.default_llm_provider || "internal-minimax-2.7")} · {String(policy.prompt_retention || "hash_only")}</span></p>
      <p><strong>预算策略</strong><span>{String(budget.effort || run?.effort_level || "standard")} · {String(budget.max_llm_calls ?? "--")} calls · {String(budget.max_wall_seconds || "--")}s</span></p>
      <p><strong>预算用量</strong><span>{String(budgetUsed.llm_calls || 0)} calls · {budgetStatus}</span></p>
      <p><strong>目标仓库</strong><span>{mr.repository_name} · {mr.target_branch}</span></p>
    </div>
  );
}

export function MetricCard({ icon, value, label, sub, danger }: { icon: React.ReactElement<{ size?: number }>; value: number | string; label: string; sub: string; danger?: boolean }) {
  return (
    <div className="metric-card">
      <span className={`metric-icon ${danger ? "danger" : ""}`}>{React.cloneElement(icon, { size: 30 })}</span>
      <strong>{value} {label}</strong>
      <small>{sub}</small>
    </div>
  );
}

export function FindingRow({
  finding,
  onToggle,
  onFalsePositive,
  onOpen
}: {
  finding: Finding;
  onToggle: () => void;
  onFalsePositive: () => void;
  onOpen: () => void;
}) {
  const source = findingSource(finding);
  const alreadyPublished = isAlreadyPublishedFinding(finding);
  return (
    <article className={`finding-row ${alreadyPublished ? "already-published" : ""}`} onClick={onOpen} role="button" tabIndex={0} onKeyDown={(event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onOpen();
      }
    }}>
      <label onClick={(event) => event.stopPropagation()}>
        <input type="checkbox" checked={Boolean(finding.selected)} onChange={onToggle} />
        <SeverityBadge severity={finding.severity} />
      </label>
      <span className="agent-pill">{agentLabel(finding.agent_id)}</span>
      <span className={`finding-source-tag ${source.type}`} title={source.detail}>{source.label}</span>
      <span
        className={`publish-state-badge ${finding.publish_state || "pending"}`}
        title={alreadyPublished ? "该问题已提交过，再次提交时会自动跳过" : publishStateLabel(finding.publish_state || "pending")}
      >
        {publishStateLabel(finding.publish_state || "pending")}
      </span>
      <span className="confidence">{finding.confidence.toFixed(2)}</span>
      <div className="finding-main">
        <div className="finding-location-line">
          <a title={finding.file_path}>{finding.file_path || "未定位文件"}</a>
          <span>{formatFindingLineRange(finding)}</span>
        </div>
        <strong>{finding.title}</strong>
        <small className="finding-description">
          {alreadyPublished ? "该问题已提交过，本次不会重复提交。" : (finding.problem_description || finding.recommendation || "暂无问题描述")}
        </small>
      </div>
      <button type="button" onClick={(event) => {
        event.stopPropagation();
        onFalsePositive();
      }}>{finding.lifecycle_state === "false_positive" ? "已误报" : "标误报"}</button>
    </article>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`severity-badge ${severity}`}>{severityText(severity)}</span>;
}

export function FindingDetailModal({
  finding,
  mr,
  projectId,
  onClose
}: {
  finding: Finding;
  mr: MergeRequest;
  projectId: string;
  onClose: () => void;
}) {
  const [sourceCode, setSourceCode] = useState("");
  const [sourcePatch, setSourcePatch] = useState("");
  const [sourceByPath, setSourceByPath] = useState<Record<string, string>>({});
  const [patchByPath, setPatchByPath] = useState<Record<string, string>>({});
  const [sourceLoading, setSourceLoading] = useState(false);
  const [ruleDetails, setRuleDetails] = useState<RuleDetail[]>([]);
  const [ruleDetailsLoading, setRuleDetailsLoading] = useState(false);
  const coveredRules = parseJsonArray(finding.covered_rules_json);
  const skippedRules = parseJsonArray(finding.skipped_rules_json);
  const sourceObservations = parseJsonObjectArray(finding.source_observations_json);
  const toolProvenance = parseJsonObjectArray(finding.tool_provenance_json);
  const qualityTrace = safeJson(String(finding.quality_trace_json || "{}"));
  const evidenceScore = safeJson(String(finding.evidence_score_json || JSON.stringify(qualityTrace.evidence_score || {})));
  const evidenceContract = (
    qualityTrace.evidence_contract && typeof qualityTrace.evidence_contract === "object"
      ? qualityTrace.evidence_contract
      : {}
  ) as Record<string, unknown>;
  const traceLocation = qualityTrace.location as Record<string, unknown> | undefined;
  const location = formatFindingLocation(finding);
  const suggestedCode = (finding.suggested_code || extractSuggestedCode(finding.recommendation)).trim();
  const primaryRules = coveredRules.length ? coveredRules : ["未声明具体 rule_id"];
  const ruleKey = primaryRules.join(",");
  const sourcePaths = Array.from(new Set(
    [
      finding.file_path,
      ...sourceObservations.map(observationFilePath)
    ].map((value) => String(value || "").trim()).filter(Boolean)
  ));
  const sourcePathKey = sourcePaths.join("\n");
  useEffect(() => {
    let cancelled = false;
    async function loadSource() {
      if (!mr.id || !sourcePaths.length) return;
      setSourceLoading(true);
      const nextPatchByPath: Record<string, string> = {};
      let changedFilePaths: string[] = [];
      try {
        const files = await api<unknown>(`/api/vcs/${projectId}/merge-requests/${mr.id}/files`);
        for (const file of normalizeMrChangedFiles(files)) {
          const fileName = normalizeRepositoryPath(file.filename || "");
          if (fileName) {
            changedFilePaths.push(fileName);
            nextPatchByPath[fileName] = file.patch || "";
          }
        }
      } catch {
        // Source file loading below still gives useful context when changed-file metadata is unavailable.
      } finally {
        const nextSourceByPath: Record<string, string> = {};
        const resolvedSourcePaths = Array.from(new Set(sourcePaths.map((filePath) => (
          matchRepositoryPath(filePath, changedFilePaths) || normalizeRepositoryPath(filePath)
        )).filter(Boolean)));
        await Promise.all(resolvedSourcePaths.map(async (filePath) => {
          try {
            const result = await api<{ content: string }>(
              `/api/vcs/${projectId}/merge-requests/${mr.id}/file?path=${encodeURIComponent(filePath)}&sha=${encodeURIComponent(mr.latest_head_sha || "")}`
            );
            nextSourceByPath[filePath] = result.content || "";
          } catch {
            nextSourceByPath[filePath] = "";
          }
        }));
        if (!cancelled) {
          setPatchByPath(nextPatchByPath);
          setSourceByPath(nextSourceByPath);
          setSourceCode(readPathMap(nextSourceByPath, finding.file_path));
          setSourcePatch(readPathMap(nextPatchByPath, finding.file_path));
        }
        if (!cancelled) setSourceLoading(false);
      }
    }
    loadSource();
    return () => {
      cancelled = true;
    };
  }, [finding.id, finding.file_path, mr.id, mr.latest_head_sha, projectId, sourcePathKey]);
  useEffect(() => {
    let cancelled = false;
    async function loadRuleDetails() {
      const ruleIds = primaryRules.filter((rule) => rule !== "未声明具体 rule_id");
      if (!ruleIds.length) {
        setRuleDetails([]);
        return;
      }
      setRuleDetailsLoading(true);
      try {
        const result = await api<{ items: RuleDetail[] }>(
          `/api/projects/${projectId}/rule-details?rule_ids=${encodeURIComponent(ruleIds.join(","))}`
        );
        if (!cancelled) setRuleDetails(result.items || []);
      } catch {
        if (!cancelled) setRuleDetails(ruleIds.map((rule) => ({ rule_id: rule, title: rule, missing: true })));
      } finally {
        if (!cancelled) setRuleDetailsLoading(false);
      }
    }
    loadRuleDetails();
    return () => {
      cancelled = true;
    };
  }, [projectId, ruleKey]);
  const problemLines = sourceCode
    ? sourceCodeWindow(sourceCode, finding.line_start || 1, finding.line_end || finding.line_start || 1)
    : sourcePatch
      ? diffCodeWindow(sourcePatch, finding.line_start || 1, finding.line_end || finding.line_start || 1)
      : textCodeLines(finding.evidence || location, finding.line_start || 1);
  const suggestionLines = textCodeLines(suggestedCode || "// 当前 finding 未提供明确代码片段，请重新检视生成建议修改代码。", finding.line_start || 1);
  const evidenceCount = sourceObservations.length || toolProvenance.length;
  const source = findingSource(finding);
  const ruleDetailsById = Object.fromEntries(ruleDetails.map((rule) => [rule.rule_id, rule]));
  const sourceLinesForTarget = (filePath: string, startLine: number, endLine: number, fallback: string) => {
    const resolvedFilePath = matchRepositoryPath(filePath, [...Object.keys(patchByPath), ...Object.keys(sourceByPath)]);
    const patch = readPathMap(patchByPath, resolvedFilePath || filePath);
    const source = readPathMap(sourceByPath, resolvedFilePath || filePath);
    const safeStart = startLine > 0 ? startLine : 1;
    const safeEnd = endLine > 0 ? endLine : safeStart;
    if (source) return sourceCodeWindow(source, safeStart, safeEnd);
    const patchLines = patch ? diffCodeWindow(patch, safeStart, safeEnd) : [];
    if (patchLines.length) return patchLines;
    return textCodeLines(fallback || `${filePath}:${safeStart}`, safeStart);
  };
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="finding-modal" onClick={(event) => event.stopPropagation()}>
        <header className="finding-modal-header">
          <div className="finding-modal-title">
            <div className="finding-modal-kicker">
              <SeverityBadge severity={finding.severity} />
              <span className={`finding-source-tag ${source.type}`}>{source.label}</span>
              <span>{agentLabel(finding.agent_id)}</span>
              <span>置信度 {finding.confidence.toFixed(2)}</span>
              {finding.publish_state && (
                <span className={`publish-state-badge ${finding.publish_state}`}>
                  {publishStateLabel(finding.publish_state)}
                </span>
              )}
            </div>
            <strong>{finding.title}</strong>
            <p>
              <span title={location}>{location}</span>
              <em>{primaryRules.slice(0, 3).join(" / ")}</em>
              {primaryRules.length > 3 && <em>+{primaryRules.length - 3}</em>}
            </p>
          </div>
        </header>

        <div className="finding-core-stack">
          <section className="finding-core-card">
            <h3>问题描述</h3>
            <p>{finding.problem_description || "暂无问题描述。"}</p>
          </section>
          <section className="finding-core-card fix">
            <h3>修复建议</h3>
            <p>{finding.recommendation || "暂无修复建议。"}</p>
          </section>
        </div>

        <div className="finding-detail-section finding-code-stack">
          <h3>问题代码</h3>
          <GithubCodeBlock
            filePath={finding.file_path}
            label={sourceLoading ? "正在加载源代码" : "源问题代码"}
            location={location}
            lines={problemLines}
            highlightStart={finding.line_start || undefined}
            highlightEnd={finding.line_end || finding.line_start || undefined}
          />
        </div>

        <div className="finding-detail-section finding-code-stack">
          <h3>建议修复代码</h3>
          <GithubCodeBlock
            filePath={finding.file_path}
            label="建议代码"
            location={location}
            lines={suggestionLines}
            mode="suggestion"
          />
        </div>

        <details className="finding-collapsible-card">
          <summary>
            <span>违反规范</span>
            <em>{primaryRules.length} 条</em>
          </summary>
          <div className="finding-detail-section finding-rule-section">
            <div className="rule-detail-list">
              {primaryRules.map((rule) => (
                <RuleDetailCard
                  key={rule}
                  ruleId={rule}
                  detail={ruleDetailsById[rule]}
                  loading={ruleDetailsLoading}
                />
              ))}
            </div>
            {skippedRules.length > 0 && <small>已检查未命中：{skippedRules.join(", ")}</small>}
          </div>
        </details>

        <details className="finding-collapsible-card">
          <summary>
            <span>质量追溯</span>
            <em>{evidenceCount} 条证据</em>
          </summary>
          <div className="finding-detail-section finding-trace-section">
            <dl className="trace-list">
              <div>
                <dt>专家</dt>
                <dd>{agentLabel(String(qualityTrace.agent_id || finding.agent_id))}</dd>
              </div>
              <div>
                <dt>定位</dt>
                <dd>{formatTraceLocation(traceLocation) || location}</dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>{source.label}</dd>
              </div>
              <div>
                <dt>证据合同</dt>
                <dd>{formatEvidenceContractStatus(evidenceContract)}</dd>
              </div>
              <div>
                <dt>证据分</dt>
                <dd>{formatEvidenceContractScore(evidenceContract)}</dd>
              </div>
              <div>
                <dt>结构证据</dt>
                <dd>{formatEvidenceScore(evidenceScore)}</dd>
              </div>
              <div>
                <dt>证据组件</dt>
                <dd>{formatEvidenceScoreComponents(evidenceScore)}</dd>
              </div>
              <div>
                <dt>缺失项</dt>
                <dd>{formatEvidenceContractMissing(evidenceContract)}</dd>
              </div>
              <div>
                <dt>去重指纹</dt>
                <dd>{String(qualityTrace.dedupe_hash || finding.id)}</dd>
              </div>
            </dl>
          </div>
        </details>

        <details className="finding-collapsible-card">
          <summary>
            <span>工具证据</span>
            <em>{sourceObservations.length || 0} 条</em>
          </summary>
          <div className="finding-detail-section">
            {sourceObservations.length ? (
              <div className="tool-evidence-list">
                {sourceObservations.map((item, index) => (
                  <article key={`${String(item.tool_name || "tool")}-${index}`}>
                    <div>
                      <strong>{String(item.tool_name || "unknown_tool")}</strong>
                      {item.rule_id !== undefined && item.rule_id !== null && <span>{String(item.rule_id)}</span>}
                      {item.confidence !== undefined && item.confidence !== null && <em>{Number(item.confidence).toFixed(2)}</em>}
                    </div>
                    <p>{String(item.message || "工具命中候选问题")}</p>
                    <small>{formatObservationLocation(item)}</small>
                    {observationFilePath(item) && (
                      <GithubCodeBlock
                        filePath={observationFilePath(item)}
                        label="工具命中源码"
                        location={formatObservationLocation(item)}
                        lines={sourceLinesForTarget(
                          observationFilePath(item),
                          observationLineStart(item),
                          observationLineEnd(item),
                          String(item.evidence || item.message || "工具命中候选问题")
                        )}
                        highlightStart={observationLineStart(item)}
                        highlightEnd={observationLineEnd(item)}
                      />
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <small>该问题由专家直接提出，当前未匹配到静态工具证据。</small>
            )}
            {toolProvenance.length > sourceObservations.length && <small>同时记录了 {toolProvenance.length} 条 provenance 元数据。</small>}
          </div>
        </details>
      </section>
    </div>
  );
}

export function RuleDetailCard({ ruleId, detail, loading }: { ruleId: string; detail?: RuleDetail; loading: boolean }) {
  const sections = detail?.sections || {};
  const preferredSections = ["规范说明", "检查点", "如何检查", "反例", "正例", "说明"];
  const visibleSections = preferredSections
    .map((name) => [name, sections[name]] as [string, string | undefined])
    .filter(([, value]) => value && value.trim());
  return (
    <article className={`rule-detail-card ${detail?.missing ? "missing" : ""}`}>
      <header>
        <div>
          <strong>{ruleId}</strong>
          <span>{loading ? "正在加载规范详情..." : (detail?.document_name || "项目规范")}</span>
        </div>
        {detail?.version && <em>{detail.version}</em>}
      </header>
      <h4>{detail?.title || ruleId}</h4>
      {detail?.missing && <p>当前项目绑定的规范文档中未找到该 rule_id 的详细说明。</p>}
      {!detail?.missing && visibleSections.length > 0 && (
        <div className="rule-detail-sections">
          {visibleSections.map(([name, value]) => (
            <section key={name}>
              <span>{name}</span>
              <p>{value}</p>
            </section>
          ))}
        </div>
      )}
      {!detail?.missing && !visibleSections.length && detail?.raw_excerpt && <p>{detail.raw_excerpt}</p>}
    </article>
  );
}

export function GithubCodeBlock({
  filePath,
  label,
  location,
  lines,
  highlightStart,
  highlightEnd,
  mode = "source"
}: {
  filePath: string;
  label: string;
  location?: string;
  lines: ParsedDiffLine[];
  highlightStart?: number;
  highlightEnd?: number;
  mode?: "source" | "suggestion" | "diff";
}) {
  return (
    <div className="code-snippet github-code">
      <div className="code-snippet-toolbar">
        <span>{label}</span>
        {location && <em title={location}>{location}</em>}
        <strong>{languageLabel(filePath)}</strong>
      </div>
      <div className="github-code-table">
        {lines.map((line, index) => {
          const displayLine = line.kind === "del" ? line.oldLine : line.newLine;
          const highlighted = Boolean(
            highlightStart &&
            displayLine &&
            displayLine >= highlightStart &&
            displayLine <= (highlightEnd || highlightStart)
          );
          const marker = line.kind === "add" || mode === "suggestion" ? "+" : line.kind === "del" ? "-" : line.kind === "meta" ? "@@" : "";
          return (
            <div className={`github-code-line ${line.kind} ${highlighted ? "highlight" : ""} ${mode}`} key={`${displayLine ?? "meta"}-${index}`}>
              <span className="old-no">{line.oldLine ?? ""}</span>
              <span className="new-no">{line.newLine ?? ""}</span>
              <span className="diff-marker" aria-label={marker ? `${marker} 变更行` : "上下文行"}>{marker}</span>
              <code>{line.content || " "}</code>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function observationFilePath(item: Record<string, unknown>) {
  const location = item.location && typeof item.location === "object" ? item.location as Record<string, unknown> : {};
  return normalizeRepositoryPath(String(
    item.file_path ||
    item.path ||
    item.filename ||
    item.file ||
    location.file_path ||
    location.path ||
    location.uri ||
    ""
  ));
}

export function observationLineStart(item: Record<string, unknown>) {
  const location = item.location && typeof item.location === "object" ? item.location as Record<string, unknown> : {};
  const region = item.region && typeof item.region === "object" ? item.region as Record<string, unknown> : {};
  const value = Number(
    item.line_start ||
    item.start_line ||
    item.startLine ||
    item.line_number ||
    item.lineNumber ||
    item.line ||
    location.line_start ||
    location.start_line ||
    location.startLine ||
    location.line ||
    region.startLine ||
    0
  );
  return Number.isFinite(value) && value > 0 ? value : 0;
}

export function observationLineEnd(item: Record<string, unknown>) {
  const location = item.location && typeof item.location === "object" ? item.location as Record<string, unknown> : {};
  const region = item.region && typeof item.region === "object" ? item.region as Record<string, unknown> : {};
  const value = Number(
    item.line_end ||
    item.end_line ||
    item.endLine ||
    location.line_end ||
    location.end_line ||
    location.endLine ||
    region.endLine ||
    observationLineStart(item) ||
    0
  );
  return Number.isFinite(value) && value > 0 ? value : observationLineStart(item);
}

export function ToolResultsPanel({ detail, onOpenFinding }: { detail: Detail; onOpenFinding: (finding: Finding) => void }) {
  const [activeObservation, setActiveObservation] = useState<Record<string, unknown> | null>(null);
  const [toolPages, setToolPages] = useState<Record<string, number>>({});
  const toolCalls = detail.session_logs?.tool_calls || [];
  const observations = detail.tool_observations || [];
  const observationsByTool = observations.reduce<Record<string, Array<Record<string, unknown>>>>((acc, item) => {
    const key = String(item.tool_name || "unknown_tool");
    acc[key] = [...(acc[key] || []), item];
    return acc;
  }, {});
  const staticCalls = toolCalls.filter((row) => String(row.tool_name || "").startsWith("static."));
  const openObservation = (row: Record<string, unknown>) => {
    const matchedFinding = findFindingForObservation(detail.findings, row);
    if (matchedFinding) {
      onOpenFinding(matchedFinding);
      return;
    }
    setActiveObservation(row);
  };
  const pageSize = 12;
  const pageForTool = (key: string, total: number, size = pageSize) => {
    const totalPages = Math.max(1, Math.ceil(total / size));
    const current = Number(toolPages[key] || 1);
    return Math.max(1, Math.min(totalPages, Number.isFinite(current) ? current : 1));
  };
  const setPageForTool = (key: string, page: number, total: number, size = pageSize) => {
    const totalPages = Math.max(1, Math.ceil(total / size));
    const next = Math.max(1, Math.min(totalPages, page));
    setToolPages((current) => ({ ...current, [key]: next }));
  };
  return (
    <>
      <div className="tool-results-panel">
        {staticCalls.map((call, index) => {
          const toolName = String(call.tool_name || "static.tool");
          const rows = observationsByTool[toolName.replace(/^static\./, "")] || observationsByTool[toolName] || [];
          const toolKey = `${toolName}-${index}`;
          const currentPage = pageForTool(toolKey, rows.length);
          const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
          const visibleRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize);
          const outputRef = safeJson(String(call.output_ref_json || "{}"));
          return (
            <section className="tool-result-card" key={`${toolName}-${index}`}>
              <header>
                <div>
                  <strong>{toolName}</strong>
                  <span>{String(call.tool_version || "unknown version")}</span>
                </div>
                <em className={`tool-run-status ${String(call.status || "").replace(/[^a-z0-9_-]/gi, "_")}`}>{String(call.status || "--")}</em>
              </header>
              <div className="tool-result-meta">
                <p><span>耗时</span><strong>{formatDurationMs(call.duration_ms)}</strong></p>
                <p><span>命中</span><strong>{rows.length}</strong></p>
                <p><span>Artifact</span><strong title={String(outputRef.path || outputRef.artifact || "--")}>{shortPath(String(outputRef.path || outputRef.artifact || "--"))}</strong></p>
              </div>
              <p className="tool-output-summary">{String(call.output_summary || "工具已执行，暂无输出摘要。")}</p>
              <div className="tool-observation-table">
                {visibleRows.map((row, rowIndex) => (
                  <button className="tool-observation-row" type="button" key={rowIndex} onClick={() => openObservation(row)}>
                    <strong>{String(row.rule_id || "--")}</strong>
                    <span>{formatObservationLocation(row)}</span>
                    <em>{Number(row.confidence || 0).toFixed(2)}</em>
                    <p>{String(row.message || "--")}</p>
                  </button>
                ))}
                {rows.length > 12 && (
                  <ToolObservationPager
                    page={currentPage}
                    totalPages={totalPages}
                    total={rows.length}
                    pageSize={pageSize}
                    onPrev={() => setPageForTool(toolKey, currentPage - 1, rows.length)}
                    onNext={() => setPageForTool(toolKey, currentPage + 1, rows.length)}
                  />
                )}
                {!rows.length && <div className="static-tool-empty">该工具本次没有产生可归一化检测结果。</div>}
              </div>
            </section>
          );
        })}
        {!staticCalls.length && observations.length > 0 && (
          <section className="tool-result-card">
            <header>
              <div>
                <strong>tool_observations</strong>
                <span>归一化静态工具检测结果</span>
              </div>
              <em className="tool-run-status completed">completed</em>
            </header>
            <div className="tool-observation-table">
              {(() => {
                const toolKey = "tool_observations";
                const fallbackPageSize = 30;
                const currentPage = pageForTool(toolKey, observations.length, fallbackPageSize);
                return observations.slice((currentPage - 1) * fallbackPageSize, currentPage * fallbackPageSize).map((row, rowIndex) => (
                <button className="tool-observation-row" type="button" key={rowIndex} onClick={() => openObservation(row)}>
                  <strong>{String(row.rule_id || "--")}</strong>
                  <span>{formatObservationLocation(row)}</span>
                  <em>{Number(row.confidence || 0).toFixed(2)}</em>
                  <p>{String(row.message || "--")}</p>
                </button>
                ));
              })()}
              {observations.length > 30 && (
                <ToolObservationPager
                  page={pageForTool("tool_observations", observations.length, 30)}
                  totalPages={Math.max(1, Math.ceil(observations.length / 30))}
                  total={observations.length}
                  pageSize={30}
                  onPrev={() => setPageForTool("tool_observations", pageForTool("tool_observations", observations.length, 30) - 1, observations.length, 30)}
                  onNext={() => setPageForTool("tool_observations", pageForTool("tool_observations", observations.length, 30) + 1, observations.length, 30)}
                />
              )}
            </div>
          </section>
        )}
        {!staticCalls.length && !observations.length && <div className="empty-finding">暂无静态工具调用记录。</div>}
      </div>
      {activeObservation && <ToolObservationModal observation={activeObservation} onClose={() => setActiveObservation(null)} />}
    </>
  );
}

export function ToolObservationPager({
  page,
  totalPages,
  total,
  pageSize,
  onPrev,
  onNext
}: {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);
  return (
    <div className="tool-observation-footer">
      <span>第 {page}/{totalPages} 页，展示 {start}-{end} 条，共 {total} 条候选命中</span>
      <div>
        <button type="button" onClick={onPrev} disabled={page <= 1}>上一页</button>
        <button type="button" onClick={onNext} disabled={page >= totalPages}>下一页</button>
      </div>
    </div>
  );
}

export function findFindingForObservation(findings: Finding[], observation: Record<string, unknown>) {
  const obsPath = observationFilePath(observation);
  const obsRule = String(observation.rule_id || "");
  const obsLine = observationLineStart(observation);
  return findings.find((finding) => {
    const findingPath = normalizeRepositoryPath(finding.file_path || "");
    const sameFile = !obsPath || findingPath === obsPath || findingPath.endsWith(`/${obsPath}`) || obsPath.endsWith(`/${findingPath}`);
    const sameLine = !obsLine || !finding.line_start || Math.abs(Number(finding.line_start) - obsLine) <= 5;
    if (!sameFile || !sameLine) return false;
    const text = `${finding.covered_rules_json || ""} ${finding.tool_provenance_json || ""} ${finding.source_observations_json || ""}`;
    return !obsRule || text.includes(obsRule) || text.includes(canonicalDisplayRule(obsRule));
  });
}

export function canonicalDisplayRule(value: string) {
  return value.includes(".prescan.") ? value.split(".prescan.", 2)[1] : value;
}

export function ToolObservationModal({ observation, onClose }: { observation: Record<string, unknown>; onClose: () => void }) {
  const location = formatObservationLocation(observation);
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="tool-observation-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>{String(observation.tool_name || "静态工具")} · {String(observation.rule_id || "--")}</strong>
            <span>{location}</span>
          </div>
          <em>{Number(observation.confidence || 0).toFixed(2)}</em>
        </header>
        <div className="tool-observation-meta-grid">
          <article>
            <span>工具</span>
            <strong>{String(observation.tool_name || "--")}</strong>
          </article>
          <article>
            <span>规则</span>
            <strong>{String(observation.rule_id || "--")}</strong>
          </article>
          <article>
            <span>位置</span>
            <strong>{location}</strong>
          </article>
          <article>
            <span>置信度</span>
            <strong>{Number(observation.confidence || 0).toFixed(2)}</strong>
          </article>
        </div>
        <div className="finding-detail-section">
          <h3>检测结果</h3>
          <p>{String(observation.message || observation.title || "该工具命中候选问题。")}</p>
        </div>
        <div className="finding-detail-section">
          <h3>原始记录</h3>
          <pre className="tool-observation-json">{JSON.stringify(observation, null, 2)}</pre>
        </div>
      </section>
    </div>
  );
}

export function MrPreviewModal({
  detail,
  files,
  loading,
  onClose
}: {
  detail: Detail;
  files: MrChangedFile[];
  loading: boolean;
  onClose: () => void;
}) {
  const [activeFile, setActiveFile] = useState("");
  const safeFiles = useMemo(() => normalizeMrChangedFiles(files), [files]);
  useEffect(() => {
    if (!safeFiles.length) {
      if (activeFile) setActiveFile("");
      return;
    }
    if (!activeFile || !safeFiles.some((file) => file.filename === activeFile)) {
      setActiveFile(safeFiles[0].filename);
    }
  }, [activeFile, safeFiles]);
  const current = safeFiles.find((file) => file.filename === activeFile) || safeFiles[0] || null;
  const tree = buildFileTree(safeFiles);
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="mr-preview-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>!{detail.mr.number} {detail.mr.title}</strong>
            <span>{detail.mr.repository_name} · {detail.mr.source_branch} → {detail.mr.target_branch} · {detail.mr.author}</span>
          </div>
          <StatusBadge status={effectiveReviewStatus(detail)} />
        </header>
        <div className="mr-preview-body">
          <aside className="mr-file-tree">
            <strong>变更文件</strong>
            {loading && <p>正在加载 diff...</p>}
            {!loading && !tree.length && <p>暂无变更文件。可能是空提交、平台未返回文件列表，或该 MR 只有元数据变化。</p>}
            {!loading && tree.map((entry) => entry.kind === "directory" ? (
              <div
                key={entry.key}
                className={`mr-file-tree-node directory ${current?.filename?.startsWith(`${entry.path}/`) ? "contains-active" : ""}`}
                style={{ paddingLeft: `${10 + entry.depth * 14}px` }}
                title={entry.path}
              >
                <Folder size={14} />
                <span>{entry.name}</span>
              </div>
            ) : (
              <button
                key={entry.key}
                type="button"
                className={`mr-file-tree-node file ${current?.filename === entry.path ? "active" : ""}`}
                style={{ paddingLeft: `${10 + entry.depth * 14}px` }}
                onClick={() => setActiveFile(entry.path)}
                title={entry.path}
              >
                <FileCode2 size={14} />
                <span>
                  <strong>{entry.name}</strong>
                  <small>{entry.path}</small>
                </span>
                <em>{entry.status}</em>
              </button>
            ))}
          </aside>
          <main className="mr-diff-view">
            {current ? (
              <>
                <div className="mr-diff-head">
                  <div>
                    <strong title={current.filename}>{basename(current.filename)}</strong>
                    <small title={current.filename}>{current.filename}</small>
                  </div>
                  <span>+{current.additions || 0} / -{current.deletions || 0}</span>
                </div>
                <GithubCodeBlock
                  filePath={current.filename}
                  label="Diff"
                  location={current.filename}
                  lines={parseUnifiedPatch(current.patch || "")}
                  mode="diff"
                />
              </>
            ) : (
              <div className="empty-finding">暂无 diff 文件。</div>
            )}
          </main>
        </div>
      </section>
    </div>
  );
}

export function TracePreview({ trace }: { trace: Array<Record<string, unknown>> }) {
  if (!trace.length) return null;
  return (
    <details className="trace-preview">
      <summary>
        <SlidersHorizontal size={16} />
        检视过程 · {trace.length} 条记录
      </summary>
      <div>
        {trace.slice(0, 8).map((item, index) => (
          <p key={index}>
            <strong>{String(item.span_key || item.event_type || "trace")}</strong>
            <span>{String(item.summary || item.status || "执行记录")}</span>
          </p>
        ))}
      </div>
    </details>
  );
}

export function agentLabel(agentId: string) {
  const map: Record<string, string> = {
    performance_agent: "Performance Agent",
    security_agent: "Security Agent",
    coding_agent: "General Coding Agent",
    ddd_agent: "DDD Design Agent",
    frontend_agent: "Frontend Agent",
    test_agent: "Test Agent",
    redis_agent: "Redis Agent",
    backend_agent: "Backend Agent"
  };
  return map[agentId] || agentId;
}

export function estimateDuration(detail: Detail, now = Date.now()) {
  const run = detail.runs[0];
  const started = String(run?.started_at || "");
  const completed = String(run?.completed_at || "");
  const start = parseBackendTime(started)?.getTime();
  const end = completed ? parseBackendTime(completed)?.getTime() : now;
  if (!detail.runs.length) return "--";
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "进行中";
  return formatElapsedSeconds(Math.max(0, Math.round(((end as number) - (start as number)) / 1000)));
}

export function safeJson(value: string) {
  try {
    return JSON.parse(value || "{}") as Record<string, unknown>;
  } catch {
    return {};
  }
}


export function parseJsonArray(value: string | undefined) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : [];
  } catch {
    return [];
  }
}

export function parseJsonObjectArray(value: string | undefined) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>> : [];
  } catch {
    return [];
  }
}

export function formatTraceLocation(location: Record<string, unknown> | undefined) {
  if (!location) return "";
  const file = String(location.file_path || "");
  if (!file) return "";
  const start = location.line_start ? Number(location.line_start) : null;
  const end = location.line_end ? Number(location.line_end) : null;
  if (!start) return file;
  if (end && end !== start) return `${file}:${start}-${end}`;
  return `${file}:${start}`;
}

export function formatEvidenceContractStatus(contract: Record<string, unknown>) {
  const status = String(contract.status || "");
  const map: Record<string, string> = {
    satisfied: "完整",
    partial: "部分完整",
    weak: "证据薄弱"
  };
  return map[status] || "未记录";
}

export function formatEvidenceContractScore(contract: Record<string, unknown>) {
  const score = Number(contract.score);
  if (!Number.isFinite(score)) return "--";
  return `${Math.round(score * 100)}%`;
}

export function formatEvidenceScore(score: Record<string, unknown>) {
  const value = Number(score.score);
  if (!Number.isFinite(value)) return "--";
  return `${Math.round(value * 100)}%`;
}

export function formatEvidenceScoreComponents(score: Record<string, unknown>) {
  const components = score.components && typeof score.components === "object"
    ? score.components as Record<string, unknown>
    : {};
  const labels: Record<string, string> = {
    tool_backing: "工具",
    snippet_quote: "源码",
    line_precision: "行号",
    rule_alignment: "规则",
    symbol_alignment: "符号",
    consensus: "共识"
  };
  const active = Object.entries(components)
    .filter(([, value]) => Number(value) > 0)
    .map(([key, value]) => `${labels[key] || key} ${Math.round(Number(value) * 100)}%`);
  return active.length ? active.join("、") : "未命中结构组件";
}

export function formatEvidenceContractMissing(contract: Record<string, unknown>) {
  const missing = Array.isArray(contract.missing) ? contract.missing.map((item) => String(item)) : [];
  if (!missing.length) return "无";
  const labels: Record<string, string> = {
    has_rule: "规范",
    has_location: "位置",
    has_source_context: "源码上下文",
    has_tool_evidence: "工具证据",
    has_recommendation: "修复建议",
    has_suggested_code: "建议代码"
  };
  return missing.map((item) => labels[item] || item).join("、");
}

export function formatObservationLocation(item: Record<string, unknown>) {
  return formatTraceLocation({
    file_path: observationFilePath(item),
    line_start: observationLineStart(item),
    line_end: observationLineEnd(item),
  }) || "--";
}

export function extractSuggestedCode(value: string) {
  const fence = value.match(/```[a-zA-Z0-9_-]*\n([\s\S]*?)```/);
  return fence ? fence[1].trim() : "";
}

export function languageLabel(filePath: string) {
  const extension = filePath.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = {
    java: "Java",
    kt: "Kotlin",
    js: "JavaScript",
    jsx: "React JSX",
    ts: "TypeScript",
    tsx: "React TSX",
    py: "Python",
    sql: "SQL",
    xml: "XML",
    yml: "YAML",
    yaml: "YAML",
    json: "JSON",
    css: "CSS",
    scss: "SCSS",
    html: "HTML",
    md: "Markdown"
  };
  return map[extension || ""] || "Code";
}
