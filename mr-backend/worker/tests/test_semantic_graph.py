from __future__ import annotations

import sys
import tempfile
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from context.semantic_graph import SemanticGraph, semantic_graph_from_tree_sitter  # noqa: E402
from tools.tree_sitter_tool import _build_index, build_graph  # noqa: E402


def _raw_graph() -> dict:
    return {
        "status": "indexed",
        "parsed_file_count": 6,
        "file_count": 6,
        "classes": [
            {
                "file_path": "src/PaymentGateway.java",
                "name": "PaymentGateway",
                "line": 1,
                "line_end": 3,
                "node_type": "interface_declaration",
                "snippet": "public interface PaymentGateway { void pay(); }",
            },
            {
                "file_path": "src/StripeGateway.java",
                "name": "StripeGateway",
                "line": 1,
                "line_end": 8,
                "node_type": "class_declaration",
                "snippet": "public class StripeGateway implements PaymentGateway { public void pay() {} }",
            },
            {
                "file_path": "src/PaypalGateway.java",
                "name": "PaypalGateway",
                "line": 1,
                "line_end": 8,
                "node_type": "class_declaration",
                "snippet": "public class PaypalGateway implements PaymentGateway { public void pay() {} }",
            },
            {
                "file_path": "src/PaymentGatewayTest.java",
                "name": "PaymentGatewayTest",
                "line": 1,
                "line_end": 12,
                "node_type": "class_declaration",
                "snippet": "public class PaymentGatewayTest { void verifiesPaymentGateway() {} }",
            },
        ],
        "functions": [
            {"file_path": "src/A.java", "name": "process", "line": 10, "line_end": 12, "snippet": "void process(String id) {}"},
            {"file_path": "src/B.java", "name": "process", "line": 20, "line_end": 22, "snippet": "void process(long id) {}"},
            {"file_path": "src/StripeGateway.java", "name": "pay", "line": 3, "line_end": 5, "snippet": "void pay() {}"},
        ],
        "imports": [
            {
                "file_path": "src/PaymentGatewayTest.java",
                "line": 1,
                "import": "import com.acme.PaymentGateway;",
            }
        ],
        "callers": [
            {"file_path": "src/Caller.java", "caller": "run", "callee": "process", "line": 7, "receiver": "service"},
            {"file_path": "src/Caller.java", "caller": "charge", "callee": "pay", "line": 12, "receiver": "gateway"},
        ],
        "config_refs": [
            {
                "file_path": "src/Caller.java",
                "caller": "charge",
                "line": 13,
                "config_key": "payment.timeout.ms",
                "snippet": "environment.getProperty(\"payment.timeout.ms\")",
            }
        ],
        "parse_errors": [],
    }


def test_explicit_interface_implementation_is_audited_syntax_edge() -> None:
    graph = semantic_graph_from_tree_sitter(_raw_graph())

    edges = [edge for edge in graph.edges if edge.kind == "implements"]

    assert len(edges) == 2
    assert {edge.confidence for edge in edges} == {"syntax"}
    assert {graph.node(edge.target_id).name for edge in edges} == {"PaymentGateway"}


def test_unmodified_caller_remains_discoverable_without_claiming_typed_resolution() -> None:
    graph = semantic_graph_from_tree_sitter(_raw_graph())

    edges = [edge for edge in graph.edges if edge.kind == "calls" and graph.node(edge.target_id).name == "pay"]

    assert edges
    assert {graph.node(edge.source_id).file_path for edge in edges} == {"src/Caller.java"}
    assert {edge.confidence for edge in edges} == {"heuristic"}


def test_test_import_and_config_read_create_audited_semantic_edges() -> None:
    graph = semantic_graph_from_tree_sitter(_raw_graph())

    test_edges = [edge for edge in graph.edges if edge.kind == "tested_by"]
    assert len(test_edges) == 1
    assert graph.node(test_edges[0].source_id).name == "PaymentGateway"
    assert graph.node(test_edges[0].target_id).kind == "test"
    assert test_edges[0].confidence == "syntax"

    config_edges = [edge for edge in graph.edges if edge.kind == "reads_config"]
    assert len(config_edges) == 1
    assert graph.node(config_edges[0].target_id).kind == "config"
    assert graph.node(config_edges[0].target_id).name == "payment.timeout.ms"
    assert graph.node(config_edges[0].source_id).file_path == "src/Caller.java"
    assert config_edges[0].confidence == "syntax"


def test_ambiguous_same_name_call_is_never_promoted_to_typed_edge() -> None:
    graph = semantic_graph_from_tree_sitter(_raw_graph())

    edges = [edge for edge in graph.edges if edge.kind == "calls" and graph.node(edge.target_id).name == "process"]

    assert len(edges) == 2
    assert {edge.confidence for edge in edges} == {"heuristic"}


def test_graph_serialization_keeps_parse_degradation() -> None:
    raw = _raw_graph()
    raw["status"] = "timeout_partial"
    raw["parse_errors"] = [{"file_path": "src/Broken.java", "error": "parse_failed"}]

    graph = semantic_graph_from_tree_sitter(raw)
    payload = graph.to_record()

    assert payload["status"] == "partial"
    assert payload["degradations"][0]["file_path"] == "src/Broken.java"


def test_tree_sitter_index_preserves_symbol_ranges_and_node_types() -> None:
    graph = _build_index(
        [
            (
                "src/Gateway.java",
                "public interface Gateway {\n  void pay();\n}\n",
            )
        ],
        {"index_kind": "test"},
    )

    interface = graph["classes"][0]
    method = graph["functions"][0]
    assert interface["node_type"] == "interface_declaration"
    assert interface["line_end"] == 3
    assert method["line_end"] >= method["line"]


def test_changed_files_are_prioritized_without_losing_repository_scan() -> None:
    with tempfile.TemporaryDirectory(prefix="jolt-semantic-priority-") as tmp:
        root = Path(tmp)
        changed = root / "module-a" / "ChangedZ.java"
        caller = root / "module-b" / "Caller.java"
        changed.parent.mkdir(parents=True)
        caller.parent.mkdir(parents=True)
        changed.write_text("class ChangedZ { void changed() {} }\n", encoding="utf-8")
        caller.write_text("class Caller { void call() {} }\n", encoding="utf-8")

        graph = build_graph(root, {"include_paths": ["module-a/ChangedZ.java"], "max_files": 2})

        indexed_paths = {item["file_path"] for item in graph["classes"]}
        assert indexed_paths == {"module-a/ChangedZ.java", "module-b/Caller.java"}


if __name__ == "__main__":
    test_explicit_interface_implementation_is_audited_syntax_edge()
    test_unmodified_caller_remains_discoverable_without_claiming_typed_resolution()
    test_test_import_and_config_read_create_audited_semantic_edges()
    test_ambiguous_same_name_call_is_never_promoted_to_typed_edge()
    test_graph_serialization_keeps_parse_degradation()
    test_tree_sitter_index_preserves_symbol_ranges_and_node_types()
    test_changed_files_are_prioritized_without_losing_repository_scan()
    print("semantic graph tests passed")
