from __future__ import annotations

import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from context.change_intent import classify_change_intent  # noqa: E402


def test_logging_only_patch_is_behavior_preserving() -> None:
    intent = classify_change_intent(
        "src/main/java/com/acme/RefundService.java",
        "@@ -10,1 +10,2 @@\n process(refund);\n+logger.info(\"refund processed {}\", refund.id());",
    )

    assert intent.labels == ("logging_only",), intent
    assert intent.semantic_delta == "behavior_preserving", intent


def test_comment_only_patch_is_behavior_preserving() -> None:
    intent = classify_change_intent(
        "src/main/java/com/acme/RefundService.java",
        "@@ -4,1 +4,2 @@\n class RefundService {\n+    // Keep the provider request id for audit replay.\n",
    )

    assert intent.labels == ("comment_or_documentation",), intent
    assert intent.semantic_delta == "behavior_preserving", intent


def test_test_file_patch_is_classified_without_claiming_production_safety() -> None:
    intent = classify_change_intent(
        "src/test/java/com/acme/RefundServiceTest.java",
        "@@ -20,1 +20,2 @@\n verifyRefund();\n+assertThat(result.status()).isEqualTo(APPROVED);",
    )

    assert intent.labels == ("test_only",), intent
    assert intent.semantic_delta == "test_change", intent


def test_behavior_change_is_not_misclassified_as_safe() -> None:
    intent = classify_change_intent(
        "src/main/java/com/acme/RefundService.java",
        "@@ -12,1 +12,1 @@\n-return gateway.refund(order);\n+return RefundResult.success(order.id());",
    )

    assert intent.labels == ("behavior_change",), intent
    assert intent.semantic_delta == "behavior_changed", intent


def test_mixed_logging_and_behavior_change_remains_mixed() -> None:
    intent = classify_change_intent(
        "src/main/java/com/acme/RefundService.java",
        "@@ -12,1 +12,2 @@\n-return gateway.refund(order);\n+logger.info(\"refund {}\", order.id());\n+return RefundResult.success(order.id());",
    )

    assert intent.labels == ("mixed",), intent
    assert intent.semantic_delta == "unknown", intent


def test_renamed_file_uses_git_status_signal() -> None:
    intent = classify_change_intent(
        "src/main/java/com/acme/RefundCoordinator.java",
        "@@ -1,1 +1,1 @@\n-class RefundManager {}\n+class RefundCoordinator {}",
        status="renamed",
    )

    assert intent.labels == ("rename_or_move",), intent
    assert intent.semantic_delta == "behavior_preserving", intent


if __name__ == "__main__":
    test_logging_only_patch_is_behavior_preserving()
    test_comment_only_patch_is_behavior_preserving()
    test_test_file_patch_is_classified_without_claiming_production_safety()
    test_behavior_change_is_not_misclassified_as_safe()
    test_mixed_logging_and_behavior_change_remains_mixed()
    test_renamed_file_uses_git_status_signal()
    print("change intent tests passed")
