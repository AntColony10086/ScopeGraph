"""Async Neo4j connection management.

This module owns the lifecycle of the two Neo4j async drivers used by the
service:

* ``structured`` — the relational/business graph (products, orders, ...).
* ``unstructured`` — the GraphRAG document graph.

Each driver is a heavy-weight, thread-safe object that should be created
exactly once per process and reused for the lifetime of the application,
hence the lazy module-level singletons. All public coroutines guard the
network boundary defensively: a downstream Neo4j outage degrades the
caller (returning ``False`` / an empty list) rather than crashing the
event loop.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Literal

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level driver singletons.
#
# The drivers are created on first call to ``get_*_driver`` and cached for
# the rest of the process. ``close_connections`` resets them back to ``None``
# so subsequent ``get_*`` calls will rebuild fresh drivers (useful in tests
# and in the FastAPI shutdown path).
# ---------------------------------------------------------------------------
_structured: AsyncDriver | None = None
_unstructured: AsyncDriver | None = None

DatabaseRole = Literal["structured", "unstructured"]
"""Logical database role used by ``execute_cypher`` to pick a driver."""

_DEFAULT_DATABASE: Final[DatabaseRole] = "structured"


# ---------------------------------------------------------------------------
# Driver construction
# ---------------------------------------------------------------------------
def _build_driver(uri: str, user: str, password: str) -> AsyncDriver:
    """Construct a single ``AsyncDriver`` instance.

    The neo4j driver does **not** open a network connection at construction
    time — the first request, or an explicit ``verify_connectivity`` call,
    triggers the handshake. Construction can therefore safely run inside
    ``get_*_driver`` without blocking the event loop.

    Args:
        uri: Bolt URI for the Neo4j server, e.g. ``bolt://localhost:7687``.
        user: Username for basic auth.
        password: Password for basic auth.

    Returns:
        A ready-to-use ``AsyncDriver``.
    """
    return AsyncGraphDatabase.driver(uri, auth=(user, password))


def get_structured_driver() -> AsyncDriver:
    """Return the singleton driver for the structured business graph.

    The driver is created on first call using credentials from
    :func:`app.config.get_settings`. Subsequent calls return the cached
    instance.

    Returns:
        The shared ``AsyncDriver`` for the structured database.
    """
    global _structured
    if _structured is None:
        settings: Settings = get_settings()
        _structured = _build_driver(
            settings.neo4j_structured_uri,
            settings.neo4j_structured_user,
            settings.neo4j_structured_password,
        )
        logger.debug(
            "Created structured Neo4j driver for %s",
            settings.neo4j_structured_uri,
        )
    return _structured


def get_unstructured_driver() -> AsyncDriver:
    """Return the singleton driver for the unstructured GraphRAG database.

    Returns:
        The shared ``AsyncDriver`` for the unstructured database.
    """
    global _unstructured
    if _unstructured is None:
        settings: Settings = get_settings()
        _unstructured = _build_driver(
            settings.neo4j_unstructured_uri,
            settings.neo4j_unstructured_user,
            settings.neo4j_unstructured_password,
        )
        logger.debug(
            "Created unstructured Neo4j driver for %s",
            settings.neo4j_unstructured_uri,
        )
    return _unstructured


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------
async def _verify(driver: AsyncDriver, label: str) -> bool:
    """Run ``verify_connectivity`` and translate any error into ``False``.

    Args:
        driver: The async driver to probe.
        label: Human-readable name of the database, used only for logging.

    Returns:
        ``True`` if the driver could open a connection, ``False`` otherwise.
    """
    try:
        await driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 — boundary, want to swallow all
        logger.warning("Neo4j %s health check failed: %s", label, exc)
        return False
    return True


async def health_check_structured() -> bool:
    """Probe the structured database.

    Returns:
        ``True`` if the structured database is reachable, ``False`` if any
        error occurred (the error is logged at ``WARNING`` level).
    """
    return await _verify(get_structured_driver(), "structured")


async def health_check_unstructured() -> bool:
    """Probe the unstructured GraphRAG database.

    Returns:
        ``True`` if the unstructured database is reachable, ``False`` if any
        error occurred (the error is logged at ``WARNING`` level).
    """
    return await _verify(get_unstructured_driver(), "unstructured")


# ---------------------------------------------------------------------------
# Cypher execution helper (kept for in-repo callers)
# ---------------------------------------------------------------------------
async def execute_cypher(
    cypher: str,
    params: dict[str, Any] | None = None,
    database: DatabaseRole = _DEFAULT_DATABASE,
) -> list[dict[str, Any]]:
    """Run a single read/write Cypher statement and return the result rows.

    This is a thin convenience wrapper around the async driver's
    ``session.run`` so callers don't have to manage sessions manually for
    the common one-shot query case. Each row is materialised into a plain
    dict via ``Record.data()``.

    Args:
        cypher: The Cypher statement to execute.
        params: Optional parameter mapping. ``None`` is treated as ``{}``.
        database: Logical database role — ``"structured"`` or
            ``"unstructured"``. Defaults to ``"structured"``.

    Returns:
        A list of row dicts. On any driver-level error the function logs
        the failure and returns an empty list, so callers can treat the
        Neo4j boundary as "best-effort" without wrapping every call in
        ``try/except``.
    """
    settings: Settings = get_settings()
    if database == "unstructured":
        driver = get_unstructured_driver()
        db_name = settings.neo4j_unstructured_database
    else:
        driver = get_structured_driver()
        db_name = settings.neo4j_structured_database

    try:
        async with driver.session(database=db_name) as session:
            result = await session.run(cypher, params or {})
            records = await result.data()
            return list(records)
    except Exception as exc:  # noqa: BLE001 — boundary, want to swallow all
        logger.error("execute_cypher failed (%s): %s", database, exc)
        return []


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------
async def close_connections() -> None:
    """Close both drivers if they exist and reset the singletons.

    Idempotent: calling this on a process that never opened a driver, or
    calling it twice in a row, is a no-op.
    """
    global _structured, _unstructured

    if _structured is not None:
        try:
            await _structured.close()
        except Exception as exc:  # noqa: BLE001 — best-effort shutdown
            logger.warning("Error closing structured Neo4j driver: %s", exc)
        finally:
            _structured = None

    if _unstructured is not None:
        try:
            await _unstructured.close()
        except Exception as exc:  # noqa: BLE001 — best-effort shutdown
            logger.warning("Error closing unstructured Neo4j driver: %s", exc)
        finally:
            _unstructured = None


__all__ = [
    "DatabaseRole",
    "close_connections",
    "execute_cypher",
    "get_structured_driver",
    "get_unstructured_driver",
    "health_check_structured",
    "health_check_unstructured",
]
