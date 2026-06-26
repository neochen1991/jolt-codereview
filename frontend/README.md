# Jolt Frontend

Jolt Frontend 是 React + Vite 前端，负责登录、项目空间、MR 队列、评审详情、规则/专家配置、用户权限、系统设置和全仓 review 的交互界面。它不是单后端前端：运行时会按 API 路径把请求分发到 Common Backend 或 MR Backend。

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
VITE_COMMON_API_BASE=http://127.0.0.1:9022 \
VITE_MR_API_BASE=http://127.0.0.1:9021 \
VITE_API_BASE=http://127.0.0.1:9021 \
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
VITE_COMMON_API_BASE=http://127.0.0.1:9022
VITE_MR_API_BASE=http://127.0.0.1:9021
VITE_API_BASE=http://127.0.0.1:9021
```

生产构建：

```bash
npm run build
```

预览或部署 `dist/` 即可。部署到 Nginx/CDN 时，需要让前端构建时使用线上 API base。

## API 分流规则

前端统一使用 `api(path, init)` 调用后端，底层由 `resolveApiBase()` 按路径分流。

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
| `VITE_COMMON_API_BASE` | Common Backend 地址。新部署必须配置 |
| `VITE_MR_API_BASE` | MR Backend 地址。新部署必须配置 |
| `VITE_API_BASE` | 旧单后端兼容地址；当上面两个变量缺失时作为 fallback |

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

1. 构建时设置 `VITE_COMMON_API_BASE` 和 `VITE_MR_API_BASE` 为可访问的 HTTPS 地址。
2. 两个后端需要允许前端域名的 CORS。
3. 登录 token 存储在浏览器 `localStorage` 的 `jolt_auth_token`。
4. 前端请求会自动添加 `Authorization: Bearer <token>`。

示例：

```bash
VITE_COMMON_API_BASE=https://jolt-common.example.com \
VITE_MR_API_BASE=https://jolt-mr.example.com \
npm run build
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
