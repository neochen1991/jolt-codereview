# Jolt CodeReview

Jolt CodeReview 是一个项目级 AI 代码检视平台，面向生产环境的 MR 自动检视、专家 Agent 协作、静态工具证据采集和人工确认发布闭环。当前实现支持：

- GitHub Pull Request 作为当前本机调试 MR 数据源。
- CodeHub Merge Request 作为可配置数据源，支持通过 endpoint/path template 对接公司内网 API。
- TS API Backend + React 前端 + Python Review Worker。
- SQLite 本机存储。
- MiniMax-M2.7 本机 LLM 配置。
- LangGraph 确定性流程编排 + 受控 DeepAgents 专家节点。
- Security / Backend / Test / Performance / DDD / Frontend / Redis / Dependency / Database 等专家 Agent 检视流。
- Agent trace、LLM 调用记录、finding 确认、dry-run/真实发布到 GitHub comment。
- macOS / Windows 跨平台启动脚本。

## Windows 快速运行

建议使用 Windows 10/11 + PowerShell。首次运行分为“安装依赖”和“启动服务”两步：

```powershell
git clone https://github.com/neochen1991/jolt-codereview.git
cd jolt-codereview
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\install-windows.ps1
.\scripts\start-windows.ps1
```

启动后访问：

- API: `http://127.0.0.1:8011`
- Frontend: `http://127.0.0.1:5173`

如果机器不能访问 GitHub release、npm registry 或 PyPI，可以先跳过静态工具和规则下载：

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\install-windows.ps1 -SkipStaticTools -SkipStaticRules
.\scripts\start-windows.ps1
```

如果已经安装过依赖，只想启动：

```powershell
npm run start:windows
```

如果缺少 `node_modules` 或 `.venv`，并希望启动脚本自动补齐基础依赖：

```powershell
.\scripts\start-windows.ps1 -InstallIfMissing
```

## 环境要求

- Windows 10/11、macOS 或 Linux。
- Node.js 24+，用于内置 `node:sqlite`。
- Python 3.10+。
- npm。
- Java 17+ 或 21+，用于 Checkstyle、PMD、SpotBugs、Dependency-Check 等 Java 工具。
- 可选：`GITHUB_TOKEN`。不配置 token 时可以同步公开仓库 PR，但 GitHub API 可能很快触发 rate limit；配置 token 后可完整拉取 PR changed files。
- 可选：`CODEHUB_TOKEN`。接入公司内网 CodeHub 时使用。

Windows PowerShell 环境变量示例：

```powershell
$env:GITHUB_TOKEN="ghp_xxx"
$env:CODEHUB_TOKEN="codehub_xxx"
$env:PYTHON_BIN="C:\Path\To\python.exe"
```

macOS / Linux 环境变量示例：

```bash
export GITHUB_TOKEN="ghp_xxx"
export CODEHUB_TOKEN="codehub_xxx"
export PYTHON_BIN="/path/to/python3"
```

`PYTHON_BIN` 可选。未配置时，启动脚本会优先使用项目内 `.venv`，然后再查找系统 Python。

## 静态工具安装与验证

AI 检视前会先运行一批静态工具，把结果结构化为 `tool_observations` 和候选 finding，供专家 Agent 二次判断。建议生产镜像和本机调试环境都安装以下工具：

Linux 一键安装：

```bash
bash scripts/install-linux.sh
```

Windows PowerShell 一键安装：

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\install-windows.ps1
```

两个脚本会安装项目 npm/Python 依赖、创建 `.venv`、准备 `config.json`、安装/验证静态工具链，并同步开源静态规则集。Linux 脚本默认使用用户目录 `$HOME/.jolt-tools`、`$HOME/.local/bin`、`$HOME/.npm-global/bin`；Windows 脚本默认使用 `%USERPROFILE%\.jolt-tools\bin`，并写入用户级 `PATH`。如果刚装完后仍提示命令不存在，请重新打开终端后再执行验证。

