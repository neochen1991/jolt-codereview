# Codex 检视质量优化 · 第二轮待实施方案

> 上一轮 (`2026-06-17-codex-review-quality-optimization-plan.md`) 已完成 T01/T04/T11/T14 全量，T06/T10/T12 部分完成；T02/T03/T05/T07/T08/T09/T13/T15 未实施。
> 本轮聚焦：补齐高 ROI 的稳定性 + 安全 + 评测 + 维护性短板；不再扩散 judge_findings.py 中的硬编码逻辑。

## 0. 执行守则

1. **一次一个 Task**：按 F01→F12 顺序合入，每个 Task 一个 commit。
2. **commit message 格式**：`F0X: <一句话目标>`。
3. **每个 Task 完成后必须跑**自己列出的「验证命令」全通过；失败即回退，不靠静态检查掩盖。
4. **不允许扩散** `worker/orchestration/nodes/judge_findings.py` 内的硬编码规则白名单或中文关键词分支；新增检视逻辑一律走数据表或独立模块。
5. **F03、F08、F09 涉及 schema/配置/前端拆分，必须先发本地 dry-run，再提交**。

---

## Stage 1 · 模型层稳定性（F01 ~ F03）

### F01 — JSON Schema 结构化输出

- **目标**：让 LLM 直接返回结构化 JSON，消除字符串清洗解析的隐性失败。
- **涉及文件**
  - `worker/llm/client.py`：`call_llm`、`summarize_pr_with_llm`
  - `worker/orchestration/nodes/run_targeted_debate.py`
  - `worker/review_runtime.py`：`route_agents_with_llm`
  - 新增 `worker/llm/schemas.py`
- **改动要点**
  - 在 `schemas.py` 集中定义四个 JSON Schema：`FINDING_LIST_SCHEMA`（专家输出）、`PR_SUMMARY_SCHEMA`、`DEBATE_VERDICT_SCHEMA`、`ROUTER_AGENT_LIST_SCHEMA`。
  - 请求体追加 `"response_format": {"type": "json_schema", "json_schema": {"name": ..., "strict": True, "schema": ...}}`；保留对不支持的 provider 的优雅降级（捕获 4xx 含 `response_format` 字样后回退一次）。
  - 解析路径优先 `json.loads`，仅在 schema 不可用降级路径走原 `parse_llm_findings`。
  - 把 schema 不匹配纳入 `recorder.event(span_id, "llm_schema_violation", ...)`。
- **验证命令**
  - `node scripts/run-python.mjs worker/tests/test_llm_schema.py`（新增，校验 schema 注入 + 降级路径）
  - `npm run verify:gold-eval`
  - `npm run verify:real-prs`
- **验收**：上述命令绿；运行一次完整 review 后 `review_runs.budget_used_json` 中至少出现一次 `schema_strict=true`。

### F02 — Seed 与响应缓存

- **目标**：温度 0.1 不够稳定，加 seed + 内存 LRU + 持久化缓存表，降低重复 review 的发散。
- **涉及文件**
  - `worker/llm/client.py`：所有 chat completions 调用追加 `"seed": int(llm.get("seed") or 13)`。
  - 新增 `worker/llm/cache.py`：LRU(in-memory 256 条) + SQLite `llm_response_cache` 二级缓存；缓存 key = sha256(provider+model+prompt+temperature+seed+response_format_name)。
  - `src/backend/db/migrations.ts`、`worker/review_runtime.py::ensure_worker_schema`：建表
    ```sql
    CREATE TABLE IF NOT EXISTS llm_response_cache (
      cache_key TEXT PRIMARY KEY,
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      response_text TEXT NOT NULL,
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_llm_response_cache_created_at ON llm_response_cache(created_at);
    ```
  - 仅当 `llm.cache_enabled` 为真（默认 `true`，可在项目配置关）才命中。
  - `recorder.llm_call(..., status="completed_cached")` 标识命中；命中时 duration_ms 记 0。
- **验证命令**
  - `node scripts/run-python.mjs worker/tests/test_llm_cache.py`（新增）
  - 手动连跑同一 MR 两次 review：第二次专家阶段 LLM 调用数应 ≥ 80% 命中缓存。
- **验收**：同 MR 两次 review，第二次 `LLM Calls` 数 ≤ 第一次的 30%，最终 findings 集合相等（diff 为空）。

### F03 — Deepagents 落点决策

