"""Image-input handler (placeholder).

A production deployment would call a vision-capable model (gpt-4o,
DeepSeek-VL, Qwen-VL, ...) here and produce a grounded analysis of the
uploaded image. For the open-source release we keep the node intentionally
minimal: it returns a canned, friendly message that nudges the user to
restate the request in text. This keeps the graph traversable when an
image is attached without coupling the public release to any specific
vision provider or its API key.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.models.state import SharedState as AgentState

_log = logging.getLogger(__name__)

PLACEHOLDER = (
    "图片识别功能尚未在本演示版本中接入；"
    "当前可受理文本与文件查询。如有图片相关需求请描述图中信息。"
)


async def image_query_node(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Return a canned response for image inputs.

    Args:
        state: Shared graph state. ``state['config']['image_path']`` is
            inspected only for diagnostic logging.
        config: LangGraph runnable config (unused).

    Returns:
        A state update containing a single :class:`AIMessage` and an
        ``agent_results.image_agent`` entry marked ``success`` so the
        graph proceeds to the hallucination check normally.
    """
    del config

    cfg = state.get("config") or {}
    image_path = str(cfg.get("image_path") or "")
    if image_path:
        _log.info("image_query_node received image: %s", image_path)

    return {
        "messages": [AIMessage(content=PLACEHOLDER)],
        "agent_results": {
            "image_agent": {
                "agent": "image_agent",
                "status": "success",
                "data": {"image_path": image_path},
                "message": "image placeholder",
            }
        },
    }
