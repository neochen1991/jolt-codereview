from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rules.registry import agent_owners_for_rule, categories_for_agent, category_for_rule

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GOLD_PATHS = (REPO_ROOT / "evaluation" / "real_gold_set.jsonl", REPO_ROOT / "evaluation" / "gold_set.jsonl")
DEFAULT_FINDING_PATHS = (REPO_ROOT / "evaluation" / "real_findings.jsonl",)


@dataclass(frozen=True)
class Example:
    source: str
    label: str
    rule_id: str
    category: str
    severity: str
    file_path: str
    line: int | None
    snippet: str
    evidence_keywords: list[str]
    score: float
    title: str = ""
    problem_description: str = ""
    recommendation: str = ""
    last_seen: str = ""

    def as_prompt_item(self) -> dict[str, Any]:
        item = {
            "source": self.source,
            "label": self.label,
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "file_path": self.file_path,
            "line": self.line,
            "snippet": self.snippet,
            "evidence_keywords": self.evidence_keywords[:8],
            "usage_policy": (
                "expected_finding 表示相似结构应重点核验并给出精确证据；"
                "skip_false_positive 表示历史相似问题被人工判为误报，只有新增源码证据时才输出；"
                "boundary_other_expert 表示问题真实存在但属于其他专家职责，当前专家遇到相似结构时应跳过。"
            ),
        }
        if self.title:
            item["title"] = self.title
        if self.problem_description:
            item["problem_description"] = self.problem_description
        if self.recommendation:
            item["recommendation"] = self.recommendation
        return item


def _language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".java": "java",
        ".kt": "java",
        ".scala": "java",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".vue": "javascript",
        ".py": "python",
        ".go": "go",
        ".sql": "sql",
        ".yml": "config",
        ".yaml": "config",
        ".properties": "config",
        ".xml": "xml",
        ".md": "markdown",
    }.get(suffix, suffix.lstrip(".") or "unknown")


def _file_languages(files: Iterable[Any]) -> set[str]:
    languages: set[str] = set()
    for item in files:
        if isinstance(item, dict):
            filename = str(item.get("filename") or item.get("file_path") or item.get("file") or "")
        else:
            filename = str(getattr(item, "filename", "") or "")
        if filename:
            languages.add(_language_for_path(filename))
    return languages


def _file_paths(files: Iterable[Any]) -> set[str]:
    paths: set[str] = set()
    for item in files:
        if isinstance(item, dict):
            filename = str(item.get("filename") or item.get("file_path") or item.get("file") or "")
        else:
            filename = str(getattr(item, "filename", "") or "")
        if filename:
            paths.add(filename)
    return paths


def _score_example(
    *,
    agent_id: str,
    languages: set[str],
    file_paths: set[str],
    agent_categories: set[str],
    item: dict[str, Any],
) -> float:
    rule_id = str(item.get("rule_id") or "")
    file_path = str(item.get("file") or item.get("file_path") or "")
    category = category_for_rule(rule_id)
    score = 0.0
    if category and category in agent_categories:
        score += 6.0
    if agent_id and agent_id in agent_owners_for_rule(rule_id):
        score += 5.0
    if _language_for_path(file_path) in languages:
        score += 3.0
    if file_path and file_path in file_paths:
        score += 4.0
    elif file_path and Path(file_path).name in {Path(path).name for path in file_paths}:
        score += 1.5
    if str(item.get("ground_truth") or "").lower() in {"true_positive", "positive"}:
        score += 1.0
    return score


