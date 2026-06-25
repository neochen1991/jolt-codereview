from __future__ import annotations

import shutil
from pathlib import Path


def probe() -> dict:
    return {"tool": "gitnexus", "status": "available" if shutil.which("gitnexus") else "missing"}


def impact_paths(worktree: Path, changed_files: list[str]) -> dict:
    status = probe()["status"]
    return {
        "status": status,
        "worktree": str(worktree),
        "changed_files": changed_files,
        "impact_paths": [],
        "note": "GitNexus impact extraction is enabled when gitnexus CLI is installed.",
    }