- **目标**：现状是「既不真用、又依赖 import」，必须二选一。
- **推荐方案**：删除路径。
- **涉及文件**
  - 删除 `worker/orchestration/deepagents_runner.py`
  - `worker/orchestration/nodes/run_experts.py`：移除对 `run_bounded_deepagent` 的调用与 `requires_deepagents` 路径
  - `src/backend/db/migrations.ts`：保留列但默认 0，不再迁移新值
  - `requirements.txt` / `pyproject.toml`：移除 `deepagents`、`langgraph` 依赖（确认其他模块未使用）
- **改动要点**
  - 删除前确认 `requires_deepagents=1` 的 agent_config 在生产为 0；删除后 fallback 走标准 expert 路径。
  - 同步删 `scripts/verify_deepagents_*.py`（如有）和文档段落。
- **验证命令**
  - `npm run verify:router-policy`（本地不再因 deepagents 缺失报错）
  - `npm run verify:gold-eval`
  - `rg deepagents worker src docs` 仅剩历史记录或注释
- **验收**：项目根 `pip install -r requirements.txt` 后 `python3 -c "import review_runtime"` 成功，无 deepagents 依赖。

---

## Stage 2 · 真评测与运营指标闭环（F04 ~ F05）

### F04 — 真开源 PR 评测集

- **目标**：替换 `evaluation/real_gold_set.jsonl` 中唯一的合成 MR，让 `verify:real-prs` 真正可信。
- **涉及文件**
  - `evaluation/real_gold_set.jsonl`
  - `evaluation/real_prs/README.md`
  - `evaluation/real_prs/<repo>-<pr>.json`（新增每个 PR 的元数据）
  - `scripts/seed-real-prs.mjs`（新增）—— 从 GitHub fetch PR diff 并 seed merge_request + review_job + review_run
- **改动要点**
  - 选 3 个真实历史已 merged 的 Java PR + 1 个 negative MR（已知 review 应无高严重度问题）：
    - 例：`spring-projects/spring-framework#XXXXX` 中 SEC-INJECT 类修复
    - `apache/dubbo` 一处 perf 修复
    - `apache/shiro` 一处 SEC-AUTHN 修复
    - negative：一处纯文档 / 纯重命名 PR
  - 每个 PR 在 README 标注：source URL、commit SHA、人工标注 gold rule_id 数组。
  - `scripts/seed-real-prs.mjs`：读取 `evaluation/real_prs/*.json`，调 GitHub API 拉 patch、insert 到本地 SQLite 的 `merge_requests`/`review_jobs`，便于本地与 CI 跑 `verify:real-prs` 前用 `npm run seed:real-prs && <跑一次 review>`。
  - `scripts/score_real_pr_reviews.py`：min-recall 维持 0.6、min-precision 提到 0.75（数据更多了应该可以收紧）；negative MR FP 维持 0。
- **验证命令**
  - `npm run seed:real-prs`
  - 跑完 review 后 `npm run verify:real-prs`
- **验收**：gold set 至少 4 个 MR、≥ 25 条 gold finding；report 中 precision ≥ 0.75、recall ≥ 0.6、negative_false_positive_count = 0。

### F05 — 反馈窗口真正滚动

- **目标**：`recent_accepted_count/recent_rejected_count` 当前等价 lifetime，要变成真 90 天窗口。
- **涉及文件**
  - 新增表 `user_feedback_events`（如果 `user_feedback` 已有 `created_at` 可复用）
  - `src/backend/services/FeedbackLearningService.ts`：写反馈时同时插入 event 行，且不再直接 `+1` 到 `recent_*` 列
  - 新增 `worker/maintenance/recalc_recent_precision.py`：每日重算 `rule_precision_history.recent_*`（窗口 90 天）
  - 新增 `scripts/maintenance/recalc-recent-precision.mjs`：node 入口，可被 cron / 部署平台调度
  - `docs/nfr-and-slo.md` §10 加一行运维要求
- **改动要点**
  - SQL：
    ```sql
    UPDATE rule_precision_history SET recent_accepted_count = 0, recent_rejected_count = 0;
    -- 然后按 (project_id, agent_id, rule_id) 聚合最近 90 天 user_feedback 写回
    ```
  - 写反馈服务保留 `accepted_count/rejected_count` 自增（lifetime）；recent 不在写路径累加。
  - 后台任务首跑写一条 `observability` 事件，便于运维确认 cron 落点。
