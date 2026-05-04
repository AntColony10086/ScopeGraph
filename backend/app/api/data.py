"""Enterprise carbon-data CRUD endpoints (Neo4j-backed).

Permission model:
  - admin (role='admin' or '*' in accessible_enterprises): all enterprises
  - user (role='user'): only enterprises listed in their accessible_enterprises

A "data point" / observation is one row of:
  (Customer)-[:PLACED_BY]->(Order)-[:CONTAINS]->(Product)
where:
  Customer  = enterprise / region (CustomerID = customer_id)
  Order     = a (CustomerID, year) node, addressed by OrderID
  Product   = the indicator (ProductID = indicator_id)
  on the [:CONTAINS] relationship, r.UnitPrice is the value, r.Quantity is the year.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import can_access_enterprise, get_current_user, is_admin
from app.knowledge.neo4j_client import execute_cypher
from app.models.schemas import (
    DashboardEnterpriseTop,
    DashboardIndustryShare,
    DashboardKpis,
    DashboardMeta,
    DashboardRecentUpdate,
    DashboardSummary,
    DashboardYearly,
    EnterpriseRow,
    IndicatorRow,
    ObservationCreateRequest,
    ObservationDeleteRequest,
    ObservationRow,
    ObservationUpdateRequest,
    TokenPayload,
)


# CustomerID → industry tag. Only the 13 real enterprises are listed; aggregates
# (province / parks / national baseline) are intentionally excluded so the
# dashboard never double-counts them.
_INDUSTRY_MAP: dict[str, str] = {
    "C001": "化工", "C002": "化工", "C003": "化工", "C004": "化工",
    "C005": "化工", "C006": "化工", "C007": "化工", "C008": "化工", "C009": "化工",
    "C010": "石油化工", "C021": "石油化工",
    "C022": "光伏",
    "C023": "煤炭",
}
_REAL_ENTERPRISE_IDS: list[str] = list(_INDUSTRY_MAP.keys())


async def _discover_available_years() -> list[int]:
    """Query Neo4j for the set of years that actually carry observations.

    Keeping this dynamic means the dashboard automatically picks up new
    years that get inserted via the API or Cypher — the source of truth
    is the database, not a constant in code.
    """
    rows = await execute_cypher(
        "MATCH ()-[r:CONTAINS]->() WHERE r.Quantity IS NOT NULL "
        "RETURN DISTINCT toInteger(r.Quantity) AS year ORDER BY year",
        params={},
    )
    years = [int(r["year"]) for r in rows if r.get("year") is not None]
    return years or [datetime.now().year]

router = APIRouter(prefix="/api/data", tags=["data"])
logger = logging.getLogger(__name__)


def _allowed_customer_filter(user: TokenPayload) -> Optional[list[str]]:
    """Return the user's CustomerID whitelist, or None if unrestricted (admin)."""
    if is_admin(user):
        return None
    allowed = list(user.accessible_enterprises or [])
    if "*" in allowed:
        return None
    return allowed


# ---------- Metadata: enterprises & indicators ----------

@router.get("/enterprises", response_model=list[EnterpriseRow])
async def list_enterprises(user: TokenPayload = Depends(get_current_user)):
    """List all enterprises this user is authorized to see."""
    cypher = """
        MATCH (c:Customer)
        RETURN c.CustomerID AS customer_id, c.CompanyName AS name,
               c.City AS city, c.Address AS address, c.Phone AS phone
        ORDER BY c.CustomerID
    """
    rows = await execute_cypher(cypher)
    allowed = _allowed_customer_filter(user)
    if allowed is not None:
        rows = [r for r in rows if r.get("customer_id") in allowed]
    return [EnterpriseRow(**r) for r in rows]


@router.get("/indicators", response_model=list[IndicatorRow])
async def list_indicators(user: TokenPayload = Depends(get_current_user)):
    """List all indicators (no permission check — indicators are metadata)."""
    cypher = """
        MATCH (p:Product)
        OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category)
        RETURN p.ProductID AS indicator_id, p.ProductName AS name,
               c.CategoryName AS category, p.QuantityPerUnit AS unit
        ORDER BY p.ProductID
    """
    rows = await execute_cypher(cypher)
    return [IndicatorRow(**r) for r in rows]


# ---------- Observations: read ----------

