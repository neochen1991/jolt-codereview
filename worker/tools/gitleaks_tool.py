from __future__ import annotations

import shutil
from pathlib import Path


def probe() -> dict:
    return {"tool": "gitleaks", "status": "available" if shutil.which("gitleaks") else "missing"}


def command(source: Path, report_path: Path) -> list[str]:
    return ["gitleaks", "detect", "--no-git", "--source", str(source), "--report-format", "json", "--report-path", str(report_path)]
