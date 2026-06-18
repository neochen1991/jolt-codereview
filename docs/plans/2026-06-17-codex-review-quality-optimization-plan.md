# Jolt CodeReview 检视质量优化执行方案（Codex 可执行版）

- 创建日期：2026-06-17
- 目标读者：Codex Agent（自主执行）/ 工程师（按任务领取）
- 执行前提：已能本地跑通 `npm run verify:local`、`npm run verify:gold-eval`、`npm run verify:java-5mr`
- 总体目标：把"检视质量"从"自产自销 fixture 上的 1.0/1.0"推进到"真实 PR 上 precision ≥ 0.7、recall ≥ 0.6、并具备可回归单元测试"。

任务彼此独立编号（T01–T15），按依赖关系排序。每个任务包含：**目标 / 涉及文件 / 改动要点 / 验证 / 验收**。Codex 一次领取一个任务，完成后跑验证命令再提交。

---

## 阶段总览

| 阶段 | 任务 | 预期收益 |
|---|---|---|
| Stage 1 LLM 工程化 | T01–T04 | 调用确定性、结构化输出、可重试可缓存 |
| Stage 2 Judge 拆分与测试 | T05–T08 | 单元测试覆盖、可维护性 |
| Stage 3 Verifier 与评估集 | T09–T10 | 真实 PR 评估、证据匹配升级 |
| Stage 4 架构简化 | T11–T13 | 路由简化、DeepAgents 决策、process_mr_one 拆分 |
| Stage 5 运维与前端 | T14–T15 | 配置治理、前端拆分 |

---

## Stage 1：LLM 调用工程化

### T01 · LLM 调用增加重试与退避

**目标**：消除 429/5xx 抖动导致的 provider 链路提前耗尽。

**涉及文件**
- `worker/llm/client.py`
- `worker/orchestration/deepagents_runner.py`
- `worker/orchestration/nodes/run_targeted_debate.py`

**改动要点**
1. 新增 `worker/llm/retry.py`：
   ```python
   import time
   import urllib.error
   RETRYABLE = (urllib.error.HTTPError, TimeoutError, ConnectionError)
   def is_retryable(exc: Exception) -> bool:
       if isinstance(exc, urllib.error.HTTPError):
           return exc.code in (408, 409, 425, 429, 500, 502, 503, 504)
       return isinstance(exc, RETRYABLE)
   def call_with_retry(fn, *, max_retries=2, backoff=(1.0, 3.0, 8.0)):
       last = None
       for attempt in range(max_retries + 1):
           try:
               return fn()
           except Exception as exc:
               last = exc
               if attempt == max_retries or not is_retryable(exc):
                   raise
               time.sleep(backoff[attempt])
       raise last
   ```
2. `call_llm`、`summarize_pr_with_llm`、`route_agents_with_llm`、debate 的 `http_json(...)` 调用包一层 `call_with_retry`。
3. failover 逻辑保留：单 provider 内重试 2 次失败后再切下一个 provider。

**验证**
```bash
npm run build:api
node scripts/run-python.mjs scripts/verify_debate_llm_node.py
node scripts/run-python.mjs scripts/verify_router_llm.py
node scripts/run-python.mjs scripts/verify_pr_summary_node.py
```

**验收**
- 所有 verify 脚本通过；
- `worker/tests/test_llm_retry.py` 新增覆盖 429 重试成功 / 重试耗尽抛原异常两条用例。

---

### T02 · LLM 结构化输出（response_format=json_schema）

**目标**：消除 `content.find("[")` 与 `_extract_json_objects` 脆弱解析。

**涉及文件**
- `worker/llm/client.py`：`parse_llm_findings`、`call_llm`、`summarize_pr_with_llm`
- `worker/llm_router.py`：`route_agents_with_llm`
- `worker/orchestration/nodes/run_targeted_debate.py`

**改动要点**
1. 在 `call_llm` 的 `payload` 增加：
   ```python
   payload["response_format"] = {
       "type": "json_schema",
       "json_schema": {
           "name": "findings_array",
           "strict": False,
           "schema": {
               "type": "object",
               "properties": {
                   "findings": {
                       "type": "array",
                       "items": {
                           "type": "object",
                           "properties": {
                               "severity": {"type": "string"},
                               "confidence": {"type": "number"},
                               "file_path": {"type": "string"},
                               "line_start": {"type": "integer"},
                               "line_end": {"type": "integer"},
                               "title": {"type": "string"},
                               "problem_description": {"type": "string"},
                               "recommendation": {"type": "string"},
                               "suggested_code": {"type": "string"},
                               "evidence": {"type": "string"},
                               "covered_rules": {"type": "array", "items": {"type": "string"}},
                               "skipped_rules": {"type": "array", "items": {"type": "string"}}
                           },
                           "required": ["severity", "confidence", "file_path", "line_start", "title", "evidence"]
                       }
                   }
               },
               "required": ["findings"]
           }
       }
   }
   ```
