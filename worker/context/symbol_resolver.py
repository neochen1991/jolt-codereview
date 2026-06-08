from __future__ import annotations

from pathlib import Path
from typing import Any

from context.repo_index import resolve_diff_symbols as _resolve_diff_symbols


def resolve_diff_symbols(index_info: dict[str, Any], worktree: Path, files: list[Any]) -> dict[str, Any]:
    return _resolve_diff_symbols(index_info, worktree, files)
