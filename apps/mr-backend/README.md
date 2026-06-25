# Jolt MR Backend

MR Backend 是 Jolt CodeReview 的核心业务后端，负责项目、仓库、MR 同步、检视队列、规则、专家 Agent、质量观测、Webhook、VCS 代理和 Python Review Worker。用户、权限、系统设置和模型配置由 Common Backend 负责。

## 服务职责

- 维护项目、成员、加入申请、邀请码和审计日志。
- 维护代码仓库和 VCS provider 配置。
- 同步 GitHub Pull Request / CodeHub Merge Request。
- 创建、暂停、停止、重试 MR review job。
- 查询 review run、trace、session logs、artifacts 和 findings。
- 管理规则集、规则文档、自定义 Skill、专家 Agent 和工具绑定。
- 提供 full repository review job 和 snapshot finding。
- 提供 VCS diff/files/file/comment/status 代理。
- 接收 GitHub / CodeHub webhook。
- 运行 Python Worker，执行静态工具、LLM 专家分析和结果汇总。

## 运行要求

- Node.js 24+
- npm
- Python 3.10+
- PostgreSQL 14+
- `requirements.txt` 中的 Python 依赖
- 可选：Java / Semgrep / Gitleaks / PMD / Checkstyle / SpotBugs / Trivy 等静态工具
- 可选：`GITHUB_TOKEN`、`CODEHUB_TOKEN`、LLM provider key

## 本仓启动

从仓库根目录安装依赖：

```bash
npm install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
  "server": {
    "host": "127.0.0.1",
    "mr_port": 8011,
    "database_driver": "postgres",
    "postgres_url": "postgresql://USER:PASSWORD@127.0.0.1:5432/jolt_codereview"
  },
  "runtime": {
    "python_bin": ".venv/bin/python"
  }
}
```

启动 MR Backend：

```bash
CONFIG_PATH=./config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
PYTHON_BIN=.venv/bin/python \
npm run dev:mr
```

启动 Worker：

```bash
CONFIG_PATH=./config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
PYTHON_BIN=.venv/bin/python \
npm run worker
```

只消费一条队列任务：

```bash
CONFIG_PATH=./config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
PYTHON_BIN=.venv/bin/python \
npm run worker:once
```

健康检查：

```bash
curl -sS http://127.0.0.1:8011/api/health
```

## 独立仓启动

导出后进入 `split-repos/mr-backend`：

```bash
npm install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json
```

启动 API：

```bash
CONFIG_PATH=./config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
PYTHON_BIN=.venv/bin/python \
npm run dev
```

启动 Worker：

```bash
CONFIG_PATH=./config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
PYTHON_BIN=.venv/bin/python \
npm run worker
```

生产启动：

```bash
npm run build
CONFIG_PATH=./config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
PYTHON_BIN=.venv/bin/python \
npm run start
```

## 配置项

| 配置/环境变量 | 说明 |
| --- | --- |
| `CONFIG_PATH` | 配置文件路径，默认当前工作目录 `config.json` |
| `server.host` | 监听地址，默认 `127.0.0.1` |
| `server.mr_port` | MR Backend 端口，默认 `8011` |
| `server.postgres_url` | PostgreSQL 连接串，必填 |
| `runtime.python_bin` / `PYTHON_BIN` | Worker 使用的 Python |
| `JOLT_INTERNAL_SERVICE_TOKEN` | 内部 API token；需要与 Common Backend 保持一致 |
| `GITHUB_TOKEN` | GitHub API token，可通过项目配置覆盖 |
| `CODEHUB_TOKEN` | CodeHub API token，可通过项目配置覆盖 |
| `MINIMAX_API_KEY` 等 LLM key | 由模型配置中的 `default_api_key_env` 指定 |

## API 接入

MR Backend 面向用户的接口使用 Common Backend 登录得到的 Bearer Token：

```bash
TOKEN=$(curl -sS http://127.0.0.1:8010/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"local-admin","password":"admin123"}' | jq -r '.token')

curl -sS http://127.0.0.1:8011/api/projects \
  -H "Authorization: Bearer $TOKEN"
```

Frontend 通过 `VITE_MR_API_BASE` 调用 MR Backend。

## API 功能清单

### Health

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务健康、SLI 摘要和服务名 |