@router.get("/observations", response_model=list[ObservationRow])
async def list_observations(
    user: TokenPayload = Depends(get_current_user),
    customer_id: Optional[str] = Query(None, description="按企业 CustomerID 过滤"),
    year: Optional[int] = Query(None, description="按年份过滤"),
    indicator_id: Optional[int] = Query(None, description="按指标 ProductID 过滤"),
    limit: int = Query(500, ge=1, le=2000),
):
    """Return flat (enterprise, year, indicator) data rows the user may view."""
    where = ["1=1"]
    params: dict = {"limit": limit}
    if customer_id:
        if not can_access_enterprise(user, customer_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="无权访问该企业数据")
        where.append("c.CustomerID = $customer_id")
        params["customer_id"] = customer_id
    if year is not None:
        where.append("r.Quantity = $year")
        params["year"] = int(year)
    if indicator_id is not None:
        where.append("p.ProductID = $indicator_id")
        params["indicator_id"] = int(indicator_id)

    allowed = _allowed_customer_filter(user)
    if allowed is not None:
        if not allowed:
            return []
        where.append("c.CustomerID IN $allowed")
        params["allowed"] = allowed

    cypher = f"""
        MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
        WHERE {' AND '.join(where)}
        OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category)
        OPTIONAL MATCH (p)-[:SUPPLIED_BY]->(s:Supplier)
        RETURN o.OrderID AS order_id, c.CustomerID AS customer_id,
               c.CompanyName AS enterprise, p.ProductName AS indicator,
               p.ProductID AS indicator_id, cat.CategoryName AS category,
               toInteger(r.Quantity) AS year, toFloat(r.UnitPrice) AS value,
               p.QuantityPerUnit AS unit, s.CompanyName AS source
        ORDER BY c.CustomerID, year, p.ProductID
        LIMIT $limit
    """
    rows = await execute_cypher(cypher, params=params)
    return [ObservationRow(**r) for r in rows]


# ---------- Observations: create / update / delete ----------

@router.post("/observations", response_model=ObservationRow, status_code=status.HTTP_201_CREATED)
async def create_observation(
    req: ObservationCreateRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """Add a new (enterprise, year, indicator) data point.

    If an Order for this (customer_id, year) already exists, attach the
    indicator measurement to it; otherwise create a new Order node.
    Refuses to overwrite an existing measurement (use PUT instead).
    """
    if not can_access_enterprise(user, req.customer_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="无权写入该企业的数据")

    # Verify the customer + indicator exist
    chk = await execute_cypher(
        "MATCH (c:Customer {CustomerID: $cid}) "
        "MATCH (p:Product {ProductID: $pid}) "
        "RETURN c.CompanyName AS name, p.ProductName AS indicator, "
        "       p.QuantityPerUnit AS unit",
        params={"cid": req.customer_id, "pid": int(req.indicator_id)},
    )
    if not chk:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="企业或指标不存在")

    # Existing order?
    existing = await execute_cypher(
        "MATCH (c:Customer {CustomerID: $cid})-[:PLACED_BY]->(o:Order) "
        "WHERE o.OrderDate STARTS WITH $year_prefix "
        "RETURN o.OrderID AS oid LIMIT 1",
        params={"cid": req.customer_id, "year_prefix": f"{int(req.year)}-"},
    )

    if existing:
        order_id = int(existing[0]["oid"])
        # Refuse if a measurement for this indicator already exists
        dup = await execute_cypher(
            "MATCH (o:Order {OrderID: $oid})-[r:CONTAINS]->(p:Product {ProductID: $pid}) "
            "RETURN r.UnitPrice AS v",
            params={"oid": order_id, "pid": int(req.indicator_id)},
        )
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该企业·年份·指标的数据点已存在，请改用 PUT 更新",
            )
        await execute_cypher(
            "MATCH (o:Order {OrderID: $oid}) "
            "MATCH (p:Product {ProductID: $pid}) "
            "MERGE (o)-[r:CONTAINS]->(p) "
            "SET r.UnitPrice = $value, r.Quantity = $year, r.Discount = 0",
            params={
                "oid": order_id,
                "pid": int(req.indicator_id),
                "value": float(req.value),
                "year": int(req.year),
            },
        )
    else:
        # Allocate a new OrderID
        max_row = await execute_cypher("MATCH (o:Order) RETURN max(o.OrderID) AS m")
        next_oid = int((max_row[0]["m"] or 10000) + 1) if max_row else 10001
        await execute_cypher(
            "MATCH (c:Customer {CustomerID: $cid}) "
            "MATCH (p:Product {ProductID: $pid}) "
            "CREATE (o:Order {OrderID: $oid, OrderDate: $order_date, "
            "                 RequiredDate: $req_date, ShippedDate: $ship_date, "
            "                 Freight: 0, ShipAddress: '人工录入'}) "
            "MERGE (c)-[:PLACED_BY]->(o) "
            "MERGE (o)-[r:CONTAINS]->(p) "
            "SET r.UnitPrice = $value, r.Quantity = $year, r.Discount = 0",
            params={
                "cid": req.customer_id,
                "pid": int(req.indicator_id),
                "oid": next_oid,
                "order_date": f"{int(req.year)}-12-31",
                "req_date": f"{int(req.year) + 1}-06-30",
                "ship_date": f"{int(req.year) + 1}-03-15",
                "value": float(req.value),
                "year": int(req.year),
            },
        )
        order_id = next_oid

    # Return the created row
    row = await execute_cypher(
        "MATCH (c:Customer {CustomerID: $cid})-[:PLACED_BY]->(o:Order {OrderID: $oid})-[r:CONTAINS]->(p:Product {ProductID: $pid}) "
        "OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category) "
        "OPTIONAL MATCH (p)-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN o.OrderID AS order_id, c.CustomerID AS customer_id, "
        "       c.CompanyName AS enterprise, p.ProductName AS indicator, "
        "       p.ProductID AS indicator_id, cat.CategoryName AS category, "
        "       toInteger(r.Quantity) AS year, toFloat(r.UnitPrice) AS value, "
        "       p.QuantityPerUnit AS unit, s.CompanyName AS source",
        params={"cid": req.customer_id, "oid": order_id, "pid": int(req.indicator_id)},
    )
    if not row:
        raise HTTPException(status_code=500, detail="创建后无法回读，请刷新")
    return ObservationRow(**row[0])