- **验证命令**
  - `node scripts/run-python.mjs worker/tests/test_recalc_recent_precision.py`（新增 + 模拟 100/200 天前的反馈，仅 90 天内进窗口）
  - `node scripts/maintenance/recalc-recent-precision.mjs --dry-run` 输出预期 diff
- **验收**：手动注入 31 天前 + 95 天前两条反馈，跑 recalc 后只有 31 天那条计入 `recent_*`。

---

## Stage 3 · 安全治理（F06 ~ F07）

### F06 — 移除配置明文 default_api_key

- **目标**：彻底关掉「示例文件 / DB / 内存」中存在明文 LLM key 的路径。
- **涉及文件**
  - `config.example.json`：删除 `llm.default_api_key`，改为说明文档
  - `src/backend/services/LlmConnectivityService.ts`：移除对 `default_api_key` 的读取
  - `src/backend/services/SettingsService.ts`（或同等位置）：禁止在 settings update 中接受 `default_api_key` 字段
  - `worker/llm_router.py`：candidate_providers 必须从环境变量读 key，缺失则该 provider 不参与选举
- **改动要点**
  - 兼容性：保留对历史 db row 的 best-effort 读取，但启动时如发现历史明文，写入 `audit.log` 并屏蔽，不再下发到 LLM 调用。
  - 文档更新：`docs/security.md` 加一段「密钥仅来源于 env 或 secret manager」。
- **验证命令**
  - `npm run typecheck`
  - `rg "default_api_key" config.example.json src` 仅剩注释或 audit
  - 启动 server，访问 `/api/admin/llm/connectivity`，未配置 env 的 provider 必须报 `missing_env_api_key`
- **验收**：示例配置不含密钥；前后端任意路径都拒绝从 DB 取 key 调用 LLM。

### F07 — 提示词注入与脱敏审计

- **目标**：现状 `redact_untrusted` 只覆盖三种 pattern；新增 IPv4、JWT、AWS-AK、阿里云 AK 等 + 注入字典扩展。
- **涉及文件**
  - `worker/prompts/builder.py`：扩 patterns 与 injection markers
  - 新增 `worker/tests/test_redact_untrusted.py`
- **改动要点**
  - 新增 patterns：`AKID/SK`、`AKIA[0-9A-Z]{16}`、`eyJ[\w-]+\.[\w-]+\.[\w-]+`（JWT）、`(?:\d{1,3}\.){3}\d{1,3}`（IPv4，命中 RFC1918 不脱敏）
  - 注入 markers 扩：`</system>`, `</user>`, `assistant:`, `tool_call`, `function_calls`
- **验证命令**
  - `node scripts/run-python.mjs worker/tests/test_redact_untrusted.py`
- **验收**：单测覆盖 8 类 pattern，命中后 `safety["redactions"]` 列出 label。

---

## Stage 4 · 维护性减负（F08 ~ F10）

### F08 — 拆分 `judge_findings.py`

- **目标**：3700+ 行单文件已超出可读边界；按职责切到 `worker/orchestration/judging/` 子包。
- **涉及文件（新增）**
  - `worker/orchestration/judging/__init__.py`（导出公开 API）
  - `worker/orchestration/judging/rules.py`：RULE_REMEDIATION、`*_RULE_IDS`、`TOOL_COVERAGE_FILL_RULES`、`PROMOTABLE_TOOL_RULES` 等常量与小工具
  - `worker/orchestration/judging/signatures.py`：`_root_cause_signature`、`_semantic_dedupe_key`、`_dedupe_key`
  - `worker/orchestration/judging/advisory_filters.py`：`_is_low_precision_unbacked_advisory`、`_prune_low_signal_final_findings`、`_is_strong_tool_supported_finding`
  - `worker/orchestration/judging/promotion.py`：`promote_tool_observations`、`supplement_bound_rule_findings`、`_fill_missing_tool_coverage`
  - `worker/orchestration/judging/judging.py`：`judge_candidate_findings`、`reconcile_rules_with_tool_observations`
  - `worker/orchestration/judging/node.py`：`make_judge_findings_node`
- **改动要点**
  - 原 `worker/orchestration/nodes/judge_findings.py` 仅保留兼容 import：
    ```py
    from orchestration.judging import (
        judge_candidate_findings,
        make_judge_findings_node,
        promote_tool_observations,
        # ...
    )
    ```
  - 拆分过程**不改行为**；通过现有测试 + 新增 F09 测试守护。
