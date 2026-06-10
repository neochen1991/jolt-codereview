from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from tools.code_graph_rules import evaluate_code_graph_rules


SUPPORTED_SUFFIXES = {
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
}

LANGUAGE_MODULES = {
    "java": ("tree_sitter_java", "language"),
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
}

CLASS_NODE_TYPES = {
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "class_definition",
    "interface_declaration",
    "type_alias_declaration",
}
FUNCTION_NODE_TYPES = {
    "method_declaration",
    "constructor_declaration",
    "function_definition",
    "function_declaration",
    "method_definition",
    "generator_function_declaration",
    "arrow_function",
}
IMPORT_NODE_TYPES = {
    "import_declaration",
    "import_statement",
    "import_from_statement",
}
CALL_NODE_TYPES = {
    "method_invocation",
    "call_expression",
    "object_creation_expression",
}
LOOP_NODE_TYPES = {
    "for_statement",
    "enhanced_for_statement",
    "while_statement",
    "do_statement",
    "for_in_statement",
}
CONTROL_WORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "new",
    "throw",
    "throws",
    "class",
    "interface",
    "enum",
    "record",
    "function",
    "def",
    "import",
}

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "target",
    "build",
    "dist",
    "out",
    ".gradle",
    ".mvn",
    ".ruff_cache",
    ".pytest_cache",
}
DEFAULT_MAX_FILES = 260
DEFAULT_MAX_FILE_BYTES = 512 * 1024
DEFAULT_TIMEOUT_SECONDS = 20.0


def language_for_path(path: str | Path) -> str | None:
    return SUPPORTED_SUFFIXES.get(Path(path).suffix.lower())


def _load_tree_sitter() -> tuple[Any, dict[str, Any]]:
    try:
        from tree_sitter import Language, Parser

        return (Language, Parser), {"status": "available", "runtime": "python-tree-sitter"}
    except Exception as exc:
        return (None, None), {"status": "missing", "runtime": "", "error": f"{type(exc).__name__}: {exc}"}


def _language(language: str) -> Any | None:
    (Language, _Parser), status = _load_tree_sitter()
    if status["status"] != "available" or Language is None:
        return None
    module_name, attr = LANGUAGE_MODULES.get(language, ("", ""))
    if not module_name:
        return None
    try:
        module = __import__(module_name)
        return Language(getattr(module, attr)())
    except Exception:
        return None


def _parser_for(language: str) -> Any | None:
    (_Language, Parser), status = _load_tree_sitter()
    lang = _language(language)
    if status["status"] != "available" or Parser is None or lang is None:
        return None
    try:
        return Parser(lang)
    except TypeError:
        parser = Parser()
        parser.set_language(lang)
        return parser


def probe() -> dict[str, Any]:
    (_Language, _Parser), status = _load_tree_sitter()
    languages: dict[str, str] = {}
    for language in sorted(set(SUPPORTED_SUFFIXES.values())):
        languages[language] = "available" if _language(language) is not None else "missing"
    return {
        "tool": "tree-sitter",
        **status,
        "languages": languages,
    }


