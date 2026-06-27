# Common 用户认证与模型配置接入文档

本文面向需要接入 Jolt Common Backend 的其它系统团队，重点说明两类公共能力：

- 用户认证服务：登录、session、用户身份校验、项目 membership、用户个人 settings。
- 模型配置服务：项目级 LLM 配置、有效配置查询、服务间配置拉取。
- 公共信息读取：项目、成员、权限、项目 settings、系统设置等公共信息。

接入系统必须通过 HTTP API 调用 Common，不允许直接读取或写入 Common 数据库表。

## 术语

| 名称 | 说明 |
| --- | --- |
| Common | 公共基础服务，提供账号、项目、权限、项目配置等 API |
| 接入系统 | 调用 Common 的业务系统，例如 MR Backend、Worker、其它平台服务 |
| 用户态 API | 面向前端或用户请求链路的 API，使用 `Authorization: Bearer <token>` |
| 内部 API | 面向后端服务间调用的 API，使用 `x-internal-service-token` |
| Project | Common 管理的项目空间，权限和配置都挂在 project 上 |
| Membership | 用户在项目下的角色，例如 `observer`、`developer`、`reviewer`、`project_admin` |
| Effective Config | 部署默认配置与项目 settings 合并后的有效配置 |

## 接入前准备

平台侧需要提供以下信息：

```bash
COMMON_API_BASE=http://127.0.0.1:9022
JOLT_INTERNAL_SERVICE_TOKEN=replace-with-service-token
```

前端应用还需要配置：

```bash
VITE_COMMON_API_BASE=http://127.0.0.1:9022
```

后端服务必须把 `JOLT_INTERNAL_SERVICE_TOKEN` 放在服务端环境变量或密钥系统中，不要下发到浏览器、移动端或任何不可信客户端。

如果本地或内网模型网关使用 `http://127.0.0.1`、`http://localhost` 或私有网段地址，需要在 Common Backend 服务端显式允许私有 LLM Base URL：

```bash
JOLT_ALLOW_PRIVATE_LLM_BASE_URLS=1
```

本地 `scripts/start-all.mjs` 会默认设置这个变量。生产环境建议保持关闭，并使用 HTTPS 模型网关。

## 鉴权方式

Common 有两套鉴权方式。

| 场景 | Header | 说明 |
| --- | --- | --- |
| 用户态请求 | `Authorization: Bearer <user_token>` | 由 `/api/auth/login` 返回 |
| 服务间请求 | `x-internal-service-token: <token>` | 由平台统一分配 |
| 服务间校验用户 | 同时携带两个 header | `Authorization` 表示待校验用户，`x-internal-service-token` 表示调用方服务身份 |

示例：

