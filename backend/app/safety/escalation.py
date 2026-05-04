"""Escalation decision policy for the chat graph.

When the autonomous assistant should hand off to a human operator is a
recurring tension in customer-service automation. We resolve it by
collapsing all triggers into a single pure function, :func:`should_escalate`,
that takes a snapshot of the current graph state and emits a structured
:class:`EscalationDecision`.

Triggers, in evaluation order:

1. **High-urgency keyword in the latest user message** — accident,
   leakage, safety incident.
2. **Three consecutive permission-denied assistant replies** — the
   assistant is going in circles; route to a human who can re-grant
   permissions.
3. **Three consecutive empty assistant replies** — the LLM produced
   nothing usable; let a human take over before the user gives up.
4. **Mid-urgency keyword in the latest user message** — explicit
   "talk to human" / "complaint".

When none fire, the default :class:`EscalationDecision` is returned.
"""

from __future__ import annotations

import re
from typing import Any, Final, Literal, Pattern, cast

from pydantic import BaseModel, Field


Urgency = Literal["low", "mid", "high"]


class EscalationDecision(BaseModel):
    """Structured outcome of an escalation evaluation.

    Attributes:
        escalate: Whether the conversation should be transferred to a
            human operator.
        reason: Short, human-readable identifier of the trigger
            (``""`` when ``escalate is False``). Designed to be logged
            and shown in operator dashboards, not to the end user.
        urgency: Rough priority bucket. ``"low"`` is the default for
            non-escalated turns; ``"mid"`` covers user-initiated handoff
            and stuck-in-loop conditions; ``"high"`` is reserved for
            safety-incident style keywords.
    """

    escalate: bool = Field(default=False, description="Whether to escalate.")
    reason: str = Field(default="", description="Trigger identifier.")
    urgency: Urgency = Field(default="low", description="Priority bucket.")


# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------


def _build_pattern(keywords: tuple[str, ...]) -> Pattern[str]:
    """Compile a case-insensitive alternation regex from *keywords*.

    The keywords contain a mix of CJK and ASCII tokens; we add ``re.UNICODE``
    so character-class behaviour stays predictable across both scripts.

    Args:
        keywords: Iterable of literal substrings to match.

    Returns:
        Compiled :class:`re.Pattern` whose :meth:`~re.Pattern.search` returns
        a match if *any* keyword is present.
    """
    return re.compile(
        "|".join(re.escape(kw) for kw in keywords),
        re.IGNORECASE | re.UNICODE,
    )


# Mid-urgency: user explicitly asks for a human or files a complaint.
_MID_URGENCY_KEYWORDS: Final[tuple[str, ...]] = (
    "人工",
    "转人工",
    "客服",
    "投诉",
    "human agent",
    "talk to a person",
)
_MID_URGENCY_PATTERN: Final[Pattern[str]] = _build_pattern(_MID_URGENCY_KEYWORDS)

# High-urgency: incident/safety keywords. "紧急" / "事故" / "泄漏" cover the
# Chinese chemical-industry safety-incident vocabulary; the English
# entries match the design-doc handoff list.
_HIGH_URGENCY_KEYWORDS: Final[tuple[str, ...]] = (
    "紧急",
    "事故",
    "泄漏",
    "safety incident",
    "urgent",
)
_HIGH_URGENCY_PATTERN: Final[Pattern[str]] = _build_pattern(_HIGH_URGENCY_KEYWORDS)

# Permission-denied markers. Matched as plain substrings on assistant
# replies — these phrases are emitted by the rule engine, not the user,
# so a regex with full alternation would be overkill.
_PERMISSION_DENIED_TOKENS: Final[tuple[str, ...]] = ("无权", "权限不足")

