# 实现缺口修复方案（2026-06-07）

> 范围：基于《2026-06-06-design-improvements.md》(P0-1 ~ P2-19) 与《2026-06-07-java-web-static-tooling.md》(J0 ~ J12) 两份方案，对当前代码逐项审计后发现的**10 个具体缺口**给出可执行的修复方案。每条均含：① 现状证据（file:line） ② 改造目标 ③ 代码骨架 ④ 数据库/接口变更 ⑤ 验收标准。
>
> 编号 **G1-G10**（Gap-Fix），按优先级 P0/P1/P2 分组。完成本文档全部 10 项后，整体一致率从 ~70% 提升至 ~95%。
>
> 总体策略：**不重写、只补齐**。所有改动尽量在现有文件内增量进行，避免新增模块。SQLite schema 改动通过 `migrations.ts` 追加新版本号实现，不破坏已有数据。

---

## 修复总览

| 编号 | 缺口 | 优先级 | 影响面 | 预计工作量 |
|------|------|--------|--------|-----------|
| G1 | Verifier 缺 `line_in_diff` 容差 / evidence 相似度 / rule_exists | P0 | 误报率↓5-10% | 1 人日 |
| G2 | 预算只记账不熔断（wall_seconds / max_cost_usd） | P0 | 成本可控 | 1 人日 |
| G3 | DeepAgents 仅 metadata，未真正调度 | P0 | 复杂场景能力 | 3 人日 |
| G4 | tree-sitter 真索引未落地 `code_index_snapshots` | P1 | RAG 上下文质量 | 5 人日 |
| G5 | VCSProvider 仅 `listOpenMergeRequests` | P1 | 平台可扩展 | 2 人日 |
| G6 | 前端缺 compare 视图 / Coverage Card 硬编码 | P1 | 用户体验 | 2 人日 |
| G7 | LLM Provider 抽象 + failover 缺失 | P2 | 可用性 | 2 人日 |
| G8 | Recorder 同步逐事件 INSERT | P2 | 吞吐 | 1 人日 |
| G9 | 评测 `evaluation_gold_set` 空表 + 无 runner + 无 CI 闸 | P2 | 质量回归保护 | 3 人日 |
| G10 | NFR / SLO 文档缺失 | P2 | 运维基线 | 1 人日 |

**合计 21 人日**，建议按 P0 → P1 → P2 顺序投入，4-5 周完成。

---

# P0 修复（必须做，否则线上风险）

## G1 Verifier 增加 `line_in_diff` 容差 + evidence 相似度 + rule_exists

### 现状证据
- `worker/orchestration/nodes/verify_findings.py:7-34` 仅做 4 项校验：`file_not_found` / `below_confidence` / `suppressed_by_feedback` / `schema_invalid`
- 设计原文（P0-1）要求：① finding.line 必须落在本次 diff 的 hunk 范围内（容差 ±3）；② evidence 文本与源码 snippet 的 token Jaccard ≥ 0.5；③ rule_id 必须在已知规则注册表内
- 当前后果：LLM 容易报"看似在文件内、但行号或代码片段已飘"的伪造问题

### 改造目标
将 verifier 通过率从 ~80% 收紧至 ~60%（真实问题保留率 ≥ 95%），把"行号飘移/evidence 编造"挡在用户视线之外。