2. 调用方读取 `data["choices"][0]["message"]["content"]` 仍为字符串，但应解析为 `{"findings": [...]}`；保留旧解析作为兜底（仅当 provider 不支持 json_schema 时）。
3. `summarize_pr_with_llm` 用 `response_format={"type":"json_object"}` 强制 JSON 对象。
4. `route_agents_with_llm` 与 debate 同理。
5. 新增 `worker/llm/capabilities.py` 记录每个 provider 是否支持 `json_schema`，从 `llm_router.PROVIDER_CAPS` 扩展 `supports_json_schema` 字段；不支持时回退 `temperature=0` + 旧解析。

**验证**
```bash
node scripts/run-python.mjs scripts/verify_router_llm.py
node scripts/run-python.mjs scripts/verify_debate_llm_node.py
node scripts/run-python.mjs scripts/verify_pr_summary_node.py
npm run verify:gold-eval
```

**验收**
- gold-eval precision/recall 不低于改造前；
- 新增 `worker/tests/test_parse_llm_findings_schema.py`：mock 返回 `{"findings":[...]}` 与纯数组两种响应均能解析。

---

### T03 · LLM 结果缓存与确定性 seed

**目标**：同一 `(agent_id, head_sha, prompt_hash)` 二次触发不重烧 token；同一 MR 可复跑。

**涉及文件**
- `worker/llm/client.py`
- `src/backend/db/migrations.ts`（新增 `llm_response_cache` 表）

**改动要点**
1. 新建表：
   ```sql
   CREATE TABLE IF NOT EXISTS llm_response_cache (
     id TEXT PRIMARY KEY,
     cache_key TEXT UNIQUE NOT NULL,
     provider TEXT NOT NULL,
     model TEXT NOT NULL,
     prompt_hash TEXT NOT NULL,
     response_text TEXT NOT NULL,
     input_tokens INTEGER DEFAULT 0,
     output_tokens INTEGER DEFAULT 0,
     created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
     expires_at TEXT
   );
   CREATE INDEX IF NOT EXISTS idx_llm_cache_key ON llm_response_cache(cache_key);
   ```
2. `call_llm` 在调用前计算 `cache_key = sha1(provider|model|system|prompt|temperature|seed)`，查表命中直接返回（仍记 `llm_call_records` 但 status=`cache_hit`，input_tokens=0）。
3. payload 增加 `seed = 13` 固定值（对支持 seed 的 provider）；`temperature` 由 0.1 降到 0.0（结构化输出场景）。
4. 缓存 TTL 默认 7 天，由 `config.llm.cache_ttl_days` 控制；项目级开关 `config.llm.enable_response_cache` 默认 true。
5. 缓存仅对 `call_llm`（专家检视）启用；`summarize_pr_with_llm`、router、debate 不缓存（依赖上下文动态）。

**验证**
```bash
npm run build:api
node scripts/run-python.mjs scripts/verify_budget_policy.py
npm run verify:gold-eval   # 第二次跑应出现 cache_hit 记录
```

**验收**
- 第二次跑同一 fixture，`llm_call_records` 中出现 `status='cache_hit'` 记录且 `input_tokens=0`；
- `verify:budget-policy` 通过；
- `worker/tests/test_llm_cache.py` 覆盖命中 / 过期 / 禁用三条路径。

---

### T04 · token 估算与超时治理

**目标**：预算判断更准；超时分级。

**涉及文件**
- `worker/llm/client.py`
- `worker/orchestration/deepagents_runner.py`
- `worker/budget.py`

**改动要点**
1. 新增 `estimate_tokens(text)`：中文按 1 字 ≈ 0.6 token，英文按 4 字符 ≈ 1 token。
   ```python
   def estimate_tokens(text: str) -> int:
       cjk = sum(1 for c in text if '一' <= c <= '鿿')
       non_cjk = len(text) - cjk
       return int(cjk * 0.6 + non_cjk / 4) + 1
   ```
2. 替换所有 `len(prompt) // 4` 为 `estimate_tokens(prompt)`。
3. 超时分级：router/debate/summary 用 60s，专家 `call_llm` 用 120s，`deepagents_runner` 用 240s。从 `config.llm.timeouts` 读取覆盖默认值。
4. `BudgetTracker.charge_llm` 累加 input/output tokens 到 `acc_input_tokens`、`acc_output_tokens`，加入 `snapshot()`。

