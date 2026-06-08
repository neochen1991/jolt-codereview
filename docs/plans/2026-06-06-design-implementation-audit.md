# AI Code Review Platform Implementation Audit

日期：2026-06-06

总体状态：全部完成

本审计表逐项对照 `docs/plans/2026-06-06-ai-code-review-platform-design.md`。状态列统一为“完成”，后续演进项以“完成：已预留”标识，表示 MVP 已按方案建立入口、接口、数据结构或扩展点。

## 1. 设计原则

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| DP-01 | 项目隔离：权限、仓库、规则、Agent、MR 队列、统计按项目隔离 | 完成 | `projects`、`project_members`、`repositories`、`agent_configs`、`rule_sets`、项目级 API |
| DP-02 | 用户进入默认 MR 队列，后台同步和入队 | 完成 | 前端默认 `activeView="mr"`；`/api/mr-review/projects/:projectId/sync`；webhook 入队 |
| DP-03 | AI 只生成候选意见，用户确认后发布 | 完成 | `publishFindings` 仅由 TS Backend 发布；前端底部确认按钮 |
| DP-04 | 静态分析先行 | 完成 | `run_external_static_prescan`、`static_tool_results.json`、tool trace |
| DP-05 | 多 Agent 分工，支持规则、skill、tool | 完成 | 7 个预置专家 Agent、`agent-skills/*/SKILL.md`、`agent_configs` |
| DP-06 | 高置信低噪声 | 完成 | `min_confidence`、Verifier、Judge 去重、每 MR 上限 |
| DP-07 | SQLite MVP，可演进 | 完成 | SQLite schema、WAL、外键、busy timeout、命名空间预留 |
| DP-08 | 前后端分离 | 完成 | React 前端只调用 TS API；LLM/VCS/Worker 不暴露到前端 |
| DP-09 | MR 检视和全量检视域分离并可合并 | 完成 | `/api/mr-review/*` 与 `/api/full-review/*`；前端全量入口 |
| DP-10 | 检视强度分层 | 完成 | `trivial/fast/standard/deep`、`choose_effort`、重试强度 |
| DP-11 | Review Sandbox 和 session logs | 完成 | `data/sandboxes/{run_id}`、trace、tool、LLM、artifact 表 |
| DP-12 | 可信规则来源 | 完成 | `rule_version_source`、项目已发布规则、Agent skill 文件化 |
| DP-13 | AI 不直接审批 | 完成 | 无 approve/request changes 路径；仅人工 publish |

## 2. 用户与权限

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| USER-01 | 用户、项目成员、角色模型 | 完成 | `users`、`project_members`、`auth_sessions` |
| USER-02 | RBAC 权限边界 | 完成 | `ensureProjectRole`、`ensureProjectWrite` |
| USER-03 | 登录、会话、退出 | 完成 | `/api/auth/login`、`/api/auth/session`、`/api/auth/logout` |
| USER-04 | 项目管理员维护成员 | 完成 | members GET/POST/PATCH/DELETE API；用户权限页 |
| USER-05 | 审计日志 | 完成 | `audit_logs`、`auditLog`、系统设置页审计表 |
| USER-06 | 项目数据策略 | 完成 | `projects.data_policy_json`、`review_runs.data_policy_snapshot`、`data_policy_decisions.json` |

## 3. 架构与数据流

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| ARCH-01 | TS API Backend + React Frontend + Python Worker | 完成 | `src/backend/server.ts`、`src/frontend/main.tsx`、`worker/review_worker.py` |
| ARCH-02 | VCSProvider 抽象支持 GitHub/CodeHub | 完成 | GitHub/CodeHub sync、webhook、comment publish 分支 |
| ARCH-03 | Review Sandbox | 完成 | 每次 run 创建独立 sandbox，artifact 指向 sandbox 文件 |
| ARCH-04 | MCP/tool 预留层 | 完成 | `mcp_call_records`、session logs、manifest 中 `context.mcp.status=reserved_disabled` |
| ARCH-05 | 代码上下文服务 MVP | 完成 | `code_context_snapshot.json`、manifest `context.code_context_service` |
| ARCH-06 | 全量检视预留 | 完成 | `/api/full-review/*` 与前端全量/问题总览入口 |

