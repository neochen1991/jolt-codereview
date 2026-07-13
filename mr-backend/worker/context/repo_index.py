from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from diff.slicer import extract_added_lines
from tools.tree_sitter_tool import language_for_path

RELATED_CONTEXT_MAX_CHARS = 8000
MAX_INDEX_FILES = 5000
MAX_FILE_LINES = 10000


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:160] or "repo"


def _repo_index_path(cache_root: Path, repository_id: str, commit_sha: str) -> Path:
    return cache_root / _safe_key(repository_id) / f"{_safe_key(commit_sha)}.json"


def _iter_source_files(worktree: Path) -> list[Path]:
    if not worktree.exists():
        return []
    result: list[Path] = []
    for path in worktree.rglob("*"):
        if len(result) >= MAX_INDEX_FILES:
            break
        if path.is_file() and language_for_path(path):
            result.append(path)
    return result


def _line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _symbols_for_line(language: str, line: str) -> list[tuple[str, str]]:
    stripped = line.strip()
    result: list[tuple[str, str]] = []
    class_match = re.search(r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", stripped)
    if language in {"typescript", "javascript"}:
        class_match = re.search(r"\b(?:class|interface|type)\s+([A-Za-z_]\w*)", stripped)
    if language == "python":
        class_match = re.search(r"\bclass\s+([A-Za-z_]\w*)", stripped)
    if class_match:
        result.append((class_match.group(1), "class"))

    patterns = {
        "python": [r"\bdef\s+([A-Za-z_]\w*)\s*\("],
        "typescript": [r"\bfunction\s+([A-Za-z_]\w*)\s*\(", r"\b(?:const|let|var)\s+([A-Za-z_]\w*)\s*="],
        "javascript": [r"\bfunction\s+([A-Za-z_]\w*)\s*\(", r"\b(?:const|let|var)\s+([A-Za-z_]\w*)\s*="],
        "java": [r"\b(?:public|private|protected|static|final|synchronized|abstract|\s)+[\w<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\("],
    }.get(language, [])
    for pattern in patterns:
        match = re.search(pattern, stripped)
        if match:
            name = match.group(1)
            if name not in {"if", "for", "while", "switch", "catch", "return"}:
                result.append((name, "function"))
    const_match = re.search(r"\b(?:const|static\s+final)\s+[\w<>\[\], ?]*\s*([A-Z][A-Z0-9_]*)\b", stripped)
    if const_match:
        result.append((const_match.group(1), "const"))
    return result


def _refs_for_line(line: str) -> list[str]:
    names = []
    for name in re.findall(r"\b([A-Za-z_]\w*)\s*\(", line):
        if name not in {"if", "for", "while", "switch", "catch", "return", "new", "throw"} and name not in names:
            names.append(name)
    return names[:20]


def _snippet_from_lines(lines: list[str], line_no: int, radius: int) -> str:
    start = max(1, line_no - radius)
    end = min(len(lines), line_no + radius)
    return "\n".join(f"{index}: {lines[index - 1]}" for index in range(start, end + 1))


def build_repo_index(worktree: Path, repository_id: str, commit_sha: str, cache_root: Path) -> dict[str, Any]:
    started = time.time()
    index_path = _repo_index_path(cache_root, repository_id, commit_sha)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists():
        index_data = _load_index(index_path)
        return {
            "status": "cached",
            "index_kind": "regex_repo_symbol_index",
            "resolver": "regex_fallback",
            "confidence": "heuristic",
            "storage_uri": str(index_path),
            "symbol_count": len(index_data.get("symbols") or []),
            "ref_count": len(index_data.get("refs") or []),
            "duration_ms": int((time.time() - started) * 1000),
        }

    source_files = _iter_source_files(worktree)
    skipped_large = 0
    symbols: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    for path in source_files:
        rel = path.relative_to(worktree).as_posix()
        language = language_for_path(rel)
        if not language:
            continue
        if _line_count(path) > MAX_FILE_LINES:
            skipped_large += 1
            continue
        try:
            lines = path.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            for name, kind in _symbols_for_line(language, line):
                symbols.append(
                    {
                        "name": name,
                        "kind": kind,
                        "file": rel,
                        "start_line": line_no,
                        "end_line": min(len(lines), line_no + 30),
                    }
                )
            for ref_name in _refs_for_line(line):
                refs.append({"symbol_name": ref_name, "file": rel, "line": line_no})
    index_path.write_text(json.dumps({"symbols": symbols, "refs": refs}, ensure_ascii=False), "utf-8")
    return {
        "status": "indexed",
        "index_kind": "regex_repo_symbol_index",
        "resolver": "regex_fallback",
        "confidence": "heuristic",
        "storage_uri": str(index_path),
        "file_count": len(source_files),
        "skipped_large_files": skipped_large,
        "symbol_count": len(symbols),
        "ref_count": len(refs),
        "duration_ms": int((time.time() - started) * 1000),
        "limits": {"max_index_files": MAX_INDEX_FILES, "max_file_lines": MAX_FILE_LINES},
    }


def _changed_symbol_names(files: list[Any]) -> list[str]:
    names: list[str] = []
    for changed in files:
        language = language_for_path(str(getattr(changed, "filename", "")))
        if not language:
            continue
        for _, line in extract_added_lines(str(getattr(changed, "patch", ""))):
            for name, _kind in _symbols_for_line(language, line):
                if name not in names:
                    names.append(name)
            for ref_name in _refs_for_line(line):
                if ref_name not in names:
                    names.append(ref_name)
    return names[:30]


def _changed_lines_by_file(files: list[Any]) -> dict[str, list[tuple[int, str]]]:
    result: dict[str, list[tuple[int, str]]] = {}
    for changed in files:
        filename = str(getattr(changed, "filename", ""))
        if not language_for_path(filename):
            continue
        result[filename] = extract_added_lines(str(getattr(changed, "patch", "")))
    return result


def _symbol_role(file_path: str, symbol_name: str) -> str:
    lowered = f"{file_path}/{symbol_name}".lower()
    if "test" in lowered:
        return "test"
    if "controller" in lowered or "/api/" in lowered or "/web/" in lowered:
        return "controller"
    if "repository" in lowered or "mapper" in lowered or "/dao/" in lowered:
        return "repository"
    if "service" in lowered or "application" in lowered:
        return "service"
    if "domain" in lowered or "aggregate" in lowered or "entity" in lowered or "valueobject" in lowered:
        return "domain"
    if "config" in lowered or "properties" in lowered:
        return "configuration"
    return "source"


def _changed_call_targets(changed_lines: list[tuple[int, str]]) -> list[str]:
    targets: list[str] = []
    for _line_no, line in changed_lines:
        for ref in _refs_for_line(line):
            if ref not in targets:
                targets.append(ref)
    return targets[:20]


def _related_test_files(worktree: Path, symbol_name: str, definition_file: str) -> list[str]:
    first = _find_test_file(worktree, symbol_name, definition_file)
    result = [first] if first else []
    definition_stem = Path(definition_file).stem.lower()
    for path in _iter_source_files(worktree):
        rel = path.relative_to(worktree).as_posix()
        lowered = rel.lower()
        if "test" not in lowered or rel in result:
            continue
        if definition_stem in lowered:
            result.append(rel)
        if len(result) >= 5:
            break
    return result


def _load_index(index_path: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        data = json.loads(index_path.read_text("utf-8"))
    except (OSError, ValueError):
        return {"symbols": [], "refs": []}
    return {
        "symbols": data.get("symbols") if isinstance(data.get("symbols"), list) else [],
        "refs": data.get("refs") if isinstance(data.get("refs"), list) else [],
    }


def _definitions_for_changed_lines(index_data: dict[str, list[dict[str, Any]]], changed_lines: dict[str, list[tuple[int, str]]]) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    symbols = index_data.get("symbols") or []
    for file_path, lines in changed_lines.items():
        for line_no, _line_text in lines:
            matches = [
                row
                for row in symbols
                if row.get("file") == file_path
                and row.get("kind") in {"function", "class"}
                and int(row.get("start_line") or 0) <= line_no
                and int(row.get("end_line") or 0) >= line_no
            ]
            if not matches:
                continue
            row = sorted(matches, key=lambda item: (0 if item.get("kind") == "function" else 1, -int(item.get("start_line") or 0)))[0]
            key = (str(row["file"]), str(row["name"]), int(row["start_line"]))
            if key not in seen:
                seen.add(key)
                definitions.append(row)
    return definitions[:30]


def _read_lines(worktree: Path, file_path: str) -> list[str]:
    target = (worktree / file_path).resolve()
    try:
        target.relative_to(worktree.resolve())
        return target.read_text("utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return []


def _find_test_file(worktree: Path, symbol_name: str, definition_file: str) -> str:
    definition_stem = Path(definition_file).stem.lower()
    symbol_lower = symbol_name.lower()
    for path in _iter_source_files(worktree):
        rel = path.relative_to(worktree).as_posix()
        lowered = rel.lower()
        if "test" not in lowered:
            continue
        if definition_stem in lowered or symbol_lower in lowered:
            return rel
        try:
            content = path.read_text("utf-8", errors="replace").lower()
        except OSError:
            continue
        if symbol_lower in content:
            return rel
    return ""


def resolve_diff_symbols(index_info: dict[str, Any], worktree: Path, files: list[Any]) -> dict[str, Any]:
    index_path = Path(str(index_info.get("storage_uri") or ""))
    if not index_path.exists():
        return {"status": "missing_index", "modified_symbols": [], "source_file_contents": {}}
    index_data = _load_index(index_path)
    modified_names = _changed_symbol_names(files)
    changed_lines = _changed_lines_by_file(files)
    source_file_contents: dict[str, str] = {}
    modified_symbols: list[dict[str, Any]] = []
    chars_used = 0
    definitions = _definitions_for_changed_lines(index_data, changed_lines)
    seen_definitions = {(str(row["file"]), str(row["name"]), int(row["start_line"])) for row in definitions}
    symbols = index_data.get("symbols") or []
    refs = index_data.get("refs") or []
    for name in modified_names:
        matches = sorted([row for row in symbols if row.get("name") == name], key=lambda item: int(item.get("start_line") or 0))
        if not matches:
            continue
        definition = matches[0]
        key = (str(definition["file"]), str(definition["name"]), int(definition["start_line"]))
        if key in seen_definitions:
            continue
        seen_definitions.add(key)
        definitions.append(definition)
    for definition in definitions[:30]:
            name = str(definition["name"])
            def_lines = _read_lines(worktree, definition["file"])
            definition_snippet = _snippet_from_lines(def_lines, int(definition["start_line"]), 15) if def_lines else ""
            symbol_changed_lines = [
                (line_no, line)
                for line_no, line in changed_lines.get(str(definition["file"]), [])
                if int(definition["start_line"]) <= line_no <= int(definition["end_line"])
            ]
            callers = []
            matching_refs = sorted(
                [ref for ref in refs if ref.get("symbol_name") == name and ref.get("file") != definition["file"]],
                key=lambda item: (str(item.get("file") or ""), int(item.get("line") or 0)),
            )
            for ref in matching_refs[:3]:
                ref_lines = _read_lines(worktree, ref["file"])
                callers.append(
                    {
                        "file": ref["file"],
                        "line": int(ref["line"]),
                        "snippet": _snippet_from_lines(ref_lines, int(ref["line"]), 8) if ref_lines else "",
                        "confidence": "heuristic",
                        "resolver": "regex_name_match",
                    }
                )
            related_tests = _related_test_files(worktree, name, str(definition["file"]))
            has_test = bool(related_tests) or any("test" in caller["file"].lower() for caller in callers) or any("test" in str(getattr(item, "filename", "")).lower() for item in files)
            item = {
                "name": name,
                "kind": definition["kind"],
                "symbol_role": _symbol_role(str(definition["file"]), name),
                "definition_file": definition["file"],
                "definition_line": int(definition["start_line"]),
                "definition_snippet": definition_snippet,
                "changed_line_count": len(symbol_changed_lines),
                "changed_lines": [{"line": line_no, "text": line[:240]} for line_no, line in symbol_changed_lines[:12]],
                "call_targets": _changed_call_targets(symbol_changed_lines),
                "callers": callers,
                "has_test": has_test,
                "test_file": related_tests[0] if related_tests else next((str(getattr(changed, "filename", "")) for changed in files if "test" in str(getattr(changed, "filename", "")).lower()), ""),
                "related_tests": related_tests,
            }
            item_size = len(json_like(item))
            if chars_used + item_size > RELATED_CONTEXT_MAX_CHARS:
                break
            chars_used += item_size
            modified_symbols.append(item)
    for changed in files:
        filename = str(getattr(changed, "filename", ""))
        lines = _read_lines(worktree, filename)
        if lines:
            source_file_contents[filename] = "\n".join(lines[:MAX_FILE_LINES])
    return {
        "status": "resolved",
        "format": "related_context_v2",
        "resolver": "regex_fallback",
        "confidence": "heuristic",
        "modified_symbols": modified_symbols,
        "changed_symbols": [
            {
                "name": item["name"],
                "kind": item["kind"],
                "symbol_role": item.get("symbol_role"),
                "definition_file": item["definition_file"],
                "definition_line": item["definition_line"],
                "changed_line_count": item.get("changed_line_count", 0),
                "call_targets": item.get("call_targets", []),
                "has_test": item.get("has_test", False),
            }
            for item in modified_symbols
        ],
        "related_tests": sorted({test for item in modified_symbols for test in item.get("related_tests", []) if test})[:20],
        "source_file_contents": source_file_contents,
        "limits": {"related_context_max_chars": RELATED_CONTEXT_MAX_CHARS},
    }


def json_like(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
