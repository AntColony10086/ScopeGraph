"""Long-term user-profile access layer.

This module mediates between the chat pipeline and the MySQL
``user_profiles`` table. It exposes:

* :class:`UserProfileDTO` — a Pydantic v2 data-transfer object that mirrors
  the relevant subset of :class:`app.models.database.UserProfile` columns
  and is safe to serialise into prompts or API responses.
* :func:`load_profile` — a coroutine that loads a single profile row by
  ``user_id`` and returns it as a DTO, or ``None`` when the user is unknown.
* :func:`update_last_seen` — refreshes the ``last_chat_at`` timestamp; a
  no-op when the user does not exist.

Two legacy helpers, :func:`get_user_profile` and
:func:`format_profile_for_prompt`, are retained at the bottom of the module
because the API layer (:mod:`app.api.chat`) and the graph layer
(:mod:`app.graph.nodes.general_chat`) still call them directly. New code
should prefer :class:`UserProfileDTO`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.database import UserProfile as ORMUserProfile
from app.models.database import get_async_session_factory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


class UserProfileDTO(BaseModel):
    """Serialisable view of a row in the ``user_profiles`` table.

    Only fields that are needed downstream (prompt injection, the profile
    REST endpoint, and the lifecycle analytics module) are exposed. The
    model uses ``model_config = ConfigDict(from_attributes=True)`` so it can
    be hydrated directly from a SQLAlchemy ORM instance via
    :meth:`UserProfileDTO.model_validate`.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(description="Primary key in user_profiles")
    username: str = Field(description="Login handle; unique per user")
    nickname: str | None = Field(
        default=None, description="Display name; falls back to username when null"
    )
    role: str = Field(
        default="user",
        description="Authorisation role; either 'user' or 'admin'",
    )
    accessible_enterprises: list[Any] | None = Field(
        default=None,
        description=(
            "JSON list of CustomerID strings the user may inspect; null or "
            "empty implies admin-style scope when role == 'admin'"
        ),
    )
    member_level: str = Field(
        default="normal",
        description="One of normal | silver | gold | platinum",
    )
    is_high_value: bool = Field(
        default=False,
        description="Behavioural flag set by analytics pipelines",
    )
    favorite_categories: dict[str, Any] | list[Any] | None = Field(
        default=None,
        description=(
            "Categorisation tags inferred from past conversations. Stored as "
            "JSON in MySQL — typically a list of strings, occasionally a dict."
        ),
    )


# ---------------------------------------------------------------------------
# Public interface — primary
# ---------------------------------------------------------------------------


async def load_profile(user_id: str) -> UserProfileDTO | None:
    """Load a single user profile by primary key.

    Args:
        user_id: The user identifier to look up.

    Returns:
        A :class:`UserProfileDTO` if the row exists, otherwise ``None``.
        Database errors are not swallowed here — callers are expected to
        treat the user-profile load as best-effort and wrap it in their own
        exception handler when a missing profile is acceptable.
    """
    factory = get_async_session_factory()  # type: ignore[no-untyped-call]
    async with factory() as session:
        row = await session.get(ORMUserProfile, user_id)
        if row is None:
            return None
        return UserProfileDTO.model_validate(row, from_attributes=True)


async def update_last_seen(user_id: str) -> None:
    """Update the ``last_chat_at`` timestamp for the given user.

    Silent no-op when the user is not found, so callers can fire this
    unconditionally at the start of a turn without an existence check.
    """
    factory = get_async_session_factory()  # type: ignore[no-untyped-call]
    async with factory() as session:
        row = await session.get(ORMUserProfile, user_id)
        if row is None:
            logger.debug("update_last_seen: user_id=%s not found; skipping", user_id)
            return
        row.last_chat_at = datetime.utcnow()
        await session.commit()


# ---------------------------------------------------------------------------
# Legacy helpers — retained for the existing callers
# ---------------------------------------------------------------------------


async def get_user_profile(user_id: str) -> dict[str, Any] | None:
    """Load a user profile and return it as a dict for prompt injection.

    Used by ``api/chat.py`` to populate the graph's ``user_profile`` slot.
    Wrapping the DTO is intentional — the graph state, the REST schemas and
    the prompt-formatting helper all consume plain dicts today, and we want
    a stable contract while we migrate the codebase to :class:`UserProfileDTO`.
    """
    factory = get_async_session_factory()  # type: ignore[no-untyped-call]
    async with factory() as session:
        row = await session.get(ORMUserProfile, user_id)
        if row is None:
            return None

        total_spend = row.total_spend
        if isinstance(total_spend, Decimal):
            total_spend_float = float(total_spend)
        elif total_spend is None:
            total_spend_float = 0.0
        else:
            total_spend_float = float(total_spend)

        avg_satisfaction: float | None
        if row.avg_satisfaction is None:
            avg_satisfaction = None
        else:
            avg_satisfaction = float(row.avg_satisfaction)

        return {
            "user_id": row.user_id,
            "nickname": row.nickname or row.username,
            "member_level": row.member_level,
            "total_orders": row.total_orders,
            "total_spend": total_spend_float,
            "favorite_categories": row.favorite_categories or [],
            "is_high_value": row.is_high_value,
            "prefer_human_service": row.prefer_human_service,
            "complaint_count": row.complaint_count,
            "avg_satisfaction": avg_satisfaction,
            "last_conversation_summary": row.last_conversation_summary,
        }


def format_profile_for_prompt(profile: dict[str, Any] | None) -> str:
    """Render a profile dict into a compact prompt fragment.

    The result is concatenated into the system prompt for the general-chat
    node so the assistant can address the user appropriately. Returns a
    polite fallback when ``profile`` is missing.
    """
    if not profile:
        return "用户信息：新用户，无历史数据"

    parts: list[str] = []

    last_summary = profile.get("last_conversation_summary")
    if last_summary:
        parts.append(f"上次咨询：{str(last_summary)[:80]}")

    if profile.get("prefer_human_service"):
        parts.append("特别注意：该用户偏好人工服务")

    if not parts:
        return "用户信息：已登录用户，无额外画像"
    return "## 当前用户信息\n- " + "\n- ".join(parts)
