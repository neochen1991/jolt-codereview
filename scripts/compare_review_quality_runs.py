from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def _string_set(values: Iterable[Any]) -> set[str]:
    return {str(value) for value in values if str(value).strip()}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _finding_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for finding in snapshot.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        finding_id = str(finding.get("finding_id") or finding.get("id") or "").strip()
        if finding_id:
            result[finding_id] = finding
    return result


def _normalize_reasons(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, tuple[str, ...]] = {}
    for candidate_id, reasons in value.items():
        raw = reasons if isinstance(reasons, list) else [reasons]
        normalized[str(candidate_id)] = tuple(sorted(_string_set(raw)))
    return normalized


def compare_worker_runs(baseline: dict[str, Any], repeated: dict[str, Any]) -> dict[str, Any]:
    baseline_candidates = _string_set(baseline.get("candidate_ids") or [])
    repeated_candidates = _string_set(repeated.get("candidate_ids") or [])
    baseline_findings = _finding_map(baseline)
    repeated_findings = _finding_map(repeated)
    common_findings = set(baseline_findings) & set(repeated_findings)
    severity_matches = sum(
        1
        for finding_id in common_findings
        if str(baseline_findings[finding_id].get("severity") or "")
        == str(repeated_findings[finding_id].get("severity") or "")
    )
    severity_agreement = severity_matches / len(common_findings) if common_findings else 1.0
    baseline_reasons = _normalize_reasons(baseline.get("decision_reasons"))
    repeated_reasons = _normalize_reasons(repeated.get("decision_reasons"))
    baseline_context = _string_set(baseline.get("context_hashes") or [])
    repeated_context = _string_set(repeated.get("context_hashes") or [])
    baseline_llm = _string_set(baseline.get("llm_fingerprints") or [])
    repeated_llm = _string_set(repeated.get("llm_fingerprints") or [])
    baseline_artifacts = _string_set(baseline.get("artifact_hashes") or [])
    repeated_artifacts = _string_set(repeated.get("artifact_hashes") or [])

    report = {
        "candidate_jaccard": round(_jaccard(baseline_candidates, repeated_candidates), 6),
        "finding_jaccard": round(_jaccard(set(baseline_findings), set(repeated_findings)), 6),
        "severity_agreement": round(severity_agreement, 6),
        "decision_reason_match": baseline_reasons == repeated_reasons,
        "context_hash_match": baseline_context == repeated_context,
        "llm_fingerprint_match": baseline_llm == repeated_llm,
        "artifact_hash_match": baseline_artifacts == repeated_artifacts,
        "candidate_only_in_baseline": sorted(baseline_candidates - repeated_candidates),
        "candidate_only_in_repeated": sorted(repeated_candidates - baseline_candidates),
        "finding_only_in_baseline": sorted(set(baseline_findings) - set(repeated_findings)),
        "finding_only_in_repeated": sorted(set(repeated_findings) - set(baseline_findings)),
    }
    report["exact_match"] = bool(
        report["candidate_jaccard"] == 1.0
        and report["finding_jaccard"] == 1.0
        and report["severity_agreement"] == 1.0
        and report["decision_reason_match"]
        and report["context_hash_match"]
        and report["llm_fingerprint_match"]
        and report["artifact_hash_match"]
    )
    return report


def _read_snapshot(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"snapshot must be a JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--repeated", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = compare_worker_runs(_read_snapshot(Path(args.baseline)), _read_snapshot(Path(args.repeated)))
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
    print(output)
    if not report["exact_match"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
