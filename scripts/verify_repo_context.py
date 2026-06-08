from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from context.repo_index import build_repo_index, resolve_diff_symbols
from orchestration.nodes.verify_findings import verify_candidate_findings
from prompts.builder import build_prompt
from review_runtime import ChangedFile


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="jolt-repo-context-"))
    try:
        worktree = temp_dir / "repo"
        cache_root = temp_dir / "cache"
        write(
            worktree / "src/main/java/com/acme/order/OrderService.java",
            """
package com.acme.order;

public class OrderService {
  private final OrderRepository repository;

  public void placeOrder(OrderRequest request) {
    repository.save(request.toEntity());
  }
}
""".strip(),
        )
        write(
            worktree / "src/main/java/com/acme/order/OrderController.java",
            """
package com.acme.order;

public class OrderController {
  private final OrderService orderService;

  public void create(OrderRequest request) {
    orderService.placeOrder(request);
  }
}
""".strip(),
        )
        write(
            worktree / "src/test/java/com/acme/order/OrderServiceTest.java",
            """
package com.acme.order;

class OrderServiceTest {
  void shouldPlaceOrder() {}
}
""".strip(),
        )
        changed = [
            ChangedFile(
                "src/main/java/com/acme/order/OrderService.java",
                "modified",
                2,
                0,
                2,
                "@@ -4,6 +4,8 @@\n+  public void placeOrder(OrderRequest request) {\n+    repository.save(request.toEntity());\n",
            )
        ]
        index_info = build_repo_index(worktree, "repo_verify", "sha_verify", cache_root)
        cached_info = build_repo_index(worktree, "repo_verify", "sha_verify", cache_root)
        related_context = resolve_diff_symbols(index_info, worktree, changed)
        agent = {
            "agent_id": "ddd_agent",
            "display_name": "DDD Agent",
            "applies_to": {"persona": "DDD reviewer", "exclusive_scope": "domain design", "review_scope": "aggregate consistency"},
            "related_context": {key: value for key, value in related_context.items() if key != "source_file_contents"},
            "tool_observations": [],
            "bound_rules": [],
        }
        prompt, _safety = build_prompt(agent, changed, "DDD-SERVICE-002: 服务方法必须保持聚合边界。")
        prompt_payload = json.loads(prompt)

        source_contents = related_context["source_file_contents"]

        def loader(file_path: str, line_no: int, window: int = 5) -> str:
            lines = source_contents[file_path].splitlines()
            start = max(1, line_no - window)
            end = min(len(lines), line_no + window)
            return "\n".join(lines[index - 1] for index in range(start, end + 1))

        accepted, rejected = verify_candidate_findings(
            [
                {
                    "agent_id": "ddd_agent",
                    "severity": "medium",
                    "confidence": 0.88,
                    "dedupe_hash": "repo-context",
                    "file_path": "src/main/java/com/acme/order/OrderService.java",
                    "line_start": 6,
                    "title": "服务方法缺少聚合边界校验",
                    "problem_description": "placeOrder 直接保存 request 转换对象，缺少聚合不变量校验。",
                    "evidence": "repository.save(request.toEntity())",
                    "covered_rules": ["DDD-SERVICE-002"],
                }
            ],
            {"src/main/java/com/acme/order/OrderService.java"},
            {"ddd_agent": {"min_confidence": 0.75}},
            set(),
            {"src/main/java/com/acme/order/OrderService.java": [(5, 7)]},
            {"DDD-SERVICE-002"},
            loader,
            [],
        )
        assert index_info["symbol_count"] >= 3, index_info
        assert cached_info["status"] == "cached", cached_info
        assert related_context["modified_symbols"], related_context
        assert any(item["name"] == "placeOrder" and item["callers"] for item in related_context["modified_symbols"]), related_context
        assert prompt_payload["related_context"]["modified_symbols"], prompt_payload["related_context"]
        assert accepted and not rejected, (accepted, rejected)
        print(
            json.dumps(
                {
                    "index_status": index_info["status"],
                    "cached_status": cached_info["status"],
                    "symbol_count": index_info["symbol_count"],
                    "ref_count": index_info["ref_count"],
                    "modified_symbols": [
                        {
                            "name": item["name"],
                            "definition_file": item["definition_file"],
                            "caller_count": len(item["callers"]),
                            "has_test": item["has_test"],
                        }
                        for item in related_context["modified_symbols"]
                    ],
                    "prompt_related_symbol_count": len(prompt_payload["related_context"]["modified_symbols"]),
                    "verifier_full_source_accepted": len(accepted),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
