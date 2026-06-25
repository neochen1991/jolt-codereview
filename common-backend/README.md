# Jolt Common Backend

Common Backend 是 Jolt 平台的公共基础服务，负责账号、登录态、项目、成员、权限、项目配置、审计和系统存储配置。其它业务服务接入 Jolt 时，应通过 Common 提供的 HTTP API 获取用户身份、项目权限和项目配置，不要直接读取 Common 的数据库表。

Common 不负责 MR 同步、代码仓库绑定、评审任务、Worker、Finding、规则/Agent 配置执行等业务域能力。这些属于各业务服务，例如 MR Backend。

专项接入文档：

- [用户认证与模型配置接入文档](docs/auth-model-config-integration.md)

## 服务能力

Common 当前提供以下公共能力：

| 能力 | 说明 | 典型使用方 |
| --- | --- | --- |
| 账号与登录 | 注册、登录、登出、改密、查询当前 session | 前端、管理后台 |
| 用户资料 | 当前用户 profile、个人偏好、个人 VCS token 等设置 | 前端、业务服务 |
| 项目目录 | 创建项目、查询可访问项目、查询可申请加入的项目 | 平台管理员、业务团队 |
| 项目成员 | 添加成员、修改角色、移除成员、查询成员列表 | 项目管理员、业务后台 |
| 邀请与加入 | 邀请码、加入申请、审批加入申请 | 项目管理员、项目成员 |
| 项目配置 | LLM、VCS、评审策略、队列策略、数据策略等项目级 settings | 前端、MR Backend、Worker、其它业务服务 |
| 权限判断 | 查询角色定义、当前用户权限、内部服务 introspect | 前端、业务服务 |
| 审计日志 | 记录登录、项目、成员、配置、邀请等操作 | 管理后台、合规排查 |
| 系统存储 | PostgreSQL 配置查看、连通性测试、初始化、切换配置 | root 管理员 |

## 接入原则

- 用户态 API 使用 `Authorization: Bearer <token>`。
- 服务间 API 使用 `x-internal-service-token: <JOLT_INTERNAL_SERVICE_TOKEN>`。
- 其它服务可以和 Common 部署在同一 PostgreSQL 实例上，但不能直接读写 Common 表。
- 其它服务需要用户、项目、成员、配置时，必须调用 Common API。
- 业务域数据放在业务服务自己的表中，例如 MR 的仓库、MR、review job、finding、worker log 等都不属于 Common。

## 快速启动

运行要求：

- Node.js 24+
- npm
- PostgreSQL 14+

从仓库根目录启动 common：

```bash
npm install
cp config.example.json config.json
```

最小配置示例：

```json
{
  "server": {
    "host": "127.0.0.1",
    "common_port": 8010,
    "database_driver": "postgres",
    "postgres_url": "postgresql://USER:PASSWORD@127.0.0.1:5432/jolt_codereview"
  }
}
```

启动：

```bash
CONFIG_PATH=$PWD/config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
npm run dev:common
```

健康检查：

```bash
curl -sS http://127.0.0.1:8010/api/health
```

期望返回：

```json
{
  "ok": true,
  "service": "jolt-common-backend"
}
```

也可以进入模块目录单独启动：

```bash
cd common-backend
npm install
cp config.example.json config.json
CONFIG_PATH=./config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
npm run dev
```

生产启动：

```bash
npm run build
CONFIG_PATH=./config.json \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
npm run start
```

本地默认种子账号：

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `local-admin` | `admin123` | `root` |

## 配置项

| 配置/环境变量 | 说明 |
| --- | --- |
| `CONFIG_PATH` | 配置文件路径，默认读取当前工作目录 `config.json` |
| `server.host` | 监听地址，默认 `127.0.0.1` |
| `server.common_port` | Common Backend 端口，默认 `8010` |
| `server.database_driver` | 固定为 `postgres` |
| `server.postgres_url` | PostgreSQL 连接串，必填 |
| `server.postgres_user` / `server.postgres_password` | 可选；需要覆盖连接串账号密码时使用 |
| `server.postgres_query_timeout_seconds` | PostgreSQL 查询超时 |
| `llm.*` | Common 提供的默认模型配置，可被项目级 `llm_policy` 覆盖 |
| `logging.enabled` | 是否写 common API 日志 |
| `logging.dir` | common API 日志目录 |
| `logging.api_file` | common API 日志文件，默认 `jolt-common-api.log` |
| `JOLT_INTERNAL_SERVICE_TOKEN` | 内部服务 token；调用 `/internal/*` 必须携带 |

## 其他团队如何接入项目

### 1. 确认 Common 地址和内部 token

平台侧需要提供：

```bash
COMMON_API_BASE=http://127.0.0.1:8010
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token
```

前端类应用还需要：

```bash
VITE_COMMON_API_BASE=http://127.0.0.1:8010
```

### 2. 登录获取用户 token

```bash
curl -sS "$COMMON_API_BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"local-admin","password":"admin123"}'
```

响应会包含：