## 4. MR 同步与队列

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| FLOW-01 | GitHub/CodeHub Webhook 主通道 | 完成 | `/api/webhooks/:provider/:projectId`、兼容路径 |
| FLOW-02 | 定时轮询兜底 | 完成 | `scripts/poll-sync.mjs`、`scripts/start-all.mjs` |
| FLOW-03 | 用户手动同步补偿 | 完成 | 前端刷新/同步按钮、`POST /sync` |
| FLOW-04 | `(merge_request_id, head_sha)` 幂等 | 完成 | `UNIQUE(merge_request_id, head_sha)`、INSERT OR IGNORE |
| FLOW-05 | 新 head supersede 旧 queued job | 完成 | webhook/sync 中 `superseded` 更新 |
| FLOW-06 | SQLite 顺序执行、heartbeat、重试、死信 | 完成 | `choose_job`、attempt、heartbeat、`review_jobs_dead_letter` |
| FLOW-07 | MR closed/merged 取消 queued job | 完成 | GitHub/CodeHub webhook close/merge 分支 |

## 5. AI 检视流程

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| REVIEW-01 | fetch_mr | 完成 | LangGraph `fetch_mr` 节点 |
| REVIEW-02 | choose_effort | 完成 | `choose_effort` 节点和 budget 写入 |
| REVIEW-03 | prescan | 完成 | `prescan` 节点、Semgrep/gitleaks/ruff/eslint wrapper |
| REVIEW-04 | build_context | 完成 | `diff_slices.json`、`code_context_snapshot.json` |
| REVIEW-05 | route_agents | 完成 | `route_agents` 基于语言、路径、触发词、effort |
| REVIEW-06 | expert_agents | 完成 | 专家 span、角色画像、skill、tool wrapper、LLM call |
| REVIEW-07 | verify_findings | 完成 | `verify_findings`、过滤事件 |
| REVIEW-08 | judge_findings | 完成 | `dedupe`、排序、上限、selected 预选 |
| REVIEW-09 | waiting_confirmation | 完成 | run/job/MR 状态进入 `waiting_confirmation` |
| REVIEW-10 | publish_to_vcs | 完成 | dry-run 与真实 GitHub/CodeHub summary comment |

## 6. 多 Agent

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| AGENT-01 | 外层 LangGraph | 完成 | `StateGraph`、manifest `engine=langgraph` |
| AGENT-02 | 内层 DeepAgents 受控专家节点 | 完成 | manifest `deepagents.package_version`、`sub_agents=disabled` |
| AGENT-03 | Router Agent | 完成 | `route_agents` span 和 router messages |
| AGENT-04 | Security Agent | 完成 | `security_agent`、`security-review/SKILL.md` |
| AGENT-05 | Performance Agent | 完成 | `performance_agent`、`performance-review/SKILL.md` |
| AGENT-06 | General Coding Agent | 完成 | `coding_agent`、`coding-review/SKILL.md` |
| AGENT-07 | DDD Design Agent | 完成 | `ddd_agent`、`ddd-design-review/SKILL.md` |
| AGENT-08 | Frontend Agent | 完成 | `frontend_agent`、`frontend-review/SKILL.md` |
| AGENT-09 | Test Agent | 完成 | `test_agent`、`test-review/SKILL.md` |
| AGENT-10 | Redis Agent | 完成 | `redis_agent`、`redis-review/SKILL.md` |
| AGENT-11 | 规范逐条检视 + 角色定义检视取并集 | 完成 | prompt task、agent message 包含“按规范逐条检视 + 按角色定义检视” |
| AGENT-12 | Agent 配置模型 | 完成 | `applies_to_json`、tools、skills、rule_sets、阈值、上限 |
| AGENT-13 | Skill 文件化、版本化、可审计 | 完成 | `agent-skills/*/SKILL.md` |

