from __future__ import annotations

import re
import sqlite3
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
    return cache_root / _safe_key(repository_id) / f"{_safe_key(commit_sha)}.sqlite"


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
        with sqlite3.connect(index_path) as conn:
            symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            ref_count = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
        return {
            "status": "cached",
            "index_kind": "repo_symbol_index",
            "storage_uri": str(index_path),
            "symbol_count": symbol_count,
            "ref_count": ref_count,
            "duration_ms": int((time.time() - started) * 1000),
        }

    source_files = _iter_source_files(worktree)
    skipped_large = 0
    with sqlite3.connect(index_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS symbols (
              name TEXT NOT NULL,
              kind TEXT NOT NULL,
              file TEXT NOT NULL,
              start_line INTEGER NOT NULL,
              end_line INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
            CREATE TABLE IF NOT EXISTS refs (
              symbol_name TEXT NOT NULL,
              file TEXT NOT NULL,
              line INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_refs_symbol ON refs(symbol_name);
            """
        )
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
                    conn.execute("INSERT INTO symbols (name, kind, file, start_line, end_line) VALUES (?, ?, ?, ?, ?)", (name, kind, rel, line_no, min(len(lines), line_no + 30)))
                for ref_name in _refs_for_line(line):
                    conn.execute("INSERT INTO refs (symbol_name, file, line) VALUES (?, ?, ?)", (ref_name, rel, line_no))
        conn.commit()
        symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        ref_count = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
    return {
        "status": "indexed",
        "index_kind": "repo_symbol_index",
        "storage_uri": str(index_path),
        "file_count": len(source_files),
        "skipped_large_files": skipped_large,
        "symbol_count": symbol_count,
        "ref_count": ref_count,
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
    modified_names = _changed_symbol_names(files)
    source_file_contents: dict[str, str] = {}
    modified_symbols: list[dict[str, Any]] = []
    chars_used = 0
    with sqlite3.connect(index_path) as conn:
        conn.row_factory = sqlite3.Row
        for name in modified_names:
            definition = conn.execute(
                "SELECT * FROM symbols WHERE name = ? ORDER BY start_line LIMIT 1",
                (name,),
            ).fetchone()
            if not definition:
                continue
            def_lines = _read_lines(worktree, definition["file"])
            definition_snippet = _snippet_from_lines(def_lines, int(definition["start_line"]), 15) if def_lines else ""
            callers = []
            for ref in conn.execute(
                "SELECT * FROM refs WHERE symbol_name = ? AND file <> ? ORDER BY file, line LIMIT 3",
                (name, definition["file"]),
            ).fetchall():
                ref_lines = _read_lines(worktree, ref["file"])
                callers.append(
                    {
                        "file": ref["file"],
                        "line": int(ref["line"]),
                        "snippet": _snippet_from_lines(ref_lines, int(ref["line"]), 8) if ref_lines else "",
                    }
                )
            test_file = _find_test_file(worktree, name, str(definition["file"]))
            has_test = bool(test_file) or any("test" in caller["file"].lower() for caller in callers) or any("test" in str(getattr(item, "filename", "")).lower() for item in files)
            item = {
                "name": name,
                "kind": definition["kind"],
                "definition_file": definition["file"],
                "definition_line": int(definition["start_line"]),
                "definition_snippet": definition_snippet,
                "callers": callers,
                "has_test": has_test,
                "test_file": test_file or next((str(getattr(changed, "filename", "")) for changed in files if "test" in str(getattr(changed, "filename", "")).lower()), ""),
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
        "format": "related_context_v1",
        "modified_symbols": modified_symbols,
        "source_file_contents": source_file_contents,
        "limits": {"related_context_max_chars": RELATED_CONTEXT_MAX_CHARS},
    }


def json_like(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
