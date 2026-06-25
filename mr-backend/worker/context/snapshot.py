from __future__ import annotations

import re
from typing import Any

from diff.slicer import extract_added_lines
from tools.gitnexus_tool import probe as probe_gitnexus
from tools.tree_sitter_tool import build_diff_graph, probe as probe_tree_sitter


def language_for_file(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".py"):
        return "python"
    if lowered.endswith((".ts", ".tsx")):
        return "typescript"
    if lowered.endswith((".js", ".jsx")):
        return "javascript"
    if lowered.endswith(".java"):
        return "java"
    if lowered.endswith(".go"):
        return "go"
    if lowered.endswith((".kt", ".kts")):
        return "kotlin"
    if lowered.endswith(".vue"):
        return "javascript"
    if lowered.endswith((".css", ".scss", ".less", ".html")):
        return "frontend"
    return "unknown"


def build_code_context_snapshot(files: list[Any]) -> dict[str, Any]:
    tree_sitter_status = probe_tree_sitter()
    tree_sitter_graph = build_diff_graph(files)
    gitnexus_status = probe_gitnexus()
    return {
        "status": "indexed",
        "index_kind": "diff_symbol_index",
        "changed_files": [
            {
                "file_path": changed.filename,
                "language": language_for_file(changed.filename),
                "imports": [
                    text.strip()
                    for _, text in extract_added_lines(changed.patch)
                    if text.strip().startswith(("import ", "from ", "require(", "import("))
                ][:20],
                "symbols": [
                    text.strip()
                    for _, text in extract_added_lines(changed.patch)
                    if re.search(r"\b(class|def|function|const|let|interface|type)\b", text)
                ][:20],
            }
            for changed in files
        ],
        "tree_sitter": {
            **tree_sitter_status,
            **tree_sitter_graph,
        },
        "gitnexus": {
            **gitnexus_status,
            "impact_paths": [],
        },
        "supported_tools": ["find_symbol", "tests_for", "siblings_in_dir"],
        "note": "Diff-local symbol index is active; configure analysis_worktree_path or repository git_url to let static tools use a full repository worktree.",
    }
