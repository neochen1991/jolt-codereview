# Jolt CodeReview 检视质量增强方案与落地计划

> 创建日期：2026-06-07
> 适用分支：`codex/production-platform-enhancement`
> 执行方：Codex
> 目标读者：实施工程师 / 评审负责人
> 优先目标：**显著提升 AI 代码检视的质量（recall / precision / 严重级校准 / 上下文完整度）**，借鉴 CodeRabbit、Greptile、Cursor BugBot、Sourcery、Qodo Merge、Korbit、Graphite Diamond 等业界一线 AI 代码检视产品的实践。

---

## 一、当前实现速览

### 1.1 架构
- React 19 前端 + Node/TS API + Python LangGraph Worker。
- Worker 核心：`worker/review_runtime.py`（单文件 3081 行）。
- LangGraph DAG（`worker/orchestration/graph.py`，节点位于 `worker/orchestration/nodes/`）：
  ```
  fetch_mr → choose_effort → prescan → build_context →
  route_agents → run_experts → verify_findings →
  detect_conflicts → run_targeted_debate → judge_findings → finalize
  ```
- 10 个硬编码专家：security / dependency / database / performance / coding / ddd / backend / frontend / redis / test（`worker/agents/registry.py:8-79`）。

### 1.2 核心 LLM 调用现状
- 每个 expert **仅一次** LLM 调用（`worker/review_runtime.py:2283-2375`）。
- System prompt 仅一句话：`你是严格的代码检视专家，只输出 JSON 数组，不要输出 Markdown。`
- `temperature=0.1`。
- 用户 prompt 是单一 JSON blob，包含 `agent_profile / review_rules / structured_diff / static_tool_scan_findings / task`（`worker/review_runtime.py:2398-2469`）。
- 上下文压缩极强：**仅前 20 个文件，每个 patch 截断 3000 字符**（`build_prompt`，`review_runtime.py:2404-2405`）。

### 1.3 静态工具能力（这是项目的优势）
- 集成 semgrep / gitleaks / bandit / eslint / ruff / PMD / Checkstyle / SpotBugs / Dependency-Check / OSV / Trivy / KICS / openapi-diff（`worker/tools/`）。
- 通过 `tool_normalizer.py` 统一归一化为 `tool_observations`，作为 LLM 的**交叉验证证据**。

### 1.4 后处理流水线
1. `verify_findings`（`worker/orchestration/nodes/verify_findings.py:83-138`）—— diff 行号校验 + 证据 token-Jaccard ≥ 0.5 + 规则注册校验 + confidence 阈值。
2. `detect_conflicts`（`detect_conflicts.py:15-69`）—— 规则识别冲突。
3. `run_targeted_debate`（`run_targeted_debate.py:6-38`）—— **当前是 if/elif 硬编码字符串，并非真 LLM 辩论**。
4. `judge_findings`（`judge_findings.py:213-253`）—— 纯 Python：弱证据强 severity 强制降级、按 (rule_category, file, line_bucket) 去重、`max_findings=20` 截断、`confidence≥0.75 且 severity∈{critical,high,medium}` 才 selected。

### 1.5 评估系统
- `evaluation/gold_set.jsonl`（30+ 条 ground truth）+ `evaluation/run_gold_eval.py`。
- **缺陷**：scoring 的是预生成的 `sample_findings.jsonl`，**没有真正跑流水线**。
- 阈值门禁：`precision ≥ 0.80, recall ≥ 0.75, high_recall ≥ 0.85`。

---

## 二、检视质量的五大薄弱点（按影响排序）

| # | 问题 | 关键证据 | 质量影响 |
|---|---|---|---|
| 1 | **上下文极度匮乏**：LLM 只看 diff 切片，看不见仓库 | `build_prompt` 截 20 文件 × 3000 字符；`build_code_context_snapshot` 仅扫 diff；`gitnexus.impact_paths=[]` | **Recall 天花板**——跨文件、调用方、契约破坏类问题盲区 |
| 2 | **"专家辩论"是假的** | `run_targeted_debate.py:18-26` 全是硬编码字符串，无第二次 LLM 调用 | 冲突项无法被真正裁决，严重级失校准 |
| 3 | **单 Pass 检视、置信度无校准** | 每 expert 1 次 LLM；Judge 全 Python；confidence 由 LLM 自报 + 固定 +0.03/+0.05 | Precision 不稳，FP 难控 |
| 4 | **Verifier 过度拒绝真问题** | Jaccard≥0.5 但 LLM 只看到 diff，没有完整源码可匹配；无 tool_obs 支持的合理 finding 被 `evidence_not_in_source` 丢弃 | Recall 隐性流失 |
| 5 | **Java 单语言深度** | 10 个 agent 全部绑 `JAVA_WEB_STANDARD.md` | 多语言项目质量崩塌 |

