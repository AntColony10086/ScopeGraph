"""Async Neo4j bootstrap importer.

Walks ``data/neo4j/*.csv`` and writes the contents into the configured
*structured* Neo4j database via ``MERGE`` (idempotent — re-running the script
won't duplicate nodes or edges, but it WILL update properties to the latest
CSV values).

Truth source = the live Neo4j database. CSV files here are a one-shot seed.
For day-to-day reads/writes go through ``/api/data/observations`` or run
Cypher directly against the cluster.

Prerequisites
-------------

1. Neo4j running and reachable at the URI configured in ``.env``.
2. Dependencies installed: ``pip install neo4j python-dotenv``.

Usage
-----

::

    cd AIconverstionSys
    python scripts/import_neo4j.py
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import AsyncGraphDatabase, AsyncSession

# --------------------------------------------------------------------------- #
# Bootstrap config
# --------------------------------------------------------------------------- #
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / "backend" / ".env")

NEO4J_URI = os.getenv("NEO4J_STRUCTURED_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_STRUCTURED_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_STRUCTURED_PASSWORD", "<change-me>")
DATA_DIR = _PROJECT_ROOT / "data" / "neo4j"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# CSV helpers
# --------------------------------------------------------------------------- #
def _load_csv(filename: str) -> list[dict[str, str]]:
    """Read every row of a CSV file in :data:`DATA_DIR` as a dict."""
    path = DATA_DIR / filename
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


async def _run_batched(
    session: AsyncSession,
    cypher: str,
    rows: list[dict[str, Any]],
    csv_name: str,
    *,
    batch_size: int = 100,
) -> int:
    """Execute ``cypher`` over ``rows`` in batches, then log a one-line summary.

    Args:
        session: Open :class:`AsyncSession` from the async driver.
        cypher: Cypher template that takes ``$rows``.
        rows: Records to send (chunked by ``batch_size``).
        csv_name: Used for the summary log line.
        batch_size: Records per network round-trip.

    Returns:
        The total number of rows imported (== ``len(rows)``).
    """
    total = len(rows)
    for offset in range(0, total, batch_size):
        chunk = rows[offset : offset + batch_size]
        await session.run(cypher, rows=chunk)
    logger.info("Imported %d rows from %s", total, csv_name)
    return total


# --------------------------------------------------------------------------- #
# Cypher templates — kept as module-level constants so they're greppable.
# --------------------------------------------------------------------------- #
_CYPHER_CATEGORY = """
UNWIND $rows AS r
MERGE (n:Category {CategoryID: toInteger(r.CategoryID)})
SET n.CategoryName = r.CategoryName,
    n.Description  = r.Description
"""

_CYPHER_SUPPLIER = """
UNWIND $rows AS r
MERGE (n:Supplier {SupplierID: toInteger(r.SupplierID)})
SET n.CompanyName = r.CompanyName,
    n.ContactName = r.ContactName,
    n.Country     = r.Country,
    n.Phone       = r.Phone
"""

_CYPHER_SHIPPER = """
UNWIND $rows AS r
MERGE (n:Shipper {ShipperID: toInteger(r.ShipperID)})
SET n.CompanyName = r.CompanyName,
    n.Phone       = r.Phone
"""

_CYPHER_EMPLOYEE = """
UNWIND $rows AS r
MERGE (n:Employee {EmployeeID: toInteger(r.EmployeeID)})
SET n.LastName  = r.LastName,
    n.FirstName = r.FirstName,
    n.Title     = r.Title,
    n.HireDate  = r.HireDate,
    n.ReportsTo = CASE r.ReportsTo WHEN '' THEN null ELSE toInteger(r.ReportsTo) END
"""

_CYPHER_PRODUCT = """
UNWIND $rows AS r
MERGE (n:Product {ProductID: toInteger(r.ProductID)})
SET n.ProductName     = r.ProductName,
    n.UnitPrice       = toFloat(r.UnitPrice),
    n.UnitsInStock    = toInteger(r.UnitsInStock),
    n.QuantityPerUnit = r.QuantityPerUnit,
    n.Discontinued    = toInteger(r.Discontinued),
    n.CategoryID      = toInteger(r.CategoryID),
    n.SupplierID      = toInteger(r.SupplierID)
"""

_CYPHER_CUSTOMER = """
UNWIND $rows AS r
MERGE (n:Customer {CustomerID: r.CustomerID})
SET n.CompanyName = r.CompanyName,
    n.ContactName = r.ContactName,
    n.Address     = r.Address,
    n.Phone       = r.Phone
"""

_CYPHER_ORDER = """
UNWIND $rows AS r
MERGE (n:Order {OrderID: toInteger(r.OrderID)})
SET n.OrderDate    = r.OrderDate,
    n.RequiredDate = r.RequiredDate,
    n.ShippedDate  = r.ShippedDate,
    n.Freight      = toFloat(r.Freight),
    n.ShipAddress  = r.ShipAddress,
    n.CustomerID   = r.CustomerID,
    n.EmployeeID   = toInteger(r.EmployeeID),
    n.ShipperID    = toInteger(r.ShipVia)
