"""Neo4j schema introspection.

The LLM prompt templates need an up-to-date description of the structured
database — node labels, relationship types and property keys — so they can
generate valid Cypher. Querying the schema on every request would be
wasteful, so this module exposes:

* :func:`fetch_schema_summary` — a single round-trip that returns a typed
  :class:`SchemaSummary` describing the live database.
* :func:`get_cached_schema` — a TTL-cached, prompt-ready string rendering
  used by the prompt templates. Falls back to a static skeleton when the
  database is unreachable so the system stays usable in dry-run mode.

Each metadata query is isolated: a failure in (e.g.) ``db.labels()`` does
not nuke the entire summary, the corresponding list just comes back empty
and a warning is logged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Final, TypedDict

from app.knowledge.neo4j_client import get_structured_driver
from app.config import get_settings

logger = logging.getLogger(__name__)


class SchemaSummary(TypedDict):
    """Typed view of a Neo4j database's metadata.

    Attributes:
        node_labels: Every ``:Label`` that appears on at least one node.
        relationship_types: Every ``[:TYPE]`` used by at least one edge.
        property_keys: Every property name registered in the schema.
    """

    node_labels: list[str]
    relationship_types: list[str]
    property_keys: list[str]


# ---------------------------------------------------------------------------
# Static fallback schema
#
# Used when the live database is unreachable (e.g. local dev without docker
# up). Keeps the prompt grounded in roughly the right vocabulary so the LLM
# does not invent random labels.
# ---------------------------------------------------------------------------
_FALLBACK_SCHEMA_TEXT: Final[str] = """\
Node Labels and Properties:
- Product: ProductID, ProductName, UnitPrice, UnitsInStock, QuantityPerUnit, Discontinued
- Category: CategoryID, CategoryName, Description
- Supplier: SupplierID, CompanyName, ContactName, Country, Phone
- Customer: CustomerID, CompanyName, ContactName, Address, Phone
- Order: OrderID, OrderDate, RequiredDate, ShippedDate, Freight, ShipAddress
- Employee: EmployeeID, LastName, FirstName, Title, HireDate
- Shipper: ShipperID, CompanyName, Phone