### Projects

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/projects` | 当前用户可访问项目 |
| `GET` | `/api/projects/discover` | 可申请加入的项目 |
| `POST` | `/api/projects` | 创建项目，可同时绑定仓库 |
| `GET` | `/api/projects/:projectId` | 项目详情 |
| `PATCH` | `/api/projects/:projectId` | 修改项目档案 |
| `GET` | `/api/projects/:projectId/settings` | 项目配置 |
| `GET` | `/api/projects/:projectId/effective-config` | 项目有效配置 |
| `POST` | `/api/projects/:projectId/settings/llm/test` | 测试项目 LLM 配置 |
| `PATCH` | `/api/projects/:projectId/settings/:key` | 保存项目配置项 |
| `GET` | `/api/projects/:projectId/audit-logs` | 项目审计日志 |

### Project Members

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/projects/:projectId/members` | 项目成员列表 |
| `POST` | `/api/projects/:projectId/members` | 添加项目成员 |
| `PATCH` | `/api/projects/:projectId/members/:memberId` | 修改项目成员角色 |
| `DELETE` | `/api/projects/:projectId/members/:memberId` | 移除项目成员 |
| `GET` | `/api/projects/:projectId/join-requests` | 加入申请列表 |
| `POST` | `/api/projects/:projectId/join-requests` | 提交加入申请 |
| `PATCH` | `/api/projects/:projectId/join-requests/:requestId` | 审批加入申请 |
| `GET` | `/api/projects/:projectId/invitations` | 邀请码列表 |
| `POST` | `/api/projects/:projectId/invitations` | 创建邀请码 |
| `POST` | `/api/projects/join-by-invite` | 使用邀请码加入项目 |

### Repositories

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/projects/:projectId/repositories` | 项目仓库列表 |
| `POST` | `/api/projects/:projectId/repositories` | 绑定 GitHub / CodeHub 仓库 |
| `DELETE` | `/api/projects/:projectId/repositories/:repositoryId` | 删除仓库绑定 |

### Rules, Skills and Agents

| Method | Path | 说明 |
| --- | --- | --- |
| `GET/POST` | `/api/projects/:projectId/rule-sets` | 规则集 |
| `GET/POST` | `/api/projects/:projectId/rule-documents` | 规则文档 |
| `GET` | `/api/projects/:projectId/rule-details` | 按 rule id 查询规则详情 |
| `GET/POST` | `/api/projects/:projectId/expert-rule-bindings` | 专家规则绑定 |
| `DELETE` | `/api/projects/:projectId/expert-rule-bindings/:bindingId` | 删除专家规则绑定 |
| `GET/POST` | `/api/projects/:projectId/custom-skills` | 自定义 Skill |
| `GET/POST` | `/api/projects/:projectId/custom-skill-assets` | Skill 附件 |
| `GET/POST` | `/api/projects/:projectId/expert-skill-bindings` | 专家 Skill 绑定 |
| `GET/PATCH` | `/api/projects/:projectId/review-policy` | Review policy |
| `GET` | `/api/projects/:projectId/agents` | 内置和项目 Agent |
| `GET/POST` | `/api/projects/:projectId/expert-profiles` | 专家 profile |
| `PATCH` | `/api/projects/:projectId/expert-profiles/:agentKey` | 修改专家 profile |
| `GET/POST` | `/api/projects/:projectId/expert-tool-bindings` | 专家工具绑定 |
| `PATCH` | `/api/projects/:projectId/agents/:agentId` | 修改 Agent 配置 |

### MR Review

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/mr-review/projects/:projectId/merge-requests` | MR 列表，支持状态/仓库/作者/时间过滤 |
| `POST` | `/api/mr-review/projects/:projectId/sync` | 同步项目仓库 MR |
| `POST` | `/api/mr-review/projects/:projectId/merge-requests/status-refresh` | 刷新远端 MR 状态 |
| `GET` | `/api/mr-review/projects/:projectId/dead-letters` | 死信任务 |
| `GET` | `/api/mr-review/merge-requests/:mrId` | MR 详情、runs、findings |
| `DELETE` | `/api/mr-review/merge-requests/:mrId` | 删除本地 MR 数据 |
| `GET` | `/api/mr-review/merge-requests/:mrId/logs` | MR 日志 |
| `GET` | `/api/mr-review/merge-requests/:mrId/export.md` | 导出 Markdown |
| `POST` | `/api/mr-review/merge-requests/:mrId/review-jobs` | 创建检视任务 |
| `POST` | `/api/mr-review/merge-requests/:mrId/pause` | 暂停检视 |
| `POST` | `/api/mr-review/merge-requests/:mrId/stop` | 停止检视 |
| `POST` | `/api/mr-review/review-jobs/:jobId/retry` | 重试任务 |
| `GET` | `/api/mr-review/review-runs/:runId` | Review run 详情 |
| `GET` | `/api/mr-review/review-runs/:runId/trace` | Agent / LLM / tool trace |
| `GET` | `/api/mr-review/review-runs/:runId/session-logs` | Session logs |
| `GET` | `/api/mr-review/review-runs/:runId/artifacts` | Artifacts |
| `GET` | `/api/mr-review/merge-requests/:mrId/review-runs/compare` | 多次运行对比 |
| `POST/GET` | `/api/mr-review/merge-requests/:mrId/external-reports` | 外部报告导入和查询 |
| `PATCH` | `/api/mr-review/review-findings/:findingId` | 标记 finding 状态 |
| `POST` | `/api/mr-review/review-findings/:findingId/feedback` | 提交人工反馈 |
| `POST` | `/api/mr-review/merge-requests/:mrId/publish` | 发布已确认 finding 到代码平台 |

