"""Runtime encoding defaults for local Python entrypoints.

Windows console sessions often default to GBK, while this project logs and
prints Chinese review data as UTF-8 JSON. Python imports this module
automatically when the repository root is on sys.path, which covers direct
`python scripts/...` runs and the review worker started from the project root.
"""

from __future__ import annotations

import os
import sys


os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
