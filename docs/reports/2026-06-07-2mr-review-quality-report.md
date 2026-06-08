# 2 MR 检视质量报告

日期：2026-06-07

## 结论

本次重新跑 2 个 Java Spring fixture MR 的完整检视流程，统计的是工具整体检视结果，而不是仅检查门禁阈值。

- 整体检出率：100%（16 / 16）
- 整体假阳率：0%（0 / 18）
- 漏检数：0
- 未知问题数：0
- 质量目标：检出率 >= 90%、假阳率 <= 10%
- 结论：达标

## 测试范围

| MR | 场景 | 预期问题数 | 最终问题数 | 命中数 | 漏检数 | 假阳数 | 检出率 | 假阳率 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `mr_repo_github_java-controller-risk_9201` | Controller 业务风险：安全、Redis、性能、异常、空值、幂等、资源释放、测试覆盖 | 14 | 14 | 14 | 0 | 0 | 100% | 0% |
| `mr_repo_github_java-dependency-risk_9202` | 依赖风险：CVE、测试依赖 scope | 2 | 4 | 2 | 0 | 0 | 100% | 0% |

## 命中规则

本次 2 个 MR 共覆盖 16 类规则：

- `BE-API-001`
- `BE-IDEMP-004`
- `CODE-EXC-003`
- `CODE-NULL-001`
- `CODE-RESOURCE-005`
- `DEP-CVE-001`
- `DEP-SCOPE-005`
- `JOLT_JAVA_FIELD_AUTOWIRED`
- `PERF-MEM-004`
- `PERF-QUERY-001`
- `REDIS-CMD-003`
- `REDIS-TTL-002`
- `SEC-INJECT-003`
- `SEC-SECRET-004`
- `SEC-SECRET-004:ERROR_RESPONSE`
- `TEST-COVER-001`

## 追溯性检查

两个 MR 的最终 finding 均已落库并进入 `waiting_confirmation` 状态。

| MR | run_id | finding 数 | trace 完整 | 有工具追溯的 finding 数 |
| --- | --- | ---: | --- | ---: |
| `mr_repo_github_java-controller-risk_9201` | `run_7d1fa71b3bf24718` | 14 | 是 | 14 |
| `mr_repo_github_java-dependency-risk_9202` | `run_1e1c48691f264e88` | 4 | 是 | 4 |

抽查样本显示每条问题均包含：

- 专家 Agent：如 `security_agent`、`redis_agent`、`backend_agent`、`dependency_agent`
- 精确位置：`file_path`、`line_start`
- 命中规范：`covered_rules_json`
- 工具来源：`tool_provenance_json`
- 工具观察：`source_observations_json`
- 质量链路：`quality_trace_json`
- 建议修改代码：`suggested_code`

## 质量观察

本次整体假阳率为 0%，但依赖 MR 出现 1 组重复问题：

- `DEP-SCOPE-005|pom.xml|2`
- 重复条数：2
- 说明：同一个测试依赖 scope 问题被静态工具采纳和依赖专家输出各保留了一条，规则相同、位置相同、语义相同。

重复问题不是假阳性，但会增加用户确认成本。后续建议继续优化 Judge 去重逻辑：同规则、同文件、同行桶、同 agent 的工具采纳项和专家项应合并为一条，并把两个来源都放入 `tool_provenance_json`。

## 复跑命令

```bash
npm run seed:java-2mr
npm run worker:once
npm run worker:once
npm run verify:java-2mr
npm run build
```

## 本次验证结果

- `npm run seed:java-2mr`：通过，重新入队 2 个 MR
- `npm run worker:once`：通过，完成 Controller MR
- `npm run worker:once`：通过，完成依赖 MR
- `npm run verify:java-2mr`：通过，整体 recall=1.0、fp_rate=0.0
- `npm run build`：通过