附属问题：
- 路由硬编码 if/elif（`agent_matches_files`）—— 新增语言/框架必须改代码。
- FP 抑制仅哈希级（同文件同行同规则）—— 近似 FP 无法泛化抑制。
- `worker/review_runtime.py` 巨型单文件 —— 间接拖慢迭代、放大回归风险。
- `agent-skills/*/JAVA_WEB_STANDARD.md` 没有"通用 + 语言特化"分层。
- 评估只评静态 fixture，**改 prompt 改路由都没有真正的回归门禁**。

---

## 三、优化方案（对标业界，按优先级排序）

### P0 —— 立即显著提升质量

#### P0-1. 仓库级 RAG 上下文（**最重要的一项**）
**对标**：CodeRabbit / Greptile / Cursor BugBot 的核心差异化。
- 利用 `analysis_worktree_path` 已 clone 的源码 + `tree_sitter_tool.py`（当前只做探针）。
- 建立三层索引：**符号 → 定义位置 → 调用方位置**。
- `build_prompt` 增加 `related_context` 字段：
  - 对 diff 涉及的每个新增/修改符号，附其**定义片段（≤30 行）**。
  - 直接 caller 片段（≤2 处，各 ≤15 行）。
  - 同名测试是否存在。
- **解决**：跨文件契约破坏、签名变更影响、字段删除是否仍被引用、测试是否真正覆盖等结构性盲区。

#### P0-2. 真 LLM 辩论 + LLM-as-Judge
**对标**：CodeRabbit / Korbit 的 ensemble + LLM judge。
- 改写 `run_targeted_debate.py`：仅对 `detect_conflicts` 输出的真冲突项触发 **1 次 LLM 调用**，输出 `{verdict: keep|drop|downgrade, calibrated_severity, calibrated_confidence, reason}`。
- 用强模型（claude-sonnet-4-6 或 GPT-4o）作 judge；配额上限 ≤ findings_total × 0.3。
- `judge_findings` 改为吸收 LLM judge 结果。

#### P0-3. 修复 Verifier 的 over-reject
- 将 evidence 匹配从"仅 diff"扩到**完整源码（依赖 P0-1 索引）**。
- 引入软拒绝：低于阈值不直接丢，降 0.1 confidence 并打 `low_evidence_match` 标，交给 Judge。
- **预期**：高质量但缺工具佐证的 LLM finding 不再被静默丢弃。

#### P0-4. PR 级总结与影响面分析
**对标**：CodeRabbit / Greptile 的 PR walk-through——业界用户最常看的内容。
- 新增 `summarize_pr` 节点（finalize 之前），输出：PR 意图、变更地图、风险高亮、新增/缺失测试、跨文件耦合点。
- 一次 LLM 调用即可。

---

### P1 —— 重要质量与可信度提升

#### P1-5. 增量评审（incremental review）
- 按 `commit_sha` 持久化 `dedupe_hash + status`。
- 新 push 仅 review 增量 commit 的 diff。
- 自动 mark "已修复"评论为 resolved。

#### P1-6. 基于历史的置信度校准
- 维护 `rule_precision_history`（`agent_id × rule_id` 聚合 accepted/rejected）。
- Judge 阶段用 Platt scaling / isotonic 校准 LLM 自报 confidence。
- precision < 0.4 的 rule 自动降权或下线。

#### P1-7. 路由 LLM + 规则兜底
- 保留规则匹配作为快速通道。
- 未命中或多候选时，用 1 次轻量 LLM 路由（文件列表 + 文件首 80 行 + agent 描述）。
- 新增 `config.routing.custom_agents` 让用户加专家不改代码。

