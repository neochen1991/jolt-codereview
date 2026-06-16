# Low-Level Rule Document Binding Review Quality Report

- MR: mr_repo_github_low_level_rule_doc_eval_9401
- Review Run: run_c9a1307cdf95463d
- Run Status: waiting_confirmation
- Bound Document: 低级缺陷专家规范文档绑定评估 (rule_doc_low_level_binding_eval, eval-v1)
- Bound Agent: low_level_defect_agent
- Parsed Rule Headings In Document: 7
- Expected Issues: 7
- Final Findings: 7
- Strict Matched Issues: 7
- Strict Missing Issues: 0
- Strict False Positive Findings: 0
- Strict Recall: 100.0%
- Strict False Positive Rate: 0.0%
- Rule-Level Recall: 100.0%
- Low-Level Agent Findings: 7
- Custom Rule Coverage By Low-Level Agent: 100.0%
- Meets Target: yes

## Expected Rule Coverage

| Rule | Status | File | Line | Title |
| --- | --- | --- | ---: | --- |
| LLDOC-CONC-107 | matched | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 16 | static SimpleDateFormat 跨线程共享 |
| LLDOC-NULL-101 | matched | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 27 | 可空对象链式解引用 |
| LLDOC-OPT-102 | matched | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 32 | Optional.get 未先判断存在性 |
| LLDOC-MONEY-103 | matched | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 36 | BigDecimal 使用 double 构造金额 |
| LLDOC-COLL-104 | matched | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 44 | 增强 for 遍历中修改集合 |
| LLDOC-EXC-105 | matched | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 55 | 异常被吞掉并返回 null |
| LLDOC-RES-106 | matched | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 61 | IO 资源未使用 try-with-resources 关闭 |

## Final Findings

| Rule(s) | Severity | Confidence | Agent | File | Line | Title |
| --- | --- | ---: | --- | --- | ---: | --- |
| LLDOC-COLL-104 | medium | 0.84 | low_level_defect_agent | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 44 | 增强 for 遍历中修改集合 |
| LLDOC-OPT-102 | medium | 0.8200000000000001 | low_level_defect_agent | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 31 | Optional.get 未先判断存在性 |
| LLDOC-RES-106 | medium | 0.82 | low_level_defect_agent | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 61 | IO 资源未使用 try-with-resources 关闭 |
| ALI-BIGDECIMAL-001, LLDOC-MONEY-103 | high | 0.94 | low_level_defect_agent | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 36 | BigDecimal 使用 double 构造金额 |
| CODE-EXC-003, LLDOC-EXC-105 | high | 0.93 | low_level_defect_agent | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 53 | 异常被吞掉并返回 null |
| ALI-CONCURRENCY-002, LLDOC-CONC-107 | high | 0.92 | low_level_defect_agent | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 16 | static SimpleDateFormat 跨线程共享 |
| CODE-NULL-001, LLDOC-NULL-101 | high | 0.8 | low_level_defect_agent | src/main/java/com/acme/lowlevel/LowLevelSettlementService.java | 27 | 可空对象链式解引用 |

## Missing Rules

None.

## Strict False Positives

None.

## Budget And Agents

- Agents Executed: low_level_defect_agent
- LLM Calls: 1
- Tool Calls: 23
- Wall Seconds: 66.843
- Truncated Reason: none