def _compact_snippet(value: Any, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated]"


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _gold_examples(paths: Iterable[Path]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text("utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(item.get("ground_truth") or "").lower() not in {"true_positive", "positive"}:
                continue
            items.append(item)
    return items


def _finding_examples(paths: Iterable[Path]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text("utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            items.append(item)
    return items


def _covered_rules(item: dict[str, Any]) -> set[str]:
    rules = item.get("covered_rules") or []
    if isinstance(rules, str):
        return {rules}
    return {str(rule) for rule in rules if str(rule).strip()}


def _line_distance(gold_line: int | None, finding: dict[str, Any]) -> int:
    if gold_line is None:
        return 10_000
    start = _as_int(finding.get("line_start") or finding.get("line"))
    end = _as_int(finding.get("line_end")) or start
    if start is None:
        return 10_000
    if end is not None and start <= gold_line <= end:
        return 0
    return min(abs(gold_line - start), abs(gold_line - end)) if end is not None else abs(gold_line - start)


def _match_finding(item: dict[str, Any], findings: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    mr_id = str(item.get("mr_id") or item.get("merge_request_id") or "")
    file_path = str(item.get("file") or item.get("file_path") or "")
    rule_id = str(item.get("rule_id") or "")
    gold_line = _as_int(item.get("line") or item.get("line_start"))
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for finding in findings:
        finding_mr_id = str(finding.get("mr_id") or finding.get("merge_request_id") or "")
        if mr_id and finding_mr_id and finding_mr_id != mr_id:
            continue
        if file_path and str(finding.get("file_path") or finding.get("file") or "") != file_path:
            continue
        if rule_id and rule_id not in _covered_rules(finding):
            continue
        distance = _line_distance(gold_line, finding)
        candidates.append((distance, str(finding.get("finding_id") or ""), finding))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _from_gold_item(
    item: dict[str, Any],
    score: float,
    *,
    label: str = "expected_finding",
    finding: dict[str, Any] | None = None,
) -> Example:
    rule_id = str(item.get("rule_id") or "")
    evidence_keywords = [str(keyword) for keyword in item.get("evidence_keywords") or []]
    snippet = (
        finding.get("evidence")
        or finding.get("problem_description")
        or finding.get("title")
        if finding
        else ""
    )
    if not snippet:
        snippet = " / ".join(evidence_keywords) if evidence_keywords else str(item.get("id") or "")
    return Example(
        source="gold",
        label=label,
        rule_id=rule_id,
        category=category_for_rule(rule_id),
        severity=str(item.get("severity") or (finding or {}).get("severity") or ""),
        file_path=str(item.get("file") or item.get("file_path") or ""),
        line=_as_int(item.get("line") or item.get("line_start")),
        snippet=_compact_snippet(snippet, limit=520),
        evidence_keywords=evidence_keywords,
        score=score,
        title=str((finding or {}).get("title") or ""),
        problem_description=_compact_snippet((finding or {}).get("problem_description") or "", limit=520),
        recommendation=_compact_snippet((finding or {}).get("recommendation") or "", limit=320),
        last_seen=str(item.get("id") or ""),
    )


def _from_feedback_item(item: dict[str, Any], score: float) -> Example:
    rule_id = str(item.get("rule_id") or "")
    snippet = (
        item.get("snippet")
        or item.get("evidence")
        or item.get("problem_description")
        or item.get("title")
        or ""
    )
    return Example(
        source="feedback",
        label="skip_false_positive",
        rule_id=rule_id,
        category=category_for_rule(rule_id),
        severity=str(item.get("severity") or ""),
        file_path=str(item.get("file_path") or item.get("file") or ""),
        line=_as_int(item.get("line_start") or item.get("line")),
        snippet=_compact_snippet(snippet, limit=420),
        evidence_keywords=[],
        score=score,
        last_seen=str(item.get("created_at") or item.get("last_seen") or ""),
    )


def retrieve_examples(
    agent_id: str,
    files: list[Any],
    *,
    k: int = 3,
    gold_paths: Iterable[Path] = DEFAULT_GOLD_PATHS,
    finding_paths: Iterable[Path] = DEFAULT_FINDING_PATHS,
    feedback_rows: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    languages = _file_languages(files)
    file_paths = _file_paths(files)
    agent_categories = categories_for_agent(agent_id)
    examples: list[Example] = []
    boundary_examples: list[Example] = []
    finding_rows = _finding_examples(finding_paths)

    for item in _gold_examples(gold_paths):
        matched_finding = _match_finding(item, finding_rows)
        score = _score_example(
            agent_id=agent_id,
            languages=languages,
            file_paths=file_paths,
            agent_categories=agent_categories,
            item=item,
        )
        rule_id = str(item.get("rule_id") or "")
        file_path = str(item.get("file") or item.get("file_path") or "")
        owned_by_agent = agent_id in agent_owners_for_rule(rule_id)
        owned_category = bool(category_for_rule(rule_id) and category_for_rule(rule_id) in agent_categories)
        same_language = _language_for_path(file_path) in languages
        if owned_by_agent or owned_category:
            if score > 0:
                examples.append(_from_gold_item(item, score, finding=matched_finding))
            continue
        if same_language:
            boundary_score = 2.0 + (0.5 if str(item.get("severity") or "").lower() in {"critical", "high"} else 0.0)
            boundary_examples.append(
                _from_gold_item(item, boundary_score, label="boundary_other_expert", finding=matched_finding)
            )

    for item in feedback_rows or []:
        if str(item.get("label") or item.get("feedback_type") or "").lower() not in {"skip_false_positive", "false_positive", "judge_rejected"}:
            continue
        score = (
            _score_example(
                agent_id=agent_id,
                languages=languages,
                file_paths=file_paths,
                agent_categories=agent_categories,
                item=item,
            )
            + 0.5
        )
        if score <= 0.5:
            continue
        examples.append(_from_feedback_item(item, score))

    positives = [item for item in examples if item.label == "expected_finding"]
    negatives = [item for item in examples if item.label == "skip_false_positive"]
    boundaries = boundary_examples
    positives.sort(key=lambda item: (-item.score, item.file_path, item.line or 0, item.last_seen))
    negatives.sort(key=lambda item: (-item.score, item.file_path, item.line or 0, item.last_seen), reverse=False)
    boundaries.sort(key=lambda item: (-item.score, item.file_path, item.line or 0, item.last_seen))
    selected: list[Example] = []
    for bucket in [positives[:1], negatives[:1], boundaries[:1]]:
        for item in bucket:
            if len(selected) < k:
                selected.append(item)
    for item in [*positives[1:], *negatives[1:], *boundaries[1:]]:
        if len(selected) >= k:
            break
        selected.append(item)
    return [item.as_prompt_item() for item in selected[:k]]
