from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from context.repo_index import build_repo_index
from context.symbol_resolver import resolve_diff_symbols
from prompts.builder import build_prompt


JAVA_SOURCE = """
package demo.service;

import demo.repository.PaymentRepository;

public class PaymentService {
    private final PaymentRepository repository;

    public PaymentService(PaymentRepository repository) {
        this.repository = repository;
    }

    public void process(String userId) {
        String sql = "select * from payment where user_id = " + userId;
        repository.executeQuery(sql);
    }
}
""".strip()

JAVA_TEST = """
package demo.service;

class PaymentServiceTest {
    void processRejectsUnsafeInput() {
        new PaymentService(null).process("u1");
    }
}
""".strip()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "src/main/java/demo/service/PaymentService.java"
        test = root / "src/test/java/demo/service/PaymentServiceTest.java"
        source.parent.mkdir(parents=True)
        test.parent.mkdir(parents=True)
        source.write_text(JAVA_SOURCE, encoding="utf-8")
        test.write_text(JAVA_TEST, encoding="utf-8")

        changed = SimpleNamespace(
            filename="src/main/java/demo/service/PaymentService.java",
            status="modified",
            additions=1,
            deletions=0,
            patch="""@@ -11,6 +11,7 @@ public void process(String userId) {
         String sql = "select * from payment where user_id = " + userId;
+        repository.executeQuery(sql);
     }
 }""",
        )
        index = build_repo_index(root, "repo_quality", "sha_quality", root / ".cache")
        related = resolve_diff_symbols(index, root, [changed])
        assert related["format"] == "related_context_v2", related
        assert related["status"] == "resolved", related
        symbols = related["modified_symbols"]
        assert symbols, related
        symbol = symbols[0]
        assert symbol["name"] == "process", symbol
        assert symbol["symbol_role"] == "service", symbol
        assert symbol["changed_line_count"] >= 1, symbol
        assert "executeQuery" in symbol["call_targets"], symbol
        assert symbol["has_test"] is True, symbol
        assert symbol["related_tests"], symbol

        prompt, _meta = build_prompt(
            {
                "agent_key": "security_agent",
                "display_name": "安全专家",
                "max_findings": 8,
                "applies_to": {"persona": "安全检视", "exclusive_scope": "security"},
                "related_context": related,
            },
            [changed],
        )
        parsed = json.loads(prompt)
        prompt_context = parsed["related_context"]
        assert prompt_context["format"] == "related_context_v2", prompt_context
        assert "changed_symbols" in prompt_context, prompt_context
        assert "related_tests" in prompt_context, prompt_context
        assert "executeQuery" in json.dumps(prompt_context, ensure_ascii=False), prompt_context

    print("Quality symbol context checks passed.")


if __name__ == "__main__":
    main()
