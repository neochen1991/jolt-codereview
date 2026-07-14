from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mr-backend" / "worker"))

fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

import review_runtime
from review_runtime import ChangedFile, route_agents, router_prompt_payload


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
    prompt_payload = router_prompt_payload(
        [
            {
                **agent("security_agent"),
                "bound_rules": [
                    {
                        "rule_id": "SEC-CMD-001",
                        "title": "命令执行安全",
                        "required_evidence": "外部输入来源；命令执行 sink；缺少白名单",
                    }
                ],
                "custom_skills": ["secure-review-skill"],
                "skill_assets": [
                    {"asset_path": "SKILL.md", "asset_type": "skill"},
                    {"asset_path": "references/security-rules.md", "asset_type": "reference"},
                ],
            }
        ],
        [
            ChangedFile(
                "src/main/java/com/acme/payment/service/CommandService.java",
                "modified",
                2,
                0,
                2,
                "+Runtime.getRuntime().exec(request.getParameter(\"cmd\"));\n",
            )
        ],
    )
    router_agent = prompt_payload["agents"][0]
    assert router_agent["bound_config"]["bound_rules"][0]["rule_id"] == "SEC-CMD-001", router_agent
    assert router_agent["bound_config"]["custom_skills"] == ["secure-review-skill"], router_agent
    assert "references/security-rules.md" in router_agent["bound_config"]["skill_asset_paths"], router_agent
    assert "不能因为绑定规则或 Skill 就强制选择" in prompt_payload["policy"], prompt_payload["policy"]

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

        dependency_files = [
            ChangedFile(
                "dubbo-dependencies-bom/pom.xml",
                "modified",
                1,
                1,
                2,
                "-<log4j2.version>2.26.0</log4j2.version>\n+<log4j2.version>2.26.1</log4j2.version>\n",
            )
        ]
        dependency_agents = [
            agent("security_agent", paths=["**/*"], languages=["xml"]),
            agent("coding_agent", paths=["**/*"], languages=["xml"]),
            agent("dependency_agent", paths=["**/pom.xml"], languages=["xml"]),
            agent("test_agent", paths=["**/*"], languages=["xml"]),
        ]
        fast_selected = route_agents(dependency_agents, dependency_files, "fast", project_config={"routing": {}}, recorder=None, span_id="span")
        fast_ids = [item["agent_id"] for item in fast_selected]
        assert fast_ids[0] == "dependency_agent", fast_ids
        assert "dependency_agent" in fast_ids, fast_ids
    finally:
        review_runtime.route_agents_with_llm = original
    print({"selected": sorted(selected_ids), "llm_router_called": called["value"]})


if __name__ == "__main__":
    main()
