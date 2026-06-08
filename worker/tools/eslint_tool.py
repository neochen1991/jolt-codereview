from __future__ import annotations

import shutil


def probe() -> dict:
    return {"tool": "eslint", "status": "available" if shutil.which("eslint") else "missing"}


def command(targets: list[str]) -> list[str]:
    return ["eslint", "--format", "json", *targets]