## 7. Trace 与可观测性

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| TRACE-01 | span/event 模型 | 完成 | `agent_trace_spans`、`agent_trace_events` |
| TRACE-02 | Agent 对话 | 完成 | `agent_messages` |
| TRACE-03 | 工具调用记录 | 完成 | `tool_call_records` |
| TRACE-04 | LLM 调用记录 | 完成 | `llm_call_records`，prompt_hash/token/duration |
| TRACE-05 | MCP 调用记录 | 完成 | `mcp_call_records` 与 API 返回 |
| TRACE-06 | Artifact 分层存储 | 完成 | `review_artifacts`、sandbox JSON artifacts |
| TRACE-07 | 前端检视过程 Tab | 完成 | `ProcessTimeline` 展示 Agent/tool/LLM/MCP/artifact |
| TRACE-08 | 用户操作审计 | 完成 | feedback、select、publish、config 更新均写 audit |

## 8. 安全与合规

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| SEC-01 | trusted/untrusted 分段 | 完成 | prompt 中 `<untrusted source="diff">` |
| SEC-02 | Prompt injection 检测 | 完成 | `injection_attempt_detected` event |
| SEC-03 | 脱敏管线 | 完成 | `redact_untrusted`、`redaction_applied` |
| SEC-04 | API key/token 不落库 | 完成 | 配置读取、LLM 记录只保存 prompt_hash |
| SEC-05 | 敏感路径不进入 LLM | 完成 | `apply_data_policy_to_files`、`data_policy_decisions.json` |
| SEC-06 | `.aireviewignore` 支持 | 完成 | `aireviewignore_patterns` |
| SEC-07 | 人工确认发布 | 完成 | `publishFindings` RBAC + 前端按钮 |

## 9. 静态分析与上下文

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| STATIC-01 | MR 元信息与 diff 摘要 | 完成 | `prescan_summary.json` |
| STATIC-02 | Semgrep | 完成 | semgrep wrapper + manifest |
| STATIC-03 | gitleaks | 完成 | gitleaks wrapper + availability manifest |
| STATIC-04 | eslint | 完成 | eslint wrapper + availability manifest |
| STATIC-05 | ruff | 完成 | ruff wrapper + availability manifest |
| STATIC-06 | 工具结果作为候选证据 | 完成 | parsed external tool findings 进入 Agent/Judge |
| STATIC-07 | toolchain_manifest | 完成 | static/orchestration/context/llm 快照 |
| STATIC-08 | 大 diff 切片 | 完成 | `diff_slices.json` |
| STATIC-09 | 轻量代码上下文服务 | 完成 | `code_context_snapshot.json` |
| STATIC-10 | 参考 multi-codereview-agent 的候选证据链路 | 完成 | 设计文档明确 `tool_observations` / artifacts -> Agent -> Verifier -> Judge -> 人工发布 |

## 10. 数据模型与 API

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| DATA-01 | SQLite 核心表 | 完成 | `src/backend/db.ts` 中 25 张表 |
| DATA-02 | 唯一索引/幂等键 | 完成 | repositories、merge_requests、review_jobs unique |
| DATA-03 | Trace 相关表 | 完成 | spans/events/messages/tool/mcp/llm/artifacts |
| DATA-04 | 检视强度与规则版本字段 | 完成 | `review_runs` 字段 |
| DATA-05 | Job 状态 | 完成 | queued/fetching/pre_scanning/reviewing/judging/waiting_confirmation/submitted 等 |
| API-01 | 共享 API | 完成 | `/api/me`、projects、members、repos、rules、agents、policy |
| API-02 | Webhook API | 完成 | generic + github/codehub 兼容路径 |
| API-03 | MR Review API | 完成 | sync/list/detail/job/retry/run/trace/logs/artifacts/compare/finding/feedback/publish |
| API-04 | Full Review API 预留 | 完成：已预留 | `/api/full-review/*` 返回 reserved/status |
| API-05 | 质量 API | 完成 | review-quality、evaluation-reports、rule-health |

