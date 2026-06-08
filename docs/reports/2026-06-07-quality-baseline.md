# 2026-06-07 MR 检视质量基线

## 1. 基线范围

本报告用于 `docs/plans/2026-06-07-review-quality-enhancement-plan.md` 的 STEP 0.1。当前只覆盖 MR 检视能力；全量检视由其他团队实现，不纳入本基线。

数据策略为 `prompt_retention=hash_only`，因此本报告记录 LLM provider/model、prompt hash、token、耗时、状态与 artifact 路径，不保存完整 prompt/response 原文。

## 2. Gold Eval

命令：

```bash
npm run verify:gold-eval
```

结果：

| 指标 | 数值 |
|---|---:|
| tp | 30 |
| fp | 0 |
| fn | 0 |
| precision | 1.0000 |
| recall | 1.0000 |
| high_recall | 1.0000 |
| gold_count | 30 |
| finding_count | 30 |

产物：`evaluation/report.json`。

## 3. Pipeline 基线样本

### 样本 A：Java Web 风险 MR fixture

| 字段 | 值 |
|---|---|
| MR | `mr_repo_github_java_fixture_9101` |
| Repository | `github/java-risky-service` |
| Run | `run_a0a310bb0829492c` |
| 状态 | `waiting_confirmation` |
| 摘要 | 输出 11 个问题；预算截断：`wall_seconds_exceeded` |
| Sandbox | `data/sandboxes/run_a0a310bb0829492c` |
| 期望问题 | 18 |
| 命中问题 | 10 |
| 漏检问题 | 8 |
| 最终 finding | 11 |
| 工具观察 | 31 |

质量指标：

| 指标 | 数值 |
|---|---:|
| detection_rate | 0.5556 |
| false_positive_rate | 0 |
| duplicate_count | 0 |

漏检规则：

- `BE-API-001`
- `REDIS-CMD-003`
- `REDIS-TTL-002`
- `CODE-NULL-001`
- `CODE-RESOURCE-005`
- `DDD-VO-002`
- `BE-IDEMP-004`
- `TEST-COVER-001`

工具与模型：

| 类型 | 结果 |
|---|---|
| LLM completed | MiniMax-M2.7，3 次，input 36,688，output 6,431 |
| LLM timeout | MiniMax-M2.7，2 次，input 12,463 |
| Static observations | `java_web_static=16`，`semgrep=7`，`pmd=4`，`trivy=2`，`osv=2` |
| Artifacts | `changed_files.json`、`diff_slices.json`、`code_context_snapshot.json`、`prescan_summary.json`、`static_tool_results.json` |

代表性 findings JSON 摘要：

```json
[
  {"agent_id":"security_agent","severity":"high","file_path":"src/main/java/com/acme/payment/PaymentController.java","line_start":33,"title":"SQL 拼接存在注入风险","covered_rules":["SEC-INJECT-003"],"tools":["semgrep","java_web_static"]},
  {"agent_id":"dependency_agent","severity":"critical","file_path":"pom.xml","line_start":8,"title":"fastjson 1.2.47 存在多个 Critical/High CVE，必须立即替换","covered_rules":["DEP-CVE-001"],"tools":["osv","trivy","java_web_static"]},
  {"agent_id":"database_agent","severity":"critical","file_path":"src/main/resources/db/migration/V20260607__payment_schema.sql","line_start":2,"title":"直接 DROP COLUMN legacy_remark 破坏发布兼容窗口且不可回滚","covered_rules":["DB-DDL-001","DB-COMPAT-005","DB-ROLLBACK-006","DB-LOCK-004"],"tools":["java_web_static"]}
]
```

### 样本 B：GitHub 安全回归 fixture

| 字段 | 值 |
|---|---|
| MR | `mr_repo_github_fixture_9001` |
| Repository | `github/vulnerable-service` |
| Run | `run_bf882267239b4a8b` |
| 状态 | `waiting_confirmation` |
| 摘要 | 输出 1 个问题 |
| Sandbox | `data/sandboxes/run_bf882267239b4a8b` |
| 最终 finding | 1 |

