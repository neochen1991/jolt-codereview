from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from context.semantic_graph import SemanticGraph, SemanticNode  # noqa: E402
from context.source_tools import FrozenSourceTools  # noqa: E402
from tools.gitnexus_tool import impact_paths  # noqa: E402


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_frozen_source_tools_read_only_expected_head() -> None:
    with tempfile.TemporaryDirectory(prefix="jolt-source-tools-") as tmp:
        root = Path(tmp)
        _git("init", cwd=root)
        _git("config", "user.email", "test@example.com", cwd=root)
        _git("config", "user.name", "Test", cwd=root)
        source = root / "src" / "Service.java"
        source.parent.mkdir(parents=True)
        source.write_text("line1\nline2\nline3\n", encoding="utf-8")
        _git("add", ".", cwd=root)
        _git("commit", "-m", "fixture", cwd=root)
        head = _git("rev-parse", "HEAD", cwd=root)
        graph = SemanticGraph(
            nodes=(SemanticNode("symbol-1", "function", "run", "src/Service.java", 2, 2),),
            edges=(),
            status="full",
            degradations=(),
        )

        tools = FrozenSourceTools(root, head_sha=head, semantic_graph=graph)

        assert "2: line2" in tools.read_source_range("src/Service.java", 2, 2)
        assert tools.find_symbol("run")[0]["file_path"] == "src/Service.java"


def test_frozen_source_tools_reject_path_traversal_and_head_drift() -> None:
    with tempfile.TemporaryDirectory(prefix="jolt-source-tools-") as tmp:
        root = Path(tmp)
        _git("init", cwd=root)
        _git("config", "user.email", "test@example.com", cwd=root)
        _git("config", "user.name", "Test", cwd=root)
        (root / "safe.txt").write_text("safe", encoding="utf-8")
        _git("add", ".", cwd=root)
        _git("commit", "-m", "fixture", cwd=root)

        try:
            FrozenSourceTools(root, head_sha="deadbeef", semantic_graph=SemanticGraph.empty())
        except ValueError as exc:
            assert "head SHA" in str(exc)
        else:
            raise AssertionError("head drift must be rejected")

        head = _git("rev-parse", "HEAD", cwd=root)
        tools = FrozenSourceTools(root, head_sha=head, semantic_graph=SemanticGraph.empty())
        try:
            tools.read_source_range("../outside.txt", 1, 1)
        except ValueError as exc:
            assert "path" in str(exc)
        else:
            raise AssertionError("path traversal must be rejected")


def test_gitnexus_stub_never_claims_completed_analysis() -> None:
    result = impact_paths(Path("/tmp/not-used"), ["src/A.java"])

    assert result["status"] == "unsupported"
    assert result["analysis_complete"] is False


if __name__ == "__main__":
    test_frozen_source_tools_read_only_expected_head()
    test_frozen_source_tools_reject_path_traversal_and_head_drift()
    test_gitnexus_stub_never_claims_completed_analysis()
    print("source tools tests passed")
