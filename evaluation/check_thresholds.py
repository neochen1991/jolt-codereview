from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--min-precision", type=float, default=0.80)
    parser.add_argument("--min-recall", type=float, default=0.75)
    parser.add_argument("--min-high-recall", type=float, default=0.85)
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text("utf-8"))
    failures = []
    if float(report.get("precision") or 0) < args.min_precision:
        failures.append(f"precision {report.get('precision')} < {args.min_precision}")
    if float(report.get("recall") or 0) < args.min_recall:
        failures.append(f"recall {report.get('recall')} < {args.min_recall}")
    if float(report.get("high_recall") or 0) < args.min_high_recall:
        failures.append(f"high_recall {report.get('high_recall')} < {args.min_high_recall}")
    if failures:
        raise SystemExit("gold evaluation threshold failed: " + "; ".join(failures))
    print(json.dumps({"ok": True, "precision": report.get("precision"), "recall": report.get("recall"), "high_recall": report.get("high_recall")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