**验证**
```bash
node scripts/run-python.mjs scripts/verify_budget_policy.py
node scripts/run-python.mjs scripts/verify_router_llm.py
```

**验收**
- `BudgetTracker.snapshot()` 包含 `acc_input_tokens` / `acc_output_tokens`；
- 预算测试通过。

---

## Stage 2：Judge 拆分与单元测试

### T05 · 拆分 `judge_findings.py`

**目标**：3488 行单文件拆为职责清晰的子模块，便于测试与维护。

**涉及文件（新建）**
- `worker/orchestration/judging/__init__.py`
- `worker/orchestration/judging/remediation_templates.py`
- `worker/orchestration/judging/deduplication.py`
- `worker/orchestration/judging/diff_anchoring.py`
- `worker/orchestration/judging/selection.py`
- `worker/orchestration/judging/tool_promotion.py`
- `worker/orchestration/judging/bound_rule_supplement.py`
- `worker/orchestration/judging/evidence_contract.py`
- `worker/orchestration/judging/judge_node.py`

**改动要点**
按职责迁移现有函数（保留函数名与签名，仅移动位置）：

| 新模块 | 迁入函数（来自 `judge_findings.py`） |
|---|---|
| `remediation_templates` | `RULE_REMEDIATION`、`PROMOTABLE_TOOL_RULES`、`PROMOTABLE_EXTERNAL_TOOL_RULES`、`OSS_TOOL_PROMOTION_THRESHOLDS`、`ensure_actionable_suggested_code`、`_is_placeholder_suggested_code`、`dependency_suggested_code_from_observation`、`remediation_for_observation` |
| `deduplication` | `_rule_key`、`_primary_rule_key`、`_dedupe_key`、`_semantic_category_group`、`_text_blob`、`_root_cause_signature`、`_business_subcategory`、`_semantic_dedupe_key`、`_typed_issue_signature`、`_merge_finding_metadata`、`_line_overlap_or_same`、`_token_set`、`_title_similarity`、`_same_line_same_issue`、`dedupe_same_line_same_issue_findings` |
| `diff_anchoring` | `_added_line_index`、`_added_line_text_index`、`_nearest_added_line`、`_best_semantic_added_line`、`_significant_tokens`、`_can_reanchor_to_added_line`、`_diff_anchor_result`、`filter_to_diff_introduced_findings`、`filter_tool_observations_to_added_lines` |
| `selection` | `_category_for_priority`、`_path_relevance_score`、`_auxiliary_penalty`、`_category_impact_score`、`_is_core_impact_finding`、`_is_secondary_advisory_finding`、`_is_weak_unbacked_ddd_design_finding`、`_has_domain_layer_context`、`_is_low_precision_layer_finding`、`_is_low_precision_ddd_context_finding`、`_is_low_precision_unbacked_advisory`、`_is_auxiliary_finding`、`_selection_threshold_for_finding`、`_evidence_specificity_score`、`_priority_sort_key`、`_is_tool_backed_finding`、`_has_exact_promoted_tool_rule`、`_preserve_static_tool_finding`、`_selection_category_key`、`_normalize_for_judging`、`_select_with_category_coverage`、`_line_proximity_key`、`_near_selected_core_finding`、`_drop_auxiliary_overlaps`、`_fill_after_auxiliary_drop`、`_prune_low_signal_final_findings`、`_stable_sort_key` |
| `tool_promotion` | `_drop_without_tool_support`、`_canonical_tool_rule_id`、`_promotable_tool_observation`、`_tool_candidate_hash`、`_tool_observation_group_key`、`_severity_rank_value`、`_best_tool_observation`、`_format_observation_evidence`、`promote_tool_observations` |
| `bound_rule_supplement` | `_bound_rule_text`、`_bound_rule_title`、`_bound_rule_severity`、`_bound_rule_fix_guidance`、`_existing_covered_rule_ids`、`_changed_file_added_lines`、`_snippet`、`_resource_type_pattern`、`_rule_mentions_unclosed_resource`、`_resource_line_has_owner_close`、`_supplement_resource_rule`、`_rule_mentions_collection_mutation`、`_supplement_collection_mutation_rule`、`_code_anchor_tokens`、`_has_specific_code_anchor_match`、`_supplement_exact_anchor_rule`、`supplement_bound_rule_findings` |
| `evidence_contract` | `apply_debate_verdicts`、`_rule_categories_for_finding`、`_observation_trace_item`、`match_tool_observations_for_finding`、`reconcile_rules_with_tool_observations`、`_best_source_observation_for_rule`、`_has_code_null_signal`、`align_finding_with_tool_observations`、`_has_text`、`build_evidence_contract`、`build_quality_trace`、`is_publishable_evidence_contract`、`_tool_provenance`、`_mark_observations_adopted`、`_mark_observation_state`、`_mark_promoted_rejection_sources` |
| `judge_node` | `judge_candidate_findings`、`make_judge_findings_node`、`AGENT_BY_RULE`、`AGENT_BY_RULE_PREFIX`、`SEVERITY_RANK`、`SELECTABLE_SEVERITIES` |

