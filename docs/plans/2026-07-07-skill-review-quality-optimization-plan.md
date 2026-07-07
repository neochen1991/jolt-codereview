# Skill/规范驱动检视质量优化方案

## 背景

当前三服务拆分后，专家 Agent 已支持绑定项目规范和 Skill，并且 Skill 规则 ID 优先级已经固定为：

```text
Skill > 绑定规范 > 专家画像
```

最近针对一个贴近线上业务的 Java 退款审核 MR 做了两组评测：

- 无 Skill 基线：precision 90.91%，recall 83.33%，漏检业务一致性和审计类问题。
- 接入退款业务 Skill，模拟候选：precision 100%，recall 100%。
- 接入退款业务 Skill，真实大模型：Skill 专项 precision 75%，recall 100%。

真实大模型结果说明：Skill 能显著提升召回，但精确率会被“同一根因重复 finding”拉低，例如 `BIZ-AUDIT-001` 同时报 Controller 和 Service 两条。

本方案目标是把 Skill/规范驱动检视从“能读到、能命中”推进到“线上稳定、低重复、低误报、可评测、可解释”。

## 目标

1. 提升 Skill/规范绑定场景的真实召回率。
2. 降低同一规则、同一业务动作、同一根因的重复 finding。
3. 让误报模式、跳过规则、补检视、过滤原因可审计。
4. 修正评测口径，支持同 MR 内局部负例和重复 finding 识别。
5. 形成可持续回归的真实大模型评测集和质量门。

## 非目标

- 不把某个业务 Skill 写死进通用代码。
- 不依赖单一模型的输出格式假设。
- 不为了提高指标直接放宽证据校验。
- 不改变专家选择仍由 Router/大模型决策的原则。

## 阶段一：评测口径修复

### 问题

当前 `score_real_pr_reviews.py` 存在两个口径问题：

1. 同一个 MR 里如果包含一条 negative gold，`by_mr` 会把整个 MR 标记为 negative。
2. 对同一根因拆成多条 finding 的情况，只能算 FP，不能区分“重复问题”和“真正误报”。

### 改造

1. Gold schema 增加局部负例字段：

```json
{
  "ground_truth": "negative",
  "negative_scope": {
    "file": "src/main/java/...",
    "line": 18,
    "rule_id": "REDIS-TTL-002",
    "evidence_keywords": ["system:refund:config"]
  }
}
```

2. 评分器新增三类指标：

```text
true_fp_count        真正误报
duplicate_fp_count   重复 finding
negative_fp_count    命中局部负例
```

3. 匹配顺序改为：

```text
positive gold matching
-> duplicate matching by semantic key
-> local negative matching
-> remaining unmatched findings as true FP
```

4. 输出 action items 时区分：

```text
recall_gap
precision_gap:true_fp
precision_gap:duplicate
precision_gap:negative
```

### 验收

- 同 MR 内同时存在正例和负例时，`by_mr.is_negative` 不再污染整个 MR。
- `BIZ-AUDIT-001` Controller/Service 重复输出时，计入 `duplicate_fp_count`，不计入 `true_fp_count`。
- 原有 `verify:real-prs`、`verify:gold-eval` 结果不回退。

## 阶段二：同根因语义去重

### 问题

真实模型会把一个业务缺陷拆成多个层次：

- Controller 缺少审计
- Service 缺少审计
- Event 未发审计事件

这些可能是同一根因，也可能是不同缺陷。当前 dedupe 主要依赖位置、规则和文本相似度，不足以表达业务动作。

### 改造

新增 `business_issue_signature`，在 `judge_findings.py` 的合并前或合并中执行。

签名字段：

```text
rule_id
business_action
root_cause
primary_entity
side_effect_set
```

生成逻辑：

1. 规则 ID 来自 `covered_rules[0]` 或 Skill checkpoint。
2. `business_action` 从标题、证据、方法名提取，例如：
   - `batch_approve_refund`
   - `refund_cache_write`
   - `refund_compensation`
3. `root_cause` 从规则类型归一化：
   - `missing_audit`
   - `missing_consistency_boundary`
   - `missing_ttl`
4. `primary_entity` 从代码符号和关键词提取：
   - `refund`
   - `order`
   - `coupon`
5. `side_effect_set` 用于区分是否同一问题：
   - `payment_refund`
   - `stock_release`
   - `coupon_return`
   - `audit_record`

合并策略：

```text
同 rule_id + 同 business_action + 同 root_cause:
  合并为 1 条 finding
  保留最靠近业务核心的 primary location
  其他位置进入 related_locations
  evidence 合并去重
```

位置优先级：