### 代码骨架
```python
# worker/orchestration/nodes/verify_findings.py

# 1. 入参新增 diff_hunks 与 rule_registry
def verify_candidate_findings(
    findings, valid_files, agent_config_by_id, suppressed_hashes,
    diff_hunks: dict[str, list[tuple[int, int]]],   # file -> [(start, end), ...]
    rule_registry: set[str],
    source_snippet_loader,                          # (file, line) -> str
):
    for finding in findings:
        reasons = []
        file_path = str(finding.get("file_path") or "")
        if file_path not in valid_files:
            reasons.append("file_not_found")

        # 2. line_in_diff 容差校验
        line_no = int(finding.get("line_number") or 0)
        if line_no > 0:
            hunks = diff_hunks.get(file_path, [])
            if not any(start - 3 <= line_no <= end + 3 for start, end in hunks):
                reasons.append("line_out_of_diff")

        # 3. evidence 相似度（token Jaccard）
        evidence = str(finding.get("evidence") or "").strip()
        if evidence and line_no > 0:
            snippet = source_snippet_loader(file_path, line_no, window=5)
            if _token_jaccard(evidence, snippet) < 0.5:
                reasons.append("evidence_not_in_source")

        # 4. rule_exists
        rule_id = str(finding.get("rule_id") or "")
        if rule_id and rule_registry and rule_id not in rule_registry:
            reasons.append("unknown_rule")

        # 5. 既有 4 项保留
        ...

def _token_jaccard(a: str, b: str) -> float:
    ta = set(re.findall(r"\w+", a.lower()))
    tb = set(re.findall(r"\w+", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
```

### 数据接入
- `diff_hunks` 已在 `prescan.py` 解析过，将其放入 LangGraph state（key=`diff_hunks_by_file`）传到 verify 节点
- `rule_registry` 从 `agent_skills/*/SKILL.md` 与 `tool_normalizer.RULE_CATEGORY_MAP` 启动时加载一次，放入 `agent_config_by_id` 同级缓存
- `source_snippet_loader` 复用 `review_runtime.py` 内已有的 `read_file_lines` 工具

### 验收标准
- 单元测试：构造 5 类绕过尝试（行号飘±5 / evidence 改写 / rule_id 编造 / 文件不存在 / confidence 不足），断言全部进入 `rejected_reasons`
- 灰度对比：同一 MR 集合下 verifier 通过率下降 15-25%，但人工评测保留率 ≥ 95%
- 拒绝原因可观测：`recorder.event("finding_verified", ...)` 增加各 `reason` 计数

---

## G2 预算运行时熔断（wall_seconds + max_cost_usd）

### 现状证据
- `worker/orchestration/nodes/choose_effort.py:13-14` 声明 `max_wall_seconds` 与 `max_cost_usd=0.0` 但全仓搜索仅 `diff_max_lines_to_llm_exceeded`(`review_runtime.py:609`) 与 `max_findings_exceeded`(`judge_findings.py:86`) 两处熔断
- `max_cost_usd=0.0` 形同未启用；`max_wall_seconds` 仅作为字段写入 `review_runs.budget_json`，从未对照检查

### 改造目标
- LLM 单价表 `LLM_PRICING` 落库或代码常量；每次 `call_llm` 累加 token×price
- 引入 `BudgetTracker` 上下文对象，在 `route_agents`、`run_experts`、`run_targeted_debate` 节点入口校验
- 超出 `max_wall_seconds` 或 `max_cost_usd` 时：跳过未执行的低优先级 agent，把已产生的 findings 走完 verifier+judge 输出，并在 `report_summary` 标注"预算截断"

### 代码骨架
```python
# worker/budget.py  (新文件，单一模块，~80 行)
import time
from dataclasses import dataclass, field

# 单价：USD per 1K tokens
LLM_PRICING = {
    "deepseek-chat":       {"in": 0.00014, "out": 0.00028},
    "qwen-max":            {"in": 0.0020,  "out": 0.0060},
    "claude-sonnet-4-6":   {"in": 0.003,   "out": 0.015},
    "gpt-4o-mini":         {"in": 0.00015, "out": 0.00060},
}

@dataclass
class BudgetTracker:
    max_wall_seconds: float
    max_cost_usd: float
    max_llm_calls: int
    started_at: float = field(default_factory=time.monotonic)
    cost_usd: float = 0.0
    llm_calls: int = 0
    truncated_reason: str | None = None

    def charge_llm(self, model: str, in_tokens: int, out_tokens: int) -> None:
        price = LLM_PRICING.get(model, {"in": 0.001, "out": 0.003})
        self.cost_usd += in_tokens * price["in"] / 1000 + out_tokens * price["out"] / 1000
        self.llm_calls += 1

    def should_stop(self) -> bool:
        if time.monotonic() - self.started_at > self.max_wall_seconds:
            self.truncated_reason = "wall_seconds_exceeded"; return True
        if self.max_cost_usd > 0 and self.cost_usd > self.max_cost_usd:
            self.truncated_reason = "cost_usd_exceeded"; return True
        return False
```