- **验证命令**
  - `node scripts/run-python.mjs worker/tests/test_judge_strong_tool_evidence.py`
  - `node scripts/run-python.mjs scripts/verify_worker_orchestration_nodes.py`
  - `npm run verify:real-prs`、`npm run verify:gold-eval`
  - `wc -l worker/orchestration/judging/*.py` 单文件 ≤ 800 行
- **验收**：上述命令绿；最大子模块 < 800 行；兼容 import 路径不变。

### F09 — Judge 单测铺开

- **目标**：T06 留下的覆盖坑补齐；锁定 F08 拆分行为，并防止未来回归。
- **涉及文件**
  - `worker/tests/test_judge_signatures.py`（新）：覆盖 `_root_cause_signature` 在 8 种业务模式（审计、状态机、SQL 拼接、TTL、KEYS、未授权、明文 secret、DDL drop）下的稳定分桶
  - `worker/tests/test_judge_promotion.py`（新）：覆盖 `promote_tool_observations` 的 (file, line±3, rule) 去重 + `_fill_missing_tool_coverage` 兜底
  - `worker/tests/test_judge_reconcile.py`（新）：覆盖 `reconcile_rules_with_tool_observations` 在 LLM 自由叠 rule 时按源观察反推
- **验证命令**
  - 三个测试逐个 `python3 worker/tests/test_judge_*.py` 直跑
- **验收**：3 个测试文件累计 ≥ 25 个 case；任一改动 judging 子包行为后必须先改测试或回滚。

### F10 — 拆分 `process_mr_one` 与 `route_agents`

- **目标**：`worker/review_runtime.py` 单文件 4200+ 行，`process_mr_one` 一个 375 行函数把 12 节点编排压成命令式。
- **涉及文件**
  - 新增 `worker/orchestration/pipeline/process_mr.py`：把 `process_mr_one` 切成 5 个有命名的步骤函数（prepare/route/run/judge/finalize），主函数只做顺序串联和异常归一化。
  - `worker/review_runtime.py`：保留薄壳调用 `pipeline.process_mr.run(...)`。
  - 不动 LangGraph 节点编排，只重构命令式入口。
- **验证命令**
  - `npm run verify:gold-eval` 全通
  - `npm run verify:real-prs` 全通
  - `npm run verify:incremental-history`
- **验收**：`process_mr_one` 主函数 ≤ 80 行；新文件单函数最长 ≤ 120 行；行为零变化（gold-eval/real-prs 指标不变）。

---

## Stage 5 · 前端与小修补（F11 ~ F12）

### F11 — 拆 `src/frontend/main.tsx`

- **目标**：单文件 7048 行无法维护；按页面拆。
- **涉及文件（新增）**
  - `src/frontend/pages/Dashboard.tsx`
  - `src/frontend/pages/ProjectDetail.tsx`
  - `src/frontend/pages/AgentBindings.tsx`
  - `src/frontend/pages/ReviewRun.tsx`
  - `src/frontend/pages/Observability.tsx`
  - `src/frontend/router.tsx`
  - `src/frontend/components/`（抽公共 panel/list/dialog）
- **改动要点**
  - `main.tsx` 只负责 mount + router；其他 import 自页面。
  - 首屏路由 lazy load，初始 bundle 体积下降。
  - 不改样式、不改 API；保留所有 props 行为。
- **验证命令**
  - `npm run typecheck && npm run build`
  - 手动 `npm run dev` 把所有页面点一遍（dashboard / project / agent / run / observability）
- **验收**：`main.tsx` ≤ 200 行；每个页面文件 ≤ 1500 行；首屏 JS 体积下降 ≥ 30%。

### F12 — Verifier 符号证据评分（原 T09）

- **目标**：当前 verifier 仅按行号匹配；引入 `related_context.changed_symbols` 做加分，提高对「跨文件影响」类问题的接纳。
- **涉及文件**
  - `worker/orchestration/nodes/verify_findings.py`
  - 新增 `worker/tests/test_verifier_symbol_evidence.py`
- **改动要点**
  - 新增 `_symbol_evidence_score(finding, related_context) -> float`：当 `finding.file_path` 命中 `changed_symbols`/`modified_symbols`/`related_tests` 且 line 在 ±5 行内时 +0.1 ~ +0.2 confidence。
  - 评分提升只用于「现在被 verifier 误杀的高置信 finding」恢复路径，不允许把低置信 finding 拉过门槛。