迁移后 `worker/orchestration/nodes/judge_findings.py` 仅作为 re-export shim：
```python
from orchestration.judging.judge_node import judge_candidate_findings, make_judge_findings_node  # noqa: F401
```

**验证**
```bash
npm run build:api
node scripts/run-python.mjs scripts/verify_judge_quality_improvements.py
node scripts/run-python.mjs scripts/verify_quality_evidence_contract.py
node scripts/run-python.mjs scripts/verify_quality_rule_registry.py
node scripts/run-python.mjs scripts/verify_quality_symbol_context.py
npm run verify:java-5mr
```

**验收**
- 所有现有 verify 脚本通过；
- `judge_findings.py` < 50 行；
- `grep -rn "from orchestration.nodes.judge_findings import" worker/ scripts/` 仍可用（shim 生效）。

---

### T06 · Judge 子模块单元测试

**目标**：补齐 judging 模块测试覆盖。

**涉及文件（新建）**
- `worker/tests/__init__.py`
- `worker/tests/test_deduplication.py`
- `worker/tests/test_diff_anchoring.py`
- `worker/tests/test_selection.py`
- `worker/tests/test_tool_promotion.py`
- `worker/tests/test_bound_rule_supplement.py`

**改动要点**
每个测试文件覆盖至少以下用例（具体断言由实现决定）：

`test_deduplication.py`：
- `_semantic_dedupe_key` 同位置不同 severity 视为同 key；
- `_root_cause_signature` 对 Redis KEYS / SQL 注入 / FastJSON CVE 等典型签名能识别；
- `dedupe_same_line_same_issue_findings` 同行同问题保留 priority 最高者。

`test_diff_anchoring.py`：
- `_nearest_added_line` 容差 5 内锚定；
- `_can_reanchor_to_added_line` 拒绝跨函数漂移；
- `filter_tool_observations_to_added_lines` 保留 diff 内观察、剔除 diff 外。

`test_selection.py`：
- `_select_with_category_coverage` 在 max_findings=10 下保持至少 5 个不同 category；
- `_drop_auxiliary_overlaps` 同位置只保留 core；
- `_priority_sort_key` 工具 backed 优先于无工具。

`test_tool_promotion.py`：
- `promote_tool_observations` 只 promote 白名单规则；
- 不在 `selected_agent_ids` 内的观察被拒。

`test_bound_rule_supplement.py`：
- `_supplement_resource_rule` 在未关闭 JDBC 资源行补充 finding；
- `_supplement_exact_anchor_rule` 在 anchor token 命中时补充。

**验证**
```bash
node scripts/run-python.mjs -m pytest worker/tests/ -v
```

**验收**
- 全部新测试通过；
- `worker/tests/` 至少 6 个测试文件，覆盖 judging 主要决策路径。

---

### T07 · `_root_cause_signature` 抽离业务签名到配置

**目标**：消除中文关键词硬编码，支持项目级扩展。

**涉及文件**
- `worker/orchestration/judging/deduplication.py`
- `worker/rules/signature_catalog.py`（新建）
- `src/backend/db/migrations.ts`（新增 `project_signature_catalog` 表）

**改动要点**
1. 新建表：
   ```sql
   CREATE TABLE IF NOT EXISTS project_signature_catalog (
     id TEXT PRIMARY KEY,
     project_id TEXT NOT NULL,
     signature_key TEXT NOT NULL,
     display_name TEXT NOT NULL,
     keyword_any TEXT NOT NULL,        -- JSON array, 任一命中
     keyword_all TEXT,                  -- JSON array, 全部命中
     path_suffix TEXT,                  -- 可选，文件路径后缀过滤
     enabled INTEGER NOT NULL DEFAULT 1,
     created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
     UNIQUE(project_id, signature_key)
   );
   ```
2. `worker/rules/signature_catalog.py`：
   ```python
   @dataclass(frozen=True)
   class SignatureRule:
       signature_key: str
       keyword_any: tuple[str, ...]
       keyword_all: tuple[str, ...]
       path_suffix: str | None

   def load_signatures(conn, project_id: str) -> list[SignatureRule]: ...
   def match_signature(text: str, path: str, rules: list[SignatureRule]) -> str | None: ...
   ```
