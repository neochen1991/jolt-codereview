from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from config import load_config
from orchestration.deepagents_runner import run_bounded_deepagent


def main() -> None:
    config = load_config()
    result = run_bounded_deepagent(
        agent={
            "agent_id": "security_agent",
            "applies_to": {
                "persona": "安全专家，专注 Spring Web 输入校验、鉴权、注入和敏感信息风险。",
                "exclusive_scope": "security",
                "review_scope": "安全漏洞和敏感信息。",
            },
            "max_tool_calls": 3,
        },
        files=[
            SimpleNamespace(
                filename="src/main/java/com/acme/payment/PaymentController.java",
                status="modified",
                additions=12,
                deletions=0,
            )
        ],
        skill_summary=(
            "SEC-INJECT-003: 禁止将外部输入拼接进 SQL 后执行；"
            "SEC-SECRET-004: 禁止在代码或配置中提交明文密码、token、secret。"
        ),
        tool_observations=[
            {
                "tool_name": "semgrep",
                "rule_id": "SEC-INJECT-003",
                "file_path": "src/main/java/com/acme/payment/PaymentController.java",
                "line_start": 33,
                "message": "JDBC SQL is concatenated before execution.",
            }
        ],
        llm_config=config.get("llm", {}),
        max_tool_calls=3,
    )
    tool_calls = result.get("tool_calls") or []
    if not tool_calls:
        raise SystemExit("DeepAgents smoke failed: no real tool calls")
    print(
        json.dumps(
            {
                "ok": True,
                "tool_call_count": len(tool_calls),
                "tool_names": [item.get("tool_name") for item in tool_calls],
                "sub_agents": result.get("sub_agents"),
                "provider": result.get("provider"),
                "model": result.get("model"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
