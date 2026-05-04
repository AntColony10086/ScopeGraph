"""Top-level intent router.

Classifies the latest user message into one of three intents (general chat,
clarification request, or full data query) and emits a
:class:`langgraph.types.Command` so the graph can dispatch directly without
needing a separate conditional edge.

The node is deliberately small: it composes a system prompt from the
shared :data:`ROUTER_SYSTEM_PROMPT` plus a user-context block that pins the
current user's bound enterprise(s), then asks a structured-output call to
return a :class:`RouteDecision`. On any LLM failure the structured-output
helper returns the default decision (``graphrag-query``) so the graph stays
traversable.
"""

from __future__ import annotations

import logging
from typing import Literal, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.graph.user_context import build_user_context_block
from app.models.state import SharedState as AgentState
from app.prompts.router_prompt import ROUTER_SYSTEM_PROMPT
from app.utils.fallback_rules import faq_cache_lookup
from app.utils.llm import get_chat_model, structured_output, to_openai_messages

_log = logging.getLogger(__name__)

NextNode = Literal[
    "respond_to_general_query",
    "additional_query_subgraph",
    "graphrag_query_subgraph",
    "create_image_query",
    "create_file_query",
    "hallucination_check",
]

_INTENT_TO_NODE: dict[str, NextNode] = {
    "general-query": "respond_to_general_query",
    "additional-query": "additional_query_subgraph",
    "graphrag-query": "graphrag_query_subgraph",
}


class RouteDecision(BaseModel):
    """Output schema for the router LLM call.

    Attributes:
        intent: One of ``general-query``, ``additional-query``,
            ``graphrag-query``. Determines the next node.
        reason: Short justification (kept terse for log lines).
        rewritten_question: An optional canonicalised form of the user's
            latest message, used downstream by the planner / cypher-gen.
    """

    intent: Literal["general-query", "additional-query", "graphrag-query"] = Field(
        ..., description="Classification of the latest user message."
    )
    reason: str = Field(default="", description="Short justification (<= 30 chars).")
    rewritten_question: str = Field(
        default="", description="Canonical phrasing of the user question."
    )


async def route_node(
    state: AgentState,
    config: RunnableConfig,
) -> Command[NextNode]:
    """Classify the user's latest message and dispatch via Command.

    The node short-circuits in three cases before falling back to the LLM:

    * If the request carried an image attachment, route to image handling.
    * If the request carried a document attachment, route to file handling.
    * If the message is an exact FAQ match, inject the cached answer and
      jump straight to hallucination_check.

    Args:
        state: Current shared graph state.
        config: LangGraph runnable config (unused but kept for interface
            compatibility with newer LangGraph versions that pass it
            positionally).

    Returns:
        A :class:`Command` whose ``goto`` is the next node and whose
        ``update`` carries the parsed router decision so downstream nodes
        can read it from ``state["router"]``.
    """
    del config  # parameter kept for LangGraph node-signature compatibility

    cfg = state.get("config") or {}
    if cfg.get("image_path"):
        _log.info("route -> create_image_query (image attached)")
        return Command(
            goto="create_image_query",
            update={
                "router": {
                    "type": "image-query",
                    "logic": "user uploaded image",
                    "question": "",
                }
            },
        )
    if cfg.get("file_path"):
        _log.info("route -> create_file_query (file attached)")
        return Command(
            goto="create_file_query",
            update={
                "router": {
                    "type": "file-query",
                    "logic": "user uploaded file",
                    "question": "",
                }
            },
        )

    messages = state.get("messages") or []
    last_text = messages[-1].content if messages else ""
    last_text_str = last_text if isinstance(last_text, str) else str(last_text)

    cached = faq_cache_lookup(last_text_str)
    if cached:
        _log.info("route -> hallucination_check (FAQ hit)")
        return Command(
            goto="hallucination_check",
            update={
                "router": {
                    "type": "faq-hit",
                    "logic": "FAQ cache hit",
                    "question": last_text_str,
                },
                "messages": [AIMessage(content=cached)],
            },
        )

    user_ctx = await build_user_context_block(
        state.get("user_role"),
        state.get("accessible_enterprises"),
    )
    system_prompt = (
        f"{ROUTER_SYSTEM_PROMPT}\n\n{user_ctx}" if user_ctx else ROUTER_SYSTEM_PROMPT
    )
    chat_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        *to_openai_messages(messages),
    ]

    model = get_chat_model(temperature=0)
    decision = await structured_output(
        model,
        RouteDecision,
        chat_messages,
        default=RouteDecision(
            intent="graphrag-query",
            reason="fallback default",
            rewritten_question=last_text_str,
        ),
    )
    decision = cast(RouteDecision, decision)

    next_node: NextNode = _INTENT_TO_NODE[decision.intent]
    _log.info("route -> %s (%s)", next_node, decision.reason[:30])

    router_payload = {
        "type": decision.intent,
        "logic": decision.reason,
        "question": decision.rewritten_question or last_text_str,
    }
    return Command(
        goto=next_node,
        update={
            "router": router_payload,
            "turn_count": (state.get("turn_count") or 0) + 1,
        },
    )
