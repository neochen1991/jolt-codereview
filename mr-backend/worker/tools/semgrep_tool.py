from __future__ import annotations

import shutil
from pathlib import Path


def probe() -> dict:
    return {"tool": "semgrep", "status": "available" if shutil.which("semgrep") else "missing"}


def command(config_path: Path, targets: list[str]) -> list[str]:
    return ["semgrep", "--config", str(config_path), "--json", "--quiet", "--no-git-ignore", *targets]