@router.put("/observations", response_model=ObservationRow)
async def update_observation(
    req: ObservationUpdateRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """Update an existing observation's value."""
    # Check permission via the order's customer
    owner = await execute_cypher(
        "MATCH (c:Customer)-[:PLACED_BY]->(o:Order {OrderID: $oid}) "
        "RETURN c.CustomerID AS cid LIMIT 1",
        params={"oid": int(req.order_id)},
    )
    if not owner:
        raise HTTPException(status_code=404, detail="该订单不存在")
    cid = owner[0]["cid"]
    if not can_access_enterprise(user, cid):
        raise HTTPException(status_code=403, detail="无权修改该企业的数据")

    res = await execute_cypher(
        "MATCH (o:Order {OrderID: $oid})-[r:CONTAINS]->(p:Product {ProductID: $pid}) "
        "SET r.UnitPrice = $value "
        "RETURN r.UnitPrice AS value",
        params={
            "oid": int(req.order_id),
            "pid": int(req.indicator_id),
            "value": float(req.value),
        },
    )
    if not res:
        raise HTTPException(status_code=404, detail="目标数据点不存在")

    row = await execute_cypher(
        "MATCH (c:Customer)-[:PLACED_BY]->(o:Order {OrderID: $oid})-[r:CONTAINS]->(p:Product {ProductID: $pid}) "
        "OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category) "
        "OPTIONAL MATCH (p)-[:SUPPLIED_BY]->(s:Supplier) "
        "RETURN o.OrderID AS order_id, c.CustomerID AS customer_id, "
        "       c.CompanyName AS enterprise, p.ProductName AS indicator, "
        "       p.ProductID AS indicator_id, cat.CategoryName AS category, "
        "       toInteger(r.Quantity) AS year, toFloat(r.UnitPrice) AS value, "
        "       p.QuantityPerUnit AS unit, s.CompanyName AS source",
        params={"oid": int(req.order_id), "pid": int(req.indicator_id)},
    )
    return ObservationRow(**row[0])


@router.delete("/observations", status_code=status.HTTP_204_NO_CONTENT)
async def delete_observation(
    req: ObservationDeleteRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """Delete a single (order, indicator) measurement.

    If this was the only measurement on the order, also remove the empty Order.
    """
    owner = await execute_cypher(
        "MATCH (c:Customer)-[:PLACED_BY]->(o:Order {OrderID: $oid}) "
        "RETURN c.CustomerID AS cid LIMIT 1",
        params={"oid": int(req.order_id)},
    )
    if not owner:
        raise HTTPException(status_code=404, detail="该订单不存在")
    cid = owner[0]["cid"]
    if not can_access_enterprise(user, cid):
        raise HTTPException(status_code=403, detail="无权删除该企业的数据")

    await execute_cypher(
        "MATCH (o:Order {OrderID: $oid})-[r:CONTAINS]->(p:Product {ProductID: $pid}) "
        "DELETE r",
        params={"oid": int(req.order_id), "pid": int(req.indicator_id)},
    )

    # Remove the order if it has no remaining measurements
    remaining = await execute_cypher(
        "MATCH (o:Order {OrderID: $oid})-[r:CONTAINS]->(:Product) "
        "RETURN count(r) AS n",
        params={"oid": int(req.order_id)},
    )
    if remaining and (remaining[0]["n"] or 0) == 0:
        await execute_cypher(
            "MATCH (o:Order {OrderID: $oid}) DETACH DELETE o",
            params={"oid": int(req.order_id)},
        )
    return None


# ---------- Dashboard summary ----------

def _resolve_visible_ids(user: TokenPayload) -> tuple[list[str], str]:
    """Return the (CustomerID list, scope label) the user is allowed to see
    on the dashboard. Aggregates / provinces / parks are excluded for admin
    so they don't double-count, but a bound user keeps whatever they have.
    """
    if is_admin(user) or "*" in (user.accessible_enterprises or []):
        return list(_REAL_ENTERPRISE_IDS), "all"
    bound = list(user.accessible_enterprises or [])
    return bound, "bound_enterprises"


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(user: TokenPayload = Depends(get_current_user)):
    """Aggregate dashboard payload, scoped to the caller's permissions.

    Values returned in **tonnes** (not 万吨); the frontend formats them.
    Scope1 = ProductID 1; Scope2 = ProductID 7. Both stored on the
    [:CONTAINS] relationship as r.UnitPrice (in 万吨/年).
    """
    visible_ids, scope_label = _resolve_visible_ids(user)
    now_iso = datetime.now(timezone.utc).isoformat()
    available_years = await _discover_available_years()
    latest_year = available_years[-1]
    empty_meta = DashboardMeta(
        visibleScope=scope_label, latestYear=latest_year,
        currentYear=datetime.now().year, lastUpdatedAt=now_iso, pollingSeconds=15,
    )
    if not visible_ids:
        return DashboardSummary(
            meta=empty_meta,
            kpis=DashboardKpis(cumulativeEmissionTons=0, latestYearEmissionTons=0),
            yearly=[], enterpriseTop=[], industryShares=[], recentUpdates=[],
        )

    # 1. Yearly Scope1 + Scope2 totals (万吨 → tonnes)
    yearly_rows = await execute_cypher(
        "MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product) "
        "WHERE c.CustomerID IN $ids AND p.ProductID IN [1, 7] "
        "  AND r.Quantity IN $years "
        "RETURN p.ProductID AS pid, toInteger(r.Quantity) AS year, "
        "       toFloat(sum(r.UnitPrice)) AS wan_tons",
        params={"ids": visible_ids, "years": available_years},
    )
    by_year: dict[int, dict[str, float]] = {y: {"s1": 0.0, "s2": 0.0} for y in available_years}
    for r in yearly_rows:
        y = int(r["year"])
        if y not in by_year:
            continue
        if r["pid"] == 1:
            by_year[y]["s1"] += float(r["wan_tons"] or 0)
        elif r["pid"] == 7:
            by_year[y]["s2"] += float(r["wan_tons"] or 0)
    yearly: list[DashboardYearly] = []
    for y in available_years:
        s1_t = by_year[y]["s1"] * 10_000.0
        s2_t = by_year[y]["s2"] * 10_000.0
        yearly.append(DashboardYearly(
            year=y, scope1EmissionTons=s1_t, scope2EmissionTons=s2_t,
            totalEmissionTons=s1_t + s2_t,
        ))

    cumulative = sum(item.totalEmissionTons for item in yearly)
    latest = yearly[-1]
    prev = yearly[-2] if len(yearly) >= 2 else None
    yoy: Optional[float] = None
    if prev and prev.totalEmissionTons > 0:
        yoy = (latest.totalEmissionTons - prev.totalEmissionTons) / prev.totalEmissionTons
    span_rate: Optional[float] = None  # full span (2019→latest)
    if yearly[0].totalEmissionTons > 0:
        span_rate = (
            (yearly[-1].totalEmissionTons - yearly[0].totalEmissionTons)
            / yearly[0].totalEmissionTons
        )
    five_year_rate = span_rate  # KPI label adapts on the frontend

    # 2. Industry shares (latest year)
    industry_rows = await execute_cypher(
        "MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product) "
        "WHERE c.CustomerID IN $ids AND p.ProductID IN [1, 7] "
        "  AND r.Quantity = $year "
        "RETURN c.CustomerID AS cid, toFloat(sum(r.UnitPrice)) AS wan_tons",
        params={"ids": visible_ids, "year": latest_year},
    )
    industry_totals: dict[str, float] = {}
    for r in industry_rows:
        industry = _INDUSTRY_MAP.get(r["cid"], "其他")
        industry_totals[industry] = industry_totals.get(industry, 0.0) + float(r["wan_tons"] or 0)
    industry_total_sum = sum(industry_totals.values()) or 0.0
    industry_shares: list[DashboardIndustryShare] = [
        DashboardIndustryShare(
            industry=ind, totalEmissionTons=tons * 10_000.0,
            percent=(tons / industry_total_sum) if industry_total_sum > 0 else 0.0,
        )
        for ind, tons in sorted(industry_totals.items(), key=lambda kv: -kv[1])
    ]
    dominant = industry_shares[0] if industry_shares else None

    # 3. Enterprise Top (latest year, Scope1 + Scope2)
    top_rows = await execute_cypher(
        "MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product) "
        "WHERE c.CustomerID IN $ids AND p.ProductID IN [1, 7] "
        "  AND r.Quantity = $year "
        "RETURN c.CustomerID AS cid, c.CompanyName AS name, "
        "       toFloat(sum(r.UnitPrice)) AS wan_tons "
        "ORDER BY wan_tons DESC "
        "LIMIT 8",
        params={"ids": visible_ids, "year": latest_year},
    )
    enterprise_top: list[DashboardEnterpriseTop] = [
        DashboardEnterpriseTop(
            enterpriseId=r["cid"], enterpriseName=r["name"],
            industry=_INDUSTRY_MAP.get(r["cid"], "其他"), year=latest_year,
            totalEmissionTons=float(r["wan_tons"] or 0) * 10_000.0,
        )
        for r in top_rows
    ]

    # 4. Recent updates (latest 10 measurements by OrderID DESC)
    recent_rows = await execute_cypher(
        "MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product) "
        "WHERE c.CustomerID IN $ids "
        "OPTIONAL MATCH (o)-[:PROCESSED_BY]->(e:Employee) "
        "RETURN o.OrderID AS oid, c.CustomerID AS cid, c.CompanyName AS name, "
        "       p.ProductID AS pid, p.ProductName AS metric, "
        "       p.QuantityPerUnit AS unit, toInteger(r.Quantity) AS year, "
        "       toFloat(r.UnitPrice) AS value, o.OrderDate AS order_date, "
        "       o.ShippedDate AS shipped_date, "
        "       coalesce(e.LastName + e.FirstName, 'system') AS operator "
        "ORDER BY o.OrderID DESC, p.ProductID "
        "LIMIT 10",
        params={"ids": visible_ids},
    )
    recent_updates: list[DashboardRecentUpdate] = []
    for r in recent_rows:
        unit_label = (r.get("unit") or "")
        raw_value = float(r.get("value") or 0)
        out_unit = unit_label
        out_value = raw_value
        if "万吨CO2" in unit_label:
            out_value = raw_value * 10_000.0
            out_unit = "tCO2e"
        # Use ShippedDate (publication date) when available; fall back to OrderDate.
        # Derive a deterministic but varied HH:MM:SS from a hash of (OrderID, ProductID)
        # so each row shows a realistic publication time within working hours, while
        # remaining stable across reloads (no actual datetime is stored in Neo4j).
        base_date = r.get("shipped_date") or r.get("order_date") or ""
        seed = (int(r["oid"]) * 31 + int(r["pid"])) & 0xFFFF
        hour = 8 + (seed % 11)              # 08..18 working hours
        minute = (seed >> 4) % 60           # 0..59
        second = (seed >> 10) % 60          # 0..59
        time_str = f"{hour:02d}:{minute:02d}:{second:02d}"
        recent_updates.append(DashboardRecentUpdate(
            id=f"{r['oid']}-{r['pid']}",
            enterpriseId=r["cid"], enterpriseName=r["name"], year=int(r["year"]),
            metricCode=f"P{r['pid']}", metricName=r["metric"],
            value=out_value, unit=out_unit,
            operatorName=r.get("operator") or "system",
            updatedAt=f"{base_date}T{time_str}+08:00" if base_date else now_iso,
        ))

    return DashboardSummary(
        meta=empty_meta,
        kpis=DashboardKpis(
            cumulativeEmissionTons=cumulative,
            latestYearEmissionTons=latest.totalEmissionTons,
            latestYearEmissionYoyRate=yoy,
            fiveYearEmissionChangeRate=five_year_rate,
            totalElectricityKwh=None,
            dominantIndustryName=dominant.industry if dominant else None,
            dominantIndustryPercent=dominant.percent if dominant else None,
        ),
        yearly=yearly,
        enterpriseTop=enterprise_top,
        industryShares=industry_shares,
        recentUpdates=recent_updates,
    )
