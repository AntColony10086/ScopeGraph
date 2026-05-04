"""Session lifecycle utilities for trimming, summarising and refreshing memory.

This module sits one layer above :mod:`app.memory.session_manager`: it
operates on already-loaded message lists and only touches Redis when it
needs to extend a session's TTL. Three concerns are addressed here:

* Bounded history — :func:`maintain_history` writes the latest user/assistant
  pair and truncates the per-session Redis list to a configurable window.
* Token budgeting — :func:`compute_context_window` shrinks an in-memory
  history to fit a model's context budget while preserving a leading system
  message when one is present.
* Light summarisation — :func:`summarize_old_turns` calls the project's
  light LLM to produce a compact summary, returning ``""`` on any failure
  so that an outage in the summariser cannot break the chat flow.

Token counting uses ``tiktoken`` when available (the ``cl100k_base`` encoding
roughly matches GPT-4-class tokenisers, which is the closest open analogue
for our hosted MiniMax models). When ``tiktoken`` is not installed we fall
back to ``len(text) // 2`` — coarse but conservative for both ASCII and CJK.

Legacy helpers used by ``api/chat.py`` and the graph subgraphs
(:class:`ConversationAnalysis`, :func:`analyze_conversation`,
:func:`save_session_record_upsert`, :func:`update_user_profile_from_analysis`,
:func:`post_session_process`) are retained at the bottom of the module.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, cast

from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.memory.session_manager import (
    _messages_key,  # noqa: PLC2701  intentional internal reuse
    append_message,
    get_messages,
    get_redis,
    load_history,
)
from app.models.database import (
    ChatSession,
    UserProfile,
    get_async_session_factory,
)
from app.utils.llm import get_light_model, safe_ainvoke, structured_output

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` for context-window budgeting.

    Prefers :mod:`tiktoken`'s ``cl100k_base`` encoding when available because
    its byte-pair table is a reasonable proxy for modern Chinese-capable
    chat models. When ``tiktoken`` is unavailable we use ``len(text) // 2``,
    which slightly over-estimates ASCII (good for safety) and slightly
    under-estimates dense CJK (acceptable; the coarse half-character
    heuristic is a deliberate trade-off for portability).
    """
    if not text:
        return 0
    try:
        import tiktoken  # local import — keeps the dep optional
    except ImportError:
        return max(1, len(text) // 2)
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("tiktoken encoding failed (%s); falling back to len/2", exc)
        return max(1, len(text) // 2)


def _message_tokens(msg: dict[str, Any]) -> int:
    """Return an estimated token count for a single chat-turn dict."""
    content = msg.get("content")
    if isinstance(content, str):
        # +4 to amortise role/content/name/separators across the message,
        # matching the standard "tokens-per-message" overhead from
        # OpenAI's cookbook examples.
        return _estimate_tokens(content) + 4
    return 4


# ---------------------------------------------------------------------------
# Public interface — primary
# ---------------------------------------------------------------------------


async def maintain_history(
    session_id: str,
    user_msg: dict[str, Any],
    assistant_msg: dict[str, Any],
    max_turns: int = 20,
) -> list[dict[str, Any]]:
    """Append the latest exchange and trim history to ``max_turns`` round-trips.

    A "turn" is a (user, assistant) pair, so the underlying Redis list is
    capped at ``max_turns * 2`` entries. Trimming uses ``LTRIM`` so it stays
    O(1) regardless of how large the list grew before the trim.

    Args:
        session_id: The active session.
        user_msg: The user's message dict (must contain ``role`` and ``content``).
        assistant_msg: The assistant's reply dict (same shape as ``user_msg``).
        max_turns: Maximum number of user/assistant pairs to retain.

    Returns:
        The (chronological) list of messages currently stored after trimming.
    """
    if max_turns <= 0:
        raise ValueError("max_turns must be positive")

    await append_message(session_id, user_msg)
    await append_message(session_id, assistant_msg)

    keep = max_turns * 2
    client = await get_redis()
    key = _messages_key(session_id)
    # ``ltrim`` with start=-keep keeps the trailing ``keep`` elements. If the
    # list already has fewer entries this is a no-op.
    await cast(Awaitable[str], client.ltrim(key, -keep, -1))

    return await load_history(session_id)


def compute_context_window(
    history: list[dict[str, Any]],
    budget_tokens: int,
) -> list[dict[str, Any]]:
    """Drop oldest non-system messages until the running token total fits.

    The function preserves a leading system message when one is present at
    index 0 — the caller has presumably constructed a system prompt that
    should accompany every model invocation. Within the remaining tail we
    drop from the *front* (oldest first) so the model always sees the most
    recent dialogue context.

    Args:
        history: Chronologically ordered list of message dicts.
        budget_tokens: Hard upper bound on the total token estimate of the
            returned list. Must be a positive integer.

    Returns:
        A new list containing the leading system message (if any) followed
        by as many trailing messages as fit within ``budget_tokens``.
    """
    if budget_tokens <= 0:
        return []
    if not history:
        return []

    has_system = bool(history) and history[0].get("role") == "system"
    system_msg = history[0] if has_system else None
    tail = history[1:] if has_system else list(history)

    base_budget = budget_tokens
    if system_msg is not None:
        base_budget -= _message_tokens(system_msg)
        if base_budget <= 0:
            # System message alone already exceeds the budget; we still hand
            # it back so the caller's prompt remains structurally valid.
            return [system_msg]

    # Walk newest -> oldest, keeping messages whose cumulative size fits.
    kept_reverse: list[dict[str, Any]] = []
    running = 0
    for msg in reversed(tail):
        cost = _message_tokens(msg)
        if running + cost > base_budget:
            break
        kept_reverse.append(msg)
        running += cost

    kept = list(reversed(kept_reverse))
    if system_msg is not None:
        return [system_msg, *kept]
    return kept


async def summarize_old_turns(turns: list[dict[str, Any]]) -> str:
    """Summarise a sequence of older turns via the light LLM, defensively.

    The summary is deliberately constrained to roughly 200 Chinese tokens so
    it can be re-injected as context without crowding out fresh turns. Any
    failure — empty input, network error, malformed response — is swallowed
    and surfaced as ``""`` to keep the chat pipeline running. The exception
    is logged at ``WARNING`` so operators can still spot recurring issues.

    Args:
        turns: List of message dicts to compress.

    Returns:
        The summary text, or ``""`` if nothing useful could be produced.
    """
    if not turns:
        return ""

    rendered_lines: list[str] = []
    for msg in turns:
        role = str(msg.get("role", "user"))
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        rendered_lines.append(f"{role}: {content}")
    if not rendered_lines:
        return ""
    transcript = "\n".join(rendered_lines)

    system_prompt = (
        "summarize these conversation turns in <=200 Chinese tokens. "
        "Keep concrete entities (product, order, enterprise IDs) and the user's "
        "current intent; drop pleasantries."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcript},
    ]

    try:
        model = get_light_model(temperature=0.1, max_tokens=400)
        response = await safe_ainvoke(model, messages)
    except Exception as exc:
        logger.warning("summarize_old_turns: LLM invocation failed: %s", exc)
        return ""

    content = getattr(response, "content", response)
    if isinstance(content, list):
        # Some providers return [{"type": "text", "text": "..."}, ...]
        parts: list[str] = []
        for piece in content:
            if isinstance(piece, dict):
                text_part = piece.get("text") or piece.get("content")
                if isinstance(text_part, str):
                    parts.append(text_part)
            elif isinstance(piece, str):
                parts.append(piece)
        return "".join(parts).strip()
    if isinstance(content, str):
        return content.strip()
    return ""


async def refresh_session(session_id: str) -> None:
    """Re-apply the configured TTL to the session's messages key.

    Useful when the session is otherwise idle (e.g. the user is viewing a
    rendered answer but has not yet typed the next question) and we want to
    extend its lifetime without writing a new message.
    """
    from app.config import get_settings  # local import avoids import cycle

    settings = get_settings()
    client = await get_redis()
    await cast(
        Awaitable[bool],
        client.expire(_messages_key(session_id), settings.redis_session_ttl),
    )


# ---------------------------------------------------------------------------
# Legacy helpers — kept for the existing API and graph layers
# ---------------------------------------------------------------------------


class ConversationAnalysis(BaseModel):
    """Structured output schema produced by :func:`analyze_conversation`."""

    summary: str = Field(description="一句话总结本次对话内容，不超过50字")
    user_intent_categories: list[str] = Field(
        default_factory=list,
        description=(
            "用户关注的指标类别，例如 ['直接排放Scope1','减排与履约','污染物排放']；"
            "无法判断时返回空列表"
        ),
    )
    satisfaction: float = Field(
        default=0.7,
        description="基于语气与问题是否解决评估的满意度（0.0-1.0）",
    )
    is_complaint: bool = Field(default=False, description="用户是否在投诉")
    prefers_human: bool = Field(default=False, description="用户是否明确要求转人工")


async def analyze_conversation(session_id: str) -> ConversationAnalysis | None:
    """Run the light LLM over the trailing 20 turns to extract analytics.

    Returns ``None`` when there are too few messages to be worth analysing
    or when the structured-output call cannot be coerced into the schema.
    """
    messages = await get_messages(session_id, last_n=20)
    if len(messages) < 2:
        return None

    transcript_lines: list[str] = []
    for msg in messages:
        speaker = "用户" if msg.get("role") in {"human", "user"} else "客服"
        text = str(msg.get("content", ""))[:200]
        transcript_lines.append(f"{speaker}: {text}")
    transcript = "\n".join(transcript_lines)

    model = get_light_model(temperature=0)
    try:
        result = await structured_output(
            model,
            ConversationAnalysis,
            [
                {
                    "role": "system",
                    "content": (
                        "分析以下客服对话，提取关键信息：\n"
                        "- summary: 一句话总结对话主题\n"
                        "- user_intent_categories: 用户关注的指标类别（例如"
                        "'直接排放Scope1'、'间接排放Scope2'、'能源消耗'、"
                        "'污染物排放'、'减排与履约'）\n"
                        "- satisfaction: 用户满意度 0.0-1.0\n"
                        "- is_complaint: 是否投诉\n"
                        "- prefers_human: 是否要求转人工"
                    ),
                },
                {"role": "user", "content": f"对话内容:\n{transcript}"},
            ],
        )
    except Exception as exc:
        logger.warning("Conversation analysis failed: %s", exc)
        return None
    return cast(ConversationAnalysis | None, result)


async def save_session_record_upsert(
    session_id: str,
    user_id: str,
    turn_count: int,
    summary: str | None = None,
    satisfaction: float | None = None,
    escalated: bool = False,
) -> None:
    """Insert or update the ``chat_sessions`` row for this conversation."""
    factory = get_async_session_factory()  # type: ignore[no-untyped-call]
    try:
        async with factory() as session:
            existing = await session.get(ChatSession, session_id)
            now = datetime.now(timezone.utc)
            if existing is not None:
                existing.user_id = user_id
                existing.ended_at = now
                existing.turn_count = turn_count
                existing.satisfaction_score = satisfaction
                existing.escalated = escalated
                existing.summary = summary
            else:
                session.add(
                    ChatSession(
                        session_id=session_id,
                        user_id=user_id,
                        ended_at=now,
                        turn_count=turn_count,
                        satisfaction_score=satisfaction,
                        escalated=escalated,
                        summary=summary,
                    )
                )
            await session.commit()
            logger.info("ChatSession upserted: %s", session_id)
    except Exception as exc:
        logger.warning("ChatSession upsert failed: %s", exc)


async def update_user_profile_from_analysis(
    user_id: str,
    analysis: ConversationAnalysis,
) -> None:
    """Roll the conversation analysis into the persistent user profile row."""
    factory = get_async_session_factory()  # type: ignore[no-untyped-call]
    try:
        async with factory() as session:
            values: dict[str, Any] = {
                "last_conversation_summary": analysis.summary,
                "total_chats": UserProfile.total_chats + 1,
                "last_chat_at": datetime.now(timezone.utc),
            }
            if analysis.satisfaction is not None:
                values["avg_satisfaction"] = analysis.satisfaction
            if analysis.is_complaint:
                values["complaint_count"] = UserProfile.complaint_count + 1
            if analysis.prefers_human:
                values["prefer_human_service"] = True

            await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == user_id)
                .values(**values)
            )

            if analysis.user_intent_categories:
                row = await session.execute(
                    select(UserProfile.favorite_categories).where(
                        UserProfile.user_id == user_id
                    )
                )
                current = row.scalar_one_or_none() or []
                if isinstance(current, str):
                    import json

                    current = json.loads(current) if current else []
                merged = list(
                    dict.fromkeys(
                        list(current or []) + analysis.user_intent_categories
                    )
                )[:5]
                await session.execute(
                    update(UserProfile)
                    .where(UserProfile.user_id == user_id)
                    .values(favorite_categories=merged)
                )

            await session.commit()
            logger.info(
                "User profile updated for %s, summary=%s", user_id, analysis.summary
            )
    except Exception as exc:
        logger.warning("User profile update failed: %s", exc)


async def post_session_process(
    session_id: str,
    user_id: str,
    turn_count: int,
    escalated: bool = False,
) -> None:
    """End-of-turn pipeline: analyse, persist, then update the user profile.

    This is invoked as a fire-and-forget task from :mod:`app.api.chat` so it
    must never raise. All failure modes log and return.
    """
    try:
        analysis = await analyze_conversation(session_id)
        summary = analysis.summary if analysis is not None else None
        satisfaction = analysis.satisfaction if analysis is not None else None

        await save_session_record_upsert(
            session_id=session_id,
            user_id=user_id,
            turn_count=turn_count,
            summary=summary,
            satisfaction=satisfaction,
            escalated=escalated,
        )

        if analysis is not None:
            await update_user_profile_from_analysis(user_id, analysis)
    except Exception as exc:
        logger.error("Post-session processing failed: %s", exc, exc_info=True)
