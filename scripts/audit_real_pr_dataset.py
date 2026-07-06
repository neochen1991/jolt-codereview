from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


IGNORED_MANIFESTS = {"latest-export-report.json"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def norm(value: Any) -> str:
    return str(value or "").strip()


def is_negative(item: dict[str, Any]) -> bool:
    return norm(item.get("ground_truth")).lower() == "negative"


def manifest_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(
        file
        for file in path.glob("*.json")
        if file.name not in IGNORED_MANIFESTS
    )


def manifest_mr_id(project_id: str, manifest: dict[str, Any]) -> str:
    repo = manifest.get("repository") if isinstance(manifest.get("repository"), dict) else {}
    owner = norm(repo.get("owner") or manifest.get("owner"))
    name = norm(repo.get("repo") or manifest.get("repo"))
    number = norm(manifest.get("pull_number") or manifest.get("number"))
    explicit = norm(manifest.get("merge_request_id") or manifest.get("mr_id"))
    if explicit:
        return explicit
    if owner and name and number:
        return f"mr_real_{project_id}_{owner}_{name}_{number}".replace("/", "_").replace("-", "_").lower()
    return ""


def load_manifests(path: Path, project_id: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    manifests: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for file in manifest_files(path):
        try:
            item = json.loads(file.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{file}: invalid JSON: {exc}")
            continue
        fixture_id = norm(item.get("id") or file.stem)
        mr_id = manifest_mr_id(project_id, item)
        if not fixture_id:
            failures.append(f"{file}: missing id")
        if not mr_id:
            failures.append(f"{file}: cannot derive mr_id")
        if fixture_id in manifests:
            failures.append(f"{file}: duplicate manifest id {fixture_id}")
        manifests[fixture_id] = {**item, "_file": str(file), "_id": fixture_id, "_mr_id": mr_id}
    return manifests, failures


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifests, failures = load_manifests(Path(args.manifest_dir), args.project_id)
    gold = read_jsonl(Path(args.gold))
    findings = read_jsonl(Path(args.findings))

    gold_ids: set[str] = set()
    duplicate_gold_ids: list[str] = []
    for item in gold:
        gold_id = norm(item.get("id"))
        if not gold_id:
            failures.append("gold item missing id")
        elif gold_id in gold_ids:
            duplicate_gold_ids.append(gold_id)
        gold_ids.add(gold_id)
        if not norm(item.get("mr_id")):
            failures.append(f"gold {gold_id or '<missing>'}: missing mr_id")
        if not is_negative(item):
            if not norm(item.get("rule_id")):
                failures.append(f"gold {gold_id or '<missing>'}: missing rule_id")
            if not norm(item.get("file") or item.get("file_path")):
                failures.append(f"gold {gold_id or '<missing>'}: missing file/file_path")
    failures.extend(f"duplicate gold id {gold_id}" for gold_id in sorted(set(duplicate_gold_ids)))

    finding_ids: set[str] = set()
    duplicate_finding_ids: list[str] = []
    for item in findings:
        finding_id = norm(item.get("finding_id") or item.get("id"))
        if finding_id:
            if finding_id in finding_ids:
                duplicate_finding_ids.append(finding_id)
            finding_ids.add(finding_id)
        if not norm(item.get("mr_id") or item.get("merge_request_id")):
            failures.append(f"finding {finding_id or '<missing>'}: missing mr_id/merge_request_id")
    failures.extend(f"duplicate finding id {finding_id}" for finding_id in sorted(set(duplicate_finding_ids)))

    positive_gold_mrs = {norm(item.get("mr_id")) for item in gold if not is_negative(item) and norm(item.get("mr_id"))}
    negative_gold_mrs = {norm(item.get("mr_id")) for item in gold if is_negative(item) and norm(item.get("mr_id"))}
    finding_mrs = {norm(item.get("mr_id") or item.get("merge_request_id")) for item in findings if norm(item.get("mr_id") or item.get("merge_request_id"))}
    manifest_mrs = {norm(item.get("_mr_id")) for item in manifests.values() if norm(item.get("_mr_id"))}

    missing_manifest_for_gold = sorted((positive_gold_mrs | negative_gold_mrs) - manifest_mrs)
    manifests_without_gold = sorted(manifest_mrs - (positive_gold_mrs | negative_gold_mrs))
    positive_mrs_without_findings = sorted(positive_gold_mrs - finding_mrs)
    negative_mrs_with_findings = sorted(negative_gold_mrs & finding_mrs)
    findings_without_gold = sorted(finding_mrs - (positive_gold_mrs | negative_gold_mrs))

    if len(manifests) < args.min_manifests:
        failures.append(f"manifest_count {len(manifests)} < {args.min_manifests}")
    if len(positive_gold_mrs) < args.min_positive_mrs:
        failures.append(f"positive_gold_mr_count {len(positive_gold_mrs)} < {args.min_positive_mrs}")
    positive_gold_count = len([item for item in gold if not is_negative(item)])
    if positive_gold_count < args.min_gold:
        failures.append(f"gold_count {positive_gold_count} < {args.min_gold}")
    if len(negative_gold_mrs) < args.min_negative_mrs:
        failures.append(f"negative_gold_mr_count {len(negative_gold_mrs)} < {args.min_negative_mrs}")
    if args.require_manifest_for_gold and missing_manifest_for_gold:
        failures.append(f"gold MRs without manifest: {', '.join(missing_manifest_for_gold)}")
    if args.require_gold_for_manifest and manifests_without_gold:
        failures.append(f"manifests without gold labels: {', '.join(manifests_without_gold)}")
    if args.require_finding_for_positive_mr and positive_mrs_without_findings:
        failures.append(f"positive gold MRs without findings: {', '.join(positive_mrs_without_findings)}")
    if args.require_negative_no_findings and negative_mrs_with_findings:
        failures.append(f"negative MRs with findings: {', '.join(negative_mrs_with_findings)}")
    if args.require_gold_for_finding and findings_without_gold:
        failures.append(f"finding MRs without gold labels: {', '.join(findings_without_gold)}")

    return {
        "ok": not failures,
        "manifest_count": len(manifests),
        "positive_gold_mr_count": len(positive_gold_mrs),
        "negative_gold_mr_count": len(negative_gold_mrs),
        "gold_count": positive_gold_count,
        "finding_count": len(findings),
        "finding_mr_count": len(finding_mrs),
        "missing_manifest_for_gold": missing_manifest_for_gold,
        "manifests_without_gold": manifests_without_gold,
        "positive_mrs_without_findings": positive_mrs_without_findings,
        "negative_mrs_with_findings": negative_mrs_with_findings,
        "findings_without_gold": findings_without_gold,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-dir", default="evaluation/real_prs")
    parser.add_argument("--gold", default="evaluation/real_gold_set.jsonl")
    parser.add_argument("--findings", default="evaluation/real_findings.jsonl")
    parser.add_argument("--project-id", default="project_default")
    parser.add_argument("--min-manifests", type=int, default=0)
    parser.add_argument("--min-positive-mrs", type=int, default=0)
    parser.add_argument("--min-gold", type=int, default=0)
    parser.add_argument("--min-negative-mrs", type=int, default=0)
    parser.add_argument("--require-manifest-for-gold", action="store_true")
    parser.add_argument("--require-gold-for-manifest", action="store_true")
    parser.add_argument("--require-finding-for-positive-mr", action="store_true")
    parser.add_argument("--require-negative-no-findings", action="store_true")
    parser.add_argument("--require-gold-for-finding", action="store_true")
    args = parser.parse_args()
    report = audit(args)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not report["ok"]:
        raise SystemExit("real PR dataset audit failed")


if __name__ == "__main__":
    main()