### Full Review

| Method | Path | 说明 |
| --- | --- | --- |
| `GET/POST` | `/api/full-review/projects/:projectId/jobs` | 全仓 review job 列表和创建 |
| `GET` | `/api/full-review/jobs/:jobId` | 全仓 review job 详情 |
| `POST` | `/api/full-review/jobs/:jobId/cancel` | 取消全仓 review job |
| `GET` | `/api/full-review/jobs/:jobId/trace` | 全仓 review trace |
| `GET` | `/api/full-review/jobs/:jobId/session-logs` | 全仓 review logs |
| `GET` | `/api/full-review/repositories/:repositoryId/snapshots` | 仓库 snapshot |
| `GET` | `/api/full-review/snapshots/:snapshotId/findings` | Snapshot findings |
| `PATCH` | `/api/full-review/findings/:findingId` | 更新 full-review finding |

### VCS and Webhook

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/vcs/:projectId/capabilities` | 当前项目 VCS 能力 |
| `GET` | `/api/vcs/:projectId/merge-requests/:mrId/diff` | MR diff |
| `GET` | `/api/vcs/:projectId/merge-requests/:mrId/files` | MR changed files |
| `GET` | `/api/vcs/:projectId/merge-requests/:mrId/file` | 单文件内容 |
| `POST` | `/api/vcs/:projectId/merge-requests/:mrId/comment` | 提交评论 |
| `POST` | `/api/vcs/:projectId/merge-requests/:mrId/status` | 更新远端状态 |
| `POST` | `/api/webhooks/github/:projectId` | GitHub webhook |
| `POST` | `/api/webhooks/codehub/:projectId` | CodeHub webhook |
| `POST` | `/api/webhooks/:provider/:projectId` | 通用 webhook |
| `POST` | `/api/webhooks/:provider/:projectId/jolt-comment` | 评论回流 webhook |

### Observability and Quality

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/projects/:projectId/queue/summary` | 队列摘要 |
| `GET` | `/api/projects/:projectId/toolchain/status` | 工具链状态 |
| `GET` | `/api/projects/:projectId/static-tools/availability` | 静态工具可用性 |
| `GET` | `/api/projects/:projectId/agents/quality` | Agent 质量数据 |
| `GET` | `/api/projects/:projectId/review-quality/metrics` | Review 质量指标 |
| `GET` | `/api/observability/review-quality` | 跨项目 review 质量观测 |
| `GET` | `/api/projects/:projectId/review-quality/summary` | Review 质量摘要 |
| `GET` | `/api/projects/:projectId/evaluation-reports` | 评估报告 |
| `GET` | `/api/projects/:projectId/rule-health` | 规则健康度 |

## Worker 运行方式

Worker 从 `review_jobs` 队列表认领任务，写入 `review_runs`、`review_findings`、tool calls、LLM calls、trace 和 session logs。

常驻模式：

```bash
npm run worker
```

单任务模式：

```bash
npm run worker:once
```

常用项目配置：

- `queue_policy.max_concurrency`: 项目内并发数。
- `queue_policy.heartbeat_timeout_seconds`: job heartbeat 超时。
- `tool_policy.static_runners`: 静态工具开关和自定义规则路径。
- `review_policy.max_added_lines_per_mr`: MR 规模阈值。
- `agent_policy.deepagents`: DeepAgents 使用策略。

## 与其它服务的关系

- Frontend 通过 `VITE_MR_API_BASE` 调用 MR Backend。
- MR Backend 和 Common Backend 必须连接同一个 PostgreSQL。
- 用户 token 由 Common Backend 签发；MR Backend 使用同一数据库读取 session 和权限。
- Worker 使用 MR Backend 同一份代码和配置，并可通过 Common Backend 内部模型 API 读取模型配置。