# Number of consecutive same-class assistant replies that triggers
# escalation. Both "empty replies" and "permission denied" share the
# same threshold by design (the 3-strikes-and-out heuristic).
_CONSECUTIVE_THRESHOLD: Final[int] = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a list of message dicts from *state*, defensively.

    Args:
        state: Graph state, expected to optionally carry ``messages``.

    Returns:
        A list of well-typed message dicts. Items that are not mappings
        are silently dropped — this keeps the function robust against
        legacy/checkpoint serialisations that occasionally contain
        ``BaseMessage`` instances or stray strings.
    """
    raw = state.get("messages") if isinstance(state, dict) else None
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(cast(dict[str, Any], item))
    return out


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    """Return the most-recent user message's content, or ``""`` if absent."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _trailing_assistant_messages(
    messages: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Return the trailing assistant messages, up to *limit*, in order.

    Walks the message list from the end, collecting the contiguous
    suffix of ``role == "assistant"`` entries. Stops early once a
    non-assistant turn is hit so that intervening user messages reset
    the consecutive counter — this is what "3 *consecutive* replies"
    means in the spec.

    Args:
        messages: Message list, oldest first.
        limit: Maximum number of trailing assistant messages to return.

    Returns:
        Up to *limit* assistant message dicts, in chronological order.
    """
    collected: list[dict[str, Any]] = []
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            break
        collected.append(msg)
        if len(collected) >= limit:
            break
    collected.reverse()
    return collected


def _is_empty_reply(msg: dict[str, Any]) -> bool:
    """True iff *msg* has no usable content (``None`` / empty / whitespace)."""
    content = msg.get("content")
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    # Non-string content (lists of parts, etc.) counts as non-empty: leave
    # the decision to richer downstream policies.
    return False


def _is_permission_denied(msg: dict[str, Any]) -> bool:
    """True iff *msg*'s content carries a permission-denied marker."""
    content = msg.get("content")
    if not isinstance(content, str):
        return False
    return any(tok in content for tok in _PERMISSION_DENIED_TOKENS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def should_escalate(state: dict[str, Any]) -> EscalationDecision:
    """Decide whether the conversation in *state* should escalate to human.

    Triggers are evaluated in priority order; the first match wins:

    1. High-urgency keyword in the latest user message
       → ``urgency="high"``.
    2. ``_CONSECUTIVE_THRESHOLD`` (3) consecutive permission-denied
       assistant replies → ``urgency="mid"``.
    3. ``_CONSECUTIVE_THRESHOLD`` (3) consecutive empty assistant replies
       → ``urgency="mid"``.
    4. Mid-urgency keyword in the latest user message → ``urgency="mid"``.

    Args:
        state: Graph state. Expected shape: ``{"messages": [{"role": ...,
            "content": ...}, ...]}``. Additional keys are ignored.

    Returns:
        :class:`EscalationDecision` with ``escalate=True`` if any rule
        fires, otherwise the default low-urgency, non-escalating instance.

    Notes:
        The function is pure — it neither mutates *state* nor performs I/O,
        which makes it safe to call from inside LangGraph nodes without
        tripping checkpointer side-effect detection.
    """
    if not isinstance(state, dict):
        return EscalationDecision()

    messages = _coerce_messages(state)
    last_user = _last_user_text(messages)

    # 1. High-urgency safety/incident keywords — top priority.
    if last_user and _HIGH_URGENCY_PATTERN.search(last_user):
        return EscalationDecision(
            escalate=True,
            reason="urgent_keyword",
            urgency="high",
        )

    # 2. Permission-denied loop — escalate the user-success path so a
    #    human can re-grant rather than letting the bot keep saying no.
    last_three = _trailing_assistant_messages(messages, _CONSECUTIVE_THRESHOLD)
    if (
        len(last_three) == _CONSECUTIVE_THRESHOLD
        and all(_is_permission_denied(m) for m in last_three)
    ):
        return EscalationDecision(
            escalate=True,
            reason="permission_denied_loop",
            urgency="mid",
        )

    # 3. Empty/null assistant replies — model went silent.
    if (
        len(last_three) == _CONSECUTIVE_THRESHOLD
        and all(_is_empty_reply(m) for m in last_three)
    ):
        return EscalationDecision(
            escalate=True,
            reason="consecutive_empty_replies",
            urgency="mid",
        )

    # 4. User-initiated handoff / complaint.
    if last_user and _MID_URGENCY_PATTERN.search(last_user):
        return EscalationDecision(
            escalate=True,
            reason="handoff_keyword",
            urgency="mid",
        )

    return EscalationDecision()


__all__ = ["EscalationDecision", "should_escalate"]
