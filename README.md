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

Windows PowerShell 等价命令：

```powershell
Copy-Item common-backend/config.example.json common-backend/config.json
Copy-Item mr-backend/config.example.json mr-backend/config.json
Copy-Item frontend/.env.example frontend/.env
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

`common-backend/config.json` 建议同时放模型配置。内网部署优先接公司模型网关；不要依赖外网代理一定可用：

```json
{
  "llm": {
    "default_provider": "dashscope-openai-compatible",
    "default_base_url": "https://your-llm-gateway/v1",
    "default_model": "your-model",
    "default_api_key_env": "JOLT_LLM_API_KEY",
    "request_timeout_seconds": 600,
    "max_output_tokens": 8192,
    "enable_stream": true
  },
  "server": {
    "host": "127.0.0.1",
    "common_port": 9022,
    "database_driver": "postgres",
    "postgres_url": "postgresql://USER:PASSWORD@PG_HOST:5432/jolt_codereview",
    "postgres_query_timeout_seconds": 120
  }
}
```

`mr-backend/config.json` 建议放 VCS、PostgreSQL、Python 路径、队列配置：

```json
{
  "github": {
    "default_token_env": "GITHUB_TOKEN",
    "default_endpoint": "https://api.github.com"
  },
  "codehub": {
    "default_token_env": "CODEHUB_TOKEN",
    "default_endpoint": "https://codehub.company.local"
  },
  "server": {
    "host": "127.0.0.1",
    "mr_port": 9021,
    "common_port": 9022,
    "database_driver": "postgres",
    "postgres_url": "postgresql://USER:PASSWORD@PG_HOST:5432/jolt_codereview",
    "postgres_query_timeout_seconds": 120
  },
  "runtime": {
    "python_bin": "C:\\path\\to\\jolt-codereview\\mr-backend\\.venv\\Scripts\\python.exe"
  },
  "queue_policy": {
    "poll_interval_seconds": 300,
    "max_concurrency": 1,
    "max_attempts": 3,
    "heartbeat_timeout_seconds": 600,
    "worker_pool_size": 1,
    "max_worker_pool_size": 20,
    "worker_reconcile_seconds": 30
  },
  "skill_debug_policy": {
    "project_max_concurrency": 2,
    "user_max_concurrency": 1,
    "daily_session_limit": 20,
    "daily_token_limit": 1000000,
    "max_duration_seconds": 1800,
    "retention_days": 14,
    "debug_job_max_concurrency": 1
  }
}
```

Token 和 API Key 可以直接写入 `config.json`，例如 `default_token`、`default_api_key`，但多人调试和内网环境不建议这么做，避免把密钥提交到 Git。推荐在配置里写 `*_env`，再由每台机器设置自己的环境变量。

`skill_debug_policy` 只影响 Skill 调试会话，不改变正式 MR 检视并发。`debug_job_max_concurrency` 限制实际调试 Job 数；正式任务排队时 Worker 不再领取新的调试 Job。超过项目/用户并发、每日次数或 Token 上限时接口返回 429；`max_duration_seconds` 会由 Worker 在节点边界执行超时检查，`retention_days` 控制调试快照、诊断和导出的保留时间。Skill 调试快照不会保存真实 Token/API Key，只保留环境变量引用或脱敏值。

Skill 新版本统一保存为 draft，不能直接进入正式检视。服务端会强制校验 Bundle；同一 Bundle 哈希必须分别取得有效的“定向 A/B”和“严格生产路由”证据后，项目管理员才能激活。`degraded` 或 `inconclusive` 结果不满足激活门禁。`skill_developer` 可以创建草稿、绑定 Skill 并查看自己发起的调试，但不能激活版本或修改项目密钥与发布配置。

### Skill Checkpoint 编译与真实任务指标

新建或整包上传 Skill 版本时，服务端会把 `SKILL.md` 和 `references/*.md` 确定性编译为 Checkpoint Manifest。单独新增或覆盖草稿版本资源时，必须同时指定 `skill_key` 和 `version`；每次保存都会重新编译当前版本的完整 Bundle，并更新 `validation_json`、Manifest、编译器版本和 Bundle hash。草稿编译失败时资源仍会保存，页面会显示具体错误，方便继续修改，但该版本不能激活或进入调试执行。

激活时服务端会对当前资源使用同一编译器再次强校验，通过后 Manifest 与不可变版本一起固化。Skill Debug 和正式 MR 检视读取同一个版本化编译产物，Worker 不会再次解释新版本 Markdown。因此流程是：`草稿保存 -> 即时编译反馈 -> 调试读取该草稿 Manifest -> 激活重检 -> 正式任务读取该激活 Manifest`。支持以下写法：

- `## SEC-CMD-001 命令执行检查` 形式的显式 ID 标题。
- “检查点 / Checkpoints / Rules”章节下的子标题，并通过 `id`、`check`、`required_evidence` 等字段描述。
- 包含 `checkpoint_id`、`title`、`check`、`required_evidence`、`false_positive_patterns`、`fix_guidance` 列的 Markdown 表格。
- `严重级别`、`适用范围`、`如何检查`、`证据要求`、`误报排除`、`修复建议` 等中英文字段别名。

代码围栏中的示例不会被解析。重复 ID 或缺少检查要求、证据要求、误报排除、修复建议时，版本不能激活；接口会返回源文件、行号和诊断代码。没有 Manifest 的历史已激活版本仍可运行，但会标记为 `legacy_fallback`，建议创建新版本重新激活。

项目管理员可在项目设置的“真实任务 Skill 仪表盘”查看：

- 全量路由率和适用路由率；适用性由 Manifest 中的 `applies_to` 与 MR 变更文件匹配。
- Skill 加载率、Checkpoint 完成率、未闭环率和 Judge 保留后的命中率。
- 人工误报率及其反馈覆盖率；无人工反馈时显示暂无数据，不按 0% 处理。
- 旧版运行数据、未闭环 Checkpoint 和 `judge_unclassified_rejection` 决策异常。

仪表盘只统计 `production_review`。Skill Debug 会生成相同的单次运行事实用于调试，但不会污染正式指标。进入 Judge 的 Skill 候选都会写入决策账本；拒绝或合并必须保存原因码、中文解释、决策阶段和时间，不能无痕消失。仪表盘和 Judge 决策详情要求 `project_admin` 权限。

上传到 `scripts/` 的文件当前只作为只读参考资源。平台会记录调用意图并返回 `blocked_by_policy`，不会直接执行上传脚本；需要可执行脚本时必须另行部署具备网络、凭据、CPU、内存和超时隔离的沙箱。

### Review 质量引擎、回放与回滚

MR Backend 支持项目级 Review 质量灰度配置。在真实 Shadow A/B 达到质量门前，推荐先使用以下安全默认值：

```json
{
  "review_quality": {
    "context_engine": "v1",
    "semantic_index": "tree_sitter",
    "llm_replay": "record",
    "quality_shadow_mode": false
  }
}
```

- `context_engine`: `v2` 按符号和 Diff Hunk 生成 ContextUnit；`v1` 回滚到旧 Prompt 拼装路径。
- `semantic_index`: `tree_sitter` 使用本地语法树；`regex` 是明确标记为 heuristic 的降级路径；`typed` 目前在缺少语言服务时会显示 `partial / typed_index_unavailable` 并回退 Tree-sitter，不会伪装为 typed 成功。
- `llm_replay`: `off` 只实时调用；`record` 记录稳定 Seed、请求/响应 Hash 和调用指纹；`replay` 只读取已有 Exchange，缺记录会明确失败且不会偷偷联网；`live_repeat` 实时重跑并更新记录。
- `quality_shadow_mode`: 标记项目允许进入 Shadow A/B。实际双跑由 `node scripts/run-review-quality-shadow.mjs` 对冻结 Snapshot 执行；Shadow Runner 强制 `publish_allowed=false`，只写独立质量报告，不替代正式发布结果。单独修改这个开关不会在普通 Review Job 内隐式双跑。

回滚顺序：先把 `context_engine` 改为 `v1`；如果语义索引异常，再把 `semantic_index` 改为 `regex`；模型网关或存储异常时把 `llm_replay` 改为 `off`。修改后只影响新建 Review Run，已有 Run 的 `coverage_json`、Context Health 和调用指纹仍保留用于审计。

生产环境默认只保留 Prompt/Response Hash，不因为 `record` 自动持久化完整模型响应。Skill Debug 使用冻结 MR Snapshot 时，可在会话 TTL 内启用 Exact Replay 存储；调试结束后由 `skill_debug_policy.retention_days` 和清理任务删除。不要在共享数据库中无限期保存源码、Prompt、工具结果或完整模型响应。Review 页面“真实任务质量仪表盘”会显示 `full / partial / patch_only / blocked`、Candidate 漏斗、Checkpoint 闭环、反馈精确率和可复现状态；没有数据时显示 unavailable，不按成功处理。

生产任务确实需要 Exact Replay 时，除把 `review_quality.llm_replay` 设为 `record/replay` 外，还必须显式授权完整响应的短期留存，否则 `replay` 会明确报“没有可用 Exchange Store”，不会偷偷改成联网调用。建议按项目数据合规要求配置：

```json
{
  "data_policy": {
    "llm_response_retention": "replay",
    "llm_response_retention_days": 14
  }
}
```

`llm_response_retention` 只有 `replay` 或 `full_debug` 会打开完整响应存储；到期记录由 Worker 建库/启动清理。包含敏感源码的项目应缩短天数、限制数据库访问并完成审计，未获授权时保持 Hash-only。

Windows 内网部署需要用项目虚拟环境安装 `mr-backend/requirements.txt`，其中包含 Tree-sitter 及语言解析器。确认 Worker 使用同一解释器：

```powershell
$env:PYTHON_BIN="$PWD\mr-backend\.venv\Scripts\python.exe"
& $env:PYTHON_BIN -c "import tree_sitter, tree_sitter_java, tree_sitter_python; print('tree-sitter ok')"
```

内网机器无法访问 PyPI 时，应在联网机器下载与目标 Windows/Python 版本匹配的 wheel，再从内部制品库或离线目录安装；不要让系统 Python 与 Worker 虚拟环境混用。源码 Worktree、PostgreSQL、CodeHub 和内部模型域名应加入 `NO_PROXY`，避免本地源码读取或内网请求被代理拦截。

如果配置文件不在默认位置，可以分别指定服务配置路径：

```bash
export COMMON_CONFIG_PATH=/absolute/path/to/common-config.json
export MR_CONFIG_PATH=/absolute/path/to/mr-config.json
```

Windows PowerShell:

```powershell
$env:COMMON_CONFIG_PATH="$PWD\common-backend\config.json"
$env:MR_CONFIG_PATH="$PWD\mr-backend\config.json"
```

### 启动环境变量清单

以下变量建议作为本机启动脚本或 PowerShell 配置保存。它们不适合只写进 `config.json`，因为有些变量用于告诉启动脚本去哪读配置，有些变量用于服务间鉴权或本地初始化。

| 环境变量 | 是否必需 | 用途 | 能否放进 config.json |
| --- | --- | --- | --- |
| `COMMON_CONFIG_PATH` | 可选 | 指定 Common 配置文件路径；默认 `common-backend/config.json` | 否 |
| `MR_CONFIG_PATH` | 可选 | 指定 MR Backend 配置文件路径；默认 `mr-backend/config.json` | 否 |
| `JOLT_INTERNAL_SERVICE_TOKEN` | 必需 | Common、MR Backend、Worker 内部通信鉴权 | 当前必须用环境变量 |
| `JOLT_SEED_DEV_DATA` | 本地首次调试建议 | 创建默认项目、默认管理员和基础配置 | 当前必须用环境变量 |
| `JOLT_LOCAL_ADMIN_PASSWORD` | 本地首次调试建议 | 设置 `local-admin` 初始化密码；默认 `admin123` | 当前必须用环境变量 |
| `JOLT_LLM_API_KEY` | 使用 LLM 时必需 | 模型网关 API Key，对应 `llm.default_api_key_env` | 可以直接写 `llm.default_api_key`，但不推荐 |
| `CODEHUB_TOKEN` | 接内网 CodeHub 时必需 | CodeHub API Token，对应 `codehub.default_token_env` | 可以直接写 `codehub.default_token`，但不推荐 |
| `GITHUB_TOKEN` | 接 GitHub 时可选 | GitHub API Token，对应 `github.default_token_env` | 可以直接写 `github.default_token`，但不推荐 |
| `PYTHON_BIN` | 可选 | Python Worker 解释器路径；优先级高于 `runtime.python_bin` | 可以放 `mr-backend.config.runtime.python_bin` |
| `JOLT_FRONTEND_HOST` | 内网访问时建议 | Frontend Gateway 监听地址；默认 `127.0.0.1` | 否，Frontend Gateway 从环境变量或 `frontend/.env` 读 |
| `JOLT_FRONTEND_PORT` | 可选 | Frontend Gateway 端口；默认 `9020` | 否 |
| `JOLT_VITE_PORT` | 可选 | Vite dev server 端口；默认 `9023` | 否 |
| `COMMON_API_BASE` | 可选 | Frontend Gateway 到 Common 的地址；默认按配置推导 | 否 |
| `MR_API_BASE` | 可选 | Frontend Gateway 到 MR Backend 的地址；默认按配置推导 | 否 |
| `JOLT_AUTO_SYNC_DISABLED` | 可选 | 设为 `1` 或 `true` 可关闭 MR 自动同步调度 | 否 |
| `HTTP_PROXY` / `HTTPS_PROXY` | 内网代理场景可选 | 访问外网或模型网关代理 | 否 |
| `NO_PROXY` / `no_proxy` | 内网代理场景建议 | 排除本机、PostgreSQL、CodeHub 内网地址不走代理 | 否 |

## 本仓三模块联调启动

三个模块各自有独立 `package.json`。首次运行先分别安装依赖：

```bash
npm --prefix common-backend install
npm --prefix mr-backend install
npm --prefix frontend install
python3 -m venv mr-backend/.venv
mr-backend/.venv/bin/pip install -r mr-backend/requirements.txt
```

Windows PowerShell:

```powershell
npm --prefix common-backend install
npm --prefix mr-backend install
npm --prefix frontend install
py -3 -m venv mr-backend\.venv
mr-backend\.venv\Scripts\python.exe -m pip install -r mr-backend\requirements.txt
```

如果只在当前仓库联调，推荐用根目录启动脚本一次拉起 Common Backend、MR Backend、Frontend Gateway 和 Vite：

```bash
JOLT_SEED_DEV_DATA=1 \
JOLT_LOCAL_ADMIN_PASSWORD=admin123 \
JOLT_INTERNAL_SERVICE_TOKEN=local-internal-token \
PYTHON_BIN=$PWD/mr-backend/.venv/bin/python \
npm run dev
```

Windows PowerShell:

```powershell
$env:JOLT_SEED_DEV_DATA="1"
$env:JOLT_LOCAL_ADMIN_PASSWORD="admin123"
$env:JOLT_INTERNAL_SERVICE_TOKEN="local-internal-token"
$env:PYTHON_BIN="$PWD\mr-backend\.venv\Scripts\python.exe"
$env:JOLT_LLM_API_KEY="your-llm-api-key"
$env:CODEHUB_TOKEN="your-codehub-token"
$env:NO_PROXY="127.0.0.1,localhost,PG_HOST,codehub.company.local"
$env:no_proxy="127.0.0.1,localhost,PG_HOST,codehub.company.local"
npm run dev
```

`JOLT_SEED_DEV_DATA=1` 只建议用于本地调试或初始化测试库。它会创建默认项目和默认管理员。默认管理员账号是：

- 用户名：`local-admin`
- 密码：`JOLT_LOCAL_ADMIN_PASSWORD`，未设置时为 `admin123`

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

### Windows 内网访问

单机调试时保持默认即可：

```powershell
$env:JOLT_FRONTEND_HOST="127.0.0.1"
npm run dev
```

浏览器访问：

```text
http://127.0.0.1:9020
```

如果要让同事从内网访问这台 Windows 机器上的页面，设置 Frontend Gateway 监听所有网卡：

```powershell
$env:JOLT_FRONTEND_HOST="0.0.0.0"
$env:JOLT_FRONTEND_PORT="9020"
npm run dev
```

同事浏览器访问：

```text
http://你的Windows内网IP:9020
```

只需要对外放通 `9020`。`9021`、`9022`、`9023` 默认不需要暴露给其他机器，浏览器只访问 Frontend Gateway，由 Gateway 转发到 Common Backend 和 MR Backend。

Windows 防火墙示例：

```powershell
New-NetFirewallRule -DisplayName "Jolt CodeReview Frontend 9020" -Direction Inbound -Protocol TCP -LocalPort 9020 -Action Allow
```

公司代理环境下，建议明确排除本机、PostgreSQL 和内网 CodeHub：

```powershell
$env:NO_PROXY="127.0.0.1,localhost,PG_HOST,codehub.company.local"
$env:no_proxy="127.0.0.1,localhost,PG_HOST,codehub.company.local"
```

如果访问外网模型网关、GitHub 或其它外部服务必须走代理，再设置：

```powershell
$env:HTTP_PROXY="http://proxy.company.local:8080"
$env:HTTPS_PROXY="http://proxy.company.local:8080"
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
- 密码：`JOLT_LOCAL_ADMIN_PASSWORD`，未设置时为 `admin123`

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

## Skill Debug PostgreSQL 集成验证

使用一个可丢弃的 PostgreSQL 数据库执行权限、配额、独立 Job、快照、取消、`stale_head`、发布保护和正式数据隔离验证：

```bash
TEST_POSTGRES_URL=postgresql://localhost:5432/jolt_skill_debug_test \
npm run verify:skill-debug-integration
```

该命令会在独立端口启动临时 Common/MR 服务，并向指定数据库写入带唯一后缀的测试数据。不要把生产数据库配置给 `TEST_POSTGRES_URL`。
