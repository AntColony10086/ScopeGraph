"""Health-check endpoints.

Exposes two routes used by the deployment platform's load balancer and
by ops dashboards:

* ``GET /health/`` — liveness probe. Returns immediately with
  ``{"status": "ok"}`` once the FastAPI process is responsive. No
  outbound network calls.
* ``GET /health/detailed`` — readiness probe. Concurrently checks every
  external dependency (the two Neo4j databases, Redis, MySQL) using
  :func:`asyncio.gather`. The four checks always run in parallel so the
  total latency is bounded by the slowest single dependency rather than
  the sum.

Each individual check returns a plain ``bool``; failures are translated
to ``False`` rather than propagated as exceptions, so the endpoint never
500s on a transient backend outage. The aggregate ``status`` field is
``"ok"`` only when every check returned ``True``; any failure flips it
to ``"degraded"`` so ops can flag the deployment without taking it out
of rotation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.knowledge.neo4j_client import (
    health_check_structured,
    health_check_unstructured,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


# ---------------------------------------------------------------------------
# Individual probes
#
# Every probe returns a ``bool`` and never raises. Each opens a fresh client
# (rather than reusing a long-lived module singleton) so the health endpoint
# exercises the full credential / DNS / TCP path the way a real request
# would, even if the rest of the application is idle.
# ---------------------------------------------------------------------------
async def _redis_ping() -> bool:
    """Open a Redis client, send ``PING``, return ``True`` on PONG.

    A short ``socket_timeout`` keeps the readiness probe responsive even
    when Redis is unreachable: we'd rather return ``False`` quickly than
    have the load balancer wait the full default timeout.

    Returns:
        ``True`` if the Redis server replied to ``PING``; ``False`` on
        any error (logged at WARNING).
    """
    try:
        import redis.asyncio as redis_async

        settings = get_settings()
        # ``from_url`` is untyped in the stub; cast through ``Any`` so the
        # rest of this function reads cleanly under ``--strict``.
        from_url: Any = redis_async.from_url
        client: Any = from_url(
            settings.redis_url,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        try:
            await client.ping()
            return True
        finally:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
    except Exception as exc:  # noqa: BLE001 — boundary, want to swallow all
        logger.warning("Redis health check failed: %s", exc)
        return False


async def _mysql_ping() -> bool:
    """Build an async engine and run ``SELECT 1``.

    The engine is disposed at the end so we don't accumulate idle pools
    on every health hit. A successful ``SELECT 1`` proves both
    network reachability *and* that the credentials are valid.

    Returns:
        ``True`` if the query succeeded; ``False`` on any error
        (logged at WARNING).
    """
    engine = None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        engine = create_async_engine(settings.mysql_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 — boundary, want to swallow all
        logger.warning("MySQL health check failed: %s", exc)
        return False
    finally:
        if engine is not None:
            try:
                await engine.dispose()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/")
async def health_root() -> dict[str, str]:
    """Basic liveness probe.

    Returns immediately with the string ``"ok"`` — does not touch any
    external dependency. Suitable for use as a Kubernetes
    ``livenessProbe`` where you want to detect a stuck process but not
    flap the pod when Redis or Neo4j are temporarily unavailable.

    Returns:
        ``{"status": "ok"}``.
    """
    return {"status": "ok"}


@router.get("/detailed")
async def health_detailed() -> dict[str, Any]:
    """Readiness probe with per-dependency status.

    Runs the four dependency checks concurrently via
    :func:`asyncio.gather`; the response time is therefore dominated by
    the slowest single backend rather than by their sum. The aggregate
    ``status`` flips to ``"degraded"`` when any single check returned
    ``False`` (or raised) so dashboards can highlight the failing
    component without taking the entire service out of rotation.

    Returns:
        A dict shaped like::

            {
                "status": "ok" | "degraded",
                "checks": {
                    "structured_neo4j": bool,
                    "unstructured_neo4j": bool,
                    "redis": bool,
                    "mysql": bool,
                },
            }
    """
    raw_results = await asyncio.gather(
        health_check_structured(),
        health_check_unstructured(),
        _redis_ping(),
        _mysql_ping(),
        return_exceptions=True,
    )

    labels = ("structured_neo4j", "unstructured_neo4j", "redis", "mysql")
    checks: dict[str, bool] = {}
    for label, raw in zip(labels, raw_results):
        if isinstance(raw, BaseException):
            logger.warning("Health probe %s raised: %s", label, raw)
            checks[label] = False
        else:
            checks[label] = bool(raw)

    overall = "ok" if all(checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


__all__ = ["router"]