只验证当前机器工具状态，不执行安装：

```bash
bash scripts/install-linux.sh --verify-only
```

```powershell
.\scripts\install-windows.ps1 -VerifyOnly
```

受限服务器或内网镜像环境可以跳过部分步骤：

```bash
bash scripts/install-linux.sh --skip-system-packages --skip-project-deps
```

```powershell
.\scripts\install-windows.ps1 -SkipWinget -SkipProjectDeps -SkipStaticRules
```

常用参数：

- Linux: `--tool-home DIR`、`--skip-system-packages`、`--skip-project-deps`、`--skip-static-tools`、`--verify-only`。
- Windows: `-ToolHome DIR`、`-SkipWinget`、`-SkipProjectDeps`、`-SkipStaticTools`、`-SkipStaticRules`、`-VerifyOnly`。
- Windows 离线/内网常用：`-SkipStaticTools -SkipStaticRules`。跳过后仍可启动平台，但对应静态工具会在设置页显示为 missing。
- 版本覆盖：`GITLEAKS_VERSION`、`PMD_VERSION`、`CHECKSTYLE_VERSION`、`SPOTBUGS_VERSION`、`DEPENDENCY_CHECK_VERSION`、`OSV_SCANNER_VERSION`、`TRIVY_VERSION`、`KICS_VERSION`。

