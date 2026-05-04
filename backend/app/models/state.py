"""Shared LangGraph state — TypedDict + Annotated reducers.

Why TypedDict (not Pydantic): LangGraph's reducer machinery (``add_messages``,
``operator.or_``, …) is wired into the **type annotations** via
:class:`typing.Annotated`. TypedDict gives the type system enough information
without forcing every node to allocate a Pydantic instance on every update.

Naming
------

``AgentState`` is the canonical name for the top-level graph state. The legacy
alias ``SharedState`` is preserved so existing imports keep working without
edits.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Sub-models — pydantic for input validation when nodes return dicts that the
# rest of the graph then converts back into typed objects.
# --------------------------------------------------------------------------- #
class Intent(BaseModel):
    """A single user intent extracted by the supervisor."""

    id: str
    intent: str
    target_agent: str
    context: str
    depends_on: list[str] = Field(default_factory=list)
    priority: int = 1


class AgentResult(BaseModel):
    """The structured result a sub-graph or tool returns to the supervisor."""

    agent: str
    status: Literal["success", "error", "need_confirmation", "need_info"]
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class PendingConfirmation(BaseModel):
    """A Tier-2 operation parked on the state until the user confirms or cancels."""

    action: str
    params: dict[str, Any]
    summary: str
    tier: int
    agent: str


# --------------------------------------------------------------------------- #
# Top-level graph state
# --------------------------------------------------------------------------- #
class AgentState(TypedDict, total=False):
    """Top-level state shared across the main LangGraph graph.

    Annotated fields carry a *reducer*: when a node returns ``{"messages": [m]}``
    the graph runtime calls ``add_messages(prev, [m])`` rather than overwriting
    the list, so concurrent branches can fan-in cleanly.
    """

    # ----- Session metadata -----
    session_id: str
    user_id: Optional[str]
    auth_level: Literal["anonymous", "authenticated"]
    user_role: str  # "user" | "admin"
    accessible_enterprises: list[str]  # CustomerID list — ["*"] means "all" (admin).

    # ----- Conversation -----
    messages: Annotated[list[BaseMessage], add_messages]
    context_summary: Optional[str]
    turn_count: int

    # ----- User profile (loaded from long-term memory) -----
    user_profile: Optional[dict[str, Any]]

    # ----- Routing / planning -----
    router: dict[str, Any]  # {type, logic, question}
    current_intents: list[dict[str, Any]]
    execution_plan: Optional[dict[str, Any]]
    intent: Optional[str]

    # ----- Agent / tool results -----
    agent_results: Annotated[dict[str, Any], operator.or_]
    pending_confirmation: Optional[dict[str, Any]]

    # ----- Cypher / GraphRAG output (used by sub-graphs that return upward) -----
    cypher: Optional[str]
    cypher_results: Optional[dict[str, Any]]
    final_answer: Optional[str]

    # ----- Per-domain caches -----
    order_cache: dict[str, Any]
    product_cache: dict[str, Any]

    # ----- Escalation -----
    escalation_flag: bool
    escalation_reason: Optional[str]
    sentiment_score: float
    consecutive_dissatisfied: int

    # ----- Attachments -----
    config: Optional[dict[str, Any]]


# Backwards-compatible alias — many call sites still ``import SharedState``.
SharedState = AgentState


# --------------------------------------------------------------------------- #
# Sub-graph states
# --------------------------------------------------------------------------- #
class GraphRAGSubState(TypedDict, total=False):
    """State carried inside the GraphRAG-query subgraph."""

    messages: Annotated[list[BaseMessage], add_messages]
    session_id: str
    user_id: Optional[str]
    user_role: str
    accessible_enterprises: list[str]
    router: dict[str, Any]

    # Guardrails decision before we run any tool.
    guardrails_decision: Optional[str]

    # Planner — decomposed sub-tasks the tool layer should answer.
    tasks: list[str]

    # Map-reduce: each tool appends to ``tool_results``.
    tool_results: Annotated[list[dict[str, Any]], operator.add]

    final_answer: Optional[str]


class AdditionalInfoSubState(TypedDict, total=False):
    """State carried inside the "ask user for missing info" subgraph."""

    messages: Annotated[list[BaseMessage], add_messages]
    session_id: str
    user_id: Optional[str]
    user_role: str
    accessible_enterprises: list[str]
    router: dict[str, Any]

    guardrails_decision: Optional[str]
    missing_info: Optional[str]


class Text2CypherSubState(TypedDict, total=False):
    """State carried inside the Text2Cypher subgraph."""

    task: str
    tool_name: str
    messages: Annotated[list[BaseMessage], add_messages]

    # Cypher generation cycle.
    generated_cypher: Optional[str]
    validation_errors: list[str]
    retry_count: int

    # Execution result.
    cypher_result: Optional[dict[str, Any]]
    final_answer: Optional[str]


__all__ = [
    "AdditionalInfoSubState",
    "AgentResult",
    "AgentState",
    "GraphRAGSubState",
    "Intent",
    "PendingConfirmation",
    "SharedState",
    "Text2CypherSubState",
]
