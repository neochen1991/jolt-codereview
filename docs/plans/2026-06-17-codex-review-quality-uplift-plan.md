# Codex 检视质量提升 · 第二轮（质量优先）

> 目标：把 `verify:real-prs` 在真实开源 PR 上的 precision 从基线（合成 MR 0.89，真实 PR 预估 0.55）拉到 ≥ 0.80，recall 从 0.80 拉到 ≥ 0.85，并在 ≥ 4 个 MR 上稳定复现。
> 不做的：纯维护性拆分、纯安全治理、纯前端重构（这些走另一条工单线）。

## 收益锚点（每个任务都映射到一个具体失败模式）

当前实测样本（Java complex 10-file MR）暴露的检视质量问题：

1. 同一专家两次跑 TP 数 8 → 9 抖动 → **可重复性缺失**
2. `DEP-CVE-001 fastjson` 这类工具命中明确的问题反而漏报 → **工具观察未被采纳为 finding**
3. `DDD-VO-002` 在同文件 line 7 和 line 12 各报一次 → **同根因判定弱**
4. 漏掉 `BE-API-001 RequestBody 缺 @Valid` 这类 LLM 必懂但实际没出 → **专家 prompt 缺少正负样例**
5. `bound_markdown_rules` 里 `skipped_rules` 字段虽要求填但**无人消费** → 项目级规则覆盖不可审计
6. `_is_low_precision_unbacked_advisory` 累积 ~40 个中文关键词分支才压住 FP → **证据强度没有上游打分，只能下游硬筛**
7. 合成评测 P=0.89 → 真实 PR 上预估骤降到 0.55 → **gold 数据过拟合**

下面 Q01 ~ Q10 每个任务都对准上面的一条或多条失败模式。

---

## Q01 · 真开源 PR Gold Set（基线必备）

- **打掉的失败模式**：#7 过拟合合成数据。
- **目标**：gold set 至少 4 个真实 PR + 1 个 negative，让后面所有 Q02–Q10 的收益可被量化。
- **改动**
  - `evaluation/real_prs/` 加 4 个 PR 元数据 JSON（推荐 spring-framework / dubbo / shiro 历史 fix commit + 1 个纯文档 PR 作 negative）
  - 新增 `scripts/seed-real-prs.mjs`：从 GitHub fetch patch + 写本地 `merge_requests/review_jobs`
  - `evaluation/real_gold_set.jsonl` 标注每个 PR 的 expected rule_id + line + evidence_keywords
  - `scripts/score_real_pr_reviews.py`：min-precision 阈值首跑 0.55、首跑后按实测 -0.05 起步逐周收紧；min-recall 0.60；negative_false_positive_count = 0
- **收益度量**：所有后续任务必须在该 set 上证明「不让 P 或 R 单调下降」才能合入。
- **验收**：`npm run verify:real-prs` 跑通，report 输出 ≥ 4 MR、≥ 25 条 gold finding。

---

## Q02 · LLM 输出可重复（Seed + JSON Schema + 缓存）

- **打掉的失败模式**：#1 抖动；以及隐性的 JSON 解析失败导致整批 finding 丢失。
- **目标**：同 MR 复跑 TP 集合一致；JSON 解析失败率 < 0.5%。
- **改动**
  - `worker/llm/client.py`：所有 chat completions 加 `seed`（默认 13）+ `response_format: json_schema`
  - 新增 `worker/llm/schemas.py`：`FINDING_LIST_SCHEMA / DEBATE_VERDICT_SCHEMA / ROUTER_SCHEMA / SUMMARY_SCHEMA`，`strict: true`
  - 新增 `worker/llm/cache.py` + 表 `llm_response_cache`（key=hash(provider+model+prompt+seed+schema_name)）
  - 不支持 schema 的 provider 自动降级一次（捕获 4xx 含 `response_format` 字样）并打 `recorder.event("schema_strict_disabled")`
- **收益度量**
  - 真 PR set 同 MR 跑两次，TP/FN/FP 集合 diff 为空
  - 第二次 review 的 LLM call 数 ≤ 第一次的 30%
  - 解析失败事件 `parse_llm_findings_failed` 周环比 ↓ 90%
- **验收**：`npm run verify:real-prs` 双跑结果完全一致；`worker/tests/test_llm_schema.py` 覆盖 schema 注入 + 降级路径。

---

## Q03 · 工具观察提级覆盖扩面