工具与模型：

| 类型 | 结果 |
|---|---|
| LLM completed | MiniMax-M2.7，4 次，input 28,530，output 3,404 |
| Static observations | `semgrep=1`，`ruff=1` |

代表性 finding：

```json
{"agent_id":"security_agent","severity":"high","file_path":"backend/api/project.py","line_start":2,"title":"源码中疑似硬编码密钥/敏感凭据","covered_rules":["SEC-SECRET-004"],"tools":["semgrep"]}
```

### 样本 C：真实 GitHub/vscode MR

| 字段 | 值 |
|---|---|
| MR | `mr_repo_26b109d48a0b49af_3796149231` |
| Repository | `github/vscode` |
| PR | `319747` |
| 标题 | Git: show hint when Git operations may be waiting for SSH authentication |
| Run | `run_fce205b61fd64d22` |
| 状态 | `waiting_confirmation` |
| 摘要 | 输出 4 个问题 |
| Sandbox | `data/sandboxes/run_fce205b61fd64d22` |

工具与模型：

| 类型 | 结果 |
|---|---|
| LLM completed | MiniMax-M2.7，7 次，input 77,752，output 35 |
| Static observations | `semgrep=1` |

注意：该 MR 来自真实 GitHub 同步，但不是 Java/Spring 项目，不能作为 Java Web 质量提升的主基线，只用于验证生产数据源链路。

## 4. 当前主要质量缺口

1. 静态工具已经命中 Redis KEYS/TTL，但最终 finding 未采纳，后续需要强化 Agent 采纳策略、Verifier 软拒绝和 Judge 校准。
2. Java fixture 对资源关闭、空值校验、接口幂等、DDD 值对象、测试覆盖仍漏检。
3. MiniMax-M2.7 在 standard effort 下出现 2 次 Timeout，整体 wall time 187.402s，触发预算截断，需要在后续步骤中降低无效调用和引入更强的上下文裁剪。
4. 真实公司内网 CodeHub / Java Spring MR 尚未接入本机凭据，本报告的样本 A 为可复现 fixture。上线前应替换为 3 个真实生产 MR：大 MR、跨文件 MR、纯 Java 业务 MR。

## 5. STEP 0.1 结论

本地 MR 检视基线已建立：

- 离线 gold-eval：`precision=1.0`、`recall=1.0`、`high_recall=1.0`。
- 完整 Java fixture pipeline：`detection_rate=0.5556`、`false_positive_rate=0`。
- Trace/LLM/Tool/Artifact 均已落库，可通过 `review_run_id` 回溯。

后续 STEP 0.2 拆分代码时，必须保持 gold-eval 数字不变，并保证 Java fixture 代表性 finding 不发生非预期变化。

## 6. STEP 0.2 回归记录

拆分后验证：

| 验证项 | 结果 |
|---|---|
| `npm run verify:gold-eval` | 通过，precision/recall/high_recall 仍为 1.0000 |
| `npm run verify:worker-orchestration` | 通过 |
| `npm run build` | 通过 |
| Java fixture rerun | `run_3fb2e9080aa9493c`，输出 14 个问题 |
| 工具观察 | 31 条，分布仍为 `java_web_static=16`、`semgrep=7`、`pmd=4`、`trivy=2`、`osv=2` |

Java fixture rerun 与 STEP 0.1 最终 finding 不完全一致，主要原因是当前 prompt hash 包含 sandbox/run 路径派生的工具 observation，且 MiniMax-M2.7 的成功/超时次数不同：STEP 0.1 为 3 次 completed + 2 次 Timeout，STEP 0.2 rerun 为 4 次 completed + 1 次 Timeout。后续应增加固定 run id 或脱敏稳定路径的 deterministic eval runner。