### 接入点
- `choose_effort.py:14` 把 `max_cost_usd` 改为分级真实值（trivial=0.05 / light=0.20 / standard=1.00 / deep=3.00）
- `review_runtime.py:1424` `call_llm` 调用前后包裹 `budget.charge_llm(model, usage.in, usage.out)`
- `run_experts.py` 主循环每轮开始 `if budget.should_stop(): break`
- `finalize.py:40-51` 把 `budget.truncated_reason` 写入 `report_summary` 与 `budget_used_json`

### 验收标准
- 单测：mock 1500 tokens × 100 次的循环，断言 standard 档（max_cost_usd=1.00）在 ~40 次后触发熔断
- 集成测：构造一个 200 文件巨型 MR，effort=light（max_wall_seconds=90），断言 wall-clock 在 95s 内返回且 `budget_used_json.truncated_reason="wall_seconds_exceeded"`
- 前端展示：`ReviewRunDetail` 页面新增"预算用量"小卡（cost / wall / llm_calls）

---

## G3 DeepAgents 真正接入（单层 bounded ReAct 子图）

### 现状证据
- `worker/orchestration/nodes/run_experts.py:55-64` 只写 `"deepagents": {"mode": "bounded_single_agent_node", ...}` 到 toolchain_manifest，无任何 deepagents 实际调用
- `prescan.py:139` 记录 `package_version("deepagents")` 但 import 后未使用

### 改造目标
仅在 effort=`deep` 或 agent 配置 `requires_deepagents=true` 时启用 DeepAgents，作为**单层有界 ReAct 子图**（≤8 tool calls / ≤90s），不启用 sub-agent 调度。其它情况维持当前 `call_llm` 路径。

### 代码骨架
```python
# worker/orchestration/deepagents_runner.py  (新文件)
from deepagents import create_deep_agent  # 已在 requirements

def run_bounded_deepagent(
    *, agent_id, system_prompt, tools, untrusted_context,
    max_tool_calls=8, budget,
):
    agent = create_deep_agent(
        tools=tools,
        instructions=system_prompt,
        # 关键：禁用 subagents，限制 tool 调用
        subagents=[],
        max_iterations=max_tool_calls,
    )
    result = agent.invoke({"messages": [{"role": "user", "content": untrusted_context}]})
    # 计费
    if usage := result.get("usage"):
        budget.charge_llm(usage["model"], usage["input_tokens"], usage["output_tokens"])
    return result["messages"][-1].content
```

### 接入点
- `run_experts.py` 在专家循环里加分支：
  ```python
  if effort == "deep" and config.get("requires_deepagents"):
      raw = run_bounded_deepagent(...)
  else:
      raw = call_llm(...)
  ```
- `agent_configs` 表新增列 `requires_deepagents BOOLEAN DEFAULT 0`（migration v6）

### 验收标准
- effort=deep 且 agent 标 `requires_deepagents=true` 时，trace 中能看到 ≥2 次 tool_call 且总 tool_call ≤ 8
- effort≠deep 时，DeepAgents 路径**不**被触发（grep `create_deep_agent` 在执行日志中 0 次出现）
- 失败回退：DeepAgents 异常时自动 fallback 到 `call_llm`，记录 `recorder.event("deepagents_fallback", ...)`

---

# P1 修复（架构完整性）

## G4 tree-sitter 真索引落地 `code_index_snapshots`

