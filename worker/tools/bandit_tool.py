from __future__ import annotations

import shutil


def probe() -> dict:
    return {"tool": "bandit", "status": "available" if shutil.which("bandit") else "missing"}


def command(targets: list[str]) -> list[str]:
    return ["bandit", "-f", "json", *targets]
