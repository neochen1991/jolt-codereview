from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import review_runtime
from review_runtime import ChangedFile, route_agents


def agent(agent_id: str, paths: list[str] | None = None, languages: list[str] | None = None) -> dict:
    return {
        "agent_id": agent_id,
        "display_name": agent_id,
        "applies_to": {
            "paths": paths or ["**/*.java"],
            "languages": languages or ["java"],
        },
    }


def main() -> None:
    original = review_runtime.route_agents_with_llm
    called = {"value": False}

    def fail_if_called(*_args, **_kwargs):
        called["value"] = True
        raise AssertionError("LLM router should not be called by default")

    review_runtime.route_agents_with_llm = fail_if_called
    try:
        files = [
            ChangedFile(
                "src/main/java/com/acme/payment/service/PaymentService.java",
                "modified",
                4,
                0,
                4,
                "+public class PaymentService {\n+  String sql = \"select * from payment\" + userId;\n+}\n",
            )
        ]
        agents = [
            agent("security_agent"),
            agent("coding_agent"),
            agent("backend_agent"),
            agent("performance_agent"),
            agent("ddd_agent"),
            agent("database_agent"),
            agent("test_agent"),
        ]
        selected = route_agents(agents, files, "standard", project_config={"routing": {}}, recorder=None, span_id="span")
        selected_ids = {item["agent_id"] for item in selected}
        assert not called["value"], "default routing unexpectedly called LLM router"
        assert {"security_agent", "coding_agent", "backend_agent", "performance_agent", "database_agent", "test_agent"}.issubset(selected_ids), selected_ids
    finally:
        review_runtime.route_agents_with_llm = original
    print({"selected": sorted(selected_ids), "llm_router_called": called["value"]})


if __name__ == "__main__":
    main()
