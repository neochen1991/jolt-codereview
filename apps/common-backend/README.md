# Jolt Common Backend

Common Backend 是 Jolt CodeReview 的公共平台服务，负责用户、会话、权限、系统设置和模型配置。它不承载 MR 队列、评审任务或 VCS 同步；这些能力属于 MR Backend。

## 服务职责

- 提供登录、注册、登出、改密和 session 查询。
- 提供当前用户 profile、个人设置和项目权限视图。
- 提供项目成员权限管理。
- 提供项目级 LLM 模型配置读取和修改。
- 提供系统级 PostgreSQL 存储配置读取、测试、初始化和切换。
- 提供内部服务鉴权和内部模型配置查询，供 MR Backend / Worker 使用。

## 运行要求

- Node.js 24+
- npm
- PostgreSQL 14+
- `config.json` 中必须配置 `server.database_driver = "postgres"` 和 `server.postgres_url`

## 本仓启动

从仓库根目录启动：

```bash
npm install
cp config.example.json config.json
```

编辑 `config.json`：

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
CONFIG_PATH=./config.json \
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

## 独立仓启动

导出后进入 `split-repos/common-backend`：

```bash
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

## 配置项

| 配置/环境变量 | 说明 |
| --- | --- |
| `CONFIG_PATH` | 配置文件路径，默认读取当前工作目录 `config.json` |
| `server.host` | 监听地址，默认 `127.0.0.1` |
| `server.common_port` | Common Backend 端口，默认 `8010` |
| `server.postgres_url` | PostgreSQL 连接串，必填 |
| `server.postgres_user` / `server.postgres_password` | 可选；需要覆盖连接串账号密码时使用 |
| `server.postgres_query_timeout_seconds` | PG 连接和查询超时 |
| `JOLT_INTERNAL_SERVICE_TOKEN` | 内部 API token；MR Backend / Worker 调用 `/internal/*` 时必须携带 |

## 用户 API 接入

先登录获取 Bearer Token：

```bash
curl -sS http://127.0.0.1:8010/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"local-admin","password":"admin123"}'
```

后续请求都带：

```bash
Authorization: Bearer <token>
```

示例：

```bash
curl -sS http://127.0.0.1:8010/api/me \
  -H "Authorization: Bearer $JOLT_TOKEN"
```

## 内部 API 接入

内部 API 不使用用户 Bearer Token，而使用服务间 token：

```bash
x-internal-service-token: <JOLT_INTERNAL_SERVICE_TOKEN>
```

示例：

```bash
curl -sS 'http://127.0.0.1:8010/internal/models/effective-config?project_id=project_default' \
  -H "x-internal-service-token: $JOLT_INTERNAL_SERVICE_TOKEN"
```

内部模型配置接口会隐藏真实 API key，只返回 provider/base url/model/key env 等运行时需要的信息。

## API 功能清单

### Health

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务健康、SLI 摘要和服务名 |

### Auth

| Method | Path | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/login` | 用户名密码登录，返回 token 和用户信息 |
| `POST` | `/api/auth/register` | 注册普通用户 |
| `GET` | `/api/auth/session` | 查询当前 token 对应 session |
| `POST` | `/api/auth/logout` | 注销当前 session |
| `POST` | `/api/auth/change-password` | 修改当前用户密码 |

### Current User

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/me` | 当前用户和可访问项目 |
| `PATCH` | `/api/me/profile` | 修改 display name / email |
| `GET` | `/api/me/settings` | 获取当前用户个人设置 |
| `PATCH` | `/api/me/settings/:key` | 保存单项个人设置 |

### Permissions

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/permissions/roles` | 角色定义和权限边界 |
| `GET` | `/api/permissions/me` | 当前用户全局和项目权限 |
| `GET` | `/api/permissions/projects/:projectId/members` | 项目成员权限列表 |
| `PATCH` | `/api/permissions/projects/:projectId/members/:memberId` | 修改项目成员角色 |
| `GET` | `/internal/auth/introspect` | 内部服务校验用户 token |

### Models

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/models/effective-config?project_id=...` | 用户态读取项目有效模型配置 |
| `PATCH` | `/api/models/projects/:projectId` | 修改项目模型配置 |
| `GET` | `/internal/models/effective-config?project_id=...` | 内部服务读取项目有效模型配置 |

### System

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/system/storage` | 查看当前数据库运行状态和存储配置 |
| `POST` | `/api/system/storage/test` | 测试 PostgreSQL 连接 |
| `POST` | `/api/system/storage/init-postgres` | 初始化 PG 表结构 |
| `POST` | `/api/system/storage/switch` | 保存数据库目标配置 |

## 权限边界

- `/api/auth/login`、`/api/auth/register` 不需要 Bearer Token。
- `/api/me/*` 需要登录。
- `/api/permissions/projects/*` 需要项目管理员或 root。
- `/api/models/projects/:projectId` 需要项目管理员或 root。
- `/api/system/*` 只有 root 可以访问。
- `/internal/*` 只接受 `x-internal-service-token`。

## 与其它服务的关系

- Frontend 通过 `VITE_COMMON_API_BASE` 调用 Common API。
- MR Backend 可以通过 `/internal/auth/introspect` 校验用户 token。
- Worker 可以通过 `/internal/models/effective-config` 读取模型配置。
- Common Backend 和 MR Backend 必须连接同一个 PostgreSQL 数据库。
