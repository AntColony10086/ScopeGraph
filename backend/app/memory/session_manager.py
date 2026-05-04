"""Redis-backed session manager for short-term conversational memory.

This module owns the lifecycle of the singleton :class:`redis.asyncio.Redis`
client used across the API and graph layers, and exposes a small set of
coroutines for reading and writing session-scoped state.

Key layout (all keys share TTL = ``settings.redis_session_ttl``)::

    aics:session:{sid}:messages    Redis list of JSON-encoded chat turns
    aics:session:{sid}:auth        JSON string holding identity context
    aics:session:{sid}:cache       Hash of arbitrary per-field JSON blobs
    aics:session:{sid}:sentiment   List of float strings (one per turn)

Network calls are wrapped in ``await`` boundaries; this module is the *only*
place in the application that talks to Redis directly, so failures in any
caller short-circuit here rather than leaking lower-level exceptions.

The functions exposed by this module fall into two groups:

* New, primary interface used by current callers and the smoke test:
  :func:`get_session_id`, :func:`get_redis`, :func:`load_history`,
  :func:`append_message`, :func:`close_session`.
* Legacy compatibility helpers retained for the existing API and graph
  layers: :func:`generate_session_id`, :func:`init_session`,
  :func:`get_session_auth`, :func:`get_messages`, :func:`cache_data`,
  :func:`get_cached_data`, :func:`update_sentiment`.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Awaitable, cast

import redis.asyncio as redis_async

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_KEY_NAMESPACE = "aics:session"
_MESSAGES_SUFFIX = "messages"
_AUTH_SUFFIX = "auth"
_CACHE_SUFFIX = "cache"
_SENTIMENT_SUFFIX = "sentiment"

# Module-level lazy singleton; initialised on first :func:`get_redis` call.
_client: redis_async.Redis | None = None


def _messages_key(session_id: str) -> str:
    """Return the Redis list key holding the chat turns for ``session_id``."""
    return f"{_KEY_NAMESPACE}:{session_id}:{_MESSAGES_SUFFIX}"


def _auth_key(session_id: str) -> str:
    """Return the Redis string key holding the auth blob for ``session_id``."""
    return f"{_KEY_NAMESPACE}:{session_id}:{_AUTH_SUFFIX}"


def _cache_key(session_id: str) -> str:
    """Return the Redis hash key holding cached lookups for ``session_id``."""
    return f"{_KEY_NAMESPACE}:{session_id}:{_CACHE_SUFFIX}"


def _sentiment_key(session_id: str) -> str:
    """Return the Redis list key holding sentiment scores for ``session_id``."""
    return f"{_KEY_NAMESPACE}:{session_id}:{_SENTIMENT_SUFFIX}"


# ---------------------------------------------------------------------------
# Public interface — primary
# ---------------------------------------------------------------------------


def get_session_id(existing: str | None) -> str:
    """Return ``existing`` if it is a non-empty string, otherwise mint a new id.

    The minted id is the first 12 hex characters of a fresh ``uuid4`` —
    short enough to fit in URLs and log lines while still leaving 48 bits of
    entropy, which is more than sufficient for per-user session collision
    resistance.

    Args:
        existing: A previously issued session id, or ``None`` when the caller
            is starting a brand new conversation.

    Returns:
        A session identifier guaranteed to be a non-empty string.
    """
    if existing:
        return existing
    return uuid.uuid4().hex[:12]


def generate_session_id() -> str:
    """Legacy wrapper that always returns a freshly generated session id.

    Retained for backward compatibility with ``api/chat.py``; new code should
    prefer :func:`get_session_id` which accepts an optional pre-existing id.
    """
    return get_session_id(None)


async def get_redis() -> redis_async.Redis:
    """Return the lazily-initialised module-level Redis client.

    The client is created from ``settings.redis_url`` with
    ``decode_responses=True`` so values come back as ``str`` rather than
    ``bytes``. The same client instance is reused for the lifetime of the
    process; call :func:`close_session` during shutdown to release the
    underlying connection pool.

    Returns:
        A connected :class:`redis.asyncio.Redis` instance.
    """
    global _client
    if _client is None:
        settings = get_settings()
        # ``redis.asyncio.Redis.from_url`` is dynamically typed in the upstream
        # package, so the strict-mode "no-untyped-call" warning is unavoidable;
        # the explicit cast preserves the precise return type at our boundary.
        _client = cast(
            redis_async.Redis,
            redis_async.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url, decode_responses=True
            ),
        )
        logger.debug("Redis client initialised at %s", settings.redis_url)
    return _client


async def load_history(session_id: str) -> list[dict[str, Any]]:
    """Return every chat turn currently stored for ``session_id``.

    The Redis list is fetched in full via ``LRANGE 0 -1`` — message lists are
    bounded by the application's per-session TTL and trimming logic in
    :mod:`app.memory.session_lifecycle`, so reading the whole list is cheap.
    Each element is JSON-decoded; entries that fail to decode are dropped
    rather than raising, so a single corrupt write cannot poison subsequent
    reads.

    Args:
        session_id: The session whose history should be returned.

    Returns:
        Chronologically ordered list of message dicts. May be empty if the
        session has no recorded turns or has expired.
    """
    client = await get_redis()
    raw_entries = await cast(
        Awaitable[list[str]],
        client.lrange(_messages_key(session_id), 0, -1),
    )
    history: list[dict[str, Any]] = []
    for raw in raw_entries:
        try:
            decoded = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            logger.warning(
                "Dropping malformed history entry for session %s: %s",
                session_id,
                exc,
            )
            continue
        if isinstance(decoded, dict):
            history.append(decoded)
    return history


async def append_message(
    session_id: str,
    msg_or_role: dict[str, Any] | str,
    content: str | None = None,
) -> None:
    """Append a single chat turn to the session's Redis list.

    This function exposes two calling conventions for backward compatibility:

    * New (preferred)::

          await append_message(sid, {"role": "user", "content": "hi"})

    * Legacy positional form used by ``api/chat.py``::

          await append_message(sid, "human", "hi")

    Either form ends up writing a JSON-encoded dict to the list and refreshing
    the per-session TTL atomically (well — sequentially; ``rpush`` and
    ``expire`` are not pipelined here, but the Redis client is single-threaded
    per connection so no observer can see one without the other in normal
    operation).

    Args:
        session_id: The target session id.
        msg_or_role: Either the full message dict or the legacy ``role`` string.
        content: Required only when ``msg_or_role`` is the legacy role string;
            ignored otherwise.

    Raises:
        TypeError: If the legacy form is used without ``content``, or if a
            dict argument is missing the required string fields.
    """
    if isinstance(msg_or_role, dict):
        msg = msg_or_role
    else:
        if content is None:
            raise TypeError(
                "append_message: legacy (role, content) form requires content"
            )
        msg = {"role": msg_or_role, "content": content}

    if "role" not in msg or "content" not in msg:
        raise TypeError(
            "append_message: msg dict must contain 'role' and 'content' keys"
        )

    settings = get_settings()
    client = await get_redis()
    key = _messages_key(session_id)
    payload = json.dumps(msg, ensure_ascii=False)
    await cast(Awaitable[int], client.rpush(key, payload))
    await cast(Awaitable[bool], client.expire(key, settings.redis_session_ttl))


async def close_session() -> None:
    """Close the module-level Redis client and reset the singleton.

    Idempotent: calling :func:`close_session` on an already-closed module is a
    no-op. Safe to invoke from FastAPI's shutdown hook.
    """
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as exc:  # pragma: no cover - defensive at network boundary
            logger.warning("Error while closing Redis client: %s", exc)
        finally:
            _client = None


# ---------------------------------------------------------------------------
# Public interface — legacy shims (kept for existing callers)
# ---------------------------------------------------------------------------


async def init_session(
    session_id: str,
    user_id: str,
    user_info: dict[str, Any],
) -> None:
    """Persist the auth blob for a freshly-opened session.

    Args:
        session_id: The session id to bind.
        user_id: Authenticated user identifier.
        user_info: Additional fields (e.g. ``username``, ``member_level``)
            merged into the stored blob alongside ``user_id``.
    """
    settings = get_settings()
    client = await get_redis()
    payload = json.dumps({"user_id": user_id, **user_info}, ensure_ascii=False)
    await cast(
        Awaitable[bool],
        client.setex(_auth_key(session_id), settings.redis_session_ttl, payload),
    )
    logger.info("Session initialised: %s for user %s", session_id, user_id)


async def get_session_auth(session_id: str) -> dict[str, Any] | None:
    """Return the auth blob for ``session_id`` or ``None`` if not set."""
    client = await get_redis()
    raw = await cast(Awaitable[str | None], client.get(_auth_key(session_id)))
    if raw is None:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Corrupt auth blob for session %s", session_id)
        return None
    return cast("dict[str, Any] | None", decoded if isinstance(decoded, dict) else None)


async def get_messages(
    session_id: str,
    last_n: int = 12,
) -> list[dict[str, Any]]:
    """Return up to the last ``last_n`` chat turns for ``session_id``.

    Args:
        session_id: The session whose tail is being read.
        last_n: Maximum number of trailing entries to return; values <= 0 are
            treated as a request for the whole list.

    Returns:
        Decoded message dicts in chronological order.
    """
    client = await get_redis()
    start = -last_n if last_n > 0 else 0
    raw_entries = await cast(
        Awaitable[list[str]],
        client.lrange(_messages_key(session_id), start, -1),
    )
    decoded_entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            decoded_entries.append(decoded)
    return decoded_entries


async def cache_data(session_id: str, field: str, data: dict[str, Any]) -> None:
    """Cache an arbitrary JSON-serialisable dict under a named field.

    Used for memoising slow lookups (e.g. last attached file) so the chat
    pipeline can avoid repeating them on follow-up turns within the same
    session.
    """
    settings = get_settings()
    client = await get_redis()
    key = _cache_key(session_id)
    await cast(
        Awaitable[int],
        client.hset(key, field, json.dumps(data, ensure_ascii=False)),
    )
    await cast(Awaitable[bool], client.expire(key, settings.redis_session_ttl))


async def get_cached_data(
    session_id: str,
    field: str,
) -> dict[str, Any] | None:
    """Return the cached dict for ``field`` or ``None`` if absent / corrupt."""
    client = await get_redis()
    raw = await cast(Awaitable[str | None], client.hget(_cache_key(session_id), field))
    if raw is None:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return cast("dict[str, Any] | None", decoded if isinstance(decoded, dict) else None)


async def update_sentiment(session_id: str, score: float) -> None:
    """Append a per-turn sentiment score to the session's sentiment list."""
    settings = get_settings()
    client = await get_redis()
    key = _sentiment_key(session_id)
    await cast(Awaitable[int], client.rpush(key, str(score)))
    await cast(Awaitable[bool], client.expire(key, settings.redis_session_ttl))
