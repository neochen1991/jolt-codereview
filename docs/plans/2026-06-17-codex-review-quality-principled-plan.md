# Codex 检视质量提升 · 第三轮（去补丁化重构）

> 反模式声明：本轮**禁止**为任何具体 rule_id、关键词、文件名模式新增代码分支。
> 所有「该不该报、该不该压、该不该提级」必须由通用打分机制 + 数据表驱动，不许出现 `if rule_id == "X"` 或 `if "审计字段" in text`。

## 当前补丁化债务清单

读 `worker/orchestration/nodes/judge_findings.py` 可见三类硬编码补丁，本轮要全部清掉：

1. **关键词分支**：`_is_low_precision_unbacked_advisory` 中 ~40 条 `if "X" in text` / `if rule == "Y"`，每加一类 FP 就再写一条
2. **离散白名单常量**：`PROMOTABLE_TOOL_RULES`、`PROMOTABLE_EXTERNAL_TOOL_RULES`、`TOOL_COVERAGE_FILL_RULES`、`DDD_RULE_IDS`、`CATEGORY_PRIMARY_RULE` —— 5 个互相重叠的集合
3. **业务关键词签名**：`_root_cause_signature` 用中文关键词正则做语义聚类（"审计字段"、"操作人"、"管理接口"…）

这三类共占 judge_findings.py 约 1200 行，且每轮 review 复盘都会再加几条。补丁不再是修 bug，是把规则知识反复硬编码到代码路径里。

---

## 设计原则

### 原则 1 · 规则知识只能存在数据里

每条 rule_id 的全部元数据（severity、agent_owner、evidence 要求、可由哪些工具提级、是否属于绑定文档…）只在**一个地方**声明 —— 规则注册表。
所有阶段（router / prompt builder / verifier / judge / observability）都向注册表查询，不允许在代码里复现规则集合。

### 原则 2 · 评分必须结构化

证据强度只从文件、行号、符号、工具命中、专家共识等**通用结构信号**计算，禁止从 finding 的中文文本里抓关键词。新增一类 FP 时，应该是发现某个结构信号被低估，调那个信号的权重；而不是写一个新分支识别这类 FP。

### 原则 3 · 例子必须自学习

few-shot 例子从评测集与历史已确认 finding 中按 (agent, language, rule_category) **检索**得到，不允许手工塞进文件。评测集长大，例子就长大。

### 原则 4 · 抑制必须从反馈数据驱动

不允许任何在代码里写「这种问题别报了」的 hint。所有抑制只能来自三个数据源：
- `rule_precision_history` 滚动窗口
- 用户反馈 FP 的结构化模式（rule + snippet hash + file glob）
- 评测集中 ground_truth=negative 的反例

---

## P0 · 真开源 PR Gold Set + 可重复化

> 没有这两个，下面 P1–P6 谁都说不清是不是真的提升。

### P0.1 真开源 PR Gold Set（基线）
- 4 个真实开源 PR + 1 个 negative MR（纯文档/重命名）
- `evaluation/real_gold_set.jsonl` 标注 expected `(rule_id, file, line, severity)`
- `scripts/seed-real-prs.mjs` 从 GitHub fetch 并落到本地 SQLite
- 门槛初始 P ≥ 0.55、R ≥ 0.55，**不预设最终值**，按 P1–P6 实际效果逐周收紧

### P0.2 LLM 输出可重复
- 所有 chat completions 加 `seed=13` + `response_format=json_schema(strict=true)`
- 表 `llm_response_cache` (key=hash(provider+model+prompt+seed+schema_name))
- 不支持 schema 的 provider 自动降级一次并打事件
- **验收**：同 MR 双跑 TP/FP/FN 集合 diff 为空

P0 是基础设施，不算质量提升项，但 P1–P6 的所有「+Xpp」声明必须在 P0 的 set 上证明。

---

## P1 · 规则注册表（消灭离散白名单与关键词签名）

### 目标
把 `judge_findings.py` 中所有规则相关的硬编码集合、关键词分支、签名逻辑，迁移到**单一结构化注册表**。代码层面的所有判定改为对注册表的查询。

### 注册表结构
新增 `worker/rules/registry.yaml`（或 `.jsonc`，便于注释），每条规则单独一节：

