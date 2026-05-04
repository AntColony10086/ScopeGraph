"""SQLAlchemy 2.0 ORM — typed-dataclass style.

The ORM models below use the SQLAlchemy 2.0 ``MappedAsDataclass`` pattern:
each model is *also* a Python dataclass, so the type checker can verify call
sites at construction time without us having to maintain hand-rolled
``__init__`` signatures.

Engine / session helpers
------------------------

* :func:`get_async_engine` — single shared :class:`AsyncEngine`, lazily built.
* :func:`get_async_session_factory` — a factory that yields ``AsyncSession``.
* :func:`init_db` — runs ``CREATE TABLE IF NOT EXISTS`` for everything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

from app.config import get_settings


class Base(MappedAsDataclass, AsyncAttrs, DeclarativeBase):
    """Common base for every ORM class — declarative + async attrs + dataclass."""


# Member-level enum kept as a tuple so it can be reused at the column level
# without re-declaring the labels inline.
_MEMBER_LEVELS: Final[tuple[str, ...]] = ("normal", "silver", "gold", "platinum")
_USER_ROLES: Final[tuple[str, ...]] = ("user", "admin")


class UserProfile(Base):
    """A registered user — login credentials, profile, and behavioral tags."""

    __tablename__ = "user_profiles"

    # ------ Primary key -------------------------------------------------- #
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # ------ Optional identity fields ------------------------------------- #
    phone: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), default=None)

    # ------ Membership & access control ---------------------------------- #
    member_level: Mapped[str] = mapped_column(
        Enum(*_MEMBER_LEVELS, name="member_level_enum"),
        default="normal",
    )
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)

    # Role-based access — admins see everything; regular users see only the
    # CustomerIDs in `accessible_enterprises` (a JSON list, e.g. ["C001","C002"]).
    role: Mapped[str] = mapped_column(
        Enum(*_USER_ROLES, name="user_role_enum"),
        default="user",
    )
    accessible_enterprises: Mapped[Optional[list[Any]]] = mapped_column(JSON, default=None)

    # ------ Profile customization ---------------------------------------- #
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    bio: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # ------ Behavioral tags ---------------------------------------------- #
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    total_spend: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    favorite_categories: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=None)
    is_high_value: Mapped[bool] = mapped_column(Boolean, default=False)
    prefer_human_service: Mapped[bool] = mapped_column(Boolean, default=False)
    complaint_count: Mapped[int] = mapped_column(Integer, default=0)

    # ------ Customer-service interaction stats --------------------------- #
    last_chat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    avg_satisfaction: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), default=None)
    total_chats: Mapped[int] = mapped_column(Integer, default=0)
    open_tickets: Mapped[int] = mapped_column(Integer, default=0)

    # ------ Conversation summary cache ----------------------------------- #
    last_conversation_summary: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # ------ Bookkeeping (managed by the database) ------------------------ #
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        init=False,
    )

    __table_args__ = (Index("idx_username", "username"),)


class ChatSession(Base):
    """One conversation between a user and the assistant."""

    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        init=False,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    satisfaction_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), default=None)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, default=None)


# --------------------------------------------------------------------------- #
# Engine + session helpers
# --------------------------------------------------------------------------- #
_engine: AsyncEngine | None = None


def get_async_engine() -> AsyncEngine:
    """Return (and lazily build) the process-wide :class:`AsyncEngine`.

    Building the engine on every call would leak connections — once made, we
    cache it for the lifetime of the process.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.mysql_url, echo=settings.debug, pool_size=10)
    return _engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return an :class:`async_sessionmaker` bound to the shared engine."""
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def init_db() -> None:
    """Create every table declared on :class:`Base` if it doesn't already exist."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