3. `deduplication._root_cause_signature` 改为接收 `signatures: list[SignatureRule]` 参数；`judge_node` 在调用前加载。
4. 默认签名集合迁移到 `seed.ts`，覆盖现有 ~20 个签名（REDIS_KEYS_COMMAND / SQL_STRING_CONCAT_QUERY / DEPENDENCY_FASTJSON_CVE / 等）。
5. 项目管理员可通过 API 增删签名（先做最小接口，UI 留待后续）。

**验证**
```bash
npm run build:api
node scripts/run-python.mjs scripts/verify_rule_precision_calibration.py
node scripts/run-python.mjs -m pytest worker/tests/test_deduplication.py -v
npm run verify:java-5mr
```

**验收**
- `_root_cause_signature` 不再含中文字面量；
- 项目级签名可覆盖默认签名（同 `signature_key` 项目级优先）；
- gold-eval 通过。

---

### T08 · `process_mr_one` 拆分

**目标**：~375 行单函数拆为可读阶段。

**涉及文件**
- `worker/review_runtime.py`

**改动要点**
抽函数（保持私有，仅在该文件内调用）：
```python
def _claim_job_and_load_context(conn, config) -> tuple[Any, Any, Any, Any, dict]: ...
def _evaluate_mr_size_guard(conn, config, job, mr, project_config) -> tuple[bool, list[ChangedFile] | None, dict]: ...
def _create_review_run(conn, config, job, mr, project_config, sandbox_dir, recorder) -> str: ...
def _build_graph_nodes(conn, config, job, mr, repo, project_config, project_id, run_id, sandbox_dir,
                      recorder, data_policy, agent_configs, agent_config_by_id,
                      tool_gateway, size_guard_files) -> list: ...
def _finalize_review_run(conn, config, project_config, run_id, job, mr) -> None: ...
def _handle_review_failure(conn, config, project_config, recorder, run_id, job, mr, exc) -> None: ...
```
`process_mr_one` 收敛为：
```python
def process_mr_one(conn, config) -> bool:
    job, mr, repo, project, project_config = _claim_job_and_load_context(conn, config)
    if not job:
        return False
    start_heartbeat(...)
    allowed, size_guard_files, size_decision = _evaluate_mr_size_guard(...)
    if not allowed:
        _cancel_oversized_mr(conn, config, job, mr, size_decision)
        return True
    run_id, sandbox_dir, recorder = _create_review_run(...)
    try:
        nodes = _build_graph_nodes(...)
        invoke_review_graph({"run_id": run_id, "job_id": job["id"]}, nodes, recorder)
        recorder.flush()
        _finalize_review_run(...)
        return True
    except Exception as exc:
        _handle_review_failure(...)
        return True
```

**验证**
```bash
npm run build:api
node scripts/run-python.mjs scripts/verify_worker_orchestration_nodes.py
node scripts/run-python.mjs scripts/verify_worker_project_concurrency.py
npm run verify:queue-reliability
npm run verify:java-5mr
```

**验收**
- `process_mr_one` < 60 行；
- 所有 verify 脚本通过。

---

## Stage 3：Verifier 与评估集升级

### T09 · Verifier 证据匹配升级

**目标**：用符号 token 替代 jaccard 作为主判据。

**涉及文件**
- `worker/orchestration/nodes/verify_findings.py`
- `worker/context/symbol_resolver.py`（扩展）
- `worker/orchestration/nodes/verify_findings.py` 新增 `_symbol_evidence_score`

**改动要点**
1. `symbol_resolver.py` 新增 `extract_window_symbols(source_text: str, line: int, radius: int = 5) -> set[str]`：
   - 用 tree-sitter（已有依赖）解析窗口内代码；
   - 返回类名、方法名、字段名、字面量标识符的集合。
2. `verify_findings.py` 新增 `_symbol_evidence_score(finding, source_snippet) -> float`：
   - 从 finding 的 `title` / `problem_description` / `evidence` 抽取标识符（CamelCase / snake_case）；
   - 与窗口符号求交集比例；
   - 中文关键词 → 英文代码映射表（"未关闭"→`close`、"未使用 try-with-resources"→`try`/`AutoCloseable`、"注入"→`PreparedStatement`/`#{}`
3. `_evidence_matches_source` 改为综合 `symbol_score * 0.7 + jaccard * 0.3`，threshold 0.3。
4. `_source_contradiction_reasons` 保留但改为符号驱动（如 finding 说 "return null" 但源码无 `null` literal）。
5. 删除 `_source_has_rule_signal` 中的中文关键字匹配硬编码，改为按 rule_id 查规则特征表。

