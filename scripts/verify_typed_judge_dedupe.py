from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from orchestration.nodes.judge_findings import judge_candidate_findings
from tools.tool_normalizer import sha1


def finding(title: str, rule: str, category: str, evidence: str) -> dict:
    return {
        "agent_id": "security_agent" if rule.startswith("SEC-") else "coding_agent",
        "severity": "high",
        "confidence": 0.9,
        "dedupe_hash": sha1(title + rule),
        "file_path": "src/main/java/demo/ArchiveService.java",
        "line_start": 90,
        "line_end": 90,
        "title": title,
        "problem_description": title,
        "recommendation": "修复该问题。",
        "suggested_code": "return;",
        "evidence": evidence,
        "covered_rules": [rule],
        "normalized_rule_category": category,
    }


def main() -> None:
    deserialization = finding(
        "ObjectInputStream 反序列化不可信对象",
        "SEC-INJECT-003",
        "UNSAFE_DESERIALIZATION",
        "new ObjectInputStream(input).readObject()",
    )
    resource_leak = finding(
        "ObjectInputStream 未使用 try-with-resources 关闭",
        "CODE-RESOURCE-005",
        "ZIP_STREAM_RESOURCE_LEAK",
        "new ObjectInputStream(input).readObject()",
    )
    duplicate_deserialization = {
        **deserialization,
        "dedupe_hash": sha1("duplicate" + "SEC-INJECT-003"),
        "confidence": 0.78,
        "title": "Java 原生反序列化缺少白名单",
    }
    final, rejected = judge_candidate_findings(
        [deserialization, resource_leak, duplicate_deserialization],
        [],
        max_findings=5,
    )
    titles = {item["title"] for item in final}
    assert len(final) == 2, final
    assert "ObjectInputStream 反序列化不可信对象" in titles, titles
    assert "ObjectInputStream 未使用 try-with-resources 关闭" in titles, titles
    assert any("deduped_lower_rank" in (item.get("rejected_reasons") or []) for item in rejected), rejected
    print(json.dumps({"final_count": len(final), "rejected_count": len(rejected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
