"""Top-level LangGraph supervisor.

The main graph is the entry point that every chat turn flows through. It
delegates intent classification to the router node, dispatches to one of
several business handlers, and finally screens the assistant's reply for
PII leaks and hallucinations before returning it to the API layer.

Topology (ASCII)::

    START
      |
      v
    +---------------+
    |  route_node   |  --(Command(goto=...))-->
    +---------------+
      |     |     |     |     |     |
      |     |     |     |     |     +-- hallucination_check  (FAQ cache hit)
      |     |     |     |     |
      |     |     |     |     +-------- create_file_query
      |     |     |     |
      |     |     |     +-------------- create_image_query
      |     |     |
      |     |     +-------------------- graphrag_query_subgraph
      |     |
      |     +---------------------------- additional_query_subgraph
      |
      +-------------------------------- respond_to_general_query
                                                 |
              all business branches converge --> v
                                       +-----------------------+
                                       |  hallucination_check  |
                                       +-----------------------+
                                                 |
                                                 v
                                                END

Key invariants:

* The router emits a :class:`langgraph.types.Command` so dispatch happens
  *inside* :func:`route_node`. The graph wiring therefore relies on
  static :func:`add_edge` calls rather than ``add_conditional_edges``.
* Every business-logic node feeds into ``hallucination_check`` (never the
  other way around) so PII / cross-tenant / grounding checks always run
  on whatever the business handler produced.
* ``hallucination_check`` is also a *direct* target of ``route_node`` for
  the FAQ-cache short-circuit path: the cached answer is appended to
  state and we still want it audited before returning to the caller.
* The two subgraphs (``additional_query_subgraph`` and
  ``graphrag_query_subgraph``) are pre-compiled :class:`CompiledStateGraph`
  objects exported from their respective modules and registered as
  regular nodes — LangGraph treats compiled subgraphs as drop-in
  callables.

Public surface:

* :func:`build_main_graph` — assemble and compile the supervisor.
* ``graph`` — module-level :class:`CompiledStateGraph` instance, built at
  import time so the API layer can stream into it without re-compilation.
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes.file_query import file_query_node
from app.graph.nodes.general_chat import general_chat_node
from app.graph.nodes.hallucination import hallucination_check_node
from app.graph.nodes.image_query import image_query_node
from app.graph.nodes.router import route_node
from app.graph.subgraphs.additional_info import additional_query_subgraph
from app.graph.subgraphs.graphrag_query import graphrag_query_subgraph
from app.models.state import SharedState

# ---------------------------------------------------------------------------
# Node-name constants
#
# Centralising the names avoids a typo in any of the half-dozen places they
# are referenced. They must match the literal targets returned by
# ``route_node`` via ``Command(goto=...)`` — see ``app.graph.nodes.router``.
# ---------------------------------------------------------------------------
_ROUTE: str = "route_node"
_GENERAL: str = "respond_to_general_query"
_ADDITIONAL: str = "additional_query_subgraph"
_GRAPHRAG: str = "graphrag_query_subgraph"
_IMAGE: str = "create_image_query"
_FILE: str = "create_file_query"
_HALLUCINATION: str = "hallucination_check"

# Every business-logic node that must be screened by the hallucination
# check before END. Order is irrelevant — these are static edges.
_BUSINESS_NODES: tuple[str, ...] = (
    _GENERAL,
    _ADDITIONAL,
    _GRAPHRAG,
    _IMAGE,
    _FILE,
)


def build_main_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """Assemble, wire, and compile the supervisor graph.

    The function is deterministic and side-effect free aside from the
    cost of constructing a :class:`StateGraph`. Each call returns a fresh
    compiled instance so callers can build a graph with their own
    checkpointer / interrupt config if needed.

    Returns:
        A :class:`CompiledStateGraph` ready to be invoked via
        ``ainvoke`` / ``astream``. The graph operates on
        :class:`app.models.state.SharedState`.
    """
    workflow: StateGraph[Any, Any, Any, Any] = StateGraph(SharedState)

    # --- Register nodes -----------------------------------------------------
    # Subgraphs are imported as ``StateGraph`` per their public type signature
    # but are actually pre-compiled :class:`CompiledStateGraph` objects (see
    # ``app.graph.subgraphs.*``). LangGraph's ``add_node`` accepts any
    # ``Runnable``, which a compiled graph satisfies, so we cast at the
    # boundary rather than mutating the upstream subgraph signatures.
    additional_runnable = cast(Runnable[Any, Any], additional_query_subgraph)
    graphrag_runnable = cast(Runnable[Any, Any], graphrag_query_subgraph)

    workflow.add_node(_ROUTE, route_node)
    workflow.add_node(_GENERAL, general_chat_node)
    workflow.add_node(_ADDITIONAL, additional_runnable)
    workflow.add_node(_GRAPHRAG, graphrag_runnable)
    workflow.add_node(_IMAGE, image_query_node)
    workflow.add_node(_FILE, file_query_node)
    workflow.add_node(_HALLUCINATION, hallucination_check_node)

    # --- Edges --------------------------------------------------------------
    # 1. START → route_node. The router itself decides where to go from
    #    here by returning ``Command(goto=...)``; no conditional edge needed.
    workflow.add_edge(START, _ROUTE)

    # 2. Every business handler funnels into the hallucination check. These
    #    are unconditional edges — once a business node finishes, the
    #    grounding / leak audit runs.
    for node in _BUSINESS_NODES:
        workflow.add_edge(node, _HALLUCINATION)

    # 3. The hallucination check is the single exit point of the graph.
    workflow.add_edge(_HALLUCINATION, END)

    return workflow.compile()


# Module-level instance used by the API layer. Compiled once at import time
# so subsequent requests skip the (small but non-zero) graph-construction
# overhead.
graph: CompiledStateGraph[Any, Any, Any, Any] = build_main_graph()


__all__ = ["build_main_graph", "graph"]
