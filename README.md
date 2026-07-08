# Jolt CodeReview 三服务运行与接入指南

Jolt CodeReview 已拆分为当前仓库根目录下的三个模块：

- `common-backend`: 公共平台后端，负责登录、用户、权限、系统设置和模型配置。
- `mr-backend`: MR 检视后端，负责项目、仓库、MR 队列、评审任务、规则、专家 Agent、质量观测、Webhook、VCS 代理和 Python Worker。
- `frontend`: 前端服务和 Frontend Gateway，对外提供浏览器入口，并按路径代理到 `common-backend` 和 `mr-backend`。

运行时只支持 PostgreSQL。SQLite 已不再作为运行库使用。

## 服务拓扑

```text
Browser
  |
  | http://127.0.0.1:9020
  v
Frontend Gateway + React/Vite (default 127.0.0.1:9020)
  |
  | /api/auth /api/me /api/permissions /api/models /api/system
  v
Common Backend (default 127.0.0.1:9022)
  |
  | same PostgreSQL database
  v
PostgreSQL
  ^
  | same PostgreSQL database
  |
MR Backend (default 127.0.0.1:9021) <---- Python Review Worker
  ^
  |
  | /api/mr-review /api/full-review /api/vcs /api/webhooks ...
  |
Frontend Gateway
```

浏览器默认只访问 Frontend Gateway，不再直连 Common/MR。Gateway 和前端 API helper 使用同一套路由规则，规则在 [frontend/src/frontend/apiRouting.ts](frontend/src/frontend/apiRouting.ts) 和 [frontend/src/gateway/server.mjs](frontend/src/gateway/server.mjs)：

- Common API: `/api/auth/*`、`/api/me/*`、`/api/users/*`、`/api/permissions/*`、`/api/models/*`、`/api/system/*`、`/internal/auth/*`、`/internal/models/*`
- MR API: 其它业务 API，主要是 `/api/projects/*`、`/api/mr-review/*`、`/api/full-review/*`、`/api/vcs/*`、`/api/webhooks/*`

## 目录说明

```text
common-backend/                 Common Backend 模块
mr-backend/                     MR Backend + Python Worker 模块
frontend/                       React/Vite Frontend 模块
scripts/export-three-repos.mjs  同步根目录三模块；传 --out 可生成临时校验副本
```

## 环境要求

- Node.js 24+
- npm
- Python 3.10+
- PostgreSQL 14+
- 可选：Java 17+ 或 21+，用于 Checkstyle、PMD、SpotBugs、Dependency-Check 等 Java 静态工具
- 可选：`GITHUB_TOKEN`，用于 GitHub PR 同步和读取 changed files
- 可选：`CODEHUB_TOKEN`，用于接入公司内网 CodeHub

## 配置文件

每个服务使用自己的本地配置文件。复制配置模板：

```bash
cp common-backend/config.example.json common-backend/config.json
cp mr-backend/config.example.json mr-backend/config.json
cp frontend/.env.example frontend/.env
```

至少需要在 `common-backend/config.json` 和 `mr-backend/config.json` 中配置 PostgreSQL。Common 负责账号、权限、项目配置和模型配置；MR Backend 负责仓库、MR、队列和 Worker：

```json
{
  "server": {
    "host": "127.0.0.1",
    "common_port": 9022,
    "mr_port": 9021,
    "database_driver": "postgres",
    "postgres_url": "postgresql://USER:PASSWORD@127.0.0.1:5432/jolt_codereview",
    "postgres_query_timeout_seconds": 120
  }
}
```

如果配置文件不在默认位置，可以分别指定服务配置路径：

```bash
export COMMON_CONFIG_PATH=/absolute/path/to/common-config.json
export MR_CONFIG_PATH=/absolute/path/to/mr-config.json
```

## 本仓三模块联调启动

三个模块各自有独立 `package.json`。首次运行先分别安装依赖：

```bash
npm --prefix common-backend install
npm --prefix mr-backend install
npm --prefix frontend install
python3 -m venv mr-backend/.venv
mr-backend/.venv/bin/pip install -r mr-backend/requirements.txt
```

