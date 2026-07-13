from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal


NodeKind = Literal["file", "class", "interface", "function", "config", "schema", "test"]
EdgeKind = Literal[
    "contains",
    "imports",
    "calls",
    "extends",
    "implements",
    "overrides",
    "reads_config",
    "uses_schema",
    "tested_by",
]
Confidence = Literal["typed", "syntax", "heuristic"]


@dataclass(frozen=True)
class SemanticNode:
    node_id: str
    kind: NodeKind
    name: str
    file_path: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class SemanticEdge:
    source_id: str
    target_id: str
    kind: EdgeKind
    confidence: Confidence
    resolver: str


@dataclass(frozen=True)
class SemanticGraph:
    nodes: tuple[SemanticNode, ...]
    edges: tuple[SemanticEdge, ...]
    status: str
    degradations: tuple[dict[str, Any], ...]

    @classmethod
    def empty(cls) -> "SemanticGraph":
        return cls(nodes=(), edges=(), status="unavailable", degradations=())

    def node(self, node_id: str) -> SemanticNode:
        for item in self.nodes:
            if item.node_id == node_id:
                return item
        raise KeyError(node_id)

    def find_nodes(self, name: str, kinds: set[str] | None = None) -> list[SemanticNode]:
        return [
            item
            for item in self.nodes
            if item.name == name and (kinds is None or item.kind in kinds)
        ]

    def incoming(self, node_id: str, kind: str | None = None) -> list[SemanticEdge]:
        return [item for item in self.edges if item.target_id == node_id and (kind is None or item.kind == kind)]

    def outgoing(self, node_id: str, kind: str | None = None) -> list[SemanticEdge]:
        return [item for item in self.edges if item.source_id == node_id and (kind is None or item.kind == kind)]

    def to_record(self) -> dict[str, Any]:
        return {
            "version": "semantic_graph_v2",
            "status": self.status,
            "nodes": [asdict(item) for item in self.nodes],
            "edges": [asdict(item) for item in self.edges],
            "degradations": list(self.degradations),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }


def _id(*parts: object) -> str:
    value = "|".join(str(part) for part in parts)
    return "sem_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:18]


def _line_end(item: dict[str, Any]) -> int:
    start = int(item.get("line") or item.get("line_start") or 1)
    return max(start, int(item.get("line_end") or item.get("end_line") or start))


def _class_kind(item: dict[str, Any]) -> NodeKind:
    node_type = str(item.get("node_type") or "")
    snippet = str(item.get("snippet") or "")
    return "interface" if "interface" in node_type or re.search(r"\binterface\s+", snippet) else "class"


