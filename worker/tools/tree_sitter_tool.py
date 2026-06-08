from __future__ import annotations

import re
from pathlib import Path
from typing import Any


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


def build_graph(worktree: Path) -> dict[str, Any]:
    files: list[tuple[str, str]] = []
    if worktree.exists():
        for path in worktree.rglob("*"):
            if path.is_file() and language_for_path(path):
                try:
                    files.append((path.relative_to(worktree).as_posix(), path.read_text("utf-8", errors="replace")))
                except OSError:
                    continue
    return _build_index(files, {"worktree": str(worktree), "index_kind": "tree_sitter_repo_graph"})


def build_diff_graph(files: list[Any]) -> dict[str, Any]:
    indexed: list[tuple[str, str]] = []
    for changed in files:
        filename = str(getattr(changed, "filename", ""))
        if not language_for_path(filename):
            continue
        indexed.append((filename, "\n".join(line for _, line in _added_lines(str(getattr(changed, "patch", ""))))))
    return _build_index(indexed, {"index_kind": "tree_sitter_diff_graph"})


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
    _walk(tree.root_node, source, file_path, language, state, ["<module>"])
    return {**state, "status": "parsed", "has_error": bool(getattr(tree.root_node, "has_error", False))}


def _walk(node: Any, source: bytes, file_path: str, language: str, state: dict[str, list[dict[str, Any]]], scope: list[str]) -> None:
    node_type = str(node.type)
    pushed = False
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
            state["functions"].append({"file_path": file_path, "language": language, "line": _line(node), "name": name})
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
                }
            )
    for child in node.named_children:
        _walk(child, source, file_path, language, state, scope)
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


def _last_identifier(text: str) -> str:
    names = re.findall(r"[A-Za-z_]\w*", text)
    return names[-1] if names else ""


def _line(node: Any) -> int:
    return int(node.start_point[0]) + 1


def _text(node: Any, source: bytes) -> str:
    if node is None:
        return ""
    return source[int(node.start_byte) : int(node.end_byte)].decode("utf-8", errors="replace")


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