启动 Common Backend：

```bash
CONFIG_PATH=$PWD/common-backend/config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
npm --prefix common-backend run dev
```

启动 MR Backend。该命令会一起启动 MR API 和常驻 Worker pool：

```bash
CONFIG_PATH=$PWD/mr-backend/config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
PYTHON_BIN=$PWD/mr-backend/.venv/bin/python \
npm --prefix mr-backend run dev
```

MR Backend 会按活跃项目的 `queue_policy.max_concurrency` 自动补足 worker pool。新项目创建后，绑定仓库并产生 MR 队列任务时会进入同一套项目级并发控制；不同项目的 MR 可以同时检视。

启动 Frontend：

```bash
COMMON_API_BASE=http://127.0.0.1:9022 \
MR_API_BASE=http://127.0.0.1:9021 \
npm --prefix frontend run dev
```

访问：

- Frontend: `http://127.0.0.1:9020`
- Frontend internal Vite dev server: `http://127.0.0.1:9023`
- Common health: `http://127.0.0.1:9022/api/health`
- MR health: `http://127.0.0.1:9021/api/health`

三个服务可以独立重启：

- 只改公共平台能力时，重启 `common-backend`。
- 只改 MR 检视、Worker、仓库同步时，重启 `mr-backend`。
- 只改页面、静态资源或 API 网关路由时，重启 `frontend`。

默认本机 root 账号：

- 用户名：`local-admin`
- 密码：`admin123`

生产环境必须先改初始化密码和密码策略。

## 同步根目录三模块

```bash
npm run sync:modules
```

该命令会更新当前仓库根目录下的：

```text
common-backend/
mr-backend/
frontend/
```

如果只想生成一份临时校验副本，不改动根目录模块，可以显式传 `--out`：

```bash
node scripts/export-three-repos.mjs --force --out=/private/tmp/jolt-three-service-export
```

## 验证

构建全部 TypeScript：

```bash
npm run build
```

验证前端 API 分流规则：

```bash
npm run verify:frontend-api-routing
```

验证 PostgreSQL SQL 兼容层：

```bash
npm run verify:pg-sql-compat
```

完整三服务 + 本机 PostgreSQL 回归：

```bash
npm run verify:split-full-regression
```

该回归会临时启动 PostgreSQL、生成三模块校验副本、构建并启动 `common-backend`、`mr-backend`、`frontend`，创建项目和 MR fixture，运行 worker，并通过 API 验证 review run、findings、日志、trace 和 artifacts。

## API 接入总览

所有面向用户的 API 使用 Bearer Token。先登录：

```bash
curl -sS http://127.0.0.1:9022/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"local-admin","password":"admin123"}'
```

响应中会返回 `token`。后续请求：

```bash
curl -sS http://127.0.0.1:9021/api/projects \
  -H "Authorization: Bearer $JOLT_TOKEN"
```

内部 API 使用 `x-internal-service-token`，只给服务间调用或 Worker 使用：