- **验证命令**
  - `node scripts/run-python.mjs worker/tests/test_verifier_symbol_evidence.py`
  - `npm run verify:real-prs` precision/recall 不下降
- **验收**：单测覆盖「命中 changed_symbols 加分」「未命中不加分」「低置信不拉过门槛」三类。

---

## 依赖与并行度

```
F01 ─┐
F02 ─┼─> F04  ─> F05 (运营)
F03 ─┘            │
                  ▼
F06, F07 (安全, 可与上面并行)

F08 ─> F09 ─> F10 ─> F12  (维护性 + verifier 强化)

F11 (前端独立)
```

- **可并行流**：{F01, F02, F03}、{F06, F07}、{F11}、{F08→F09→F10→F12}。
- **关键路径**：F01 → F04 → F05（评测和反馈闭环），约 4 个 commit。

---

## 风险与回滚

| 任务 | 主要风险 | 回滚策略 |
|---|---|---|
| F01 | provider 不支持 strict json_schema → 拉低成功率 | 捕获 4xx 后自动降级走旧解析；env `LLM_DISABLE_JSON_SCHEMA=1` 全局关 |
| F02 | 缓存命中污染（schema 变更后用旧响应） | cache_key 包含 schema name；`llm_response_cache` 7 日过期可手动 `DELETE` 清空 |
| F03 | 误删 deepagents 路径导致历史 agent_config 失效 | 删除前 SQL 巡检 `requires_deepagents=1` 数；保留兼容 import 一个 release |
| F04 | 真 PR 评测分数波动大 | min-precision/recall 在 first run 后按实际值 -0.05 起步，逐周收紧 |
| F05 | 90 天窗口重算误杀历史抑制 | 重算前快照 `rule_precision_history` 到 `_backup_*` 表 |
| F06 | 删 config 后历史部署启动失败 | 启动期对历史 row 走只读屏蔽 + 告警，不直接报错退出 |
| F08 | 拆分行为漂移 | 必须在 F09 测试就位后合入；先合 F09 一个 PR、再合 F08 |
| F10 | 命令式重构破坏报错路径 | 用 `verify:gold-eval` + 一次手动 sad-path（kill provider）覆盖 |
| F11 | 前端路由切换导致权限/守卫漏接 | router 层补 e2e 截图（`scripts/verify-observability.mjs` 风格的 puppeteer 巡检） |
| F12 | 误把低置信 finding 拉过 verifier | 单测三类 case + real-prs precision 不下降 |

---

## 完成标准

- F01 ~ F12 全部 commit 入库，且对应 verify 命令全部绿。
- `npm run verify:real-prs` 在 ≥ 4 个真实 PR 上 precision ≥ 0.75、recall ≥ 0.6、negative_false_positive_count = 0。
- `npm run verify:gold-eval` 不下降。
- `worker/orchestration/nodes/judge_findings.py` ≤ 50 行（仅兼容 re-export）。
- `worker/orchestration/judging/*.py` 单文件 ≤ 800 行。
- `src/frontend/main.tsx` ≤ 200 行；每页面文件 ≤ 1500 行。
- `config.example.json` 无明文密钥；`/api/admin/llm/connectivity` 缺 env 时报 `missing_env_api_key`。
- `rule_precision_history.recent_*` 由 cron 重算驱动，写路径不再直接累加。

---

## 与第一轮的差异

| 维度 | 第一轮 (06-17 v1) | 本轮 (06-17 v2) |
|---|---|---|
| LLM 工程 | T01 重试、T04 token/超时 | F01 JSON Schema、F02 seed+cache、F03 deepagents 退场 |
| 评测 | T10 真 PR 评测脚手架 | F04 真 PR 数据集、F05 反馈窗口真滚动 |
| 安全 | T13 移除 default_api_key（未做） | F06 落实 + F07 脱敏扩面 |
| 维护性 | T05 judge 拆分（未做）、T08 pipeline 拆分（未做）、T15 前端拆分（未做） | F08 → F09 → F10、F11 |
| Verifier | T09 符号证据（未做） | F12 补齐 |

本轮所有任务都是「上一轮未完成」或「上一轮埋的债」，没有重复已完成项；按 F01→F12 顺序合入即可在 2 周内完成。
