from __future__ import annotations

import shutil


def probe() -> dict:
    return {"tool": "ruff", "status": "available" if shutil.which("ruff") else "missing"}


def command(targets: list[str]) -> list[str]:
    return ["ruff", "check", "--output-format", "json", *targets]
