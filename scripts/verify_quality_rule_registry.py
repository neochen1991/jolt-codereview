from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from rules.markdown_rule_parser import parse_markdown_rules
from rules.rule_loader import load_bound_rules
from prompts.builder import build_prompt


RULE_DOC = """
## SEC-INJECT-003 SQL 拼接存在注入风险
- severity: high
- category: security
- applies_to: src/main/java/**/*.java

### 规范说明
禁止将外部输入拼接到 SQL 或 JPQL 中。

### 检查点
- 新增代码是否使用 `+ userInput` 拼接 SQL。
- MyBatis XML 是否使用 `${}` 接收请求字段。

### 证据要求
- 必须给出 diff 行。
- 必须展示问题行附近源码。

### 反例
String sql = "select * from t where id = " + userId;

### 正例
PreparedStatement ps = connection.prepareStatement("select * from t where id = ?");

### 误报模式
- 拼接的是固定白名单字段。
- SQL 片段来自枚举常量且没有用户输入。

### 修复建议
使用 PreparedStatement、MyBatis #{} 或类型安全查询构造器。
"""


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE rule_documents (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          name TEXT NOT NULL,
          doc_type TEXT NOT NULL DEFAULT 'markdown',
          content TEXT NOT NULL,
          version TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE expert_rule_bindings (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          agent_key TEXT NOT NULL,
          rule_document_id TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 100
        );
        """
    )
    conn.execute(
        "INSERT INTO rule_documents (id, project_id, name, content, version, status) VALUES (?, ?, ?, ?, ?, 'active')",
        ("doc_quality", "project_quality", "质量规范", RULE_DOC, "v1"),
    )
    conn.execute(
        "INSERT INTO expert_rule_bindings (id, project_id, agent_key, rule_document_id, priority) VALUES (?, ?, ?, ?, ?)",
        ("bind_quality", "project_quality", "security_agent", "doc_quality", 10),
    )
    return conn


def main() -> None:
    rules = parse_markdown_rules(RULE_DOC)
    assert len(rules) == 1, rules
    item = rules[0].to_prompt_item()
    assert item["rule_id"] == "SEC-INJECT-003", item
    assert item["category"] == "security", item
    assert item["severity"] == "high", item
    assert "必须给出 diff 行" in item["required_evidence"], item
    assert "String sql" in item["negative_examples"], item
    assert "PreparedStatement" in item["positive_examples"], item
    assert "固定白名单字段" in item["false_positive_patterns"], item
    assert "PreparedStatement" in item["fix_guidance"], item

    bound = load_bound_rules(make_db(), "project_quality", "security_agent")
    assert len(bound) == 1, bound
    loaded = bound[0]
    assert loaded["document_name"] == "质量规范", loaded
    assert loaded["priority"] == 10, loaded
    assert loaded["required_evidence"] == item["required_evidence"], loaded
    assert loaded["false_positive_patterns"] == item["false_positive_patterns"], loaded

    prompt, _meta = build_prompt(
        {
            "agent_key": "security_agent",
            "display_name": "安全专家",
            "max_findings": 8,
            "applies_to": {"persona": "安全检视", "exclusive_scope": "security"},
            "bound_rules": bound,
        },
        [
            SimpleNamespace(
                filename="src/main/java/demo/PaymentRepository.java",
                status="modified",
                patch="+ String sql = \"select * from t where id = \" + userId;",
                additions=1,
                deletions=0,
            )
        ],
    )
    assert "false_positive_patterns" in prompt, prompt
    assert "required_evidence" in prompt, prompt
    assert "固定白名单字段" in prompt, prompt

    print("Quality rule registry checks passed.")


if __name__ == "__main__":
    main()