```text
Service/Domain > Controller > Infra > Config
```

### 数据结构

`review_findings.quality_trace_json` 增加：

```json
{
  "semantic_dedupe": {
    "signature": "BIZ-AUDIT-001|batch_approve_refund|missing_audit|refund",
    "merged_count": 2,
    "related_locations": [
      {
        "file_path": "src/main/java/.../RefundAdminController.java",
        "line_start": 16,
        "reason": "entrypoint_evidence"
      }
    ]
  }
}
```

### 验收

- 真实退款 Skill MR 中 `BIZ-AUDIT-001` 从 2 条合并为 1 条。
- Skill 专项真实大模型 precision 从 75% 提升到 100%，recall 保持 100%。
- 合并后的 finding 仍展示 Controller 入口和 Service 执行证据。

## 阶段三：Skill 编写规范和校验器

### 问题

Skill 作者容易踩 parser 边界。例如 Markdown bullet 写成：

```markdown
- system:refund:config 永久配置 key
```

会被当前 parser 当成字段键值，导致误报模式没有进入 `false_positive_patterns`。

### 改造

新增 `scripts/verify-skill-bundle.mjs` 或 Python 版校验器，支持校验本地 Skill 目录或数据库中的 Skill assets。

检查项：

1. `SKILL.md` 存在且 frontmatter 合法。
2. `references/` 下规则能被解析成 checkpoint。
3. 每个 checkpoint 必须有：
   - `checkpoint_id`
   - `required_evidence`
   - `false_positive_patterns`
   - `fix_guidance`
4. 检查疑似被字段 parser 吞掉的 bullet：

```text
- xxx:yyy ...
```

5. 检查 rule id 冲突：

```text
同一个 Skill 内重复 checkpoint_id
Skill 与绑定规范重复但语义不一致
```

6. 输出解析预览：

```json
{
  "checkpoint_id": "REDIS-TTL-002",
  "required_evidence": "...",
  "false_positive_patterns": "永久配置 key，例如 system:refund:config ..."
}
```

### 接入点

- 前端上传 Skill 文件夹时调用校验 API。
- Common/MR 后台保存 Skill 前做一次校验。
- `npm run verify` 增加固定样本校验。

### 验收

- 上传含 `- system:refund:config ...` 的 Skill 时给出明确警告。
- 上传修正后的 Skill 时通过。
- 校验结果能展示到页面，让规则作者知道哪些 reference 被读取。

## 阶段四：Skill 执行 Trace 产品化

### 问题

当前后端已有事件：

- `bound_skill_started`
- `bound_skill_checked`
- `bound_batch_findings_rejected`
- `bound_rule_coverage_retry_completed`

但页面上还不够直观，用户难以判断 Agent 是否真的按 Skill 执行。

### 改造

检视结果页新增 “Skill 执行记录” 面板：

```text
Skill: refund-risk-review-skill
读取文件:
- SKILL.md
- references/refund-review-rules.md

Checkpoint:
- BIZ-CONSISTENCY-001 命中 1 条
- BIZ-AUDIT-001 命中 2 条，合并为 1 条
- REDIS-TTL-002 命中 1 条，跳过 1 条永久配置 key

过滤:
- bound_false_positive_pattern_match: 1
- bound_skill_checkpoint_mismatch: 0

补检视:
- retry: 0/3
```

### API

MR backend 增加或复用：

```http
GET /api/review-runs/:runId/skill-trace
```

返回：

```json
{
  "skills": [
    {
      "skill_key": "refund-risk-review-skill",
      "assets": ["SKILL.md", "references/refund-review-rules.md"],
      "checkpoints": [
        {
          "checkpoint_id": "BIZ-AUDIT-001",
          "hit_count": 2,
          "merged_count": 1,
          "rejected_count": 0,
          "retry_count": 0
        }
      ]
    }
  ]
}
```

### 验收

- 用户能看到每个 Skill checkpoint 是否检查、命中、跳过、过滤、补检视。
- 被 false positive pattern 过滤的 finding 能看到原因和命中的误报模式。

## 阶段五：真实大模型 Skill 回归集

### 问题

模拟候选能验证系统后处理，但不能代表真实模型依照 Skill 的能力。

### 改造

新增真实大模型回归集目录：

```text
evaluation/skill_real_llm/
├── refund-risk-review-skill/
│   ├── SKILL.md
│   └── references/refund-review-rules.md
├── refund-business-mr.json
├── refund-business-gold.jsonl
└── expected-thresholds.json
```

新增脚本：

```bash
npm run eval:skill-real-llm
```

默认不放进 `npm run verify`，避免每次 CI 都消耗真实模型费用。提供手动门：

