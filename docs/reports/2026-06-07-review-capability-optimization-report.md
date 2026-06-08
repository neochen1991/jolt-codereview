# 2026-06-07 检视能力优化实施记录

## 背景

本次优化基于代码能力评估结论，目标是让 MR 检视链路更符合生产化原则：默认采用开源静态工具，减少内置启发式扫描对最终结果的影响，并扩大高置信工具观察进入最终候选问题的能力。

## 已完成优化

1. 默认专家不再绑定 `static.heuristic_prescan`。
   - `agent_configs` seed 默认工具列表已清空，安全专家仅保留显式的 `github.list_pull_files`。
   - 用户新建自定义专家时，如果未配置 tools，不再自动注入 legacy heuristic 工具。
   - Worker fallback Agent 默认工具列表已清空。

2. 专家执行阶段默认跳过内置 Java 启发式扫描。
   - `run_experts` 仅在项目显式开启 `tool_policy.enable_builtin_java_heuristics`、`tool_policy.enable_jolt_builtin_rules` 或 `tool_policy.static_runners.java_web_static.enabled=true` 时才尝试调用 `static.heuristic_prescan`。
   - 默认链路只消费 Prescan 阶段产生的开源静态工具 observation。

3. 扩大开源工具 observation 晋升范围。
   - 新增统一阈值：`semgrep`、`pmd`、`checkstyle`、`spotbugs`、`dependency-check`、`osv`、`trivy`、`kics`、`openapi-diff`、`gitleaks`。
   - 仍要求工具结果可定位到文件与行号；依赖漏洞类至少要求文件可定位。
   - 新增回归断言覆盖 `checkstyle`、`spotbugs`、`dependency-check` 高置信 observation 晋升。

4. 强化验证脚本。
   - `verify:agents` 现在会拒绝默认专家绑定 legacy heuristic。
   - `verify:real-tooling` 现在会检查默认 seed 和 Agent API 不再自动注入 `static.heuristic_prescan`。

## 验证结果

| 命令 | 结果 |
|---|---|
| `npm run verify:real-tooling` | 通过 |
| `npm run verify:agents` | 通过 |
| `npm run verify:java-conventions` | 通过，检测 19 类规则，18 类进入晋升验证 |
| `npm run verify:custom-agents` | 通过 |
| `npm run verify:custom-skills` | 通过 |
| `npm run verify:worker-orchestration` | 通过 |
| `npm run build` | 通过 |
| `npm run verify:java-5mr` | 通过，`recall=1.0`，`fp_rate=0` |

## 仍需后续处理

1. 上传 Skill 的 `scripts/` 当前仍默认不执行，只记录受控调用意图。生产环境必须先实现独立沙箱 runner，再允许执行用户上传脚本。
2. Java 5MR 当前是本地 fixture 评测，仍需接入真实 CodeHub Java Spring MR 回归集。
3. SQLite 队列适合本地和试点，千人团队生产部署仍建议迁移到服务端数据库和独立 Worker 池。
