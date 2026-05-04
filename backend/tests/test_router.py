"""Router node behavioral tests.

These tests verify the router dispatches each intent to the correct downstream
node by mocking out the LLM call. No DB / network access required.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

from app.graph.nodes.router import RouteDecision, route_node


def _make_state(text: str) -> dict:
    """Build a minimal graph state with a single user message."""
    return {
        "messages": [HumanMessage(content=text)],
        "config": {},
        "user_role": "user",
        "accessible_enterprises": [],
        "turn_count": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "expected_node"),
    [
        ("general-query", "respond_to_general_query"),
        ("additional-query", "additional_query_subgraph"),
        ("graphrag-query", "graphrag_query_subgraph"),
    ],
)
async def test_route_dispatches_correct_node(intent: str, expected_node: str) -> None:
    """Router emits Command(goto=correct_node) for each classified intent."""
    state = _make_state("请问 2023 年化工企业 A 的 Scope1 排放是多少")
    fake_decision = RouteDecision(
        intent=intent, reason="unit-test", rewritten_question="x"
    )
    with patch(
        "app.graph.nodes.router.structured_output",
        new=AsyncMock(return_value=fake_decision),
    ), patch(
        "app.graph.nodes.router.build_user_context_block",
        new=AsyncMock(return_value=""),
    ), patch(
        "app.graph.nodes.router.get_chat_model",
        return_value=object(),
    ):
        cmd = await route_node(state, {})

    assert cmd.goto == expected_node
    # Router stores its decision in the update payload
    assert cmd.update["router"]["type"] == intent


@pytest.mark.asyncio
async def test_route_falls_back_on_llm_failure() -> None:
    """When structured_output yields the default fallback, route accordingly."""
    state = _make_state("anything")
    fallback = RouteDecision(
        intent="graphrag-query", reason="fallback default", rewritten_question="x"
    )
    with patch(
        "app.graph.nodes.router.structured_output",
        new=AsyncMock(return_value=fallback),
    ), patch(
        "app.graph.nodes.router.build_user_context_block",
        new=AsyncMock(return_value=""),
    ), patch(
        "app.graph.nodes.router.get_chat_model",
        return_value=object(),
    ):
        cmd = await route_node(state, {})

    assert cmd.goto == "graphrag_query_subgraph"


@pytest.mark.asyncio
async def test_route_image_attachment_short_circuits() -> None:
    """If state.config.image_path is set, router goes straight to image node."""
    state = _make_state("look at this")
    state["config"]["image_path"] = "/tmp/foo.png"

    cmd = await route_node(state, {})
    assert cmd.goto == "create_image_query"


@pytest.mark.asyncio
async def test_route_file_attachment_short_circuits() -> None:
    """If state.config.file_path is set, router goes straight to file node."""
    state = _make_state("read this")
    state["config"]["file_path"] = "/tmp/foo.pdf"

    cmd = await route_node(state, {})
    assert cmd.goto == "create_file_query"


@pytest.mark.asyncio
async def test_route_faq_cache_hit_short_circuits() -> None:
    """An FAQ cache hit bypasses the LLM and jumps to hallucination_check."""
    state = _make_state("ignored — cache lookup result is patched")
    with patch(
        "app.graph.nodes.router.faq_cache_lookup",
        return_value="缓存的 FAQ 回答",
    ):
        cmd = await route_node(state, {})

    assert cmd.goto == "hallucination_check"
    assert cmd.update["router"]["type"] == "faq-hit"