Relationships:
- (Product)-[:BELONGS_TO]->(Category)
- (Product)-[:SUPPLIED_BY]->(Supplier)
- (Customer)-[:PLACED_BY]->(Order)
- (Employee)-[:PROCESSED_BY]->(Order)
- (Order)-[:SHIPPED_VIA]->(Shipper)
- (Order)-[:CONTAINS]->(Product)
- (Employee)-[:REPORTS_TO]->(Employee)
"""


# ---------------------------------------------------------------------------
# Per-query Cypher
# ---------------------------------------------------------------------------
_LABELS_CYPHER: Final[str] = "CALL db.labels() YIELD label RETURN label"
_REL_TYPES_CYPHER: Final[str] = (
    "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
)
_PROPERTY_KEYS_CYPHER: Final[str] = (
    "CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey"
)


async def _collect_strings(
    session: object,
    cypher: str,
    field: str,
    label: str,
) -> list[str]:
    """Run a metadata Cypher query and return its single string column.

    Args:
        session: An open neo4j async session.
        cypher: The metadata query to run.
        field: The column name yielded by the query.
        label: Human-readable name of the metadata kind (e.g. ``"labels"``)
            used solely in the warning emitted on failure.

    Returns:
        A list of the column's values, or an empty list on any error
        (logged at ``WARNING``). The function never raises.
    """
    try:
        # ``session`` is typed as ``object`` to avoid leaking neo4j's
        # internal generic types into this helper's signature; the actual
        # runtime object is an ``AsyncSession``.
        result = await session.run(cypher)  # type: ignore[attr-defined]
        rows = await result.data()
    except Exception as exc:  # noqa: BLE001 — DB boundary
        logger.warning("Schema introspection (%s) failed: %s", label, exc)
        return []
    return [row[field] for row in rows if isinstance(row.get(field), str)]


# ---------------------------------------------------------------------------
# Primary public API
# ---------------------------------------------------------------------------
async def fetch_schema_summary() -> SchemaSummary:
    """Read live schema metadata from the structured Neo4j database.

    The three queries (labels, relationship types, property keys) are run
    inside one session but each one is wrapped in an isolated try/except —
    a failure in one does not kill the others.

    Returns:
        A :class:`SchemaSummary` dict. Any field that could not be fetched
        comes back as an empty list rather than raising, so callers can
        always rely on the keys existing.
    """
    summary: SchemaSummary = {
        "node_labels": [],
        "relationship_types": [],
        "property_keys": [],
    }

    settings = get_settings()
    driver = get_structured_driver()

    try:
        async with driver.session(
            database=settings.neo4j_structured_database
        ) as session:
            summary["node_labels"] = await _collect_strings(
                session, _LABELS_CYPHER, "label", "labels"
            )
            summary["relationship_types"] = await _collect_strings(
                session,
                _REL_TYPES_CYPHER,
                "relationshipType",
                "relationship types",
            )
            summary["property_keys"] = await _collect_strings(
                session, _PROPERTY_KEYS_CYPHER, "propertyKey", "property keys"
            )
    except Exception as exc:  # noqa: BLE001 — DB boundary
        logger.warning("Schema introspection: session unavailable: %s", exc)

    return summary


# ---------------------------------------------------------------------------
# Prompt-ready cached rendering (used by graphrag prompts)
# ---------------------------------------------------------------------------
_CACHE_TTL_SECONDS: Final[float] = 60.0

_cached_schema_text: str | None = None
_cached_at: float = 0.0
_cache_lock = asyncio.Lock()


def _render_summary(summary: SchemaSummary) -> str:
    """Render a :class:`SchemaSummary` into the form the prompts expect.

    Args:
        summary: The structured summary returned by
            :func:`fetch_schema_summary`.

    Returns:
        A multi-line string containing two sections (labels with their
        property keys, then relationship types) ready to inject into the
        Cypher-generation prompt.
    """
    label_lines = [
        f"- {label}" for label in summary["node_labels"]
    ] or ["- (none discovered)"]
    rel_lines = [
        f"- [:{rel}]" for rel in summary["relationship_types"]
    ] or ["- (none discovered)"]
    prop_line = ", ".join(summary["property_keys"]) or "(none discovered)"

    return (
        "Node Labels:\n"
        + "\n".join(label_lines)
        + "\n\nRelationships:\n"
        + "\n".join(rel_lines)
        + "\n\nKnown Property Keys:\n"
        + prop_line
        + "\n"
    )


async def get_cached_schema() -> str:
    """Return a prompt-ready schema string, refreshed at most every 60 s.

    On the first call (or after the TTL expires) the live schema is
    fetched. If the live fetch returns no labels — typically because the
    database is unreachable — the static fallback skeleton is used.

    Returns:
        A schema description suitable for direct interpolation into the
        prompt templates.
    """
    global _cached_schema_text, _cached_at

    now = time.monotonic()
    if _cached_schema_text is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
        return _cached_schema_text

    async with _cache_lock:
        # Re-check after acquiring the lock in case another coroutine
        # populated the cache while we were waiting.
        now = time.monotonic()
        if _cached_schema_text is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
            return _cached_schema_text

        summary = await fetch_schema_summary()
        if summary["node_labels"]:
            _cached_schema_text = _render_summary(summary)
        else:
            _cached_schema_text = _FALLBACK_SCHEMA_TEXT
        _cached_at = time.monotonic()
        return _cached_schema_text


def invalidate_schema_cache() -> None:
    """Drop the cached schema text so the next call refetches.

    Useful after a bulk import, or in tests that swap the database.
    """
    global _cached_schema_text, _cached_at
    _cached_schema_text = None
    _cached_at = 0.0


__all__ = [
    "SchemaSummary",
    "fetch_schema_summary",
    "get_cached_schema",
    "invalidate_schema_cache",
]