### 现状证据
- `worker/tools/tree_sitter_tool.py` 共 22 行，`build_graph` 返回空 functions/classes/imports
- `review_runtime.py:725` 注释明写 *"MVP uses diff-local symbol summary; full tree-sitter/ctags repository index is reserved"*
- `migrations.ts:231` `code_index_snapshots` 表已建但未写入

### 改造目标
对 Java/TS/Python 三种语言，提取 **函数定义 / 类定义 / import / 直接调用关系**，按 commit_sha 缓存到 `code_index_snapshots`，供 LLM 上下文与 RAG 检索使用。

### 实施方案

**方案 A（推荐，1 周）**：使用 `tree_sitter_languages` Python 包 + 预写 .scm 查询
```
worker/tools/tree_sitter_tool.py  扩展为 ~250 行
worker/tools/tree_sitter_queries/
  ├── java.scm        (function_definition / class_definition / import / method_invocation)
  ├── typescript.scm
  └── python.scm
```

**方案 B（备选，3 天）**：直接调用 `tree-sitter` CLI，按行级 `--scope` 输出 JSON

### 代码骨架（方案 A）
```python
# worker/tools/tree_sitter_tool.py
from tree_sitter_languages import get_parser, get_language

QUERIES = {  # 启动时加载 .scm 文件
    "java": Path(__file__).parent / "tree_sitter_queries/java.scm",
    "typescript": ...,
    "python": ...,
}

def build_repo_index(worktree: Path, commit_sha: str) -> dict:
    snapshot = {"commit_sha": commit_sha, "files": []}
    for file in worktree.rglob("*"):
        lang = _detect_lang(file)
        if not lang or lang not in QUERIES:
            continue
        parser = get_parser(lang)
        tree = parser.parse(file.read_bytes())
        query = get_language(lang).query(QUERIES[lang].read_text())
        captures = query.captures(tree.root_node)
        snapshot["files"].append({
            "path": str(file.relative_to(worktree)),
            "language": lang,
            "functions": [...], "classes": [...],
            "imports": [...], "calls": [...],
        })
    return snapshot

def persist_index(conn, project_id, commit_sha, snapshot):
    conn.execute(
        "INSERT OR REPLACE INTO code_index_snapshots (project_id, commit_sha, index_kind, payload_json, created_at) "
        "VALUES (?, ?, 'tree_sitter_v1', ?, CURRENT_TIMESTAMP)",
        (project_id, commit_sha, json.dumps(snapshot, ensure_ascii=False)),
    )
```

### 接入点
- `review_runtime.py:689` `build_code_context_snapshot` 改为调用 `build_repo_index` + `persist_index`
- `route_agents.py` 在分配 agent 时，从 snapshot 查 `callers/callees`，注入到 agent system prompt
- 复用现有 `code_index_snapshots` 表，无需新 schema

### 验收标准
- 一个 50K LOC Java 项目，全量索引 < 30s（增量基于 mtime < 5s）
- 索引产物 `payload_json` 大小 < 5MB（gzip 后 < 1MB）
- LLM 上下文里能看到"被修改的 `OrderService.payOrder` 被 3 个 controller 调用"——上下文完整性指标人工抽查 ≥ 80%

---

## G5 VCSProvider 扩到完整能力面

### 现状证据
- `src/backend/vcs/VcsProvider.ts` 仅 21 行，单一 `listOpenMergeRequests()`
- worker 当前仍直连 GitHub/CodeHub API（`worker/review_runtime.py` 内 `requests.get(...)` 风格）

### 改造目标
统一 5 个能力：`fetch_diff` / `fetch_files` / `post_comment` / `update_status` / `capabilities`。worker 通过 HTTP 调 backend，backend 转发到具体 provider，避免 worker 持有 git token。