"""

_CYPHER_ORDER_DETAILS = """
UNWIND $rows AS r
MATCH (o:Order   {OrderID:   toInteger(r.OrderID)})
MATCH (p:Product {ProductID: toInteger(r.ProductID)})
MERGE (o)-[rel:CONTAINS]->(p)
SET rel.UnitPrice = toFloat(r.UnitPrice),
    rel.Quantity  = toInteger(r.Quantity),
    rel.Discount  = toFloat(r.Discount)
"""

# Pure-graph relationships built from existing nodes (no per-row CSV).
_CYPHER_RELATIONSHIPS: tuple[tuple[str, str], ...] = (
    (
        "Product -[:BELONGS_TO]-> Category",
        """
        MATCH (p:Product), (c:Category)
        WHERE p.CategoryID = c.CategoryID
        MERGE (p)-[:BELONGS_TO]->(c)
        """,
    ),
    (
        "Product -[:SUPPLIED_BY]-> Supplier",
        """
        MATCH (p:Product), (s:Supplier)
        WHERE p.SupplierID = s.SupplierID
        MERGE (p)-[:SUPPLIED_BY]->(s)
        """,
    ),
    (
        "Customer -[:PLACED_BY]-> Order",
        """
        MATCH (c:Customer), (o:Order)
        WHERE o.CustomerID = c.CustomerID
        MERGE (c)-[:PLACED_BY]->(o)
        """,
    ),
    (
        "Employee -[:PROCESSED_BY]-> Order",
        """
        MATCH (e:Employee), (o:Order)
        WHERE o.EmployeeID = e.EmployeeID
        MERGE (e)-[:PROCESSED_BY]->(o)
        """,
    ),
    (
        "Order -[:SHIPPED_VIA]-> Shipper",
        """
        MATCH (o:Order), (sh:Shipper)
        WHERE o.ShipperID = sh.ShipperID
        MERGE (o)-[:SHIPPED_VIA]->(sh)
        """,
    ),
    (
        "Employee -[:REPORTS_TO]-> Employee",
        """
        MATCH (e:Employee)
        WHERE e.ReportsTo IS NOT NULL
        MATCH (mgr:Employee {EmployeeID: e.ReportsTo})
        MERGE (e)-[:REPORTS_TO]->(mgr)
        """,
    ),
)


# --------------------------------------------------------------------------- #
# Importer
# --------------------------------------------------------------------------- #
async def _import_nodes(session: AsyncSession) -> None:
    """Load every node CSV into the database."""
    logger.info("Loading nodes …")
    await _run_batched(session, _CYPHER_CATEGORY, _load_csv("categories.csv"), "categories.csv")
    await _run_batched(session, _CYPHER_SUPPLIER, _load_csv("suppliers.csv"), "suppliers.csv")
    await _run_batched(session, _CYPHER_SHIPPER, _load_csv("shippers.csv"), "shippers.csv")
    await _run_batched(session, _CYPHER_EMPLOYEE, _load_csv("employees.csv"), "employees.csv")
    await _run_batched(session, _CYPHER_PRODUCT, _load_csv("products.csv"), "products.csv")
    await _run_batched(session, _CYPHER_CUSTOMER, _load_csv("customers.csv"), "customers.csv")
    await _run_batched(session, _CYPHER_ORDER, _load_csv("orders.csv"), "orders.csv")


async def _import_relationships(session: AsyncSession) -> None:
    """Build all derived relationships, then load the order_details edge table."""
    logger.info("Building relationships …")
    for label, cypher in _CYPHER_RELATIONSHIPS:
        await session.run(cypher)
        logger.info("Built relationship: %s", label)

    await _run_batched(
        session,
        _CYPHER_ORDER_DETAILS,
        _load_csv("order_details.csv"),
        "order_details.csv",
    )


async def _verify_counts(session: AsyncSession) -> None:
    """Log the row count of every node label — sanity check after import."""
    labels = ("Category", "Supplier", "Shipper", "Employee", "Product", "Customer", "Order")
    logger.info("Verifying node counts …")
    for label in labels:
        result = await session.run(f"MATCH (n:{label}) RETURN count(n) AS c")
        record = await result.single()
        count = record["c"] if record else 0
        logger.info("  %-9s = %d", label, count)


async def import_all() -> None:
    """End-to-end import: connect, wipe, load nodes, build edges, verify."""
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        async with driver.session() as session:
            logger.info("Wiping prior dataset …")
            await session.run("MATCH (n) DETACH DELETE n")

            await _import_nodes(session)
            await _import_relationships(session)
            await _verify_counts(session)
    finally:
        await driver.close()

    logger.info("Import complete.")


def main() -> int:
    """CLI entry-point — returns a process exit code."""
    try:
        asyncio.run(import_all())
        return 0
    except Exception:  # noqa: BLE001
        logger.exception(
            "Import failed — confirm Neo4j is running and the password in .env is correct."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