def semantic_graph_from_tree_sitter(raw: dict[str, Any]) -> SemanticGraph:
    nodes: list[SemanticNode] = []
    edges: list[SemanticEdge] = []
    node_by_id: dict[str, SemanticNode] = {}

    def add_node(node: SemanticNode) -> SemanticNode:
        if node.node_id not in node_by_id:
            node_by_id[node.node_id] = node
            nodes.append(node)
        return node_by_id[node.node_id]

    paths = sorted(
        {
            str(item.get("file_path") or "")
            for key in ("classes", "functions", "imports", "callers", "config_refs")
            for item in raw.get(key) or []
            if isinstance(item, dict) and str(item.get("file_path") or "")
        }
    )
    file_nodes: dict[str, SemanticNode] = {}
    for path in paths:
        kind: NodeKind = "test" if "test" in path.lower() else "file"
        file_nodes[path] = add_node(SemanticNode(_id("file", path), kind, path.rsplit("/", 1)[-1], path, 1, 1))

    class_nodes: list[tuple[dict[str, Any], SemanticNode]] = []
    function_nodes: list[tuple[dict[str, Any], SemanticNode]] = []
    for item in raw.get("classes") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("file_path") or "")
        start = int(item.get("line") or item.get("line_start") or 1)
        node = add_node(
            SemanticNode(_id("class", path, item.get("name"), start), _class_kind(item), str(item.get("name") or ""), path, start, _line_end(item))
        )
        class_nodes.append((item, node))
        if path in file_nodes:
            edges.append(SemanticEdge(file_nodes[path].node_id, node.node_id, "contains", "syntax", "tree_sitter"))

    for item in raw.get("functions") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("file_path") or "")
        start = int(item.get("line") or item.get("line_start") or 1)
        node = add_node(
            SemanticNode(_id("function", path, item.get("name"), start), "function", str(item.get("name") or ""), path, start, _line_end(item))
        )
        function_nodes.append((item, node))
        owner = min(
            (class_node for _, class_node in class_nodes if class_node.file_path == path and class_node.line_start <= start <= class_node.line_end),
            key=lambda candidate: candidate.line_end - candidate.line_start,
            default=file_nodes.get(path),
        )
        if owner:
            edges.append(SemanticEdge(owner.node_id, node.node_id, "contains", "syntax", "tree_sitter"))

    classes_by_name: dict[str, list[SemanticNode]] = {}
    for _, node in class_nodes:
        classes_by_name.setdefault(node.name, []).append(node)
    for item, source in class_nodes:
        snippet = str(item.get("snippet") or "")
        for relation, pattern in (
            ("implements", r"\bimplements\s+([^\{]+)"),
            ("extends", r"\bextends\s+([A-Za-z_]\w*)"),
        ):
            match = re.search(pattern, snippet)
            if not match:
                continue
            names = re.findall(r"[A-Za-z_]\w*", match.group(1))
            for name in names:
                targets = classes_by_name.get(name) or []
                if len(targets) == 1:
                    edges.append(SemanticEdge(source.node_id, targets[0].node_id, relation, "syntax", "tree_sitter_declaration"))

    # A test importing exactly one production type is a syntax-audited test
    # association. Name-only Test suffix matching remains a discovery fallback
    # in FrozenSourceTools and is not promoted to a semantic edge here.
    for item in raw.get("imports") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("file_path") or "")
        test_file = file_nodes.get(path)
        if not test_file or test_file.kind != "test":
            continue
        imported = str(item.get("import") or "")
        names = re.findall(r"[A-Za-z_]\w*", imported)
        imported_name = names[-1] if names else ""
        targets = [node for node in classes_by_name.get(imported_name, []) if node.file_path != path]
        if len(targets) == 1:
            edges.append(SemanticEdge(targets[0].node_id, test_file.node_id, "tested_by", "syntax", "tree_sitter_import"))

    functions_by_name: dict[str, list[SemanticNode]] = {}
    for _, node in function_nodes:
        functions_by_name.setdefault(node.name, []).append(node)
    for call in raw.get("callers") or []:
        if not isinstance(call, dict):
            continue
        path = str(call.get("file_path") or "")
        caller_name = str(call.get("caller") or "<module>")
        line = int(call.get("line") or 1)
        caller_candidates = [node for _, node in function_nodes if node.file_path == path and node.name == caller_name]
        caller = caller_candidates[0] if len(caller_candidates) == 1 else add_node(
            SemanticNode(_id("caller", path, caller_name, line), "function", caller_name, path, line, line)
        )
        targets = functions_by_name.get(str(call.get("callee") or "")) or []
        same_file = [target for target in targets if target.file_path == path]
        if len(same_file) == 1:
            edges.append(SemanticEdge(caller.node_id, same_file[0].node_id, "calls", "syntax", "tree_sitter_local_call"))
        else:
            for target in targets:
                edges.append(SemanticEdge(caller.node_id, target.node_id, "calls", "heuristic", "tree_sitter_name_match"))

    for ref in raw.get("config_refs") or []:
        if not isinstance(ref, dict):
            continue
        path = str(ref.get("file_path") or "")
        key = str(ref.get("config_key") or "").strip()
        if not path or not key:
            continue
        line = int(ref.get("line") or 1)
        caller_name = str(ref.get("caller") or "<module>")
        caller_candidates = [
            node
            for _, node in function_nodes
            if node.file_path == path and node.name == caller_name and node.line_start <= line <= node.line_end
        ]
        source = caller_candidates[0] if len(caller_candidates) == 1 else add_node(
            SemanticNode(_id("config_reader", path, caller_name, line), "function", caller_name, path, line, line)
        )
        target = add_node(SemanticNode(_id("config", key), "config", key, path, line, line))
        edges.append(SemanticEdge(source.node_id, target.node_id, "reads_config", "syntax", "tree_sitter_config_call"))

    degradations = tuple(item for item in raw.get("parse_errors") or [] if isinstance(item, dict))
    raw_status = str(raw.get("status") or "unavailable")
    status = "full" if raw_status in {"indexed", "cached"} and not degradations else "partial" if nodes else "unavailable"
    unique_edges = {
        (edge.source_id, edge.target_id, edge.kind, edge.confidence, edge.resolver): edge for edge in edges
    }
    return SemanticGraph(
        nodes=tuple(sorted(nodes, key=lambda item: (item.file_path, item.line_start, item.kind, item.name))),
        edges=tuple(sorted(unique_edges.values(), key=lambda item: (item.source_id, item.kind, item.target_id))),
        status=status,
        degradations=degradations,
    )