```bash
curl -sS 'http://127.0.0.1:9022/internal/models/effective-config?project_id=project_default' \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

## Common Backend API 功能

Common Backend 默认端口 `9022`，只承载公共平台能力。

| 功能 | 主要 API |
| --- | --- |
| 健康检查 | `GET /api/health` |
| 登录注册与会话 | `POST /api/auth/login`、`POST /api/auth/register`、`GET /api/auth/session`、`POST /api/auth/logout`、`POST /api/auth/change-password` |
| 当前用户 | `GET /api/me`、`PATCH /api/me/profile`、`GET /api/me/settings`、`PATCH /api/me/settings/:key` |
| 权限 | `GET /api/permissions/roles`、`GET /api/permissions/me`、`GET /api/permissions/projects/:projectId/members`、`PATCH /api/permissions/projects/:projectId/members/:memberId` |
| 模型配置 | `GET /api/models/effective-config`、`PATCH /api/models/projects/:projectId` |
| 仓库 | `GET/POST /api/projects/:projectId/repositories`、`DELETE /api/projects/:projectId/repositories/:repositoryId` |
| 系统存储 | `GET /api/system/storage`、`POST /api/system/storage/test`、`POST /api/system/storage/init-postgres`、`POST /api/system/storage/switch` |
| 内部鉴权 | `GET /internal/auth/introspect` |
| 内部模型配置 | `GET /internal/models/effective-config` |

详细说明见 [common-backend/README.md](common-backend/README.md)。

## MR Backend API 功能

MR Backend 默认端口 `9021`，承载项目和检视业务能力。

| 功能 | 主要 API |
| --- | --- |
| 健康检查 | `GET /api/health` |
| 规则与 Skill | `/api/projects/:projectId/rule-sets`、`/rule-documents`、`/rule-details`、`/expert-rule-bindings`、`/custom-skills`、`/custom-skill-assets`、`/expert-skill-bindings`、`/review-policy` |
| 专家 Agent | `GET /api/projects/:projectId/agents`、`GET/POST /api/projects/:projectId/expert-profiles`、`PATCH /api/projects/:projectId/expert-profiles/:agentKey`、`GET/POST /api/projects/:projectId/expert-tool-bindings` |
| MR 队列 | `GET /api/mr-review/projects/:projectId/merge-requests`、`POST /api/mr-review/projects/:projectId/sync`、`POST /api/mr-review/projects/:projectId/merge-requests/status-refresh`、`GET /api/mr-review/projects/:projectId/dead-letters` |
| MR 详情与评审 | `GET /api/mr-review/merge-requests/:mrId`、`GET /api/mr-review/merge-requests/:mrId/logs`、`POST /api/mr-review/merge-requests/:mrId/review-jobs`、`POST /api/mr-review/merge-requests/:mrId/pause`、`POST /api/mr-review/merge-requests/:mrId/stop`、`POST /api/mr-review/review-jobs/:jobId/retry` |
| Review Run | `GET /api/mr-review/review-runs/:runId`、`GET /api/mr-review/review-runs/:runId/trace`、`GET /api/mr-review/review-runs/:runId/session-logs`、`GET /api/mr-review/review-runs/:runId/artifacts` |
| Finding 操作 | `PATCH /api/mr-review/review-findings/:findingId`、`POST /api/mr-review/review-findings/:findingId/feedback`、`POST /api/mr-review/merge-requests/:mrId/publish` |
| Full Review | `/api/full-review/projects/:projectId/jobs`、`/api/full-review/jobs/:jobId`、`/api/full-review/jobs/:jobId/trace`、`/api/full-review/jobs/:jobId/session-logs`、`/api/full-review/repositories/:repositoryId/snapshots`、`/api/full-review/snapshots/:snapshotId/findings` |
| VCS 代理 | `GET /api/vcs/:projectId/capabilities`、`GET /api/vcs/:projectId/merge-requests/:mrId/diff`、`/files`、`/file`、`POST /comment`、`POST /status` |
| Webhook | `POST /api/webhooks/github/:projectId`、`POST /api/webhooks/codehub/:projectId`、`POST /api/webhooks/:provider/:projectId` |
| 观测与质量 | `GET /api/projects/:projectId/queue/summary`、`/toolchain/status`、`/static-tools/availability`、`/agents/quality`、`/review-quality/summary`、`/evaluation-reports`、`/rule-health`、`GET /api/observability/review-quality` |

详细说明见 [mr-backend/README.md](mr-backend/README.md)。

## Frontend 接入方式

Frontend 默认端口 `9020`。浏览器只访问 Frontend Gateway；Gateway 需要知道两个后端地址：

```bash
COMMON_API_BASE=http://127.0.0.1:9022
MR_API_BASE=http://127.0.0.1:9021
```

旧的 `VITE_COMMON_API_BASE`、`VITE_MR_API_BASE`、`VITE_API_BASE` 只保留给浏览器直连后端的历史部署，默认不要设置。

详细说明见 [frontend/README.md](frontend/README.md)。
