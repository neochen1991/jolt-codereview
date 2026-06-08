from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from review_runtime import ChangedFile, load_skill_summary


def main() -> None:
    java_summary = load_skill_summary(
        "security-review",
        [ChangedFile("src/main/java/com/acme/ProjectController.java", "modified", 1, 0, 1, "+class ProjectController {}")],
    )
    python_summary = load_skill_summary(
        "security-review",
        [ChangedFile("app/views.py", "modified", 1, 0, 1, "+eval(request.args['x'])")],
    )
    go_summary = load_skill_summary(
        "coding-review",
        [ChangedFile("cmd/server/main.go", "modified", 1, 0, 1, "+resp, _ := http.Get(url)")],
    )
    assert "Security Core Standard" in java_summary, java_summary[:500]
    assert "Security Java Standard" in java_summary, java_summary[:500]
    assert "Security Agent Java Web 代码规范" in java_summary, java_summary[:500]
    assert "Security Core Standard" in python_summary, python_summary[:500]
    assert "Security Python Standard" in python_summary, python_summary[:500]
    assert "Security Agent Java Web 代码规范" not in python_summary, python_summary[:500]
    assert "Coding Go Standard" in go_summary, go_summary[:500]
    print(json.dumps({"java_layers": 3, "python_avoids_java_standard": True, "go_layer_loaded": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