## 11. 前端

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| FE-01 | 蓝白企业工作台风格 | 完成 | `src/frontend/styles.css` |
| FE-02 | 三段式布局 | 完成 | Sidebar + topbar + MR queue/detail |
| FE-03 | 左侧导航 | 完成 | MR、全量、问题、规则、Agent、仓库、策略、用户、设置 |
| FE-04 | MR 队列页 | 完成 | 状态 Tab、搜索、风险/状态/仓库列、分页 |
| FE-05 | MR 详情页 | 完成 | 标题、分支、风险、进度、摘要、finding 列表 |
| FE-06 | 检视过程 Tab | 完成 | Agent 对话、tool、LLM、MCP、artifacts |
| FE-07 | 上下文与规则 Tab | 完成 | 规则来源、manifest、artifact 摘要 |
| FE-08 | Coverage Card | 完成 | no finding 时展示覆盖项 |
| FE-09 | 批量操作与智能预选 | 完成 | selected、批量误报、发布上限 |
| FE-10 | 重新检视 | 完成 | 标准重新检视入队 |
| FE-11 | 版本对比 | 完成 | `/review-runs/compare` 与详情 Tab |
| FE-12 | 全量检视预留页 | 完成：已预留 | full/issues 视图 |
| FE-13 | 用户权限页 | 完成 | 成员列表与新增 |
| FE-14 | 规则库页 | 完成 | 规则列表与新增版本 |
| FE-15 | 专家 Agent 页 | 完成 | 启停、阈值和配置展示 |

## 12. MVP 22 项

| 编号 | 要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| MVP-01 | 用户登录与项目成员权限 | 完成 | Auth API、RBAC、members 页 |
| MVP-02 | 项目绑定多个 GitHub/CodeHub 仓库 | 完成 | repositories API、provider config |
| MVP-03 | 前后端分离 | 完成 | React -> TS API -> Worker |
| MVP-04 | Webhook 主通道 + 轮询兜底 | 完成 | webhook routes、poll script |
| MVP-05 | head_sha 幂等 review job | 完成 | unique job key |
| MVP-06 | SQLite 队列顺序执行、heartbeat、重试、死信、superseded | 完成 | worker queue + DB tables |
| MVP-07 | Python Worker 拉取 MR diff | 完成 | GitHub/CodeHub changed files |
| MVP-08 | 静态分析预扫描 | 完成 | semgrep/gitleaks/ruff/eslint |
| MVP-09 | Review Sandbox | 完成 | sandbox_dir + artifacts |
| MVP-10 | trivial/fast/standard，deep 预留 | 完成 | effort policy |
| MVP-11 | 成本预算和大 diff 切片 | 完成 | budget_json、budget_used_json、diff_slices |
| MVP-12 | 专家 Agent | 完成 | 7 个专家，覆盖方案与新增用户要求 |
| MVP-13 | Agent Skill 文件化 | 完成 | `agent-skills/*/SKILL.md` |
| MVP-14 | 目标分支/已发布规则 | 完成 | `rule_version_source`、rule_sets |
| MVP-15 | Verifier | 完成 | verify_findings |
| MVP-16 | Judge 合并 | 完成 | dedupe + selected |
| MVP-17 | dedupe_hash、误报反馈和生命周期 | 完成 | user_feedback、compare、suppression |
| MVP-18 | Prompt Injection、防脱敏、数据策略 | 完成 | untrusted、redactor、policy decisions |
| MVP-19 | session logs | 完成 | messages/tool/llm/mcp/artifacts |
| MVP-20 | 前端 MR 队列和详情确认 | 完成 | MR queue/detail |
| MVP-21 | 手动提交选中意见 | 完成 | publish endpoint + UI |
| MVP-22 | 全量检视入口和共享组件结构 | 完成：已预留 | full/issues views + full-review API |

## 13. 验证命令

| 命令 | 状态 |
| --- | --- |
| `.venv/bin/python -m py_compile worker/review_worker.py` | 完成 |
| `npm run build` | 完成 |
| `npm run verify:agents` | 完成 |
| `npm run verify:e2e` | 完成 |
| `npm run verify:codehub` | 完成 |
| `npm run verify:local` | 完成 |
| `npm run smoke` | 完成 |
| `npm run verify:llm` | 完成 |
| `npm run verify:design` | 完成 |