```json
{
  "token": "USER_TOKEN",
  "user": {
    "id": "user_local_admin",
    "username": "local-admin",
    "global_role": "root"
  }
}
```

后续用户态请求都带：

```bash
Authorization: Bearer <USER_TOKEN>
```

### 3. 创建或申请加入项目

root 创建项目：

```bash
curl -sS "$COMMON_API_BASE/api/projects" \
  -H "Authorization: Bearer $JOLT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"支付系统","description":"支付团队接入 Jolt"}'
```

普通用户查看可申请加入的项目：

```bash
curl -sS "$COMMON_API_BASE/api/projects/discover" \
  -H "Authorization: Bearer $JOLT_TOKEN"
```

申请加入项目：

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/join-requests" \
  -H "Authorization: Bearer $JOLT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"requested_role":"developer","reason":"支付团队接入"}'
```

项目管理员审批：

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/join-requests/$REQUEST_ID" \
  -X PATCH \
  -H "Authorization: Bearer $JOLT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"status":"approved"}'
```

### 4. 配置项目 settings

项目管理员可以写项目配置。Common 只负责保存和返回配置；具体业务含义由接入服务解释。

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/settings/llm_policy" \
  -X PATCH \
  -H "Authorization: Bearer $JOLT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "default_provider": "dashscope-openai-compatible",
    "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
    "default_model": "MiniMax-M2.7",
    "default_api_key_env": "MINIMAX_API_KEY"
  }'
```

常用 settings key：

| Key | 用途 | 说明 |
| --- | --- | --- |
| `llm_policy` | 模型配置 | provider、base url、model、api key env、timeout 等 |
| `vcs_policy` | 代码平台访问配置 | GitHub/CodeHub token、endpoint；由 MR 服务解释 |
| `review_policy` | 评审策略 | MR 服务使用，例如 MR 大小阈值 |
| `budget_policy` | 预算策略 | LLM 调用次数、token、耗时预算 |
| `agent_policy` | Agent 策略 | 业务服务可定义 Agent 开关 |
| `tool_policy` | 工具策略 | 业务服务可定义工具开关和限制 |
| `queue_policy` | 队列策略 | 业务服务可定义并发、重试、轮询间隔 |
| `publish_policy` | 发布策略 | 业务服务可定义评论/发布行为 |
| `data_policy` | 数据安全策略 | 敏感路径、脱敏、数据驻留等 |
| `token_usage` | Token 上报策略 | 上报 endpoint、鉴权、员工号来源等 |

读取项目配置：

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/settings" \
  -H "Authorization: Bearer $JOLT_TOKEN"
```

读取项目有效配置：

```bash
curl -sS "$COMMON_API_BASE/api/projects/$PROJECT_ID/effective-config" \
  -H "Authorization: Bearer $JOLT_TOKEN"
```

### 5. 业务服务通过内部 API 接入

业务后端拿到用户请求后，可以把用户 Bearer Token 透传给 Common 做鉴权和权限获取：

```bash
curl -sS "$COMMON_API_BASE/internal/auth/introspect" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

响应示例：

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
      "codehub_token": "...",
      "github_token": "..."
    }
  }
}
```

Worker 或后台任务没有用户 Bearer Token 时，可以按 `user_id` 查询用户设置和项目成员关系：

```bash
curl -sS "$COMMON_API_BASE/internal/auth/introspect?user_id=$USER_ID" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

业务服务读取项目有效配置：

```bash
curl -sS "$COMMON_API_BASE/internal/models/effective-config?project_id=$PROJECT_ID" \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

该接口会隐藏 `llm.default_api_key`，并返回 `source.project_settings`，业务服务可按自己的领域解释 `review_policy`、`vcs_policy`、`queue_policy` 等配置。

## API 清单

### Health

| Method | Path | 权限 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/health` | 无 | 服务健康和服务名 |

### Auth 与当前用户

| Method | Path | 权限 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/api/auth/login` | 无 | 用户名密码登录，返回 token |
| `POST` | `/api/auth/register` | 无 | 注册用户；首个用户为 root |
| `GET` | `/api/auth/session` | Bearer | 查询当前 session |
| `POST` | `/api/auth/logout` | Bearer | 注销当前 session |
| `POST` | `/api/auth/change-password` | Bearer | 修改当前用户密码 |
| `GET` | `/api/me` | Bearer | 当前用户和可访问项目 |
| `PATCH` | `/api/me/profile` | Bearer | 修改 display name / email |
| `GET` | `/api/me/settings` | Bearer | 当前用户个人设置，敏感字段脱敏 |
| `PATCH` | `/api/me/settings/:key` | Bearer | 保存个人设置；支持 `vcs_tokens`、`preferences` |

### Projects

