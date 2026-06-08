# Jolt CodeReview 静态工具安装与使用评估报告

生成时间：2026-06-07 10:45 CST

## 1. 本机安装结果

本机已完成 13 个静态工具安装与 PATH 验证，后端工具状态接口曾返回 `available_count=13`、`missing_count=0`。

| 工具 | 版本/路径 | 安装状态 |
| --- | --- | --- |
| Semgrep | `1.164.0`，`/opt/homebrew/bin/semgrep` | 已安装 |
| Gitleaks | `8.30.1`，`/opt/homebrew/bin/gitleaks` | 已安装 |
| Ruff | `0.15.15`，`/opt/homebrew/bin/ruff` | 已安装 |
| Bandit | `1.9.4`，`/opt/homebrew/bin/bandit` | 已安装 |
| ESLint | `v10.4.1`，`/Users/neochen/.npm-global/bin/eslint` | 已安装 |
| PMD | `7.25.0`，`/opt/homebrew/bin/pmd` | 已安装 |
| Checkstyle | `13.5.0`，`/opt/homebrew/bin/checkstyle` | 已安装 |
| SpotBugs | `4.9.8`，`/opt/homebrew/bin/spotbugs` | 已安装 |
| OWASP Dependency-Check | `12.2.2`，`/opt/homebrew/bin/dependency-check` | 已安装 |
| OSV Scanner | `2.3.8`，`/opt/homebrew/bin/osv-scanner` | 已安装 |
| Trivy | `0.71.0`，`/opt/homebrew/bin/trivy` | 已安装 |
| KICS | `2.1.20`，`/opt/homebrew/bin/kics` | 已安装 |
| OpenAPI Diff | `0.24.1`，`/Users/neochen/.npm-global/bin/openapi-diff` | 已安装 |

本次还补充了 README 安装指引，覆盖 macOS/Linux、Windows、设置页状态卡、项目级 `tool_policy.static_runners` 配置和常见 skip 条件。

## 2. 本次全流程检视

检视对象：`mr_repo_github_java_fixture_9101`

Review run：`run_a977a89ad6ed46ae`

最终状态：`waiting_confirmation`

耗时：`2026-06-07 02:37:20` 到 `2026-06-07 02:42:14`

最终问题数：20 个，其中 `critical=1`、`high=4`、`medium=15`。

过程记录：

| 项 | 结果 |
| --- | --- |
| 工具调用 | 24 条 |
| LLM 调用 | 9 条 |
| LLM 完成 | 5 条 |
| LLM 超时 | 4 条 |
| 输入 token | 71,915 |
| 输出 token | 11,749 |
| 静态工具候选观察 | 29 条 |
| 产物 | `changed_files.json`、`data_policy_decisions.json`、`diff_slices.json`、`code_context_snapshot.json`、`prescan_summary.json`、`static_tool_results.json` |

最终问题覆盖了 SQL 注入、硬编码密码、生产配置泄露、Actuator 暴露、Redis KEYS、Redis TTL、资源未关闭、异常处理、字段注入、DDD 弱类型 Map、依赖风险、测试依赖 scope、数据库不可回滚 DDL、NOT NULL 迁移风险、缺少测试等 Java Web 高价值问题。

## 3. 工具执行效果

| 工具 | 本次状态 | 命中/贡献 | 评估 |
| --- | --- | --- | --- |
| Semgrep | completed | 7 条观察 | 效果好，命中硬编码密码、RequestBody 缺少校验、SQL 拼接等，适合承载公司 Java/Spring 规则。 |
| Gitleaks | completed | 0 条 | 执行稳定，本例未发现 secret。对配置文件和提交密钥兜底有价值。 |
| PMD | completed | 4 条观察 | 命中资源未关闭、字面量比较、宽泛异常捕获，能补齐通用编码质量问题。 |
| Checkstyle | completed | 0 条 | 执行稳定；当前内置规则较轻，仅作为基础风格兜底。生产建议绑定公司 Checkstyle 配置。 |
| Trivy | completed | 2 条观察 | 成功下载 DB 并识别依赖漏洞信号，对依赖风险有效。首次运行会受网络和 DB 缓存影响。 |
| KICS | completed | 0 条 | 修复后能自动使用 Homebrew queries 路径；本例无 IaC 风险命中。 |
| Java Web 定制规则 | completed | 16 条观察 | 对 Java Web 场景价值最高，补齐 Redis、测试覆盖、Spring、DB migration 等业务化规则。 |
| Ruff/Bandit/ESLint | skipped_no_targets | 0 条 | 本次 MR 无 Python/前端文件，跳过正确。 |
| SpotBugs | skipped_no_compiled_classes | 0 条 | 需要完整仓库构建产物 `target/classes` 或 `build/classes`。当前 diff 物化目录无法发挥作用。 |
| Dependency-Check | timeout | 0 条 | 首次初始化 NVD 数据超过 40 秒，需生产预热缓存、配置 NVD API key、提高 timeout。 |
| OSV Scanner | failed | 0 条 | 当前 materialized diff 目录未形成完整可解析 Maven 工程，OSV 报 `No package sources found`。配置完整仓库路径后再评估。 |
| OpenAPI Diff | skipped_no_openapi_targets | 0 条 | 本次 MR 无 OpenAPI 文件。若要启用破坏性 API 检测，需要配置 `base_spec_path`。 |

