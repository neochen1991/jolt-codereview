# Jolt Frontend

Jolt Frontend 是前端服务，也是浏览器访问入口。默认对外端口是 `9020`，内部包含一个轻量 Frontend Gateway：浏览器只访问同源 `/api/*`，Gateway 再按路径代理到 Common Backend 或 MR Backend。开发模式下 Gateway 会同时拉起 Vite dev server，Vite 默认只监听内部端口 `9023`。

## 服务职责

- 登录、注册、改密和当前用户信息展示。
- 项目选择、项目维护、成员权限、加入申请和邀请码。
- MR 队列过滤、批量操作、MR 详情、review run、findings、trace、session logs、artifacts。
- 规则集、规则文档、自定义 Skill、专家 Agent、工具绑定和 review policy 配置。
- Full review job、snapshot findings 和质量观测页面。
- 系统级 PostgreSQL 存储配置页面。

## 运行要求

- Node.js 24+
- npm
- 已启动 Common Backend
- 已启动 MR Backend

## 本仓启动

从仓库根目录：

```bash
npm install
npm run dev:web
```

访问：

```text
http://127.0.0.1:9020
```

## 模块启动

进入当前仓库根目录下的 `frontend`：

```bash
npm install
cp .env.example .env
npm run dev
```

`.env` 示例：

```bash
JOLT_FRONTEND_HOST=127.0.0.1
JOLT_FRONTEND_PORT=9020
JOLT_VITE_PORT=9023
COMMON_API_BASE=http://127.0.0.1:9022
MR_API_BASE=http://127.0.0.1:9021
```

生产构建：

```bash
npm run build
npm run start
```

生产模式下 `npm run start` 会启动同一个 Frontend Gateway，从 `dist/` 提供静态资源，并继续把 `/api/*`、`/internal/*` 代理到 Common/MR。部署时浏览器入口仍然只需要暴露 Frontend Gateway。

## API 分流规则

前端统一使用 `api(path, init)` 调用同源 API。默认 `resolveApiBase()` 返回空字符串，即走 Frontend Gateway；Gateway 的路由规则和前端路由规则保持一致。

Common Backend 路径：

```text
/api/auth/*
/api/me/*
/api/users/*
/api/permissions/*
/api/models/*
/api/system/*
/internal/auth/*
/internal/models/*
```

其它路径默认走 MR Backend，例如：

```text
/api/projects/*
/api/mr-review/*
/api/full-review/*
/api/vcs/*
/api/webhooks/*
/api/observability/*
```

配置优先级：

| 环境变量 | 说明 |
| --- | --- |
| `COMMON_API_BASE` | Frontend Gateway 代理到 Common Backend 的地址，默认 `http://127.0.0.1:9022` |
| `MR_API_BASE` | Frontend Gateway 代理到 MR Backend 的地址，默认 `http://127.0.0.1:9021` |
| `JOLT_FRONTEND_HOST` | Frontend Gateway 监听地址，默认 `127.0.0.1` |
| `JOLT_FRONTEND_PORT` | Frontend Gateway 监听端口，默认 `9020` |
| `JOLT_VITE_PORT` | 开发模式内部 Vite 端口，默认 `9023` |
| `VITE_COMMON_API_BASE` / `VITE_MR_API_BASE` / `VITE_API_BASE` | 仅保留给旧的浏览器直连后端部署；默认不要设置 |

## 用户接入流程

默认入口：

```text
/login
```

默认本机 root 账号：

- 用户名：`local-admin`
- 密码：`admin123`

登录成功后进入：

```text
/projects
```

进入项目工作台后，URL 形态：

```text
/projects/:projectId/:view
/projects/:projectId/review?mr=:mrId
```

常用 view：

| View | 功能 |
| --- | --- |
| `mr` / `review` | MR 队列和 MR 详情 |
| `full` | 全仓 review |
| `rules` | 规则与 Skill |
| `agents` | 专家 Agent |
| `repos` | 仓库绑定 |
| `policy` | Review policy 和工具策略 |
| `users` | 用户权限 |
| `queue` | 队列运维 |
| `personal` | 个人设置 |
| `settings` | 项目设置 |
| `system` | 系统设置 |

## 前端页面和 API 对应关系

| 页面 | Common API | MR API |
| --- | --- | --- |
| 登录/注册 | `/api/auth/*` | - |
| 项目选择 | `/api/me` | `/api/projects/discover`、`/api/projects/join-by-invite` |
| MR 队列 | - | `/api/mr-review/projects/:projectId/merge-requests`、`/sync`、`/status-refresh` |
| MR 详情 | - | `/api/mr-review/merge-requests/:mrId`、`/review-runs/:runId/*`、`/review-findings/:findingId` |
| Full Review | - | `/api/full-review/*` |
| 规则与专家 | - | `/api/projects/:projectId/rule-*`、`/custom-skills`、`/agents`、`/expert-*` |
| 项目设置 | `/api/models/*` | `/api/projects/:projectId/settings/*`、`/repositories` |
| 用户权限 | `/api/permissions/*` | `/api/projects/:projectId/members`、`/join-requests`、`/invitations` |
| 系统设置 | `/api/system/*` | - |

## 接入其它系统

如果把 Frontend 部署在独立域名下：

1. 对外只暴露 Frontend Gateway 域名。
2. 在 Frontend Gateway 所在机器配置 `COMMON_API_BASE` 和 `MR_API_BASE`。
3. Common/MR 后端只需要允许 Frontend Gateway 访问；浏览器不再直接访问两个后端。
4. 登录 token 存储在浏览器 `localStorage` 的 `jolt_auth_token`。
5. 前端请求会自动添加 `Authorization: Bearer <token>`。

示例：

```bash
npm run build
COMMON_API_BASE=http://jolt-common.internal:9022 \
MR_API_BASE=http://jolt-mr.internal:9021 \
npm run start
```

## 验证

构建：

```bash
npm run build
```

验证 API 分流：

```bash
npm run verify
```

手工前端冒烟建议：

1. 打开 `/login`。
2. 使用 `local-admin/admin123` 登录。
3. 进入默认项目。
4. 打开 MR 队列，确认能显示 MR 和状态。
5. 打开一个 MR 详情，确认 review run、findings、工具结果可以显示。
6. 打开系统设置，点击“测试配置”，确认 Common Backend 能连接 PostgreSQL。