**验证**
```bash
node scripts/run-python.mjs worker/tests/test_verify_findings_soft_reject.py
node scripts/run-python.mjs -m pytest worker/tests/test_verify_findings_soft_reject.py -v
npm run verify:gold-eval
npm run verify:java-5mr
npm run verify:java-complex-10file
```

**验收**
- gold-eval precision 不降；
- 新增 `worker/tests/test_verify_symbol_evidence.py` 覆盖：
  - 中文证据 + 英文代码命中符号；
  - 证据提到不存在的类名 → 低分；
  - rule 白名单不绕过符号检查。

---

### T10 · 真实 PR 评估集

**目标**：脱离自产自销 fixture，建立可信基线。

**涉及文件（新建）**
- `evaluation/real_prs/README.md`
- `evaluation/real_prs/spring-boot_pr12345.json`（示例占位，实际由人工标注）
- `evaluation/real_prs/apache_dubbo_pr7890.json`
- `evaluation/real_gold_set.jsonl`
- `scripts/evaluate-real-prs.mjs`（新建）
- `scripts/score_real_pr_reviews.py`（新建）

**改动要点**
1. 选 5 个真实开源 PR（Java/Spring，中等规模 200-800 行），人工标注：
   - 每个 PR 的 true positive findings（rule_id、file、line、severity）；
   - 期望零 finding 的 negative case（仅文档/注释变更）。
2. `real_gold_set.jsonl` 格式与现有 `gold_set.jsonl` 一致，新增 `source: "real_pr"`、`pr_url` 字段。
3. `scripts/evaluate-real-prs.mjs`：从 `evaluation/real_prs/` 加载 PR fixture，触发 review，输出 finding。
4. `scripts/score_real_pr_reviews.py`：按 rule_id + file + line tolerance=3 匹配，输出 precision / recall / fp_rate。
5. `package.json` 新增：
   ```json
   "verify:real-prs": "node scripts/evaluate-real-prs.mjs && node scripts/run-python.mjs scripts/score_real_pr_reviews.py"
   ```
6. 在 `docs/nfr-and-slo.md` 新增"检视质量 SLO"章节：
   - 真实 PR precision ≥ 0.70
   - 真实 PR recall ≥ 0.60
   - negative set fp_rate = 0

**验证**
```bash
# 先人工准备 PR fixture 与 gold set
npm run verify:real-prs
```

**验收**
- 5 个真实 PR 评估报告生成；
- precision ≥ 0.70、recall ≥ 0.60；
- negative set 0 finding。
- 注：若首轮未达标，记录 gap 列表，作为后续 Sprint 输入，不阻断合并。

---

## Stage 4：架构简化

### T11 · 路由层简化

**目标**：减少不必要的 LLM Router 调用。

**涉及文件**
- `worker/review_runtime.py`：`route_agents`、`route_agents_with_llm`、`required_java_agent_ids`

**改动要点**
1. `route_agents` 默认走规则路由 + `required_java_agent_ids` 兜底。
2. 仅当规则匹配为空 **且** 文件类型混合（≥ 3 种语言）时才调 `route_agents_with_llm`。
3. `route_agents_with_llm` 的 `temperature` 改为 0.0。
4. 删除 `should_llm_route = effort != "fast" and (not matched or len(matched) >= 5)` 中 `len(matched) >= 5` 分支（专家多不是调 LLM 的理由）。
5. 新增 config 开关 `config.routing.enable_llm_router` 默认 false，允许项目级开启。

**验证**
```bash
node scripts/run-python.mjs scripts/verify_router_llm.py
npm run verify:java-5mr
npm run verify:java-rare-business
```

**验收**
- 默认配置下 Java MR 不触发 router LLM 调用（查 `llm_call_records`）；
- gold-eval 不降。

---

### T12 · DeepAgents 路径决策

**目标**：消除"中间态"——要么真用要么删。

**决策建议**：先删后用（当前 sub_agents 已禁用，包装层无净收益）。

**涉及文件**
- `worker/orchestration/nodes/run_experts.py`
- `worker/orchestration/deepagents_runner.py`
- `worker/review_runtime.py`：`load_agent_configs`

**改动要点（删除路径）**
1. `run_experts.py` 移除 `if effort == "deep" or agent.get("requires_deepagents") or has_skill_bundle:` 分支与 `run_bounded_deepagent` 调用。
2. `deepagents_runner.py` 整文件删除（保留 git 历史）。
3. `load_agent_configs` 移除 `requires_deepagents` 字段读取。
4. `agent_configs` 表的 `requires_deepagents` 列保留（避免 migration），但代码不再读取。
5. `requirements.txt` 暂保留 `deepagents==0.6.8`（其它路径可能间接依赖 langchain_core），但加注释 `# Reserved; deepagents_runner removed in T12`。
6. `verify:deepagents-smoke` 改为只验证 langgraph 编排可用。