### 代码骨架
```typescript
// src/backend/vcs/VcsProvider.ts
export interface VcsCapabilities {
  inline_comment: boolean;
  status_check: boolean;
  thread_reply: boolean;
  draft_review: boolean;
}

export interface VcsProvider {
  readonly name: "github" | "codehub";
  listOpenMergeRequests(opts: ListOpts): Promise<MergeRequestRef[]>;
  fetchDiff(mr: MrRef): Promise<DiffPayload>;
  fetchFile(mr: MrRef, path: string, sha?: string): Promise<string>;
  postComment(mr: MrRef, c: InlineComment): Promise<{ id: string }>;
  postSummary(mr: MrRef, body: string): Promise<{ id: string }>;
  updateStatus(mr: MrRef, s: ReviewStatus): Promise<void>;
  capabilities(): VcsCapabilities;
}
```

### 接入点
- `GithubProvider.ts` / `CodeHubProvider.ts` 各补 5 个方法（已有 API 客户端可复用）
- 新增 `src/backend/routes/vcs-proxy.routes.ts`：`POST /api/vcs/:project_id/comment`、`POST /api/vcs/:project_id/status`、`GET /api/vcs/:project_id/diff`
- worker 替换直连为 backend HTTP 调用，token 不出 backend 进程

### 验收标准
- worker 进程内 `grep -E "github.com/api|codehub.*token"` 命中 0 次
- 切换 GitHub → CodeHub 仅需改一处 provider name 配置，不动 worker 代码
- 能力声明在 UI"集成"页可见，inline_comment=false 的 provider 自动隐藏行内评论功能

---

## G6 前端 compare 视图 + Coverage Card 数据化

### 现状证据
- 后端 `src/backend/routes/review.routes.ts:201` `/api/mr-review/merge-requests/:mrId/review-runs/compare` 已返回 `added/resolved/retained`，前端 `main.tsx` 全文 0 处调用
- `src/frontend/main.tsx:1511-1537` Coverage Card 6 行规则硬编码

### 改造目标
- 在 MR 详情页新增"对比上一次检视" Tab，展示 added（红）/ resolved（绿）/ retained（灰）三栏
- Coverage Card 从 `review_runs.coverage_json`（新增列）读取：实际跑过的工具 + 规则数 + 命中数

### 代码骨架
```tsx
// src/frontend/main.tsx 新增组件
function ReviewRunCompareTab({ mrId, runId }: { mrId: string; runId: string }) {
  const { data } = useFetch(`/api/mr-review/merge-requests/${mrId}/review-runs/compare?run_id=${runId}`);
  if (!data) return <Spinner />;
  return (
    <div className="grid grid-cols-3 gap-4">
      <FindingList title={`新增 (${data.added.length})`} items={data.added} variant="danger" />
      <FindingList title={`已解决 (${data.resolved.length})`} items={data.resolved} variant="success" />
      <FindingList title={`仍存在 (${data.retained.length})`} items={data.retained} variant="muted" />
    </div>
  );
}

// CoverageCard 替换硬编码
function CoverageCard({ run }: { run: ReviewRun }) {
  const items = run.coverage?.tools ?? [];   // 新字段
  return <div>{items.map(t => <CoverageRow key={t.id} tool={t} />)}</div>;
}
```

### 后端配合
- `migrations.ts` v6 增列 `review_runs.coverage_json TEXT`
- `worker/orchestration/nodes/finalize.py` 在写 review_runs 时填入：
  ```python
  coverage = {
      "tools": [
          {"id": "semgrep",       "rules_run": 47, "files_scanned": 18, "hits": 3},
          {"id": "gitleaks",      "rules_run": 12, "files_scanned": 162, "hits": 0},
          {"id": "java_web_static", "rules_run": 23, "files_scanned": 14, "hits": 7},
      ],
      "agents_executed": [...],
  }
  ```

### 验收标准
- 重新检视同一 MR，能在 compare Tab 看到对应 added/resolved 数字
- Coverage Card 在"无问题"的 MR 上能展示"扫过 47 条规则、0 命中"——避免用户怀疑工具未运行

---

# P2 修复（产品打磨）