| 工具 | 用途 | macOS / Linux 安装 | Windows 安装 |
| --- | --- | --- | --- |
| Tree-sitter | 变更文件 AST 解析、类/方法/调用关系代码图谱 | `.venv/bin/python -m pip install -r requirements.txt` | `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| Semgrep | Java/Spring 安全与通用 SAST | `pipx install semgrep` 或 `brew install semgrep` | `py -3 -m pip install semgrep` 或 `pipx install semgrep` |
| Gitleaks | 密钥泄露扫描 | `brew install gitleaks` | `winget install Gitleaks.Gitleaks` |
| Ruff | Python 代码扫描 | `brew install ruff` 或 `python -m pip install ruff` | `py -3 -m pip install ruff` |
| Bandit | Python 安全扫描 | `brew install bandit` 或 `python -m pip install bandit` | `py -3 -m pip install bandit` |
| ESLint | JS/TS/前端扫描 | `npm install -g eslint` | `npm install -g eslint` |
| PMD | Java 规范、复杂度、安全规则 | `brew install pmd` | 下载 PMD release，解压后把 `bin` 加入 `PATH` |
| Checkstyle | Java 风格与基础规范 | `brew install checkstyle` | 下载 Checkstyle jar，配置 `checkstyle.cmd` 或把包装脚本加入 `PATH` |
| SpotBugs | Java 字节码缺陷扫描 | `brew install spotbugs` | 下载 SpotBugs release，解压后把 `bin` 加入 `PATH` |
| OWASP Dependency-Check | 依赖 CVE 扫描 | `brew install dependency-check` | 下载 Dependency-Check CLI，解压后把 `bin` 加入 `PATH` |
| OSV Scanner | OSV 依赖漏洞扫描 | `brew install osv-scanner` | `winget install Google.OSV-Scanner` 或下载 release |
| Trivy | 依赖、容器、IaC、Secret 扫描 | `brew install trivy` | `winget install AquaSecurity.Trivy` |
| KICS | Kubernetes / Docker / Terraform 配置风险 | `brew install kics` | 下载 KICS release，解压后把可执行文件加入 `PATH` |
| OpenAPI Diff | OpenAPI 破坏性变更检测 | `npm install -g openapi-diff` | `npm install -g openapi-diff` |

macOS 快速安装：

```bash
brew install semgrep gitleaks ruff bandit pmd checkstyle spotbugs dependency-check osv-scanner trivy kics
npm install -g eslint openapi-diff
```

Windows PowerShell 快速安装：

```powershell
py -3 -m pip install semgrep ruff bandit
npm install -g eslint openapi-diff
winget install Gitleaks.Gitleaks
winget install Google.OSV-Scanner
winget install AquaSecurity.Trivy
```

Windows 下 PMD、Checkstyle、SpotBugs、Dependency-Check、KICS 建议从官方 release 下载 zip，解压到固定目录，例如 `C:\Tools\pmd`、`C:\Tools\spotbugs`，然后把对应 `bin` 或包装脚本目录加入系统 `PATH`。修改 `PATH` 后需要重新打开终端，并重启 API 服务，设置页的工具状态卡才会刷新。

安装后验证：

```bash
semgrep --version
gitleaks version
ruff --version
bandit --version
eslint --version
pmd --version
checkstyle --version
spotbugs -version
dependency-check --version
osv-scanner --version
trivy --version
kics version
openapi-diff --version
python3 scripts/verify_java_tool_runners.py
npm run verify:static-tools
```

Windows PowerShell：

```powershell
semgrep --version
gitleaks version
ruff --version
bandit --version
eslint --version
pmd --version
checkstyle --version
spotbugs -version
dependency-check --version
osv-scanner --version
trivy --version
kics version
openapi-diff --version
py -3 scripts\verify_java_tool_runners.py
npm run verify:static-tools
```

启动 API 后，也可以直接访问：

```bash
curl -sS http://127.0.0.1:8011/api/projects/project_default/static-tools/availability
```

前端 `系统设置` 页面会显示“静态工具可用性”卡片，按 SAST、Java、Dependency、IaC/API 等分类展示工具路径、版本、状态和安装提示。后端探测兼容 Windows `PATHEXT`，可以识别 `.exe`、`.cmd`、`.bat` 等命令。

### 内置开源规则集

Jolt CodeReview 会把业界开源规则集下载到 `config/static-rules/`，作为本项目的内置规则。执行：

```bash
npm run sync:static-rules
npm run verify:static-rules
```

当前内置规则来源：

- Semgrep community rules：`semgrep/java`、`semgrep/generic`、`semgrep/yaml`、`semgrep/secrets`。
- PMD Java category rules：`bestpractices.xml`、`errorprone.xml`、`security.xml`、`performance.xml`。
- Checkstyle：官方 `google_checks.xml`、`sun_checks.xml`。
- Gitleaks：官方默认 `gitleaks.toml`，运行时通过 composite config 继承开源默认规则。
- KICS：官方 `assets/queries` IaC 规则。

项目可以在 `系统设置 -> 静态工具策略` 里追加团队规则：

- Semgrep：填写追加 `--config` 路径或 registry config，保存到 `static_runners.semgrep.custom_config_paths`。
- PMD：填写追加 ruleset，保存到 `static_runners.pmd.custom_rulesets`。
- Gitleaks：填写扩展配置，保存到 `static_runners.gitleaks.extend_config_path`，运行时仍 `useDefault=true`。
- Checkstyle：填写团队 Checkstyle XML，保存到 `static_runners.checkstyle.config_path`。
- KICS：填写团队 queries 目录，保存到 `static_runners.kics.custom_queries_path`。

项目级工具参数可以放在项目配置的 `tool_policy.static_runners` 中。常用配置：

```json
{
  "tool_policy": {
    "analysis_worktree_path": "/path/to/full/repo",
    "static_runners": {
      "dependency-check": {
        "timeout_seconds": 180,
        "data_directory": "data/cache/dependency-check",
        "nvd_api_key_env": "NVD_API_KEY",
        "nvd_api_delay_ms": 1000,
        "nvd_api_results_per_page": 2000
      },
      "osv-scanner": {
        "offline": false,
        "allow_no_lockfiles": true
      },
      "spotbugs": {
        "class_dirs": ["target/classes"]
      },
      "trivy": {
        "cache_dir": "data/cache/trivy",
        "scanners": ["vuln", "secret", "misconfig"]
      },
      "kics": {
        "custom_queries_path": "config/team-rules/kics/queries"
      },
      "checkstyle": {
        "config_path": "config/checkstyle.xml"
      },
      "semgrep": {
        "custom_config_paths": ["config/team-rules/semgrep"]
      },
      "pmd": {
        "custom_rulesets": ["config/team-rules/pmd/team-rules.xml"]
      },
      "gitleaks": {
        "extend_config_path": "config/team-rules/gitleaks.toml"
      }
    }
  }
}
```

说明：

- `analysis_worktree_path` 指向完整仓库时，PMD、Checkstyle、OSV、Trivy、KICS 等工具能读取完整上下文；未配置时会回退到 MR diff 物化目录。
- SpotBugs 需要 `target/classes` 或 `build/classes`，因此建议在 CI 或后台队列中先执行项目构建。
- SpotBugs 也可以通过 `tool_policy.static_runners.spotbugs.class_dirs` 指定 CI artifact 或完整仓库下的编译目录。
- OpenAPI Diff 需要配置 `tool_policy.openapi_diff.base_spec_path`，否则会记录为 `skipped_requires_baseline_spec`。
- OSV Scanner 使用 2.x 命令形态 `scan source --recursive --no-ignore --format json --output-file ...`；在内网或离线环境可以配置 `offline`、`offline_vulnerabilities`、`download_offline_databases`。
- Dependency-Check 首次运行会下载/初始化漏洞库，生产环境建议预热缓存、配置 `NVD_API_KEY`，并把 timeout 调到 180 秒以上。

## 本机配置

仓库包含一个可直接本机调试的 `config.json`。Windows 启动脚本会自动设置：

```powershell
$env:CONFIG_PATH="<repo>\config.json"
$env:PYTHON_BIN="<repo>\.venv\Scripts\python.exe"
```

如果你需要重置配置，可以从示例文件恢复：

```powershell
Copy-Item config.example.json config.json -Force
```

macOS / Linux：

```bash
cp config.example.json config.json
```

`config.json` 里的 LLM 配置示例：

```json
{
  "llm": {
    "default_provider": "dashscope-openai-compatible",
    "default_base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
    "default_model": "MiniMax-M2.7",
    "default_api_key_env": null,
    "default_api_key": "<LOCAL_ONLY_API_KEY>"
  }
}
```

生产或团队共享环境建议改用 `default_api_key_env` 或 secret store，避免在团队仓库中长期保存明文 key。

## 启动

Windows 推荐：

```powershell
.\scripts\start-windows.ps1
```

或：

```powershell
npm run start:windows
```

跨平台通用：

```bash
npm run dev
```

启动后：

- API: `http://127.0.0.1:8011`
- Frontend: `http://127.0.0.1:5173`