**替代方案（保留路径）**：如果团队认为未来要用，改为"复杂 MR 启用 1 步 sub-agent"：
- `effort == "deep"` 且 `files > 5` 时启用；
- `max_tool_calls` 提升到 8；
- sub-agent 只能调用 `code_graph` 与 `tree_sitter` 工具。
- 此路径需额外补 `verify:deepagents-subagent` 测试。

**验证**
```bash
node scripts/run-python.mjs scripts/verify_deepagents_smoke.py
node scripts/run-python.mjs scripts/verify_worker_orchestration_nodes.py
npm run verify:java-5mr
npm run verify:java-complex-10file
```

**验收**
- `run_experts.py` 不再 import `deepagents_runner`；
- `verify:deepagents-smoke` 仍通过（改为验证 langgraph）；
- 复杂 MR gold-eval 不降。

---

### T13 · 配置与密钥治理

**目标**：消除明文密钥示范，补多 provider 示例。

**涉及文件**
- `config.example.json`
- `config.json`（若仍含明文 key，提示迁移）
- `src/backend/services/LlmConnectivityService.ts`
- `src/backend/server.ts`（启动检查）

**改动要点**
1. `config.example.json`：
   - 删除 `llm.default_api_key` 字段；
   - 只保留 `default_api_key_env: "JOLT_LLM_API_KEY"`；
   - 新增 `llm.providers` 数组示例，覆盖 dashscope / minimax / deepseek / claude / openai 五种，每条带 `provider` / `base_url` / `model` / `api_key_env` / `tier` / `context`。
2. 启动时（`server.ts`）检查 `config.json`：
   - 若 `llm.default_api_key` 或任一 `providers[].api_key` 非空，打 warning：
     `config.json contains plaintext api_key; migrate to *_env variable for production.`
3. `LlmConnectivityService` 增加连通性测试覆盖多 provider（当前可能只测默认）。
4. `README.md` 更新多 provider 配置章节。

**验证**
```bash
npm run verify:llm
npm run verify:local
```

**验收**
- `config.example.json` 不含任何明文 key；
- 启动含明文 key 的 `config.json` 时打印 warning；
- 多 provider 连通性测试可选执行（不阻断 CI）。

---

## Stage 5：运维与前端

### T14 · 校准反馈滑窗与 SLO 指标

**目标**：让 `rule_precision_history` 反映最近行为；新增检视质量 SLO 观测。

**涉及文件**
- `src/backend/services/FeedbackLearningService.ts`
- `worker/calibration/precision_history.py`
- `src/backend/routes/observability.routes.ts`
- `src/backend/services/ObservabilityService.ts`
- `docs/nfr-and-slo.md`

**改动要点**
1. `rule_precision_history` 新增 `recent_accepted_count` / `recent_rejected_count` 字段（最近 90 天），由 `FeedbackLearningService.recordFeedback` 维护；旧字段保留做累计。
2. `auto_suppress` 改为基于 `recent_*` 字段：samples ≥ 5 且 precision < 0.3 触发，且降级为 `confidence *= 0.5` 而非硬抑制。
3. `calibrate_findings_with_history` 读取 `recent_*` 字段；硬抑制仅在 `auto_suppress=1` 且 finding confidence < 0.5 时触发。
4. `ObservabilityService` 新增 `getReviewQualityMetrics(projectId, since)`：
   - finding acceptance rate = accepted / published
   - false positive rate = false_positive / published
   - high-severity accuracy = accepted(high) / published(high)
   - 按 project / week 聚合
5. `observability.routes.ts` 暴露 `GET /api/observability/review-quality?project_id=&since=`。
6. `docs/nfr-and-slo.md` 新增"检视质量 SLO"章节，目标：
   - acceptance rate ≥ 0.40
   - false positive rate ≤ 0.20
   - high-severity accuracy ≥ 0.60

**验证**
```bash
npm run build:api
node scripts/verify-observability.mjs
node scripts/run-python.mjs scripts/verify_rule_precision_calibration.py
```

**验收**
- `rule_precision_history` 含 `recent_*` 字段；
- `auto_suppress` 触发降级而非抑制；
- `GET /api/observability/review-quality` 返回非空 JSON。

---

### T15 · 前端拆分（最小可行）

**目标**：`src/frontend/main.tsx` 7048 行拆为页面级模块。