```yaml
- id: SEC-INJECT-003
  severity_floor: high
  agent_owners: [security_agent, database_agent]
  category: injection
  evidence_requirements:
    requires_line: true
    min_evidence_components: 3   # 见 P2
  tool_sources:
    - tool: java_web_static
      tool_rule_id: SQL_INJECTION
      min_confidence: 0.84
    - tool: semgrep
      tool_rule_id: java.lang.security.audit.formatted-sql-string
      min_confidence: 0.80
  signature_keys: [covered_rules, file_path, line_bucket, primary_symbol]
  promote_from_tool: true
  is_bound_document_rule: false
```

注册表必须由现有规则文档（`agent_configs.bound_rules`、内置 `RULE_*` 常量）**程序化生成首版**，不许手工誊抄。生成脚本 `scripts/build_rule_registry.py` 提交到 repo，CI 校验注册表与源数据一致。

### 代码层连锁清理
- 删除 `PROMOTABLE_TOOL_RULES`、`PROMOTABLE_EXTERNAL_TOOL_RULES`、`TOOL_COVERAGE_FILL_RULES`、`DDD_RULE_IDS`、`CATEGORY_PRIMARY_RULE` 五个常量集合
- 删除 `_root_cause_signature` 全部中文关键词分支，改为 `signature(finding) = tuple(finding[k] for k in registry[rule].signature_keys)`
- 删除 `_canonical_tool_rule_id` 中按工具名特判的逻辑，改为查 `registry[*].tool_sources`
- 工具提级逻辑改为：`registry.find_by_tool_observation(observation)` → 拿到目标 rule + 阈值，做单一判断
- `judge_findings.py` 不允许再 import 任何 `set[str]` 字面量；CI lint 规则强制

### 验收
- `judge_findings.py` 行数减 ≥ 800
- `rg "if .* == \"" worker/orchestration/judging/` 找不到任何按 rule_id 的相等判断
- 真 PR set 上 P/R 不下降

---

## P2 · 通用证据评分（消灭关键词分支）

### 目标
彻底删除 `_is_low_precision_unbacked_advisory` 这个上千行的「按关键词识别 FP」函数。改为：每条 finding 入库前算一个**结构化** `evidence_score`，judge 仅按分数阈值决定保留/降级/丢弃。

### 评分函数（仅结构信号）
新增 `worker/orchestration/judging/evidence_score.py::score(finding, related_context, tool_observations) -> float`：

| 组件 | 取值范围 | 计算方式 |
|---|---|---|
| `tool_backing` | 0 ~ 0.30 | 至少一个工具观察落在 `(file, line ± 5, rule_id ∈ registry.tool_sources[rule])`；命中数越多分越高（log scale） |
| `snippet_quote` | 0 ~ 0.20 | `finding.evidence` 中至少 30 字符是命中文件 ±20 行真实源码的子串 |
| `line_precision` | 0 ~ 0.10 | `line_end - line_start ≤ 3` 满分，> 20 行 0 分 |
| `rule_alignment` | 0 ~ 0.10 | `covered_rules ∩ {observation.promoted_rule for observation in source_observations}` 非空 |
| `symbol_alignment` | 0 ~ 0.15 | `related_context.changed_symbols` 中存在符号位于 `[line_start - 2, line_end + 2]` |
| `consensus` | 0 ~ 0.15 | 同 `signature(finding)` 由 ≥ 2 个独立 agent 报出 |

满分 1.0；阈值默认 `< 0.35` 丢弃、`< 0.50` 降一级 severity、`≥ 0.50` 保留。阈值写在 `registry.yaml` 顶部 `defaults` 段，可被 rule 级别覆盖。

### 评分函数禁止做的事
- 不许读 `finding.title / problem_description / evidence` 的中文文本做关键词匹配
- 不许写 `if rule_id == "X"`
- 不许出现「白名单 / 黑名单」字面量
- 修一个 FP 类问题的唯一手段是：调某个组件的权重，或加一个**新的结构信号组件**（且必须对所有规则生效）

### 代码层连锁清理
- 删除 `_is_low_precision_unbacked_advisory`、`_prune_low_signal_final_findings` 中所有关键词分支
- 删除 `_is_strong_tool_supported_finding` 这种「特定置信度 + 特定 rule 集合」组合判断（用 `evidence_score >= 0.6` 替代）
- `verify_findings` 节点把 `evidence_score` 与各组件得分写入 `review_findings.evidence_score_json`，前端可看
- 历史关键词分支用 `git log -p` 留档，但不许在代码里以注释形式残留

### 验收
- `judge_findings.py` 再减 ≥ 400 行（叠加 P1 共减 ≥ 1200 行）
- `worker/tests/test_evidence_score.py` 覆盖 6 个组件的边界值与组合
- 真 PR set 上 precision **不降**（理想 +2~4pp，因为分数比关键词更稳）