```bash
npm run eval:skill-real-llm -- --skill refund-risk-review-skill --model current
```

输出：

```json
{
  "precision": 0.75,
  "recall": 1.0,
  "duplicate_fp_count": 1,
  "true_fp_count": 0,
  "negative_fp_count": 0,
  "llm_calls": 3,
  "tokens": {
    "input": 14620,
    "output": 4476
  }
}
```

### 验收阈值

短期：

```text
recall >= 0.90
true_precision >= 0.85
negative_fp_count = 0
```

完成语义去重后：

```text
recall >= 0.90
precision >= 0.90
duplicate_fp_count <= 1
negative_fp_count = 0
```

## 阶段六：Skill 覆盖率闭环

### 问题

现在 coverage retry 能补检视，但缺少长期统计：哪些 Skill checkpoint 经常未闭环、哪些误报多、哪些规则命中后被人工驳回。

### 改造

新增 Skill checkpoint 级指标：

```text
checked_count
hit_count
skip_count
retry_count
retry_hit_count
rejected_count
manual_accept_count
manual_reject_count
duplicate_merge_count
```

聚合维度：

```text
project_id
skill_key
checkpoint_id
agent_id
model
week
```

在项目维护页展示：

```text
规则         检查次数  命中率  误报率  重复率  补检视命中率
BIZ-AUDIT   120      32%    8%     18%    41%
```

### 验收

- 能看出哪个 Skill 规则需要改写。
- 能看出哪个模型对某类 Skill 表现差。
- 人工反馈能回流到 suppression hints 或 Skill 改进建议。

## 推荐实施顺序

### 第 1 周：评测口径和真实回归脚本

1. 修改 `score_real_pr_reviews.py` 支持局部负例和 duplicate FP。
2. 固化退款业务 Skill 真实大模型评测集。
3. 新增 `eval:skill-real-llm` 脚本。
4. 产出第一版报告：真实模型 Skill precision/recall/duplicate。

### 第 2 周：语义去重

1. 实现 `business_issue_signature`。
2. 在 judge merge 阶段合并同根因 finding。
3. 保留 `related_locations`。
4. 跑退款 Skill 真实评测，确认 precision 从 75% 提升到 90% 以上。

### 第 3 周：Skill 校验和上传体验

1. 实现 Skill bundle 校验器。
2. 前端上传时展示解析结果。
3. 保存 Skill 前阻断严重格式问题。
4. 文档补充 Skill 编写规范。

### 第 4 周：Trace 和指标面板

1. 后端提供 `skill-trace` API。
2. 前端结果页展示 Skill 执行记录。
3. 项目维护页展示 Skill checkpoint 质量统计。

## 最小可交付版本

如果只做一个最小闭环，建议先交付：

1. `score_real_pr_reviews.py` 支持 duplicate FP。
2. `judge_findings.py` 合并同 rule_id + 同业务动作 + 同根因。
3. `scripts/eval-skill-real-llm.*` 固化真实大模型 Skill 评测。
4. 前端结果页展示 Skill checkpoint 命中/过滤/补检视记录。

这四项能直接解决当前真实评测暴露的问题：召回已经够，精确率被重复拉低，用户又需要看到 Skill 是否真的被执行。

## 当前退款 Skill 评测基线

### 无 Skill

```text
precision = 90.91%
recall    = 83.33%
TP=10 FP=1 FN=2
```

### Skill 模拟候选

```text
precision = 100%
recall    = 100%
TP=12 FP=0 FN=0
```

### Skill 真实大模型专项

```text
precision = 75%
recall    = 100%
TP=3 FP=1 FN=0
```

真实大模型的 FP 是 `BIZ-AUDIT-001` 重复拆分，不是规则 ID 错误，也不是 Skill 未读取。

## 风险和注意事项

1. 语义去重不能过度合并不同业务缺陷。
2. 局部负例评测需要明确 file/line/rule/evidence，否则会掩盖真实误报。
3. Skill 校验不能只做 Markdown 语法，要展示实际解析后的 checkpoint。
4. 真实 LLM 回归不能默认进 CI，应作为手动质量门或夜间任务。
5. 模型切换后必须重新跑真实 Skill 评测，不能沿用旧模型指标。

## 成功标准

三类指标同时达标才算完成：

```text
真实 Skill 召回率 >= 90%
真实 Skill 精确率 >= 90%
局部负例误报数 = 0
```

产品体验上，用户必须能回答：

```text
这个 Agent 读取了哪些 Skill 文件？
每条 Skill 规则是否检查了？
命中了什么？
跳过了什么？
过滤了什么？
重复问题是否合并了？
```
