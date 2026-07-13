from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from context.semantic_graph import SemanticGraph, SemanticNode


class FrozenSourceTools:
    def __init__(self, worktree: Path, *, head_sha: str, semantic_graph: SemanticGraph):
        self.worktree = worktree.resolve()
        self.head_sha = str(head_sha).strip()
        self.semantic_graph = semantic_graph
        if not self.worktree.is_dir():
            raise ValueError(f"source worktree does not exist: {self.worktree}")
        actual = subprocess.run(
            ["git", "-C", str(self.worktree), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not self.head_sha or actual != self.head_sha:
            raise ValueError(f"source worktree head SHA mismatch: expected {self.head_sha}, actual {actual}")

    def _safe_path(self, file_path: str) -> Path:
        relative = Path(str(file_path or "").replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("source path rejected")
        resolved = (self.worktree / relative).resolve()
        try:
            resolved.relative_to(self.worktree)
        except ValueError as exc:
            raise ValueError("source path outside frozen worktree") from exc
        if not resolved.is_file():
            raise ValueError(f"source path not found: {file_path}")
        return resolved

    def read_source_range(self, file_path: str, line_start: int, line_end: int) -> str:
        path = self._safe_path(file_path)
        lines = path.read_text("utf-8", errors="replace").splitlines()
        start = max(1, int(line_start))
        end = min(len(lines), max(start, int(line_end)))
        return "\n".join(f"{line}: {lines[line - 1]}" for line in range(start, end + 1))

    @staticmethod
    def _node_record(node: SemanticNode) -> dict[str, Any]:
        return {
            "symbol_id": node.node_id,
            "kind": node.kind,
            "name": node.name,
            "file_path": node.file_path,
            "line_start": node.line_start,
            "line_end": node.line_end,
        }

    def find_symbol(self, name: str) -> list[dict[str, Any]]:
        return [self._node_record(node) for node in self.semantic_graph.find_nodes(str(name))]

    def find_callers(self, name: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for target in self.semantic_graph.find_nodes(str(name), {"function"}):
            for edge in self.semantic_graph.incoming(target.node_id, "calls"):
                result.append({**self._node_record(self.semantic_graph.node(edge.source_id)), "confidence": edge.confidence, "resolver": edge.resolver})
        return result

    def find_callees(self, symbol_id: str) -> list[dict[str, Any]]:
        return [
            {**self._node_record(self.semantic_graph.node(edge.target_id)), "confidence": edge.confidence, "resolver": edge.resolver}
            for edge in self.semantic_graph.outgoing(symbol_id, "calls")
        ]

    def find_implementations(self, name: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for target in self.semantic_graph.find_nodes(str(name), {"interface", "class"}):
            for edge in self.semantic_graph.incoming(target.node_id, "implements"):
                result.append({**self._node_record(self.semantic_graph.node(edge.source_id)), "confidence": edge.confidence, "resolver": edge.resolver})
        return result

    def find_tests(self, name: str) -> list[dict[str, Any]]:
        lowered = str(name).lower()
        return [
            self._node_record(node)
            for node in self.semantic_graph.nodes
            if node.kind == "test" and (lowered in node.name.lower() or lowered in node.file_path.lower())
        ]

    def find_config_refs(self, name: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for target in self.semantic_graph.find_nodes(str(name)):
            for edge in self.semantic_graph.incoming(target.node_id, "reads_config"):
                result.append({**self._node_record(self.semantic_graph.node(edge.source_id)), "confidence": edge.confidence})
        return result