---

## P3 · Few-shot 自检索（消灭手工例子）

### 目标
专家 prompt 需要 few-shot 例子，但**不允许在仓库里维护手工例子文件**。例子必须在每次 review 时按 (agent_id, file_language, top_rule_categories) 从两个数据源检索：

- 正例来源：`evaluation/real_gold_set.jsonl` 中 ground_truth=true_positive 的条目
- 负例来源：`review_findings WHERE lifecycle_state IN ('rejected_false_positive', 'judge_rejected')` 中近 90 天的 FP

### 检索逻辑
新增 `worker/prompts/example_retriever.py`：

```python
def retrieve_examples(agent_id, files, k=3) -> list[Example]:
    languages = {language_for_file(f.filename) for f in files}
    rule_categories = registry.categories_for_agent(agent_id)
    # 命中 (agent_id, language) 的 positive 取 top-2，negative 取 top-1
    # 排序：先按 rule_category 重合度，再按 last_seen 时间
```

每个 Example 包含：脱敏后的 snippet + expected_finding_or_skip + 来源（gold / feedback）。
prompt builder 把检索结果注入新段 `learned_examples`（取代当前任何手工 examples 段，若有）。

### 禁止项
- 仓库里不许出现 `worker/prompts/examples/*.jsonl`（手工维护）
- 不许把任何 finding 文本硬编码进代码或 prompt 模板
- 检索器查不到例子时（评测集太小、无历史反馈）就**不注入** `learned_examples` 段，专家走零样本路径，不允许写 fallback 例子

### 自然演化
评测集每加一条 PR、用户每标一次 FP，例子库自动更新；零代码改动质量缓慢上升。

### 验收
- `rg "examples" worker/prompts/` 仅有 `example_retriever.py`
- 单测覆盖：评测集为空时返回 []、命中时按规则相关度排序
- 真 PR set precision +2~4pp、recall +2~4pp（评测集到位后）

---

## P4 · 通用 Critic 二审（不针对规则）

### 目标
对最终入库前 top-k finding 跑一次小型 critic LLM 二审。critic 只看 finding + 真实源码片段，**不知道**任何项目级规则、不针对任何 rule_id 调阈值。

### 触发条件（结构化，不针对 rule）
- `severity ∈ {critical, high}` 或 `evidence_score < 0.55`
- 单次 review 至多 8 次 critic 调用，按 evidence_score 升序优先
- 所有 critic 调用走 P0.2 的缓存层

### Critic Prompt 模板
固定模板，参数仅有：finding 字段、文件 ±20 行真实源码、bound_document（如果有）。
**模板里不允许出现任何具体 rule_id**。

### 处理 critic 输出
critic 否定时：finding 不删除，但 `severity` 降一级、`confidence × 0.7`、写 `quality_trace.critic_verdict`。
critic 肯定时：写 `critic_verdict=confirmed`，不主动加分（避免 critic 偏置传导）。

### 禁止项
- critic prompt 不允许携带规则注册表内容（保持「另一双眼睛」的独立性）
- 不允许针对特定 agent 跳过 critic
- 不允许写「critic 在这个 rule 上倾向 FP，所以加权」一类补丁

### 验收
- `worker/orchestration/nodes/critic_pass.py` 不超过 200 行，无 `if rule_id == ...` 分支
- 真 PR set 上 negative MR FP 数 = 0、precision +5~8pp、high_severity_accuracy +5~8pp

---

## P5 · 反馈驱动抑制（不写死 hint）

### 目标
用户标 FP 后，自动学到「该项目这种结构的 finding 不要再报」。但不允许在代码里写任何 hint。

### 数据结构
新增表 `rule_suppression_hints`：

```sql
CREATE TABLE rule_suppression_hints (
  project_id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  file_glob TEXT NOT NULL,           -- 自动从 file_path 抽取（前 2 段路径）
  snippet_hash TEXT NOT NULL,        -- normalized_snippet 的 sha1
  snippet_excerpt TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  last_marked_at TEXT NOT NULL,
  PRIMARY KEY (project_id, rule_id, file_glob, snippet_hash)
);
```

### 写路径
`FeedbackLearningService` 标 FP 时：
1. 抽 `(rule_id, file_glob, snippet_hash, snippet_excerpt)` 写入
2. **不在代码里**判断「这个规则该不该抑制」，只是写入

