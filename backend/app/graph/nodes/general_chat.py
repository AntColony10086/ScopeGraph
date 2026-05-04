"""General-chat handler.

Used for greetings, small-talk, and any user message the router classified
as ``general-query``. Builds a chat-style prompt from
:data:`CHAT_SYSTEM_PROMPT`, optionally enriched with the user's persona
profile, and asks a *light* model for a short reply.

Reasoning models (e.g. MiniMax M2.x) wrap their internal chain-of-thought
in ``<think>...</think>``. We strip those tags via :func:`strip_thinking`
before returning, so only the polished answer is shown to the user.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.memory.user_profile import format_profile_for_prompt
from app.models.state import SharedState as AgentState
from app.prompts.chat_prompt import CHAT_SYSTEM_PROMPT
from app.utils.llm import (
    get_light_model,
    safe_ainvoke,
    strip_thinking,
    to_openai_messages,
)

_log = logging.getLogger(__name__)

# Keep the rolling window short — small-talk doesn't need long context and
# trimming reduces token spend on each turn.
_HISTORY_WINDOW = 6
_DEFAULT_MAX_TOKENS = 1024


async def general_chat_node(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Reply to non-business chat using the lightweight chat model.

    Args:
        state: Shared graph state. We read ``messages`` for history and
            ``user_profile`` for optional persona injection.
        config: LangGraph runnable config (unused but accepted).

    Returns:
        State update with the new :class:`AIMessage` and an
        ``agent_results.chat_agent`` summary entry. On any exception the
        node returns a polite fallback so the graph still reaches END.
    """
    del config

    profile = state.get("user_profile")
    profile_block = format_profile_for_prompt(profile) if profile else ""
    system_prompt = (
        f"{CHAT_SYSTEM_PROMPT}\n\n{profile_block}" if profile_block else CHAT_SYSTEM_PROMPT
    )

    history = state.get("messages") or []
    chat_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        *to_openai_messages(history[-_HISTORY_WINDOW:]),
    ]

    model = get_light_model(temperature=0.7, max_tokens=_DEFAULT_MAX_TOKENS)

    try:
        response = await safe_ainvoke(model, chat_messages)
        raw = response.content if isinstance(response.content, str) else str(response.content)
        reply = strip_thinking(raw)
    except Exception as e:  # noqa: BLE001
        _log.warning("general_chat_node fallback after error: %s", e)
        reply = (
            "您好～服务正在繁忙重试，"
            "您可以告诉我企业名+年份+指标（例如「化工企业A 2023 Scope1 排放」），"
            "我马上为您查询～"
        )

    if not reply:
        reply = "您好～请问您想了解哪家企业的碳数据？"

    return {
        "messages": [AIMessage(content=reply)],
        "agent_results": {
            "chat_agent": {
                "agent": "chat_agent",
                "status": "success",
                "data": {},
                "message": reply,
            }
        },
    }