| Method | Path | 权限 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/projects` | Bearer | 当前用户可访问项目；root 返回全部项目 |
| `GET` | `/api/projects/discover` | Bearer | 可发现项目和当前加入/申请状态 |
| `POST` | `/api/projects` | root | 创建项目 |
| `GET` | `/api/projects/:projectId` | observer+ | 查询项目详情 |
| `PATCH` | `/api/projects/:projectId` | project_admin+ | 修改项目名称、描述、data policy |
| `GET` | `/api/projects/:projectId/members` | project_admin+ | 查询成员列表 |
| `POST` | `/api/projects/:projectId/members` | project_admin+ | 添加或更新成员 |
| `PATCH` | `/api/projects/:projectId/members/:memberId` | project_admin+ | 修改成员角色 |
| `DELETE` | `/api/projects/:projectId/members/:memberId` | project_admin+ | 移除成员 |
| `GET` | `/api/projects/:projectId/settings` | observer+ | 查询项目 settings |
| `PATCH` | `/api/projects/:projectId/settings/:key` | project_admin+ | 保存项目单项 setting |
| `GET` | `/api/projects/:projectId/effective-config` | observer+ | 查询项目有效配置 |
| `GET` | `/api/projects/:projectId/join-requests` | project_admin+ | 查询加入申请 |
| `POST` | `/api/projects/:projectId/join-requests` | Bearer | 提交加入申请 |
| `PATCH` | `/api/projects/:projectId/join-requests/:requestId` | project_admin+ | 审批加入申请 |
| `GET` | `/api/projects/:projectId/invitations` | project_admin+ | 查询邀请 |
| `POST` | `/api/projects/:projectId/invitations` | project_admin+ | 创建邀请码 |
| `POST` | `/api/projects/join-by-invite` | Bearer | 使用邀请码加入项目 |
| `GET` | `/api/projects/:projectId/audit-logs` | project_admin+ | 查询项目审计日志 |

### Permissions

| Method | Path | 权限 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/permissions/roles` | 无 | 角色定义 |
| `GET` | `/api/permissions/me` | Bearer | 当前用户权限和项目 membership |
| `GET` | `/api/permissions/projects/:projectId/members` | project_admin+ | 成员权限列表 |
| `PATCH` | `/api/permissions/projects/:projectId/members/:memberId` | project_admin+ | 修改成员角色 |
| `GET` | `/internal/auth/introspect` | internal token | 内部服务鉴权、用户、membership、用户 settings |

### Models 与项目配置

| Method | Path | 权限 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/models/effective-config?project_id=...` | root | 查询项目有效模型配置 |
| `PATCH` | `/api/models/projects/:projectId` | root | 修改项目模型配置 |
| `GET` | `/internal/models/effective-config?project_id=...` | internal token | 内部服务读取项目有效配置 |

### System

| Method | Path | 权限 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/system/storage` | root | 查看数据库运行状态和存储配置 |
| `POST` | `/api/system/storage/test` | root | 测试 PostgreSQL 连接 |
| `POST` | `/api/system/storage/init-postgres` | root | 初始化 PostgreSQL 表结构 |
| `POST` | `/api/system/storage/switch` | root | 保存数据库目标配置到 `config.json` |

## 角色模型

全局角色：

| Role | 说明 |
| --- | --- |
| `user` | 普通用户 |
| `root` | 平台管理员，可管理所有项目和系统配置 |

项目角色：

| Role | Rank | 说明 |
| --- | --- | --- |
| `observer` | 1 | 只读查看项目 |
| `developer` | 2 | 项目开发成员 |
| `reviewer` | 3 | 可参与评审或审批类能力 |
| `project_admin` | 4 | 项目管理员，可管理成员、邀请和项目配置 |
| `system_admin` | 5 | root 在项目视图中的映射角色 |

接口文档中的 `observer+`、`project_admin+` 表示需要该角色或更高权限。root 默认拥有所有项目的 `system_admin` 权限。

## 响应和错误格式

成功响应通常直接返回对象或数组。错误响应格式：

```json
{
  "error": "unauthorized",
  "message": "login is required"
}
```

常见状态：

| 状态码 | 含义 |
| --- | --- |
| `400` | 参数不合法 |
| `401` | 未登录或内部 token 缺失 |
| `403` | 权限不足 |
| `404` | 资源不存在 |
| `500` | 服务内部错误 |

## 与其它服务的关系

- Frontend 通过 `VITE_COMMON_API_BASE` 调用 Common 用户态 API。
- MR Backend 通过 `/internal/auth/introspect` 校验用户 token 和项目权限。
- MR Worker 通过 `/internal/models/effective-config` 获取项目配置。
- 其它业务服务也应该按同样方式接入 Common。
- Common 可以与业务服务共用同一个 PostgreSQL 实例，但表归属必须清晰：业务服务不能直接读写 `users`、`projects`、`project_members`、`project_settings`、`user_settings`、`auth_sessions` 等 Common 表。

## 接入检查清单

- 已拿到 `COMMON_API_BASE`。
- 已拿到 `JOLT_INTERNAL_SERVICE_TOKEN`，并只在服务端保存。
- 前端请求使用用户 Bearer Token。
- 后端服务调用 `/internal/auth/introspect` 校验用户和 membership。
- 后台任务调用 `/internal/models/effective-config` 获取项目配置。
- 项目管理员已经配置所需 settings。
- 业务服务没有直接 SQL 读取 Common 表。