- **打掉的失败模式**：#2 高置信工具命中没变成 finding（fastjson DEP-CVE-001、KEYS REDIS-CMD-003 等会被白名单漏过）。
- **目标**：把 OSV-Scanner / Trivy / Semgrep / Gitleaks / java_web_static / tree_sitter_code_graph 中**置信度 ≥ 0.85 且行号精确**的观察，按规则映射默认上升为候选 finding。
- **改动**
  - 新增 `worker/orchestration/judging/tool_promotion_table.yaml`：把当前散落在 `judge_findings.py` 里的 `PROMOTABLE_TOOL_RULES`、`PROMOTABLE_EXTERNAL_TOOL_RULES`、`TOOL_COVERAGE_FILL_RULES` 合并为一张表，每条带：
    ```yaml
    - tool_rule_id: AvoidCatchingGenericException
      promote_to: CODE-EXC-003
      min_confidence: 0.84
      requires_line: true
      severity_floor: medium
      agent_owner: coding_agent
    ```
  - `judge_findings.py` 改为读表，禁止再新增硬编码常量集合（lint 规则可加：禁止在该文件新增 `set[str]` 字面量）
  - `_fill_missing_tool_coverage` 改为对**整张表的 promote_to 列表**做兜底，不再只覆盖 10 条规则
  - 同时为每条入表规则补 1 行 gold case 到 `evaluation/real_gold_set.jsonl`
- **收益度量**：真 PR set recall +5–10pp，重点在 DEP / SEC / REDIS 类。
- **验收**：表行数 ≥ 30；`verify:real-prs` recall 单调不降；`rg "PROMOTABLE_.*RULES = {" worker/orchestration` 仅剩兼容 import。

---

## Q04 · 专家 Prompt 加正负样例（Few-shot）

- **打掉的失败模式**：#4 LLM 漏报本应必出的高显著问题（`@Valid` 缺失、controller 直接吃 Map）；以及反向 — 把不属于职责的 finding 报出来。
- **目标**：每个 expert persona 在 prompt 里带 1 个 positive 例 + 1 个 negative 例 + 1 个边界例（明显问题但不属于本专家），全部基于真 PR 截取。
- **改动**
  - 新增 `worker/prompts/examples/<agent_id>.jsonl`，每条 `{persona, role: positive|negative|boundary, snippet, expected_finding | expected_skip_reason}`
  - `worker/prompts/builder.py::build_prompt` 新增 `examples` 段（紧邻 `agent_profile`），最多 3 条，按 agent_id 加载
  - 例子来源：从 Q01 的真 PR 评测里挑、并交叉用 `evaluation/real_findings.jsonl` 的历史 FP/FN 作 negative
  - `redact_untrusted` 不应用于 examples（因为是受信内容）
- **收益度量**：真 PR set precision +3–5pp（negative example 抑制越权报告）、recall +3–5pp（positive example 唤起明显遗漏）。
- **验收**：每个 active agent 都有 examples 文件；`verify:real-prs` precision 与 recall 同时不降，且至少一项 +3pp。

---

## Q05 · 上游证据强度评分（替代下游硬筛）

- **打掉的失败模式**：#6 `_is_low_precision_unbacked_advisory` 已经膨胀到 ~40 个中文关键词分支。这是「LLM 自由发挥 → judge 硬筛」结构的必然恶化。要改成在 finding 入库前先打证据分。
- **目标**：每条 finding 写入时计算 `evidence_score ∈ [0, 1]`，judge 仅看分数 + 阈值，不再看关键词。
- **改动**
  - 新增 `worker/orchestration/judging/evidence_score.py::score_evidence(finding, related_context, tool_observations) -> dict`，返回：
    ```
    { "score": 0.0–1.0,
      "components": {
        "tool_match": 0.0–0.4,    # 工具命中同 file ±5 行同 rule
        "symbol_match": 0.0–0.2,  # related_context.changed_symbols 命中
        "snippet_quote": 0.0–0.2, # finding.evidence 中含 file 真实片段子串
        "line_precision": 0.0–0.1,# line_start==line_end 或区间 ≤ 5
        "rule_alignment": 0.0–0.1 # covered_rules 与 source_observations 的 rule 相交
      }}
    ```
  - `verify_findings` 节点把 score 写入 `finding.evidence_score`
  - `judge_candidate_findings` 用 `evidence_score < 0.35` 替代当前所有 `_is_low_precision_unbacked_advisory` 关键词分支（保留为 fallback 1 个 release）
  - 新增 `worker/tests/test_evidence_score.py` 锁死 5 类典型 case 的分数
- **收益度量**
  - 单元测试覆盖既有 ~40 条关键词分支的等价语义
  - 真 PR set precision 不降（理想 +1–2pp，靠分数比关键词更准）
  - judge_findings.py 净减 ≥ 200 行硬编码分支
- **验收**：`evidence_score` 字段进入 `review_findings` 表 + 前端可看；上述测试与 verify 全绿。

---

## Q06 · 绑定规则覆盖闸门