```bash
curl -sS "$COMMON_API_BASE/internal/auth/introspect" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

## 公共信息读取 API

Common 负责提供跨系统共享的用户、项目、权限、项目设置和系统设置。其它系统读取这些公共信息时，应按调用场景选择 Bearer 用户态 API 或 internal 服务间 API。

### 读取方式选择

| 场景 | 使用方式 | 说明 |
| --- | --- | --- |
| 前端页面读取用户、项目、成员、settings | Bearer 用户态 API | 使用当前登录用户权限，敏感字段已脱敏 |
| 业务后端收到用户请求后做鉴权 | `/internal/auth/introspect` | 同时携带用户 Bearer Token 和 internal token |
| Worker、定时任务读取项目配置 | `/internal/models/effective-config` | 只携带 internal token，返回运行时完整配置 |
| 无用户上下文读取成员、审计、邀请等管理列表 | 需要新增 internal API | 当前这些列表只提供 Bearer 用户态接口 |

### API 总览

| 信息类型 | API | 鉴权 | 说明 |
| --- | --- | --- | --- |
| 当前用户和可访问项目 | `GET /api/me` | Bearer | 返回 `user` 和当前用户可访问的 `projects` |
| 当前用户个人设置 | `GET /api/me/settings` | Bearer | 返回个人 settings，敏感字段脱敏 |
| 用户身份和项目 membership | `GET /internal/auth/introspect` | internal token，可携带 Bearer | 返回 `active`、`user`、`memberships`、用户 settings |
| 项目列表 | `GET /api/projects` | Bearer | 当前用户可访问项目；root 返回全部项目 |
| 可发现项目 | `GET /api/projects/discover` | Bearer | 返回可申请加入项目和申请状态 |
| 项目详情 | `GET /api/projects/:projectId` | observer+ | 返回项目名称、描述、data policy |
| 项目成员 | `GET /api/projects/:projectId/members` | project_admin+ | 返回成员、用户、角色列表 |
| 项目 settings | `GET /api/projects/:projectId/settings` | observer+ | 返回项目 settings，敏感字段脱敏 |
| 项目有效配置 | `GET /api/projects/:projectId/effective-config` | observer+ | 返回部署默认配置和项目 settings 合并后的配置，敏感字段脱敏 |
| 内部项目有效配置 | `GET /internal/models/effective-config?project_id=...` | internal token | 返回运行时完整项目配置和 `source.project_settings` |
| 角色定义 | `GET /api/permissions/roles` | 无 | 返回全局角色和项目角色定义 |
| 当前用户权限 | `GET /api/permissions/me` | Bearer | 返回当前用户和项目 membership |
| 成员权限列表 | `GET /api/permissions/projects/:projectId/members` | project_admin+ | 返回项目成员权限视图 |
| 加入申请 | `GET /api/projects/:projectId/join-requests` | project_admin+ | 返回项目加入申请 |
| 邀请码 | `GET /api/projects/:projectId/invitations` | project_admin+ | 返回项目邀请记录 |
| 项目审计 | `GET /api/projects/:projectId/audit-logs` | project_admin+ | 返回项目操作审计日志 |
| 系统存储设置 | `GET /api/system/storage` | root | 返回数据库驱动、PostgreSQL 状态和配置状态 |

### 典型读取示例

业务后端校验用户 token 并获取 membership：

```bash
curl -sS "$COMMON_API_BASE/internal/auth/introspect" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

Worker 按项目读取运行时配置：

```bash
curl -sS "$COMMON_API_BASE/internal/models/effective-config?project_id=$PROJECT_ID" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

后台任务按用户 ID 读取用户 settings 和 membership：

```bash
curl -sS "$COMMON_API_BASE/internal/auth/introspect?user_id=$USER_ID" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

前端或管理后台读取项目成员：

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/members" \
  -H "Authorization: Bearer $USER_TOKEN"
```

前端或管理后台读取项目 settings：

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/settings" \
  -H "Authorization: Bearer $USER_TOKEN"
```

### 脱敏规则和边界

- Bearer 用户态接口会脱敏敏感字段，例如 `default_api_key` 只返回 `default_api_key_has_value` 和 `default_api_key_masked`。
- `/internal/models/effective-config` 面向服务运行时，可能返回完整项目配置，调用方不能把响应原样返回给前端。
- `/internal/auth/introspect` 可能返回用户 settings，调用方不要在日志中打印 token、API key、VCS token。
- Common 不提供业务域数据，例如仓库、MR、Review Job、Finding、Worker 日志。
- 当前没有通用的 internal 成员列表、审计列表、邀请列表接口；无用户上下文的后端服务如需这些数据，应新增 internal API，不允许直接读 Common 表。

## 用户认证服务

### 登录获取用户 token

接口：

```http
POST /api/auth/login
Content-Type: application/json
```

请求：

```json
{
  "username": "local-admin",
  "password": "admin123"
}
```

curl：

```bash
curl -sS "$COMMON_API_BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"local-admin","password":"admin123"}'
```

响应：

```json
{
  "token": "USER_TOKEN",
  "user": {
    "id": "user_local_admin",
    "username": "local-admin",
    "display_name": "本机管理员",
    "email": "local@example.com",
    "global_role": "root",
    "status": "active"
  }
}
```