### 读路径
- prompt builder 把命中当前 diff 的 hints 注入 `historical_suppressions` 段（≤ 5 条），用通用提示语：「以下相似模式在本项目被人工判为 FP，若再次发现请提供新增证据」
- judge 阶段对命中 hint 的 finding：`evidence_score -= 0.1 × log(count + 1)`，并写 `quality_trace.matched_suppression_hint`

### 禁止项
- 抑制规则文件、抑制白名单、抑制黑名单——**一律不许在 repo 中存在**
- 不允许某个 rule_id 默认进入抑制（必须有真实用户反馈才有 hint）
- 不允许跨项目共享 hint（避免一个项目的偏好污染另一个项目）

### 验收
- 单测：FP 标记 → hint 写入 → 下次同 snippet 出现 → evidence_score 下降 → finding 降级
- 真 PR set 持续运行 30 天后，FP 重复率 ↓ 80%

---

## P6 · 共识与符号证据（已并入 P2）

P2 的 `consensus` 与 `symbol_alignment` 组件已经吸收了原 Q07/Q09 的功能，无需独立任务。
关键约束：这两个组件对所有 rule 一视同仁地参与打分，不许写「DDD 规则才算 symbol_alignment」一类条件。

---

## 任务依赖图

```
P0.1 真 PR Gold Set ─┐
P0.2 seed/cache ─────┴──── 基线
                            │
                            ▼
                          P1 规则注册表 (基础)
                            │
                            ▼
                          P2 通用证据评分 (依赖 P1)
                            │
                          ┌─┴─┐
                          ▼   ▼
                        P3 自检索 few-shot
                        P4 通用 critic
                        P5 反馈驱动抑制
```

P3、P4、P5 互相独立，可并行；都依赖 P2 完成（因为它们都要写 evidence_score 或 quality_trace）。

---

## 与上一轮（Q01-Q10）的差异

| 维度 | Q 系列（已废弃） | P 系列（本轮） |
|---|---|---|
| 工具提级 | Q03 维护一张 YAML 白名单 | P1 注册表中每条规则**自己声明** tool_sources |
| FP 控制 | Q05 写 evidence_score 但保留旧关键词分支作 fallback | P2 删光关键词分支，只剩 evidence_score |
| Few-shot | Q04 仓库里维护 examples 文件 | P3 运行时从评测集 + 反馈库检索 |
| 共识/符号 | Q07/Q09 独立任务 | 并入 P2 评分组件，无独立分支 |
| 抑制 | Q10 设计 hint 表 | 同样设计 hint 表，但严格禁止任何 repo 内 hint 文件 |
| 工程纪律 | 没有禁止补丁 | 显式禁止 `if rule_id == "X"`、关键词分支、规则白名单字面量、手工例子 |

---

## CI 守门（防补丁化复发）

新增 `scripts/lint_no_rule_branches.py`，CI 必跑：

- `worker/orchestration/judging/` 与 `worker/orchestration/nodes/judge_findings.py` 中**禁止**：
  - `set[str]` / `frozenset[str]` 的字面量声明，且元素含 `-`、`_` 之类规则 ID 字符
  - 任何 `if .* == "[A-Z]+-[A-Z]+-\d+"` 的相等判断
  - 任何 `if "[一-龥]+" in (text|finding|item)` 的中文关键词匹配
- `worker/prompts/` 中**禁止**：
  - 提交以 `examples` 为名的 jsonl 文件
- 违反则 CI 红，需要走「提议在注册表加字段」或「提议加新评分组件」流程绕开。

---

## 完成标准

- `npm run verify:real-prs` 在 4 真 PR + 1 negative 上：P ≥ 0.78、R ≥ 0.65、negative FP = 0
- `worker/orchestration/nodes/judge_findings.py` 行数 ≤ 1500（当前 3700+）
- `rg "PROMOTABLE_.*RULES" worker/` 仅剩兼容 import
- `rg "if .*\"[A-Z]+-[A-Z]+-\d+\"" worker/orchestration/judging/` 为空
- `rg "if \"[一-龥]+\" in" worker/orchestration/judging/` 为空
- `evidence_score`、`quality_trace.consensus_agents`、`quality_trace.critic_verdict`、`quality_trace.matched_suppression_hint` 全部经 review_findings 表落库且前端可看
- `lint_no_rule_branches.py` 进 CI 必跑

每加一条规则、每改一类 FP，全部走「在注册表加字段」或「在 evidence_score 加组件」两条路径之一。代码不许再针对具体问题打补丁。