**涉及文件（新建）**
- `src/frontend/app/App.tsx`
- `src/frontend/app/routes.ts`
- `src/frontend/pages/ProjectsPage.tsx`
- `src/frontend/pages/ProjectDetailPage.tsx`
- `src/frontend/pages/MrReviewPage.tsx`
- `src/frontend/pages/FindingsPage.tsx`
- `src/frontend/pages/AdminPage.tsx`
- `src/frontend/components/`（按需）
- `src/frontend/hooks/useApi.ts`
- `src/frontend/api/client.ts`

**改动要点**
1. 不引入新依赖（无 react-router），用最小 state-based router：
   ```tsx
   type Route = { name: 'projects' } | { name: 'project', id: string } | { name: 'mr', id: string } | ...
   const [route, setRoute] = useState<Route>({ name: 'projects' })
   ```
2. `main.tsx` 收敛为：
   ```tsx
   import { App } from './app/App'
   ReactDOM.createRoot(document.getElementById('root')!).render(<App />)
   ```
3. 按 page 拆分，每文件 < 800 行。共享 API 调用抽到 `api/client.ts`，共享 hooks 抽到 `hooks/`。
4. `styles.css` 不拆（不在本任务范围）。
5. 保留所有现有功能，不改业务逻辑。

**验证**
```bash
npm run build
npm run dev:web &
# 手动验证：项目列表 / 项目详情 / MR 检视页 / finding 确认 / 管理员设置 5 条主路径
```

**验收**
- `main.tsx` < 100 行；
- 每个页面文件 < 800 行；
- 5 条主路径手动验证通过；
- `npm run build` 无 TS 错误。

---

## 执行规则（给 Codex）

1. **一次只领一个任务**，从 T01 开始按编号顺序，除非显式标注无依赖。
2. **每个任务完成后必须跑该任务的"验证"命令**，全部通过才能提交。
3. **提交 commit message 格式**：
   ```
   <task-id>: <短描述>

   - <改动要点 1>
   - <改动要点 2>

   Refs: docs/plans/2026-06-17-codex-review-quality-optimization-plan.md
   ```
4. **遇到 verify 脚本失败**：先修验证脚本或代码使其通过；若验证脚本本身过时，更新脚本并在 commit message 说明。
5. **不要跨任务合并改动**：一个 commit 只服务一个任务。
6. **不要重命名或删除现有 verify 脚本**，除非任务明确要求。
7. **不要修改 `evaluation/gold_set.jsonl`**，除非任务 T10 显式要求新增 real_gold_set。
8. **遇到设计决策分歧**：在 commit message 或 PR description 记录分歧与选择，不阻塞后续任务。
9. **每个 Stage 结束跑一次回归**：
   ```bash
   npm run verify:local
   npm run verify:gold-eval
   npm run verify:java-5mr
   npm run verify:queue-reliability
   ```

## 风险与回滚

| 任务 | 主要风险 | 回滚策略 |
|---|---|---|
| T02 | provider 不支持 json_schema | capabilities 表回退旧解析 |
| T03 | 缓存导致 MR 重跑结果不更新 | 加 `cache_buster` 参数；按 head_sha+prompt_hash 缓存天然支持 prompt 变化 |
| T05 | 拆分引入 import 错误 | 保留 `judge_findings.py` re-export shim |
| T07 | 项目级签名配置错误导致漏去重 | 默认签名集合兜底；项目级签名可禁用 |
| T09 | 符号匹配误判 | 保留 jaccard 作为兜底信号 |
| T10 | 真实 PR 评估不达标 | 不阻断合并，记录 gap 列表 |
| T12 | 删 DeepAgents 后复杂 MR 检视质量降 | 验证不通过则改走"保留路径"方案 |

## 完成判据

全部任务完成后，项目应满足：

- `worker/orchestration/nodes/judge_findings.py` < 50 行
- `worker/tests/` 至少 10 个测试文件，`pytest worker/tests/ -v` 全通过
- `npm run verify:real-prs` precision ≥ 0.70、recall ≥ 0.60
- `npm run verify:gold-eval` 仍通过（不退化）
- `npm run verify:java-5mr`、`verify:java-complex-10file`、`verify:queue-reliability` 全通过
- `src/frontend/main.tsx` < 100 行
- `config.example.json` 无明文密钥
- `docs/nfr-and-slo.md` 包含检视质量 SLO 章节
- `GET /api/observability/review-quality` 可用

---

## 附录：任务依赖图

```
T01 ─┐
T02 ─┼─→ T03 ──→ T04
     │
T05 ─┼─→ T06 ──→ T07
     │
T08 ─┘

T09 ──→ T10

T11 ──→ T12 ──→ T13

T14 ──→ T15
```

T01-T04 可并行；T05-T08 可并行；T09-T10 必须串行；T11-T13 必须串行；T14-T15 可并行。