## G7 LLM Provider Router + failover

### 现状证据
- `worker/review_runtime.py:551` 仅维护 `llm_providers_allowed` 名单，`call_llm`(:1424) 单一直连，无能力路由、无 failover

### 改造方案
```python
# worker/llm_router.py (新文件 ~120 行)
PROVIDER_CAPS = {
    "deepseek": {"context": 64_000,  "vision": False, "tier": "fast"},
    "qwen":     {"context": 128_000, "vision": True,  "tier": "balanced"},
    "claude":   {"context": 200_000, "vision": True,  "tier": "premium"},
}

def pick_provider(*, required_context: int, vision: bool, allowed: list[str]) -> list[str]:
    candidates = [p for p in allowed if PROVIDER_CAPS[p]["context"] >= required_context]
    if vision:
        candidates = [p for p in candidates if PROVIDER_CAPS[p]["vision"]]
    return sorted(candidates, key=lambda p: ("premium fast balanced".split().index(PROVIDER_CAPS[p]["tier"])))

def call_llm_with_failover(prompt, *, providers, budget, recorder, span):
    last_err = None
    for provider in providers:
        try:
            return _call_one(provider, prompt, budget=budget)
        except (RateLimitError, ServiceUnavailable, TimeoutError) as e:
            recorder.event(span, "llm_failover", f"{provider} failed: {type(e).__name__}", {"err": str(e)[:200]})
            last_err = e
            continue
    raise last_err
```

### 接入点
- `review_runtime.py:1424` 旧 `call_llm` 改为薄封装，内部走 `call_llm_with_failover`
- agent 配置可指定 `preferred_tier="premium"`，路由器据此挑选首选

### 验收标准
- 故意把首选 provider 改为不可达的 URL，trace 中能看到一次 `llm_failover` 后 fallback 成功
- 单测覆盖：required_context=150K 时不会选到 deepseek

---

## G8 Recorder 异步批写

### 现状证据
- `Recorder` 每个 event / tool_call / span 都同步 INSERT，重型 MR 一次跑 5000+ 行 INSERT，串行化耗时显著

### 改造方案
```python
# worker/recorder.py
class BatchedRecorder:
    def __init__(self, conn, flush_interval=2.0, max_batch=200):
        self.queue: list[tuple[str, tuple]] = []
        self.lock = threading.Lock()
        threading.Thread(target=self._flush_loop, daemon=True).start()

    def event(self, span, type_, msg, payload):
        with self.lock:
            self.queue.append(("INSERT INTO trace_events ...", (...)))
            if len(self.queue) >= self.max_batch:
                self._flush_now()

    def _flush_loop(self):
        while True:
            time.sleep(self.flush_interval)
            self._flush_now()

    def _flush_now(self):
        with self.lock:
            batch, self.queue = self.queue, []
        if not batch:
            return
        with self.conn:
            for sql, params in batch:
                self.conn.execute(sql, params)
```

### 验收标准
- 同一压力测试 MR（800 finding），trace 写入耗时从 ~12s 降到 ~2s
- 进程异常退出前 `atexit` flush，丢失事件 ≤ 5 条

---

## G9 评测 gold set + runner + CI 闸

### 现状证据
- `migrations.ts:413` `evaluation_gold_set` 表已建但 0 行；无 runner 脚本；CI 仅跑 lint/test，无 review 质量回归

### 改造方案

**Step 1 — 种子数据**：从过往 30 个已确认的 MR finding 抽取，写入 `evaluation/gold_set.jsonl`：
```jsonl
{"id": "gold-001", "repo": "demo/java-service", "mr_id": 42, "commit_sha": "abc123",
 "file": "OrderService.java", "line": 87, "rule_id": "SQL-INJECTION",
 "severity": "high", "ground_truth": "true_positive",
 "evidence_keywords": ["String.format", "executeQuery"]}
```

