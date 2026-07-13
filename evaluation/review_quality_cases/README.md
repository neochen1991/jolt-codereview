# Review Quality Cases

本目录用于维护能够证明 Review Worker 召回率与精确率的冻结评测案例。它和
`evaluation/real_gold_set.jsonl` 的区别是：这里保存案例输入、跨文件关系、人工标注状态和
期望执行阶段，`real_gold_set.jsonl` 继续作为统一评分入口。

## Case schema

每个案例使用一个独立目录，并包含 `case.json`：

```json
{
  "case_id": "cross-file-interface-001",
  "category": "cross_file",
  "source": "real_open_source_curated",
  "repository": "owner/repository",
  "base_sha": "...",
  "head_sha": "...",
  "changed_files": ["src/A.java"],
  "required_context_files": ["src/B.java"],
  "gold": [
    {
      "rule_id": "CODE-STATE-004",
      "file": "src/A.java",
      "line": 42,
      "severity": "high",
      "root_cause": "...",
      "trigger_condition": "..."
    }
  ],
  "review": {
    "reviewer_1": "",
    "reviewer_2": "",
    "status": "pending"
  }
}
```

`category` 必须是：

- `large_file_late_hunk`
- `cross_file`
- `same_name_negative`
- `negative_mr`
- `skill_hit`
- `skill_no_hit`

## 标注规则

1. 输入必须冻结到 base/head SHA；本地构造用例必须提交完整 fixture 和生成脚本。
2. Gold 必须描述根因、触发条件、影响和最小准确位置，不能只写规则名。
3. 跨文件案例必须列出 `required_context_files`，并注明关系类型。
4. 正例和负例都需要两名评审者独立确认；分歧必须记录解决说明。
5. `review.status=approved` 后才能进入正式质量门；`pending` 只能进入开发回归。
6. 自动生成或模型提出的 Gold 不能自动标记为 approved。

## 最小数据配比

- 大文件后半段问题不少于 15 个。
- 跨文件问题不少于 30 个。
- 同名、重载和错误关联负例不少于 20 个。
- 无缺陷 MR 或历史误报负例不少于 30 个。
- 每个主要 Skill 至少 5 个命中案例和 3 个不命中案例。

## 质量运行

评分器确定性：

```bash
npm run verify:real-pr-repeatability
```

Worker 两次真实运行比较：

```bash
PYTHONPATH=mr-backend/worker python3 scripts/verify_review_worker_repeatability.py \
  --baseline-run <run_id> \
  --repeated-run <run_id> \
  --snapshot-dir artifacts/repeatability
```

Worker 比较使用稳定 `dedupe_hash`，不会比较每次运行都会变化的数据库主键。
