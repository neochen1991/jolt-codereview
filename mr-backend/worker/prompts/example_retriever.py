from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rules.registry import agent_owners_for_rule, categories_for_agent, category_for_rule

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_PATHS = (ROOT / "evaluation" / "real_gold_set.jsonl", ROOT / "evaluation" / "gold_set.jsonl")


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
    last_seen: str = ""

    def as_prompt_item(self) -> dict[str, Any]:
        return {
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
                "skip_false_positive 表示历史相似问题被人工判为误报，只有新增源码证据时才输出。"
            ),
        }


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


def _score_example(*, agent_id: str, languages: set[str], agent_categories: set[str], item: dict[str, Any]) -> float:
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


def _from_gold_item(item: dict[str, Any], score: float) -> Example:
    rule_id = str(item.get("rule_id") or "")
    evidence_keywords = [str(keyword) for keyword in item.get("evidence_keywords") or []]
    snippet = " / ".join(evidence_keywords) if evidence_keywords else str(item.get("id") or "")
    return Example(
        source="gold",
        label="expected_finding",
        rule_id=rule_id,
        category=category_for_rule(rule_id),
        severity=str(item.get("severity") or ""),
        file_path=str(item.get("file") or item.get("file_path") or ""),
        line=_as_int(item.get("line") or item.get("line_start")),
        snippet=_compact_snippet(snippet, limit=240),
        evidence_keywords=evidence_keywords,
        score=score,
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
    feedback_rows: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    languages = _file_languages(files)
    agent_categories = categories_for_agent(agent_id)
    examples: list[Example] = []

    for item in _gold_examples(gold_paths):
        score = _score_example(agent_id=agent_id, languages=languages, agent_categories=agent_categories, item=item)
        if score <= 0:
            continue
        examples.append(_from_gold_item(item, score))

    for item in feedback_rows or []:
        if str(item.get("label") or item.get("feedback_type") or "").lower() not in {"skip_false_positive", "false_positive", "judge_rejected"}:
            continue
        score = _score_example(agent_id=agent_id, languages=languages, agent_categories=agent_categories, item=item) + 0.5
        if score <= 0.5:
            continue
        examples.append(_from_feedback_item(item, score))

    positives = [item for item in examples if item.label == "expected_finding"]
    negatives = [item for item in examples if item.label == "skip_false_positive"]
    positives.sort(key=lambda item: (-item.score, item.file_path, item.line or 0, item.last_seen))
    negatives.sort(key=lambda item: (-item.score, item.file_path, item.line or 0, item.last_seen), reverse=False)
    selected = [*positives[: max(0, k - 1)], *negatives[:1]]
    selected.sort(key=lambda item: (-item.score, item.label, item.file_path, item.line or 0))
    return [item.as_prompt_item() for item in selected[:k]]