工具候选观察分布：

| 来源 | 数量 |
| --- | ---: |
| `java_web_static` | 16 |
| `semgrep` | 7 |
| `pmd` | 4 |
| `trivy` | 2 |

## 4. 当前发现的问题

1. Dependency-Check 默认 40 秒 timeout 不适合首次运行。它需要下载 356,003 条 NVD 数据；没有 NVD API key 时速度更慢。
2. OSV Scanner 对“仅 diff 物化目录”的 Maven 文件识别弱，最好使用完整仓库工作区。
3. SpotBugs 必须依赖编译产物，后台队列需要在工具阶段前支持项目构建或接入 CI artifact。
4. Semgrep 在 Codex 沙箱的非交互命令里可能遇到 `~/.semgrep` 写入和证书存储限制；在本次 worker 全流程中已正常执行，普通本机终端和生产容器需保证 HOME 可写、证书链可用。
5. API 长跑 session 在 Codex 沙箱中出现过跨 session curl 不可达，但进程仍打印监听。本次核心检视数据已通过 SQLite 和 artifact 验证；生产部署需用进程守护和健康检查兜底。

## 5. 已做的运行增强

1. KICS runner 会自动发现 Homebrew queries 目录：`/opt/homebrew/opt/kics/share/kics/assets/queries`。
2. 静态工具 runner 支持项目级 timeout 配置：

```json
{
  "tool_policy": {
    "static_runners": {
      "dependency-check": {
        "timeout_seconds": 180
      }
    }
  }
}
```

## 5.1 后续优化落地

本报告输出后继续完成了以下优化：

1. OSV Scanner 改为 2.x 命令形态：`scan source --recursive --no-ignore --format json --output-file ...`。其中 `--no-ignore` 可以让 MR sandbox 中的 Maven `pom.xml` 被稳定识别。
2. OSV Scanner 支持项目级 `offline`、`offline_vulnerabilities`、`download_offline_databases`、`allow_no_lockfiles`、`all_packages`、`no_resolve`、`data_source`、`maven_registry` 和 `extra_args`。
3. Dependency-Check 支持项目级 `nvd_api_key_env` / `nvd_api_key`、`data_directory`、`nvd_api_delay_ms`、`nvd_api_results_per_page`、`nvd_api_endpoint`、代理参数、suppression 文件、exclude pattern 和 `extra_args`。
4. SpotBugs 支持 `class_dirs`、`class_dir`、`compiled_classes_path`，可以直接绑定 CI 编译产物或完整仓库下的 `target/classes`。
5. Trivy 支持 `cache_dir`、`skip_db_update`、`skip_java_db_update`、`offline_scan`、`scanners` 和 `extra_args`。
6. `scripts/verify_java_tool_runners.py` 增加配置参数验证，覆盖 Dependency-Check、OSV Scanner、SpotBugs 的生产配置路径。

## 6. 生产化建议

1. 在 Java Spring 项目上，默认启用 Semgrep、PMD、Checkstyle、Trivy、Java Web 定制规则；Dependency-Check、OSV、SpotBugs 作为完整仓库/CI 模式增强。
2. 后台检视队列应为每个项目配置 `analysis_worktree_path`，或者在拉取 MR 后 checkout 完整仓库，再把 diff 和完整工程同时提供给工具。
3. CI 镜像预热 Trivy DB、Dependency-Check NVD DB、OSV 缓存；Dependency-Check 配置 NVD API key。
4. Java 项目在 SpotBugs 前执行 `mvn -q -DskipTests package` 或使用 CI 编译 artifact。
5. 公司规则优先写成 Semgrep/PMD/Checkstyle/Java Web deterministic rules，再让专家 Agent 做语义确认和修复建议生成。
6. 对工具状态建立平台级巡检：设置页展示安装状态，后台定时记录每次工具执行状态、耗时、命中数、失败摘要。
7. 将“工具命中但 Agent 未采纳”的观察纳入后续评估，用于调优规则置信度、去重策略和专家 prompt。
