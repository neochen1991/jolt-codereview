from __future__ import annotations

import shutil
from pathlib import Path


def probe() -> dict:
    return {"tool": "gitnexus", "status": "available" if shutil.which("gitnexus") else "missing"}


def impact_paths(worktree: Path, changed_files: list[str]) -> dict:
    return {
        "status": "unsupported",
        "analysis_complete": False,
        "cli_status": probe()["status"],
        "worktree": str(worktree),
        "changed_files": changed_files,
        "impact_paths": [],
        "note": "GitNexus CLI probing exists, but impact extraction is not implemented; no-impact must not be inferred.",
    }