`npm run dev` 由 Node 脚本启动，不依赖 bash，可在 Windows 下运行。Windows 专用脚本会在启动前补齐 `CONFIG_PATH` 和 `PYTHON_BIN`。
Python Worker 会优先使用 `PYTHON_BIN`、`config.json` 中的 `runtime.python_bin`，其次自动使用项目内 `.venv`。

启动后会同时拉起：

- TS API Backend
- Python Review Worker loop
- Frontend Vite dev server
- Poller：默认每 5 分钟调用一次项目同步接口，作为 Webhook 之外的兜底通道。可用 `POLL_INTERVAL_MS` 调整。

## GitHub 数据源调试

默认调试仓库是 `microsoft/vscode`：

```bash
npm run seed:github
```

指定仓库：

```bash
GITHUB_REPO=owner/repo npm run seed:github
```

Windows PowerShell：

```powershell
$env:GITHUB_REPO="owner/repo"
npm run seed:github
```

## CodeHub 数据源配置

CodeHub 仓库可以通过 API 或前端绑定，核心是提供 `provider_config`：

```json
{
  "provider": "codehub",
  "external_repo_id": "trade-platform/payment-service",
  "name": "payment-service",
  "provider_config": {
    "endpoint": "https://codehub.internal.example.com",
    "project_key": "trade-platform",
    "repo_id": "trade-platform/payment-service",
    "token_env": "CODEHUB_TOKEN",
    "list_mrs_path": "/api/v1/repos/{repo_id}/merge-requests?state=open&per_page=50",
    "files_path_template": "/api/v1/repos/{repo_id}/merge-requests/{mr_number}/files",
    "comment_path_template": "/api/v1/repos/{repo_id}/merge-requests/{mr_number}/comments"
  }
}
```

