from __future__ import annotations

import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from tools.code_graph_rules import evaluate_code_graph_rules  # noqa: E402


class ChangedFile:
    def __init__(self, filename: str) -> None:
        self.filename = filename


def _graph(import_text: str) -> dict:
    file_path = "src/main/java/com/acme/api/PaymentController.java"
    return {
        "status": "indexed",
        "classes": [
            {
                "file_path": file_path,
                "name": "PaymentController",
                "line": 5,
                "line_end": 20,
                "snippet": "@RestController class PaymentController {}",
            }
        ],
        "functions": [],
        "callers": [],
        "imports": [{"file_path": file_path, "line": 3, "import": import_text}],
    }


def test_repository_substring_in_dto_type_does_not_create_layer_violation() -> None:
    file_path = "src/main/java/com/acme/api/PaymentController.java"

    findings = evaluate_code_graph_rules(
        _graph("import com.acme.api.dto.RepositorySearchResponse;"),
        [ChangedFile(file_path)],
    )

    assert not any(item["tool_rule_id"] == "DDD-LAYER-001" for item in findings), findings


def test_repository_substring_in_unrelated_package_segment_does_not_create_layer_violation() -> None:
    file_path = "src/main/java/com/acme/api/PaymentController.java"

    findings = evaluate_code_graph_rules(
        _graph("import com.acme.repositorymodel.PaymentView;"),
        [ChangedFile(file_path)],
    )

    assert not any(item["tool_rule_id"] == "DDD-LAYER-001" for item in findings), findings


def test_explicit_repository_path_still_creates_layer_violation() -> None:
    file_path = "src/main/java/com/acme/api/PaymentController.java"

    findings = evaluate_code_graph_rules(
        _graph("import com.acme.payment.repository.PaymentRepository;"),
        [ChangedFile(file_path)],
    )

    layer_findings = [item for item in findings if item["tool_rule_id"] == "DDD-LAYER-001"]
    assert len(layer_findings) == 1, findings
    assert "PaymentRepository" in layer_findings[0]["evidence"], layer_findings


if __name__ == "__main__":
    test_repository_substring_in_dto_type_does_not_create_layer_violation()
    test_repository_substring_in_unrelated_package_segment_does_not_create_layer_violation()
    test_explicit_repository_path_still_creates_layer_violation()
    print("code graph repository dependency tests passed")