- **打掉的失败模式**：#5 `bound_markdown_rules` 在 prompt 里要求专家逐条检查并填 `skipped_rules`，但 judge 与 verifier 都没消费这个字段，等于规范没落地。
- **目标**：让项目级 Markdown 规范的覆盖率成为可审计指标，并在低覆盖时触发一次重检。
- **改动**
  - `worker/orchestration/nodes/run_experts.py`：每个专家产出后聚合 `covered_rules ∪ skipped_rules`，与 `agent.bound_rules` 求差集得到 `unchecked_rules`
  - 当 `unchecked_rules / total_bound_rules > 0.3` 时，记 `recorder.event("bound_rule_coverage_low")` 并对该专家发起一次「补检视」LLM 调用，prompt 里只列剩余 rule_id（小 prompt、小 max_tokens）
  - `judge_findings` 的 `supplement_bound_rule_findings` 改为只接受**已被声明为 covered**的 rule，避免 LLM 提交 rule_id 但没真检查
  - `ObservabilityService` 新增 `bound_rule_coverage` 指标到 `/api/projects/:projectId/review-quality/metrics`
- **收益度量**：`verify:real-prs` 在标了 bound_rules 的 PR 上 recall +2–4pp；产品侧拿到「项目规范覆盖率」指标。
- **验收**：metrics 接口返回 `bound_rule_coverage` 字段；测试覆盖「未达 70% 触发补检视」与「补检视产物受 evidence_score 约束」。

---

## Q07 · 多专家共识加权

- **打掉的失败模式**：当前同一行若被两个不同专家独立指出同一问题，judge 会按 `_same_line_same_issue` 直接去重保留分高的一条 → **共识信号被丢弃**。共识应该提升 confidence，不是被压缩。
- **目标**：去重保留代表 finding，但 `confidence` 按共识计数加权。
- **改动**
  - `judge_candidate_findings` 在去重前记 `consensus_agents = sorted({agent_id, ...})`
  - 加权规则：基础 conf × `(1 + 0.05 × min(3, len(consensus_agents) - 1))`，clip 到 0.99
  - `consensus_agents` 写入 `finding.quality_trace.consensus_agents`
  - `evidence_score` 中新增可选组件 `consensus`（max +0.1）
- **收益度量**：高严重度命中率上升（多专家独立命中往往是真问题）；`high_severity_accuracy` SLO +3pp。
- **验收**：单测覆盖「2 专家共识 → +5%」「3 专家共识 → +10%」「单专家不加权」三类；`verify:real-prs` 高严重度召回不降。

---

## Q08 · 对抗性二次校验（Top-k Critic）

- **打掉的失败模式**：当前 Top finding 仅靠 verifier + judge 静态规则把关，没有「另一个角色再读一遍」。这是真实评审里防 FP 的最后一关。
- **目标**：对最终入库前 Top-k（k=8，高严重度优先）发起一次小型 critic LLM，prompt 极小（仅 finding + 真实片段 + bound rule），返回 `{is_real_bug, reason, suggested_severity, suggested_confidence}`。
- **改动**
  - 新增 `worker/orchestration/nodes/critic_pass.py`，挂在 `judge_findings` 之后、`summarize_pr` 之前
  - 仅对 `severity in {critical, high}` 或 `evidence_score < 0.55` 的 finding 触发，避开浪费
  - critic 否定时：finding 不删除，但 `severity` 降一级且 `confidence × 0.7`，并写 `quality_trace.critic_verdict`
  - 单 review critic 调用上限 8 次、共享 LLM 缓存
- **收益度量**：真 PR set negative MR FP 数 → 0；高严重度 precision +5–8pp。
- **验收**：critic 在 cache miss 情况下单 MR 调用 ≤ 8 次；测试覆盖「肯定保留」「否定降级」「证据不足跳过」三类。

---

## Q09 · Verifier 用源码上下文与符号

- **打掉的失败模式**：verifier 当前主要看 patch 文本片段；跨文件影响和「被改函数的调用方」类问题被误杀。
- **目标**：verifier 加载 finding 命中文件的 ±20 行真实源码（已有 `source_snippet_loader_for_files` 工具），并消费 `related_context.changed_symbols / modified_symbols / related_tests`。
- **改动**
  - `verify_findings.py`：每个 finding 调 snippet loader 取 `[line_start-20, line_end+20]` 真实源码，作为 `verification_context`
  - 新增 `_symbol_evidence_score(finding, related_context)`：命中 changed_symbols → +0.1，命中 related_tests → +0.05
  - 该分加进 Q05 的 `evidence_score.symbol_match` 组件（避免双计）
  - 文件不可获取时 graceful fallback 走旧逻辑
- **收益度量**：DDD/架构类 recall +2–4pp；跨文件影响类问题进入 final findings 的比例上升。
- **验收**：`worker/tests/test_verifier_symbol_evidence.py` 三类 case 全绿；`verify:real-prs` precision 不降。

---

## Q10 · FP 反馈 → 同模式抑制

