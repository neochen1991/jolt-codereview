from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.quality.diff_scope import DiffScope, canonical_review_path
from orchestration.nodes.judge_findings import (
    filter_to_diff_introduced_findings,
    filter_tool_observations_to_added_lines,
)
from orchestration.nodes.verify_findings import verify_candidate_findings


@dataclass
class ChangedFile:
    filename: str
    patch: str
    status: str = "modified"


PATCH = """@@ -8,3 +8,4 @@ public void update() {
     authorize();
+    repository.update(request);
     audit();
 }"""


def finding(*, file_path: str = "src/AuthService.java", line: int = 9) -> dict:
    return {
        "agent_id": "security_agent",
        "severity": "high",
        "confidence": 0.92,
        "dedupe_hash": "candidate",
        "file_path": file_path,
        "line_start": line,
        "line_end": line,
        "title": "更新接口缺少权限验证",
        "problem_description": "未授权用户可以修改数据。",
        "evidence": "repository.update(request)",
        "recommendation": "在更新前执行权限校验。",
        "covered_rules": ["SEC-AUTH-001"],
    }


def test_windows_paths_resolve_to_canonical_git_path() -> None:
    scope = DiffScope.from_files([ChangedFile("src/AuthService.java", PATCH)])

    assert canonical_review_path(r".\src\AuthService.java") == "src/AuthService.java"
    assert scope.resolve_path(r"b\src\AuthService.java") == "src/AuthService.java"


def test_verifier_accepts_exact_added_line() -> None:
    scope = DiffScope.from_files([ChangedFile("src/AuthService.java", PATCH)])

    accepted, rejected = verify_candidate_findings(
        [finding(line=9)],
        scope.changed_files,
        {"security_agent": {"min_confidence": 0.75}},
        set(),
        source_snippet_loader=lambda _file, _line, window=5: "repository.update(request)",
        diff_scope=scope,
    )

    assert len(accepted) == 1, (accepted, rejected)
    assert rejected == []


def test_verifier_rejects_context_line_even_when_inside_hunk() -> None:
    scope = DiffScope.from_files([ChangedFile("src/AuthService.java", PATCH)])

    accepted, rejected = verify_candidate_findings(
        [finding(line=8)],
        scope.changed_files,
        {"security_agent": {"min_confidence": 0.75}},
        set(),
        source_snippet_loader=lambda _file, _line, window=5: "authorize();",
        diff_scope=scope,
    )

    assert accepted == []
    assert "line_not_added_by_diff" in rejected[0]["rejected_reasons"]


def test_judge_does_not_reanchor_nearby_context_line() -> None:
    kept, rejected = filter_to_diff_introduced_findings(
        [finding(line=8)],
        [ChangedFile("src/AuthService.java", PATCH)],
    )

    assert kept == []
    assert rejected[0]["line_start"] == 8
    assert rejected[0]["rejected_reasons"] == ["not_on_added_or_modified_line"]


def test_judge_rejects_finding_from_unchanged_file() -> None:
    kept, rejected = filter_to_diff_introduced_findings(
        [finding(file_path="src/Unchanged.java", line=9)],
        [ChangedFile("src/AuthService.java", PATCH)],
    )

    assert kept == []
    assert rejected[0]["rejected_reasons"] == ["file_not_changed_by_diff"]


def test_missing_patch_fails_closed() -> None:
    kept, rejected = filter_to_diff_introduced_findings(
        [finding(line=9)],
        [ChangedFile("src/AuthService.java", "")],
    )

    assert kept == []
    assert rejected[0]["rejected_reasons"] == ["diff_patch_unavailable"]


def test_tool_observation_from_unchanged_file_is_rejected() -> None:
    kept, rejected = filter_tool_observations_to_added_lines(
        [
            {
                "tool_name": "semgrep",
                "rule_id": "SEC-AUTH-001",
                "file_path": "src/Unchanged.java",
                "line_start": 9,
                "message": "missing authorization",
            }
        ],
        [ChangedFile("src/AuthService.java", PATCH)],
    )

    assert kept == []
    assert rejected[0]["rejected_reasons"] == ["tool_observation_file_not_changed"]


if __name__ == "__main__":
    test_windows_paths_resolve_to_canonical_git_path()
    test_verifier_accepts_exact_added_line()
    test_verifier_rejects_context_line_even_when_inside_hunk()
    test_judge_does_not_reanchor_nearby_context_line()
    test_judge_rejects_finding_from_unchanged_file()
    test_missing_patch_fails_closed()
    test_tool_observation_from_unchanged_file_is_rejected()