接入系统应保存 `token`，后续用户态 API 请求统一携带：

```http
Authorization: Bearer USER_TOKEN
```

### 查询当前 session

接口：

```http
GET /api/auth/session
Authorization: Bearer <user_token>
```

响应：

```json
{
  "authenticated": true,
  "user": {
    "id": "user_local_admin",
    "username": "local-admin",
    "global_role": "root",
    "status": "active"
  }
}
```

前端可用该接口做刷新页面后的登录态恢复。

### 查询当前用户和项目列表

接口：

```http
GET /api/me
Authorization: Bearer <user_token>
```

响应：

```json
{
  "user": {
    "id": "user_local_admin",
    "username": "local-admin",
    "global_role": "root"
  },
  "projects": [
    {
      "id": "project_default",
      "name": "默认项目",
      "description": "本机调试项目"
    }
  ]
}
```

前端通常用 `/api/me` 初始化用户信息和项目切换器。

### 服务端校验用户 token

接入系统后端不要自己解析或查询 Common 数据库。收到用户请求后，应把用户 token 透传给 Common 内部接口校验。

接口：

```http
GET /internal/auth/introspect
Authorization: Bearer <user_token>
x-internal-service-token: <service_token>
```

curl：

```bash
curl -sS "$COMMON_API_BASE/internal/auth/introspect" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

响应：

```json
{
  "active": true,
  "user": {
    "id": "user_local_admin",
    "username": "local-admin",
    "global_role": "root",
    "is_root": true
  },
  "memberships": [
    {
      "project_id": "project_default",
      "role": "system_admin"
    }
  ],
  "settings": {
    "vcs_tokens": {
      "codehub_token": "token-value",
      "github_token": "token-value"
    },
    "preferences": {}
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `active` | token 是否有效 |
| `user.id` | Common 用户 ID |
| `user.username` | 登录用户名 |
| `user.global_role` | 全局角色，当前支持 `user`、`root` |
| `user.is_root` | 是否平台 root |
| `memberships` | 用户可访问项目和角色列表 |
| `settings` | 用户个人 settings，供后端服务读取用户级 token 或偏好 |

接入系统应在本地做权限判断：

```ts
type Membership = { project_id: string; role: string };

const roleRank: Record<string, number> = {
  observer: 1,
  developer: 2,
  reviewer: 3,
  project_admin: 4,
  system_admin: 5
};

function hasProjectRole(memberships: Membership[], projectId: string, minRole: string) {
  const membership = memberships.find((item) => item.project_id === projectId);
  return Boolean(membership && roleRank[membership.role] >= roleRank[minRole]);
}
```

### 后台任务按 user_id 获取用户信息

Worker、定时任务或异步任务可能没有用户 Bearer Token，但任务表里保存了 `requested_by` 用户 ID。此时可以通过 `user_id` 查询：

```bash
curl -sS "$COMMON_API_BASE/internal/auth/introspect?user_id=$USER_ID" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

响应结构与 Bearer token introspect 相同。

### 用户个人 settings

用户态接口：

```http
GET /api/me/settings
PATCH /api/me/settings/:key
Authorization: Bearer <user_token>
```

当前支持：

| Key | 说明 |
| --- | --- |
| `vcs_tokens` | 用户级代码平台 token，例如 `github_token`、`codehub_token` |
| `preferences` | 用户偏好 |

保存示例：

```bash
curl -sS "$COMMON_API_BASE/api/me/settings/vcs_tokens" \
  -X PATCH \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"github_token":"ghp_xxx","codehub_token":"codehub_xxx"}'
```

用户态读取时敏感字段会脱敏；内部 introspect 会返回真实 settings，供可信后端服务使用。

## 模型配置服务

Common 的模型配置服务负责保存和返回项目级 LLM 配置。它不负责实际调用模型；模型调用由接入业务服务完成。

### 配置来源

Effective Config 的来源：

1. Common 部署配置中的 `llm.*` 默认值。
2. 项目 settings 中的 `llm_policy`。
3. 其它项目 settings，例如 `data_policy`、`queue_policy`、`token_usage`，会被放入 effective config，供业务服务按需解释。

`llm_policy` 会合并到 `effective_config.llm`。

### 项目管理员配置 LLM

推荐使用项目 settings 接口：

```http
PATCH /api/projects/:projectId/settings/llm_policy
Authorization: Bearer <user_token>
Content-Type: application/json
```

请求：

```json
{
  "default_provider": "dashscope-openai-compatible",
  "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
  "default_model": "MiniMax-M2.7",
  "default_api_key": "sk-...",
  "request_timeout_seconds": 120,
  "max_output_tokens": 8192,
  "enable_stream": true
}
```

curl：

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/settings/llm_policy" \
  -X PATCH \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "default_provider": "dashscope-openai-compatible",
    "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
    "default_model": "MiniMax-M2.7",
    "default_api_key_masked": "****abcd",
    "default_api_key_has_value": true,
    "request_timeout_seconds": 120,
    "max_output_tokens": 8192,
    "enable_stream": true
  }'
```

响应：

```json
{
  "key": "llm_policy",
  "value": {
    "default_provider": "dashscope-openai-compatible",
    "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
    "default_model": "MiniMax-M2.7",
    "default_api_key": "sk-...",
    "request_timeout_seconds": 120,
    "max_output_tokens": 8192,
    "enable_stream": true
  },
  "updated_at": "2026-06-25T10:00:00Z"
}
```

也可以使用 root 专用模型接口：

```http
PATCH /api/models/projects/:projectId
Authorization: Bearer <root_token>
```

该接口只接受模型相关字段，适合平台管理入口使用。

### 用户态读取项目有效配置

项目成员可以读取自己有权限项目的 effective config：

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/effective-config" \
  -H "Authorization: Bearer $USER_TOKEN"
```

响应示例：

```json
{
  "project_id": "project_default",
  "source": {
    "deployment_defaults": true,
    "project_settings": {
      "llm_policy": {
        "default_model": "MiniMax-M2.7"
      }
    }
  },
  "effective_config": {
    "llm": {
      "default_provider": "dashscope-openai-compatible",
      "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
      "default_model": "MiniMax-M2.7",
      "default_api_key": "sk-...",
      "request_timeout_seconds": 120,
      "max_output_tokens": 8192,
      "enable_stream": true
    }
  }
}
```

### 内部服务读取模型配置

业务服务和 Worker 推荐使用内部接口，避免依赖用户权限链路：

```http
GET /internal/models/effective-config?project_id=<project_id>
x-internal-service-token: <service_token>
```

curl：

```bash
curl -sS "$COMMON_API_BASE/internal/models/effective-config?project_id=$PROJECT_ID" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

响应：

```json
{
  "project_id": "project_default",
  "llm": {
    "default_provider": "dashscope-openai-compatible",
    "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
    "default_model": "MiniMax-M2.7",
    "default_api_key": "sk-...",
    "request_timeout_seconds": 120,
    "max_output_tokens": 8192,
    "enable_stream": true
  },
  "effective_config": {
    "llm": {
      "default_provider": "dashscope-openai-compatible",
      "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
      "default_model": "MiniMax-M2.7",
      "default_api_key": "sk-..."
    },
    "data_policy": {},
    "queue_policy": {}
  },
  "source": {
    "deployment_defaults": true,
    "project_settings": {
      "llm_policy": {},
      "data_policy": {}
    }
  }
}
```

安全说明：

- 用户态 Common API 不会回显 `llm.default_api_key` 明文，只返回脱敏状态。
- 支持直接使用 `default_api_key`，由 Common 保存项目级 API Key，并通过内部模型配置接口提供给业务服务。
- `source.project_settings` 会返回项目 settings，业务服务可按自己的领域解释其中的 `review_policy`、`vcs_policy`、`queue_policy` 等字段。

## 推荐接入模式

### 前端系统

1. 用户登录 `/api/auth/login`，保存 token。
2. 页面初始化调用 `/api/me`。
3. 项目切换器使用 `/api/projects`。
4. 项目设置页面读写 `/api/projects/:projectId/settings`。
5. 请求业务系统 API 时，把用户 token 透传给业务系统。

### 后端业务服务

1. 接收前端请求。
2. 从 `Authorization` header 中提取用户 token。
3. 调用 `/internal/auth/introspect` 校验 token。
4. 根据 `memberships` 判断用户是否有项目权限。
5. 需要模型或项目策略时，调用 `/internal/models/effective-config`。
6. 只读写业务服务自己的数据库表。

伪代码：

```ts
async function requireProjectRole(req, projectId, minRole) {
  const auth = await fetch(`${COMMON_API_BASE}/internal/auth/introspect`, {
    headers: {
      Authorization: req.headers.authorization,
      "x-internal-service-token": process.env.JOLT_INTERNAL_SERVICE_TOKEN
    }
  }).then((res) => res.json());

  if (!auth.active) throw new Error("unauthorized");
  if (auth.user?.is_root) return auth.user;

  const membership = auth.memberships.find((item) => item.project_id === projectId);
  if (!membership || !hasProjectRole(membership.role, minRole)) {
    throw new Error("forbidden");
  }
  return auth.user;
}
```

### Worker 或定时任务

1. 任务表保存 `project_id`，必要时保存 `requested_by` 用户 ID。
2. 启动任务后调用 `/internal/models/effective-config?project_id=...` 获取项目配置。
3. 如需用户级 token 或偏好，调用 `/internal/auth/introspect?user_id=...`。
4. 不直接读 Common 表。

## 缓存建议

后端服务可以缓存 Common 返回结果，但需要控制过期时间：

| 数据 | 建议 TTL | 说明 |
| --- | --- | --- |
| `/internal/auth/introspect` | 30-120 秒 | 权限变更后应尽快生效 |
| `/internal/models/effective-config` | 30-300 秒 | 模型和项目策略变更频率通常较低 |
| `/api/permissions/roles` | 1 小时 | 角色定义很少变化 |

当业务对权限实时性要求高时，不要缓存 introspect 结果。

## 错误处理

常见错误：

| 状态码 | error | 处理建议 |
| --- | --- | --- |
| `400` | `bad_request` 或参数提示 | 检查请求体字段 |
| `401` | `unauthorized` | 用户重新登录，或检查 internal token |
| `403` | `forbidden` | 提示用户无权限，或联系项目管理员 |
| `404` | `not_found` | 检查 project_id、setting key、资源 ID |
| `500` | `internal_error` | 记录请求 ID/上下文并联系平台维护者 |

内部 API 如果返回 `401`，优先检查：

- 是否设置了 `JOLT_INTERNAL_SERVICE_TOKEN`。
- 请求 header 是否为 `x-internal-service-token`。
- 调用方和 Common 是否使用同一份 token。

## 安全要求

- 不要把 `JOLT_INTERNAL_SERVICE_TOKEN` 暴露给浏览器。
- 不要在日志中打印用户 token、internal token、API key、VCS token。
- 不要把 Common 返回的用户 settings 原样返回给前端；用户态 `/api/me/settings` 已做脱敏，内部 API 没有脱敏。
- 不要直接读取 Common 的 `users`、`auth_sessions`、`projects`、`project_members`、`project_settings`、`user_settings` 表。
- API key 可由项目设置页直接填写为 `default_api_key`；普通用户接口只返回脱敏状态，内部服务接口用于运行时读取。

## 最小接入检查清单

- 已配置 `COMMON_API_BASE`。
- 已配置服务端 `JOLT_INTERNAL_SERVICE_TOKEN`。
- 前端能通过 `/api/auth/login` 获取 token。
- 后端能通过 `/internal/auth/introspect` 校验 token。
- 后端能根据 `memberships` 判断项目权限。
- 后端或 Worker 能通过 `/internal/models/effective-config` 获取项目模型配置。
- 没有直接 SQL 读取 Common 表。