- **打掉的失败模式**：用户在前端标 FP 后，目前只更新 `rule_precision_history`，**该模式下次还会被报出来**（因为是按 rule_id 全局降权，不针对具体片段模式）。
- **目标**：把每次 FP 反馈拆出「rule_id + snippet 摘要 + 文件类型」三元组，作为下次 review 的预判抑制提示。
- **改动**
  - 新增表 `rule_suppression_hints (project_id, rule_id, file_glob, snippet_hash, snippet_excerpt, last_marked_at, count)`
  - `FeedbackLearningService` 标 FP 时写一行（snippet_hash = sha1 of normalized snippet）
  - `worker/prompts/builder.py::build_prompt` 把命中当前 diff 的 hints 注入 `suppression_hints` 段（≤ 5 条），用语：「以下模式在本项目历史上已被人工判为 FP，若再次发现请提供新增证据再输出」
  - `judge_findings` 也读这张表，对命中 hint 的 finding `confidence × 0.6` 并写 `quality_trace.matched_suppression_hint`
- **收益度量**：项目运营满 30 天后，FP 重复率（同 rule + 同文件 + 同近似片段再次报出）↓ 80%。
- **验收**：单测覆盖「写入 → 命中 → 降权」全链路；前端 FP 反馈触发后下次 review 看到 `quality_trace.matched_suppression_hint`。

---

## 依赖与顺序

```
Q01 (真 PR 集) ──┐
Q02 (seed/cache) ┴── 基线先稳定，没这两个所有提升都不可测
                     │
                     ▼
                 Q03 (工具表)        ← recall 大头
                 Q04 (few-shot)      ← precision + recall 双拉
                 Q05 (evidence score)← 替代关键词硬筛，FP 控制核心
                 Q06 (bound 覆盖)    ← 项目规范落地
                 Q07 (共识加权)      ← 高严重度精度
                     │
                     ▼
                 Q09 (verifier 升级) ← 跨文件 recall
                 Q08 (critic 二审)   ← FP 兜底
                     │
                     ▼
                 Q10 (FP 抑制反馈)   ← 长期质量复利
```

可并行：{Q03, Q04} 并行；{Q05, Q06, Q07} 并行；{Q08, Q09} 并行。

---

## 收益总览（在 4 真 PR + 1 negative 的 set 上）

| 任务 | precision Δ | recall Δ | 高严重度精度 Δ | 主要受益维度 |
|---|---|---|---|---|
| Q01 | — | — | — | 把基线建到真实数据 |
| Q02 | +1 ~ 2 | +1 ~ 3 | — | 解析失败止血、可测 |
| Q03 | -1 ~ 0 | **+5 ~ 10** | +2 ~ 4 | 工具命中真正成 finding |
| Q04 | **+3 ~ 5** | **+3 ~ 5** | +2 ~ 4 | 专家更准更全 |
| Q05 | **+3 ~ 6** | -1 ~ 0 | +1 ~ 2 | 替代关键词硬筛 |
| Q06 | +1 ~ 2 | +2 ~ 4 | +1 ~ 2 | 项目级规范覆盖 |
| Q07 | +1 ~ 2 | -1 ~ 0 | **+3 ~ 5** | 共识 = 信号 |
| Q08 | **+5 ~ 8** | -1 ~ 0 | **+5 ~ 8** | 真 FP 拦截 |
| Q09 | 0 ~ +1 | **+2 ~ 4** | +1 ~ 2 | 跨文件影响 |
| Q10 | +2 ~ 4 累计 | — | +1 ~ 2 累计 | 长期复利 |

**叠加预期**（保守取下沿、保守去 30% 重叠）：
- precision: 0.55 → **0.78 ~ 0.82**
- recall: 0.45 → **0.62 ~ 0.70**
- high-severity accuracy: 当前 0.67 → **0.82 ~ 0.88**

---

## 不在本轮做的（已写入另一条工单线）

- 拆 `judge_findings.py` 维护性重构 → 等 Q05 落地后该文件硬编码自然 -200 行，再决定是否拆
- 移除 `default_api_key` / 提示词脱敏扩面 / 前端拆分 / deepagents 退场 → 安全与维护性专项
- LangGraph 节点重排 → 当前 12 节点拓扑不是质量瓶颈

---

## 完成标准

`npm run verify:real-prs` 在 ≥ 4 个真实开源 PR + 1 个 negative MR 上：

- precision ≥ 0.80
- recall ≥ 0.65
- high_severity_accuracy ≥ 0.80
- negative_false_positive_count = 0
- 同 MR 复跑 TP 集合一致（Q02 锁定）
- 每条 finding 携带 `evidence_score`、`consensus_agents`、`quality_trace.critic_verdict`（Q05/Q07/Q08 写入）
- `bound_rule_coverage` 指标在 metrics 接口可见且 ≥ 0.7（Q06）

10 个 commit、2 周内可完成。
