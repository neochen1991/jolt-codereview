from __future__ import annotations

from typing import Any, Callable

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - exercised on machines missing required dependencies
    END = "__end__"
    StateGraph = None  # type: ignore[assignment]

GraphNode = tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]


def invoke_review_graph(
    initial_state: dict[str, Any],
    nodes: list[GraphNode],
    recorder: Any,
) -> dict[str, Any]:
    graph_span = recorder.span("langgraph_orchestrator", "orchestrator")
    node_names = [name for name, _ in nodes]
    if StateGraph is None:
        recorder.event(
            graph_span,
            "langgraph_missing",
            "LangGraph 是生产检视编排的必需依赖，请先安装 Python requirements",
            {"nodes": node_names, "engine": "unavailable"},
        )
        recorder.finish(graph_span, "failed")
        raise RuntimeError("LangGraph is required in production review orchestration; install requirements.txt")

    graph = StateGraph(dict)
    for name, fn in nodes:
        graph.add_node(name, fn)
    graph.set_entry_point(nodes[0][0])
    for (current, _), (next_name, _) in zip(nodes, nodes[1:]):
        graph.add_edge(current, next_name)
    graph.add_edge(nodes[-1][0], END)
    recorder.event(
        graph_span,
        "langgraph_started",
        f"LangGraph StateGraph 启动 {len(nodes)} 个节点",
        {"nodes": node_names, "engine": "langgraph"},
    )
    try:
        result = graph.compile().invoke({**initial_state, "orchestration_engine": "langgraph"})
        recorder.event(graph_span, "langgraph_completed", "LangGraph StateGraph 执行完成", {"nodes": node_names})
        recorder.finish(graph_span)
        return result
    except Exception:
        recorder.finish(graph_span, "failed")
        raise