**Step 2 — runner**：
```python
# evaluation/run_gold_eval.py
def evaluate_against_gold(gold_path, review_findings_by_mr):
    metrics = {"tp": 0, "fp": 0, "fn": 0, "by_rule": defaultdict(lambda: [0,0,0])}
    gold = [json.loads(l) for l in open(gold_path)]
    for item in gold:
        actual = review_findings_by_mr.get(item["mr_id"], [])
        match = _find_match(item, actual)   # file + line±5 + rule_id
        if match: metrics["tp"] += 1
        else:     metrics["fn"] += 1
    precision = metrics["tp"] / max(1, metrics["tp"] + metrics["fp"])
    recall    = metrics["tp"] / max(1, metrics["tp"] + metrics["fn"])
    return {"precision": precision, "recall": recall, "by_rule": metrics["by_rule"]}
```

**Step 3 — CI 闸**：
```yaml
# .github/workflows/quality-gate.yml
- name: gold set regression
  run: |
    python evaluation/run_gold_eval.py --gold evaluation/gold_set.jsonl --out report.json
    python evaluation/check_thresholds.py report.json \
      --min-precision 0.80 --min-recall 0.75
```

### 验收标准
- gold_set 初始 ≥ 30 条，覆盖 high/medium/low + 5 个核心规则
- CI 在 precision<0.80 或 recall<0.75 时阻断合并
- 每周自动跑一次 + 把结果写入 `evaluation_reports` 表，前端"质量"页可视化趋势

---

## G10 NFR / SLO 文档

### 现状证据
- `docs/` 下无 NFR；无 SLO 定义

### 输出物
新增 `docs/nfr-and-slo.md`（约 200 行），覆盖：

1. **可用性 SLO**
   - 99.5% 月度可用性（webhook → 入队成功）
   - 错误预算：3.6h/月

2. **性能 SLI**
   - light 档：P95 ≤ 90s
   - standard 档：P95 ≤ 5min
   - deep 档：P95 ≤ 15min
   - 队列等待 P95 ≤ 30s

3. **质量 SLO**
   - 误报率（feedback 标 false_positive 比例）≤ 25%
   - 漏报率（gold set recall）≥ 75%

4. **容量基线**
   - 单实例 worker 并发 8 个 MR
   - SQLite 单库 ≤ 50GB（超出迁移 PostgreSQL）
   - Trace 保留 30 天，超出归档到 S3

5. **数据合规**
   - 出境策略已在 `review_runtime.py:549` 落实
   - 客户敏感路径 mask / skip / fail_job 三档配置
   - LLM 厂商白名单按 `data_residency=cn-north-1` 过滤

### 验收标准
- 文档 review 通过；接入 `/api/health` 端点暴露 SLI 实时值
- 监控告警基于本文档阈值配置（暂占位，告警系统待定）

---

# 里程碑（4-5 周）

| 周次 | 完成项 | 交付物 |
|------|--------|--------|
| Week 1 | G1 + G2 + G10 | Verifier 加固 / 预算熔断 / NFR 文档 |
| Week 2 | G6 + G8 | 前端 compare/coverage / 异步 trace |
| Week 3 | G4 | tree-sitter 真索引上线 |
| Week 4 | G3 + G5 + G7 | DeepAgents 子图 / VCSProvider 完整 / LLM Router |
| Week 5 | G9 | 评测 gold set + CI 闸 |

每周末跑一次 gold set，发布前要求所有 G1-G10 验收标准全绿。

---

# 验收总表

完成本文档后，再次执行实现一致性审计，预期结果：

| 维度 | 当前 | 目标 |
|------|------|------|
| P0 完成度 | 80% | 100% |
| P1 完成度 | 50% | 95% |
| P2 完成度 | 40% | 90% |
| J 系列完成度（不含 CI 侧执行） | 75% | 90% |
| **整体一致率** | **70%** | **95%** |

如 4-5 周后仍有 1-2 项未达成，应在本文档新增 "G11 + 延后理由"，避免 silent drift。