不同公司内网 CodeHub 的 REST 路径可能不同，因此 provider 层使用 path template 适配；前端和 MR Review 业务层只看统一的 `merge_request` 数据。

## 验证

Windows PowerShell：

```powershell
npm run build
npm run verify:windows
npm run smoke
npm run worker:once
npm run verify:local
npm run verify:llm
```

跨平台通用：

```bash
npm run build
npm run smoke
npm run worker:once
npm run verify:local
npm run verify:llm
npm run verify:e2e
npm run verify:codehub
```

`smoke` 会检查 API health、用户、项目和 MR 列表。`worker:once` 会消费一个 queued review job。`verify:local` 会检查项目成员、规则库、Agent 配置、review policy、MR 队列、session logs、agent messages、tool calls、LLM calls 和 artifacts。`verify:llm` 会真实调用 MiniMax-M2.7，并只打印脱敏 key。`verify:e2e` 会创建一个 GitHub provider 的本机 fixture MR，跑完整 review job，验证 finding、dry-run 发布记录和误报反馈闭环。
`verify:e2e`、`verify:codehub` 和 `verify:local` 还会校验 LangGraph 编排、DeepAgents 受控专家节点、静态工具 manifest 与过程记录。`verify:codehub` 会发送一个 CodeHub webhook fixture，验证 CodeHub MR 入队、worker 检视和静态工具记录。

## Windows 常见问题

- PowerShell 提示脚本不可执行：先执行 `Set-ExecutionPolicy -Scope Process Bypass -Force`，只影响当前终端窗口。
- `node:sqlite` 或 `Cannot find module node:sqlite`：Node.js 版本过低，升级到 Node.js 24+ 后重新执行 `npm install`。
- `Python 3 was not found`：安装 Python 3.10+，或设置 `$env:PYTHON_BIN="C:\Path\To\python.exe"`。
- Python 报 `UnicodeEncodeError` / `UnicodeDecodeError` / `gbk codec can't encode/decode`：优先使用 `.\scripts\start-windows.ps1` 或 `npm run start:windows`。脚本会设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 并切换控制台到 UTF-8；如果你直接运行 Python，也先执行 `$env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"; chcp 65001`。
- 安装后 `pmd`、`checkstyle`、`spotbugs`、`dependency-check` 等命令仍不可用：重新打开 PowerShell，让用户级 `PATH` 生效，然后执行 `npm run verify:windows`。
- `npm run dev` 能启动但 Worker 不运行：优先使用 `.\scripts\start-windows.ps1`，它会设置 `CONFIG_PATH` 和 `PYTHON_BIN`。
- 端口被占用：关闭占用 `8011` 或 `5173` 的进程，或修改 `config.json` 中的 `server.port` 后重启。
- Dependency-Check 首次运行很慢：它会初始化漏洞库。生产环境建议预热缓存，并配置 `NVD_API_KEY`。
- 内网不能下载 GitHub release：执行 `.\scripts\install-windows.ps1 -SkipStaticTools -SkipStaticRules` 先启动平台，再由管理员离线安装工具到 `%USERPROFILE%\.jolt-tools\bin` 或系统 `PATH`。

## 发布评论

前端 MR 详情页可以选择 finding 并点击：

- `Dry-run`：只写入 `vcs_publish_records`，不调用 GitHub。
- `提交选中意见`：调用 GitHub issue comments API，需要 `GITHUB_TOKEN`。

AI 不会自动发布评论，必须由用户确认。