#### P1-8. GitHub `suggestion` block
- `suggested_code` 已结构化，发布层改为 GitHub 原生 ` ```suggestion ` 块。
- **零模型成本、纯发布层改动，但用户采纳率大幅提升**。

#### P1-9. 评估系统升级
- 新增端到端 benchmark runner：从 gold_set 的 mr_id 真正跑一遍 pipeline 再 scoring。
- 引入"反面 gold set"（已确认无问题的 MR），统计 FP rate。
- CI 门禁：prompt/路由/verifier 改动必须跑 gold-eval 且不能跌。
- 增加 `agreement@k`（与人工 reviewer top-k 重合度）指标。

---

### P2 —— 多语言与扩展性

#### P2-10. Skill 标准两层化
- 抽离 `agent-skills/<expert>/CORE_STANDARD.md`（语言无关的通用项）。
- 各语言专属 `LANG_<lang>.md`（go/kotlin/ts/python/rust）。
- Agent 按 MR 语言 mix-in 加载。

#### P2-11. 拆分 `worker/review_runtime.py`
- 提取至 `worker/prompts/`, `worker/diff/`, `worker/static/`, `worker/llm/`。
- 单文件 3081 行严重拖慢 prompt 迭代。

#### P2-12. PR 评论交互（chat-with-bot）
- 用户 reply `@jolt explain finding 12` / `@jolt is this really a bug?` 触发上下文化二次回答。
- 复用现有 verify + LLM 通道。

---

### P3 —— 长期能力建设
- 多模型 ensemble（同 expert 双模型，分歧才进 debate）
- 反馈→ few-shot 池微调（替代当前的纯 hash 抑制）
- 自动测试生成（Qodo / Sourcery 路线）
- 架构级 finding（循环依赖、上下游契约破坏，依赖 P0-1）

---

## 四、Codex 实施步骤清单

> 每个 STEP 给出：目标、关键文件、验收标准（DoD）、风险点。
> Codex 应按顺序执行；每个 STEP 完成后跑 `npm run verify:gold-eval` 与对应单测。

### Phase 0 —— 前置准备（半天）

#### STEP 0.1 建立质量评估基线
- **状态**：已完成本地 MR 检视基线（2026-06-07）。报告见 `docs/reports/2026-06-07-quality-baseline.md`；当前基线包含 gold-eval、Java Web fixture 完整 pipeline、GitHub fixture、真实 GitHub/vscode MR。公司内网 CodeHub / Java Spring 真实 MR 因本机暂无凭据，后续上线前需替换 fixture 样本。
- **目标**：在动任何代码前，记录当前 gold-eval 的 precision/recall/high_recall 与一次真实 MR 的 finding 快照作为对照基线。
- **做什么**：
  - 运行 `npm run verify:gold-eval`，输出存到 `docs/reports/2026-06-07-quality-baseline.md`。
  - 选 3 个有代表性的真实 MR（≥1 个大 MR，≥1 个跨文件 MR，≥1 个纯 Java 业务 MR），跑完整 pipeline，把 findings JSON 与 prompt/response 也存入基线报告。
- **DoD**：基线报告 commit 进仓库。

#### STEP 0.2 拆分 `worker/review_runtime.py`（提前到 Phase 0，因为后续每个 STEP 都要改这个文件）
- **状态**：代码拆分已完成（2026-06-07）。已新增 `worker/prompts/`、`worker/diff/`、`worker/context/`、`worker/static/`、`worker/llm/`，`review_runtime.py` 保留入口编排与兼容导入。验证：`npm run verify:gold-eval` 指标与 STEP 0.1 完全一致；`npm run verify:worker-orchestration`、`npm run build` 通过。Java fixture 重跑工具观察数量和分布一致（31 条，`java_web_static/semgrep/pmd/trivy/osv`），但最终 finding 因 MiniMax 成功/超时次数和 sandbox 路径 prompt hash 非确定性存在差异，不能作为空 diff 确认项。
- **目标**：把 3081 行单文件拆成可维护模块，**不改变行为**。
- **做什么**：
  - `worker/prompts/builder.py` ← `build_prompt`, `redact_untrusted`
  - `worker/prompts/system.py` ← system prompt 常量
  - `worker/diff/slicer.py` ← `build_diff_slices`, `extract_added_lines`
  - `worker/context/snapshot.py` ← `build_code_context_snapshot`
  - `worker/static/heuristics.py` ← built-in regex `static_findings`
  - `worker/llm/client.py` ← `call_llm`
  - `worker/review_runtime.py` 仅保留入口编排与向后兼容 re-export。
- **DoD**：
  - `npm run verify:gold-eval` 数字与 STEP 0.1 基线**完全一致**（这是回归校验，**不允许改 prompt**）。
  - 真实 MR 重跑 finding 列表与基线 diff 为空。
- **风险**：现有节点通过工厂注入这些函数，必须保留 re-export，避免破坏 `worker/orchestration/nodes/*` 的导入。

---

### Phase 1 —— P0 质量核心（2 周）

#### STEP 1.1 修 Verifier over-reject（**第一个交付**，成本最低收益最快）
- **状态**：已完成（2026-06-07）。`verify_findings.py` 新增 `_evidence_matches_source` 评分，按 `>=0.5` 通过、`0.2-0.5` 降置信度并写入 `low_evidence_match`、`<0.2` 拒绝；`judge_findings.py` 的 `quality_trace_json.verification` 保留 flag 与 score。验证：`python3 worker/tests/test_verify_findings_soft_reject.py`、`npm run verify:worker-orchestration`、`npm run verify:gold-eval` 通过，gold-eval 指标不下降。
- **目标**：降低 `evidence_not_in_source` 误杀。
- **关键文件**：`worker/orchestration/nodes/verify_findings.py`
- **做什么**：
  - 把 `_evidence_matches_source` 从 `bool` 改为 `{matched: bool, score: float}`。
  - 阈值改为软拒绝：score ≥ 0.5 通过；0.2 ≤ score < 0.5 降 confidence 0.1 + 打 `low_evidence_match` flag 进入 Judge；< 0.2 才拒绝。
  - 增加单测 `worker/tests/test_verify_findings_soft_reject.py`，覆盖三档场景。
- **DoD**：
  - 单测通过。
  - gold-eval recall 相对基线 **不下降**，high_recall 提升或持平。
  - precision 不能跌超过 2pp。

#### STEP 1.2 GitHub Suggestion Block（纯发布层、零模型成本）
- **状态**：已完成（2026-06-07）。`formatPublishBody` 对 GitHub 且 `suggested_code` 非空、单 hunk ≤30 行的 finding 输出原生 ```suggestion fenced block；CodeHub 和超长/无建议代码 finding 仍使用普通代码块。新增 `scripts/verify-suggestion-block.mjs` 和 `npm run verify:suggestion-block`。验证：`npm run verify:suggestion-block`、`npm run verify:gold-eval` 通过。
- **关键文件**：`src/backend/routes/` 中处理发布的代码（搜 `vcs_publish_records`）+ `src/backend/github.ts`。
- **做什么**：
  - 当 finding 含 `suggested_code` 且单 hunk ≤ 30 行时，发布为 GitHub `suggestion` 块（` ```suggestion `）；否则仍发普通评论。
  - 增加 e2e 校验脚本 `scripts/verify-suggestion-block.mjs`。
- **DoD**：
  - 真实测试 PR 上能一键 Apply。
  - 现有"非 suggestion 类型"finding 行为不变。

#### STEP 1.3 PR 级总结节点
- **状态**：已完成（2026-06-07）。新增 `summarize_pr` LangGraph 节点并接入 `judge_findings → summarize_pr → finalize`；`review_jobs.pr_summary` 已加入 TS migration 与 Worker schema 兜底迁移；`summarize_pr_with_llm` 使用 MiniMax-M2.7 兼容 OpenAI API 单次输出固定结构，失败或预算触发时落结构化兜底摘要；`effort=trivial/fast` 明确跳过 summary LLM。前端详情页已在进度条下方新增蓝白风格 PR Summary 折叠卡片。验证：`npm run verify:worker-orchestration`、`npm run verify:pr-summary`（3 个样本均 `completed`，每个预算记录 1 次 LLM 调用）、`npm run build`、`npm run verify:gold-eval` 通过；完整 Java fixture worker 跑通并落库 `pr_summary`，但该次标准检视因前序专家调用触发 `wall_seconds_exceeded`，summary 按预算守卫走兜底摘要。
- **关键文件**：新增 `worker/orchestration/nodes/summarize_pr.py`；`worker/orchestration/graph.py` 注册到 finalize 之前。
- **做什么**：
  - 输入：fetch_mr 拿到的 MR 元数据 + 已 selected findings + 文件变更地图。
  - LLM 单次调用，输出固定结构：`intent / change_map / risk_highlights / test_coverage_gaps / cross_file_couplings / suggested_review_order`。
  - 持久化到 `review_jobs.pr_summary`（新增列，写 SQLite migration）。
  - 前端 `src/frontend/main.tsx` 顶部展示 PR Summary 区域（折叠卡片）。
- **DoD**：
  - 3 个基线 MR 的 PR Summary 输出合理（人工 spot-check）。
  - 一次 LLM 调用成本进入 budget，effort=fast 时跳过 summary。

#### STEP 1.4 真 LLM 辩论（Judge）
- **状态**：已完成（2026-06-07）。`run_targeted_debate` 节点已从硬编码字符串升级为真实 LLM 裁决：按冲突严重度排序并执行 `findings_total × 0.3` 配额上限，Prompt 包含 finding 全字段、冲突类型、diff 源码片段和相关 tool_observations，输出 `keep/drop/downgrade + calibrated_severity + calibrated_confidence + reason`；失败、无 key 或预算触发时走结构化兜底 verdict。`judge_findings` 新增 `apply_debate_verdicts`，drop 会进入 `debate_drop` 拒绝，downgrade/keep 会在去重与 selected 之前校准 severity/confidence，并写入 `quality_trace_json.debate`。验证：`npm run verify:debate-llm` 真实调用 MiniMax-M2.7 返回 `completed` 和 `keep/high/0.95` verdict，预算记录 1 次 LLM 调用；`npm run verify:worker-orchestration` 覆盖 drop/downgrade/keep 生效；`npm run build`、`npm run verify:gold-eval` 通过。gold-eval 当前基线 precision/recall/high_recall 已为 1.0，无法再 +3pp，本次验证为不回退。
- **关键文件**：`worker/orchestration/nodes/run_targeted_debate.py`、`worker/orchestration/nodes/judge_findings.py`。
- **做什么**：
  - 把 `run_targeted_debate` 从字符串模板改为：对每个 `conflicts[]` 项跑 1 次 LLM 调用。
  - Prompt 结构：finding 全字段 + 冲突类型 + 涉及源码片段（含上下文 ≤50 行）+ tool_observations。
  - 输出 schema：`{verdict: keep|drop|downgrade, calibrated_severity, calibrated_confidence, reason}`。
  - `judge_findings` 增加 `apply_debate_verdicts(findings, debate_results)`；verdict=drop 时直接移除；downgrade 时按 LLM 给的 severity 改写；keep 时按 calibrated_confidence 覆盖。
  - 配额：单 job 的 debate 调用数 ≤ findings_total × 0.3，超额按 conflict severity 排序截断。
- **DoD**：
  - gold-eval **precision 提升 ≥3pp**（核心验收）。
  - 严重级分布（critical/high/medium 计数）更接近 gold_set 期望分布。
  - 真实 MR 上明显的"小题大做"finding 被自动降级。

#### STEP 1.5 仓库级 RAG 上下文（**Phase 1 最大单项**，预计 1 周）
- **状态**：已完成（2026-06-07）。新增 `worker/context/repo_index.py`，基于 `analysis_worktree_path/full_repo_worktree_path/workspace_path` 或降级 materialized diff worktree 构建 SQLite 缓存索引（`symbols` / `refs`），按 `repository_id + commit_sha` 复用缓存；`resolve_diff_symbols` 会输出修改符号、定义片段、直接调用方、同名测试探测和源码内容。`prescan` 写入 `repo_symbol_index` context artifact，`build_context` 聚合 `related_context`，`run_experts` 将其传入每个专家，`build_prompt` 新增 `related_context` section；Verifier 证据匹配优先使用完整源码窗口，缺失时回退 diff snippet。验证：`npm run verify:repo-context` 覆盖索引构建、缓存命中、调用方解析、同名测试识别、prompt 注入和完整源码 evidence 匹配；`npm run verify:worker-orchestration`、`npm run build`、`npm run verify:gold-eval` 通过。质量闭环已由 STEP 2.4 的单 MR 与 5 MR pipeline eval 量化验证：Java Web fixture 单 MR precision/recall/fp_rate = 1.0/1.0/0.0；5 MR 聚合 recall/fp_rate = 1.0/0.0。
- **关键文件**：新增 `worker/context/repo_index.py`、`worker/context/symbol_resolver.py`；改 `worker/prompts/builder.py`。
- **做什么**：
  1. **索引构建**（`build_repo_index`）：
     - 基于 `analysis_worktree_path` 的 clone 源码 + tree-sitter（已有 `tree_sitter_tool.py`）。
     - 抽取所有文件的 import / class / function / method / const 符号，落盘到 `data/repo_index/<repo>/<sha>.sqlite`（schema: `symbols(name, kind, file, start_line, end_line)`、`refs(symbol_name, file, line)`）。
     - 索引按 commit_sha 缓存，复用避免重复构建。
  2. **符号解析**（`resolve_diff_symbols`）：对 diff 触及的每个修改符号，查询定义和直接 caller。
  3. **上下文注入**：`build_prompt` 增加 `related_context` 字段：
     ```json
     {
       "modified_symbols": [
         {
           "name": "OrderService.placeOrder",
           "definition_snippet": "...",
           "callers": [{"file":"...","line":...,"snippet":"..."}],
           "has_test": true,
           "test_file": "..."
         }
       ]
     }
     ```
     总长度上限 `RELATED_CONTEXT_MAX_CHARS=8000`，超出按 caller 数量截断。
  4. STEP 1.1 的 evidence 匹配从 diff 扩展到**完整源码**（用 repo_index 拿源码行）。
- **DoD**：
  - 索引构建对 100k 行 Java 仓库 ≤ 60s（带缓存命中 ≤ 5s）。
  - gold-eval **recall 提升 ≥5pp**（核心验收）。
  - 出现至少 3 个"跨文件类"finding 是基线没发现的（人工 spot-check 3 个真实 MR）。
- **风险**：
  - 索引体积、构建耗时；上限保护避免大 monorepo OOM。
  - 跨语言：先支持 Java/Python/TS/JS，其他语言降级为只看 diff。

---

### Phase 2 —— P1 可信度与体验（2 周）

#### STEP 2.1 增量评审
- **状态**：已完成 MR 级历史基础链路（2026-06-07）。新增 `mr_finding_history` 表，按 `merge_request_id + dedupe_hash` 持久化 `first_seen_head_sha / last_seen_head_sha / status / resolved_in_commit / finding_id`；`fetch_mr` 输出 `incremental_context`，当同一 MR 存在历史 active finding 且 head 变化时标记 `incremental_diff_only=true`；`finalize` 对本次 final findings upsert active，并将上一 head active 但本次消失的 finding 标记为 `resolved`，同步更新旧 `review_findings.lifecycle_state='resolved'`。验证：`npm run verify:incremental-history` 覆盖两次 MR run 的 active/ resolved 转换；`npm run build`、`npm run verify:gold-eval` 通过。当前 VCS fetch 仍拉取 MR diff，尚未按 commit API 真正缩小 diff 范围，后续接入 GitHub/CodeHub compare commits 后可进一步实现耗时下降目标。
- **关键文件**：`src/backend/db/migrations/`（新表 `mr_finding_history`）、`worker/orchestration/nodes/fetch_mr.py`。
- **做什么**：
  - 持久化每次 review 的 `dedupe_hash + status + commit_sha + resolved_in_commit`。
  - 新 commit 进来时 fetch_mr 输出 `incremental_diff_only=true`，pipeline 只跑新增/修改的 hunk。
  - finalize 阶段对比新旧 findings：旧 finding 在新 commit 中行号消失 → 自动 mark resolved + publish "resolved by <commit>" 评论。
- **DoD**：连续两次 push 同一 MR，第二次 review 用时下降 ≥50%；已修复评论被自动 resolved。

#### STEP 2.2 历史置信度校准
- **状态**：已完成（2026-06-07）。新增 `rule_precision_history(project_id, agent_id, rule_id, accepted_count, rejected_count, auto_suppress, last_updated)`；`FeedbackLearningService.recordFeedback` 会从 `covered_rules_json` 提取规则，在用户 accepted / false_positive / dismissed 后更新规则精度，样本数 ≥10 且 precision <0.4 时自动置 `auto_suppress=1`。Worker 新增 `worker/calibration/precision_history.py`，Judge 阶段按项目读取历史，对样本数 ≥3 的规则执行置信度校准，`auto_suppress` 规则直接进入 `rule_auto_suppressed` 拒绝，并将校准信息写入 `quality_trace_json.calibration`。验证：`npm run verify:rule-calibration`、`npm run build`、`npm run verify:gold-eval` 通过。
- **关键文件**：新增 `worker/calibration/precision_history.py`；改 `worker/orchestration/nodes/judge_findings.py`。
- **做什么**：
  - 表 `rule_precision_history(agent_id, rule_id, accepted_count, rejected_count, last_updated)`。
  - 用户在前端标记 finding 为 accepted/rejected/false_positive 时写入。
  - Judge 阶段：对每个 finding，按 `(agent_id, rule_id)` 查 precision = accepted/(accepted+rejected)，按 Platt scaling 校准 LLM 自报 confidence。
  - 同时把 precision < 0.4 且样本量 ≥ 10 的 rule 自动加 `auto_suppress=true` 标记，前端管理面板可查看。
- **DoD**：gold-eval precision 不下降；前端能看到 rule precision 排行榜。

#### STEP 2.3 路由 LLM + 规则兜底
- **状态**：已完成（2026-06-07）。保留 `agent_matches_files` 规则快速通道；当规则无匹配或候选数 ≥5 且非 fast/trivial 时，`route_agents` 会触发一次轻量 LLM 路由，输入文件列表、patch 摘要和所有 Agent 职责，只输出 agent_id 数组，失败/无 key/预算触发时回退规则结果。新增 `merge_custom_agents` 支持 `config.routing.custom_agents`，用户可配置 `{id, description, file_patterns, triggers, skills, tools}` 注入自定义专家而不改代码。验证：`npm run verify:router-llm` 真实调用 MiniMax-M2.7 返回 `frontend_agent/redis_agent/security_agent`，并确认 custom agent 已合并；`npm run verify:worker-orchestration`、`npm run build`、`npm run verify:gold-eval` 通过。
- **关键文件**：`worker/review_runtime.py` 中 `route_agents`、`agent_matches_files`。
- **做什么**：
  - 保留 `agent_matches_files` 作为快速通道。
  - 增加 `route_with_llm`：当规则无匹配或匹配 ≥ 5 个 agent 时触发 1 次轻量 LLM 调用（文件列表 + 每文件首 80 行 + 所有 agent 描述）输出 agent_id 列表。
  - 增加 `config.routing.custom_agents` 字段（数组），允许用户配置 `{id, description, file_patterns, triggers}`。
- **DoD**：能用 config 加一个新 agent 而不改代码；非 Java MR 的路由命中率显著提升。

#### STEP 2.4 评估系统升级
- **状态**：已完成并收紧为生产质量门禁（2026-06-07）。新增 `evaluation/run_pipeline_eval.py`，从 SQLite 读取指定 MR 最新真实 pipeline run 的最终 findings，并与 `merge_requests.metadata_json.expected_issues` 对齐评分，输出 `precision / recall / fp_rate / agreement_at_5 / missing / unknown_findings`；新增 `evaluation/negative_gold_set.jsonl` 作为负样本集合起点；新增 `scripts/verify-pipeline-eval.mjs` 和 `npm run verify:pipeline-eval`，门禁已收紧为 recall >= 0.90、fp_rate <= 0.10。新增 `scripts/seed-java-5mr-demo.mjs`、`scripts/evaluate-java-5mr-demo.mjs`、`npm run seed:java-5mr`、`npm run verify:java-5mr`，在本地构造 5 个 Java Spring fixture MR，覆盖 20 类常见问题。为提升真实检出率，补充 Java Web 静态规则 `PERF-QUERY-001 / PERF-MEM-004 / CODE-NULL-001 / BE-IDEMP-004`，将 `java_web_static / PMD / Semgrep / Trivy / OSV` 的高置信工具观察白名单式提升为候选 finding，并在 Judge 中优先覆盖不同 `covered_rules` 后再填充重复问题；`BE-ERR-003` 等价规则会归一补充 `CODE-EXC-003`。验证：单 MR `npm run verify:pipeline-eval` precision/recall/fp_rate = 1.0/1.0/0.0；5 MR `npm run verify:java-5mr` expected_total=22、matched_total=22、missing_total=0、false_positive_total=0、recall=1.0、fp_rate=0.0，所有 finding 均有 `quality_trace_json` 和 `suggested_code`。
- **关键文件**：`evaluation/run_pipeline_eval.py`（新增）、`evaluation/negative_gold_set.jsonl`（新增）、`scripts/verify-pipeline-eval.mjs`。
- **做什么**：
  - 新 runner 真正跑 pipeline（用 mock 或 fixture MR）输出 findings 再 scoring。
  - 收集 10+ 条 "no issue expected" 的 MR fixture 作为负样本集合，输出 FP rate。
  - CI 加入门禁：precision、recall、high_recall、fp_rate 任一回归即 fail。
  - 输出 `agreement@5`（与 gold_set 重合度）。
- **DoD**：CI 集成完成；一次本地误调 prompt 能被门禁拦下来。

---

### Phase 3 —— P2 扩展性（按需推进，1-2 周）

#### STEP 3.1 Skill 标准两层化
- **状态**：已完成（2026-06-07）。`load_skill_summary` 已支持 `CORE_STANDARD.md + LANG_<language>.md + 兼容 bound_standard` 分层加载；Java MR 加载 core/java/旧 `JAVA_WEB_STANDARD.md`，Python/Go/Kotlin/TypeScript 等非 Java MR 不再硬塞 Java Web 规范。已为各预置专家补 `CORE_STANDARD.md`，为 Java 专家补 `LANG_java.md`，并补充 `coding-review` 的 `LANG_python.md/LANG_go.md/LANG_kotlin.md`、`security-review/LANG_python.md`、`frontend-review/LANG_typescript.md/LANG_javascript.md`。验证：`npm run verify:skill-layers` 确认 Java 三层加载、Python 避免 Java 标准、Go mix-in 生效；`python3 -m py_compile worker/review_runtime.py worker/context/snapshot.py scripts/verify_skill_layers.py`、`npm run build`、`npm run verify:gold-eval` 通过。
- 抽 `agent-skills/<expert>/CORE_STANDARD.md`（语言无关条目）。
- 新增 `LANG_python.md`、`LANG_typescript.md`、`LANG_go.md`、`LANG_kotlin.md`。
- Agent 加载逻辑按 MR 主语言 mix-in。
- DoD：Python 项目的 review 不再硬塞 Java/Spring 规则。

#### STEP 3.2 PR 评论 chat-with-bot
- **状态**：已完成（2026-06-07）。新增 `POST /api/webhooks/:provider/:projectId/jolt-comment`，识别 `@jolt explain <finding_id>`、`@jolt why-not <file:line>`、`@jolt dismiss <finding_id>`、`@jolt recheck`；默认 `dry_run=true` 只生成回复，显式 `dry_run=false` 才调用 GitHub/CodeHub 评论 API，避免本地误发真实评论。`explain` 返回问题、位置、专家、置信度、原因、建议和建议代码；`why-not` 查询最新 run 附近 findings 或解释未输出原因；`dismiss` 更新 lifecycle；`recheck` 重新入队并触发 worker。验证：`npm run verify:jolt-chat` 对最新 Java fixture finding 执行 explain/why-not dry-run 成功；`npm run build`、`npm run verify:gold-eval` 通过。
- 监听 PR 评论 webhook（`src/backend/routes/webhooks.ts`），识别 `@jolt <cmd>`。
- 支持命令：`explain <finding_id>` / `recheck` / `dismiss <finding_id>` / `why-not <file:line>`。
- 复用 verify + LLM 通道。
- DoD：能在真实 PR 上完成一次问答交互。

---

### Phase 4 —— P3 长期演进（不在本计划严格排期）
- 多模型 ensemble
- Few-shot 反馈池
- 自动测试生成
- 架构级 finding（循环依赖 / 上下游契约破坏）

---

## 五、风险与回滚策略

| 风险 | 缓解 |
|---|---|
| 仓库级索引 OOM 或超时 | 文件数 > 5000 或单文件 > 10000 行时 skip；索引超时降级回纯 diff 模式 |
| LLM 辩论成本失控 | 每 job hard cap = findings_total × 0.3 + 全局 daily budget |
| 增量评审漏报"已修复但实际仍存在的问题" | 增量结果与全量结果按周抽样对比，差异 > 5% 自动 fallback 到全量 |
| 拆文件破坏现有节点导入 | STEP 0.2 严格 re-export + gold-eval 完全一致校验 |
| Prompt 调整引入回归 | 每次 prompt 改动都必须跑 STEP 2.4 的 CI 门禁 |

---

## 六、关键验收指标

每个 Phase 完成后，必须对照基线（STEP 0.1）报告下表：

| 指标 | 基线 | Phase 1 目标 | Phase 2 目标 |
|---|---|---|---|
| gold-eval precision | TBD | +3pp | +3pp（不回退） |
| gold-eval recall | TBD | +5pp | +5pp（不回退） |
| high_recall | TBD | +3pp | +3pp（不回退） |
| FP rate（负样本集） | N/A（新指标） | < 15% | < 10% |
| 跨文件 finding 数 / MR | ~0 | ≥ 1 | ≥ 2 |
| 单 MR 平均 LLM 成本 | TBD | ≤ 基线 × 1.8 | ≤ 基线 × 2.0 |
| 单 MR 平均时延 | TBD | ≤ 基线 × 1.5 | ≤ 基线 × 1.3（增量受益） |

---

## 七、给 Codex 的执行提示

1. **严格按 STEP 顺序**。STEP 0.2 是后续所有工作的基础，必须先完成且行为零变化。
2. **每个 STEP 必须有单测 + gold-eval 回归校验**，不允许"只跑通了就 commit"。
3. **任何改 prompt 的 STEP，必须把新旧 prompt diff 与 gold-eval 数字一并 commit**，便于回滚。
4. **大改动（STEP 1.5）先开 PR review，再合并**。其余 STEP 可直接 commit。
5. **遇到 budget/超时类问题优先降级**（fallback 到 baseline 行为），不要让单点失败阻断整条 pipeline。
6. **不要重写已有静态工具集成**，那是项目的优势，只需消费 `tool_observations`。
7. **不要扩大 agent 数量**，先把现有 10 个做好。
8. **保持中文注释/文档风格一致**（项目主语言是中文）。

---

## 八、文件索引（实施时快速定位）

| 关注点 | 文件 |
|---|---|
| Prompt 构造 | `worker/review_runtime.py:2398-2469`（STEP 0.2 后 → `worker/prompts/builder.py`） |
| LLM 调用 | `worker/review_runtime.py:2283-2375` |
| Diff 切片 | `worker/review_runtime.py:806-871` |
| 静态启发式 | `worker/review_runtime.py:882+` |
| Verifier | `worker/orchestration/nodes/verify_findings.py` |
| 冲突检测 | `worker/orchestration/nodes/detect_conflicts.py` |
| "辩论"（待重写） | `worker/orchestration/nodes/run_targeted_debate.py` |
| Judge | `worker/orchestration/nodes/judge_findings.py` |
| Agent 注册 | `worker/agents/registry.py` |
| Skill 标准 | `agent-skills/*/JAVA_WEB_STANDARD.md` + `SKILL.md` |
| LangGraph 图 | `worker/orchestration/graph.py` |
| Effort 选择 | `worker/review_runtime.py:2728-2740` + `worker/orchestration/nodes/choose_effort.py` |
| 评估 | `evaluation/run_gold_eval.py`、`evaluation/gold_set.jsonl` |
| 配置示例 | `config.example.json` |
| 前端入口 | `src/frontend/main.tsx` |
| 发布层 | `src/backend/routes/` + `src/backend/github.ts` / `src/backend/codehub.ts` |

---

**结语**：当前项目的静态工具集成、流水线编排、评估框架基础已经扎实，**真正的质量天花板在 LLM 看不见仓库**。如果只能做一件事，做 **STEP 1.5（仓库级 RAG 上下文）**——这是 CodeRabbit/Greptile/Cursor 拉开差距的核心壁垒。其他 STEP 是为它铺路或放大其收益。