def build_graph(worktree: Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    started = time.monotonic()
    max_files = _positive_int(options.get("max_files"), DEFAULT_MAX_FILES)
    max_file_bytes = _positive_int(options.get("max_file_bytes"), DEFAULT_MAX_FILE_BYTES)
    timeout_seconds = float(_positive_int(options.get("timeout_seconds"), int(DEFAULT_TIMEOUT_SECONDS)))
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    ignore_dirs.update(str(item) for item in options.get("ignore_dirs") or [] if str(item))
    include_paths = [str(item).replace("\\", "/") for item in options.get("include_paths") or [] if str(item)]
    files: list[tuple[str, str]] = []
    skipped: list[dict[str, Any]] = []
    truncated = False
    timeout = False
    if worktree.exists():
        candidates = _candidate_paths(worktree, include_paths, ignore_dirs)
        seen: set[str] = set()
        for path in candidates:
            if time.monotonic() - started > timeout_seconds:
                timeout = True
                break
            if not path.is_file() or not language_for_path(path) or _ignored_path(path, worktree, ignore_dirs):
                continue
            relative_path = path.relative_to(worktree).as_posix()
            if relative_path in seen:
                continue
            seen.add(relative_path)
            if len(files) >= max_files:
                truncated = True
                skipped.append({"file_path": relative_path, "reason": "max_files_exceeded"})
                break
            try:
                size = path.stat().st_size
                if size > max_file_bytes:
                    skipped.append({"file_path": relative_path, "reason": "max_file_bytes_exceeded", "size_bytes": size})
                    continue
                files.append((relative_path, path.read_text("utf-8", errors="replace")))
            except OSError as exc:
                skipped.append({"file_path": relative_path, "reason": f"os_error:{type(exc).__name__}"})
                continue
    graph = _build_index(files, {"worktree": str(worktree), "index_kind": "tree_sitter_repo_graph"})
    graph["truncated"] = truncated
    graph["timeout"] = timeout
    graph["skipped_files"] = skipped[:100]
    graph["limits"] = {
        **(graph.get("limits") or {}),
        "max_files": max_files,
        "max_file_bytes": max_file_bytes,
        "timeout_seconds": timeout_seconds,
        "ignore_dirs": sorted(ignore_dirs),
        "include_path_count": len(include_paths),
    }
    if timeout and graph.get("status") == "indexed":
        graph["status"] = "timeout_partial"
    elif truncated and graph.get("status") == "indexed":
        graph["status"] = "indexed_partial"
    return graph


def build_diff_graph(files: list[Any]) -> dict[str, Any]:
    indexed: list[tuple[str, str]] = []
    for changed in files:
        filename = str(getattr(changed, "filename", ""))
        if not language_for_path(filename):
            continue
        indexed.append((filename, "\n".join(line for _, line in _added_lines(str(getattr(changed, "patch", ""))))))
    return _build_index(indexed, {"index_kind": "tree_sitter_diff_graph"})


def architecture_findings_from_graph(
    graph: dict[str, Any],
    changed_files: list[Any],
    *,
    raw_artifact_id: str | None = None,
) -> list[dict[str, Any]]:
    return evaluate_code_graph_rules(graph, changed_files, raw_artifact_id=raw_artifact_id)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _candidate_paths(worktree: Path, include_paths: list[str], ignore_dirs: set[str]) -> list[Path]:
    if include_paths:
        candidates: list[Path] = []
        seen: set[str] = set()
        for relative in include_paths:
            safe = Path(relative.replace("\\", "/"))
            if safe.is_absolute() or ".." in safe.parts:
                continue
            path = worktree / safe
            if path.exists() and path.is_file():
                key = path.resolve().as_posix()
                if key not in seen:
                    seen.add(key)
                    candidates.append(path)
            parent = path.parent
            if parent.exists() and parent.is_dir() and not _ignored_path(parent, worktree, ignore_dirs):
                for sibling in parent.iterdir():
                    if sibling.is_file() and language_for_path(sibling):
                        key = sibling.resolve().as_posix()
                        if key not in seen:
                            seen.add(key)
                            candidates.append(sibling)
        return candidates
    return [path for path in worktree.rglob("*") if path.is_file()]


def _ignored_path(path: Path, worktree: Path, ignore_dirs: set[str]) -> bool:
    try:
        relative = path.relative_to(worktree)
    except ValueError:
        return True
    return any(part in ignore_dirs for part in relative.parts)


def _build_index(files: list[tuple[str, str]], base: dict[str, Any]) -> dict[str, Any]:
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    parsed_files = 0
    for file_path, content in files:
        language = language_for_path(file_path)
        if not language:
            continue
        parsed = _parse_file(file_path, language, content)
        if parsed.get("status") != "parsed":
            parse_errors.append({"file_path": file_path, "language": language, "error": parsed.get("error", "parse_failed")})
            continue
        parsed_files += 1
        functions.extend(parsed["functions"])
        classes.extend(parsed["classes"])
        imports.extend(parsed["imports"])
        calls.extend(parsed["calls"])
        if parsed.get("has_error"):
            parse_errors.append({"file_path": file_path, "language": language, "error": "tree_contains_error_nodes"})
    return {
        "tool": "tree-sitter",
        **probe(),
        **base,
        "status": "indexed" if parsed_files else "missing_parser" if files else "no_targets",
        "file_count": len(files),
        "parsed_file_count": parsed_files,
        "functions": functions[:2000],
        "classes": classes[:2000],
        "imports": imports[:2000],
        "callers": calls[:4000],
        "callees": sorted({item["callee"] for item in calls})[:2000],
        "impact_symbols": _impact_symbols(functions, classes, calls),
        "parse_errors": parse_errors[:100],
        "limits": {"max_functions": 2000, "max_classes": 2000, "max_calls": 4000},
    }


def _parse_file(file_path: str, language: str, content: str) -> dict[str, Any]:
    parser = _parser_for(language)
    if parser is None:
        return {"status": "missing_parser", "error": f"missing parser for {language}"}
    source = content.encode("utf-8", errors="replace")
    try:
        tree = parser.parse(source)
    except Exception as exc:
        return {"status": "parse_failed", "error": f"{type(exc).__name__}: {exc}"}
    state = {"functions": [], "classes": [], "imports": [], "calls": []}
    _walk(tree.root_node, source, file_path, language, state, ["<module>"], 0)
    return {**state, "status": "parsed", "has_error": bool(getattr(tree.root_node, "has_error", False))}


def _walk(
    node: Any,
    source: bytes,
    file_path: str,
    language: str,
    state: dict[str, list[dict[str, Any]]],
    scope: list[str],
    loop_depth: int,
) -> None:
    node_type = str(node.type)
    pushed = False
    next_loop_depth = loop_depth + 1 if node_type in LOOP_NODE_TYPES else loop_depth
    if node_type in IMPORT_NODE_TYPES:
        state["imports"].append({"file_path": file_path, "language": language, "line": _line(node), "import": _text(node, source).strip()})
    if node_type in CLASS_NODE_TYPES:
        name = _node_name(node, source)
        if name:
            state["classes"].append({"file_path": file_path, "language": language, "line": _line(node), "name": name})
            scope.append(name)
            pushed = True
    elif node_type in FUNCTION_NODE_TYPES:
        name = _node_name(node, source) or _assigned_function_name(node, source)
        if name and name not in CONTROL_WORDS:
            state["functions"].append(
                {
                    "file_path": file_path,
                    "language": language,
                    "line": _line(node),
                    "name": name,
                    "snippet": _snippet(node, source, 1200),
                }
            )
            scope.append(name)
            pushed = True
    if node_type in CALL_NODE_TYPES:
        callee = _call_name(node, source)
        if callee and callee not in CONTROL_WORDS:
            state["calls"].append(
                {
                    "file_path": file_path,
                    "language": language,
                    "line": _line(node),
                    "caller": scope[-1] if scope else "<module>",
                    "callee": callee,
                    "receiver": _call_receiver(node, source),
                    "snippet": _snippet(node, source, 500),
                    "loop_depth": loop_depth,
                }
            )
    for child in node.named_children:
        _walk(child, source, file_path, language, state, scope, next_loop_depth)
    if pushed:
        scope.pop()


def _node_name(node: Any, source: bytes) -> str:
    child = node.child_by_field_name("name")
    if child is not None:
        return _text(child, source)
    for child in node.named_children:
        if child.type in {"identifier", "type_identifier"}:
            return _text(child, source)
    return ""


def _assigned_function_name(node: Any, source: bytes) -> str:
    parent = getattr(node, "parent", None)
    if parent is None:
        return ""
    text = _text(parent, source)
    match = re.search(r"\b(?:const|let|var)\s+([A-Za-z_]\w*)\s*=", text)
    return match.group(1) if match else ""


def _call_name(node: Any, source: bytes) -> str:
    for field in ("name", "function", "constructor"):
        child = node.child_by_field_name(field)
        name = _last_identifier(_text(child, source)) if child is not None else ""
        if name:
            return name
    text = _text(node, source)
    match = re.search(r"([A-Za-z_]\w*)\s*\(", text)
    return match.group(1) if match else ""


def _call_receiver(node: Any, source: bytes) -> str:
    child = node.child_by_field_name("object")
    if child is not None:
        return _text(child, source).strip()
    text = _text(node, source)
    match = re.search(r"([A-Za-z_]\w*)\s*\.\s*[A-Za-z_]\w*\s*\(", text)
    return match.group(1) if match else ""


def _last_identifier(text: str) -> str:
    names = re.findall(r"[A-Za-z_]\w*", text)
    return names[-1] if names else ""


def _line(node: Any) -> int:
    return int(node.start_point[0]) + 1


def _text(node: Any, source: bytes) -> str:
    if node is None:
        return ""
    return source[int(node.start_byte) : int(node.end_byte)].decode("utf-8", errors="replace")


def _snippet(node: Any, source: bytes, limit: int) -> str:
    return re.sub(r"\s+", " ", _text(node, source)).strip()[:limit]


def _impact_symbols(functions: list[dict[str, Any]], classes: list[dict[str, Any]], calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    defined = {str(item["name"]) for item in functions + classes}
    result: list[dict[str, Any]] = []
    for call in calls:
        callee = str(call.get("callee") or "")
        if callee in defined:
            result.append(
                {
                    "symbol": callee,
                    "caller": call.get("caller"),
                    "file_path": call.get("file_path"),
                    "line": call.get("line"),
                }
            )
    return result[:1000]


def _added_lines(patch: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    new_line = 0
    for raw in patch.splitlines():
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) - 1 if match else new_line
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            new_line += 1
            result.append((new_line, raw[1:]))
        elif raw.startswith(" ") and not raw.startswith(("diff --git", "index ")):
            new_line += 1
    return result
