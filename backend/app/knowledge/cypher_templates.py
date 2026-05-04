"""Pre-built Cypher query template dictionary for the Region A chemical
carbon database.

The graph repurposes the e-commerce schema as follows:
  Customer  →  化工企业 / 自治区聚合 / 对标省份 / 化工产业园
  Product   →  指标（Scope1/Scope2/标煤/SO2/履约缺口…），QuantityPerUnit 为单位
  Category  →  指标大类（直接/间接/价值链/能源/污染/减排履约）
  Supplier  →  数据来源（生态环境部、自治区生态环境厅、CPCIF、CQC…）
  Order     →  一次（企业, 年份）观测；OrderDate 仅是上报时间
  CONTAINS  →  关系上的 r.UnitPrice 是数值，r.Quantity 是年份
"""

from __future__ import annotations

CYPHER_TEMPLATES: list[dict] = [
    # ==================== Indicator Metadata ====================
    {
        "id": "meta_001",
        "description": "查询所有指标类别",
        "examples": ["你们提供哪些数据", "有哪些指标维度", "数据涵盖哪些方面"],
        "cypher": """
            MATCH (c:Category)
            OPTIONAL MATCH (p:Product)-[:BELONGS_TO]->(c)
            RETURN c.CategoryName AS category, c.Description AS description,
                   count(p) AS indicator_count
            ORDER BY indicator_count DESC
        """,
        "params": [],
    },
    {
        "id": "meta_002",
        "description": "查询某类别下的所有指标",
        "examples": ["直接排放Scope1有哪些指标", "污染物排放下面都有什么", "减排与履约类指标"],
        "cypher": """
            MATCH (p:Product)-[:BELONGS_TO]->(c:Category)
            WHERE c.CategoryName CONTAINS $category
            RETURN p.ProductID AS id, p.ProductName AS indicator,
                   p.QuantityPerUnit AS unit
            ORDER BY p.ProductID
        """,
        "params": ["category"],
    },
    {
        "id": "meta_003",
        "description": "查询某指标的元信息（类别、单位、数据来源）",
        "examples": ["Scope1的口径", "配额履约缺口怎么算", "标煤消费的单位"],
        "cypher": """
            MATCH (p:Product)
            WHERE p.ProductName CONTAINS $keyword
            OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category)
            OPTIONAL MATCH (p)-[:SUPPLIED_BY]->(s:Supplier)
            RETURN p.ProductName AS indicator, p.QuantityPerUnit AS unit,
                   c.CategoryName AS category, s.CompanyName AS source
        """,
        "params": ["keyword"],
    },
    {
        "id": "meta_004",
        "description": "查询所有数据来源",
        "examples": ["数据从哪来", "有哪些数据源", "都是谁报送的数据"],
        "cypher": """
            MATCH (s:Supplier)
            OPTIONAL MATCH (p:Product)-[:SUPPLIED_BY]->(s)
            RETURN s.CompanyName AS source, s.City AS city,
                   count(p) AS indicator_count
            ORDER BY indicator_count DESC
        """,
        "params": [],
    },
    {
        "id": "meta_005",
        "description": "查询所有有数据的企业/区域",
        "examples": ["你们覆盖哪些企业", "支持哪些化工厂", "数据覆盖范围"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)
            RETURN c.CustomerID AS code, c.CompanyName AS subject,
                   count(DISTINCT o.OrderDate) AS year_count
            ORDER BY year_count DESC, c.CustomerID
        """,
        "params": [],
    },

    # ==================== Enterprise × Year × Indicator Lookups ====================
    {
        "id": "data_001",
        "description": "查询某企业某年某指标的数据",
        "examples": ["化工企业A2022年Scope1", "化工企业D2023直接排放", "化工企业E2021年外购电力间接排放"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE c.CompanyName CONTAINS $enterprise
              AND p.ProductName CONTAINS $indicator
              AND r.Quantity = $year
            RETURN c.CompanyName AS enterprise, $year AS year,
                   p.ProductName AS indicator,
                   r.UnitPrice AS value, p.QuantityPerUnit AS unit
        """,
        "params": ["enterprise", "indicator", "year"],
    },
    {
        "id": "data_002",
        "description": "查询某企业某指标的全部年份序列",
        "examples": ["化工企业A历年Scope1", "化工企业D直接排放变化", "地区A化工配额履约缺口时间序列"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE c.CompanyName CONTAINS $enterprise
              AND p.ProductName CONTAINS $indicator
            RETURN c.CompanyName AS enterprise, p.ProductName AS indicator,
                   r.Quantity AS year, r.UnitPrice AS value,
                   p.QuantityPerUnit AS unit
            ORDER BY r.Quantity
        """,
        "params": ["enterprise", "indicator"],
    },
    {
        "id": "data_003",
        "description": "查询某指标某年所有企业的横向对比",
        "examples": ["2023年地区A各化工企业Scope1对比", "2022 PVC企业排放排名", "2023 Scope2排放最高"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE p.ProductName CONTAINS $indicator
              AND r.Quantity = $year
            RETURN c.CompanyName AS enterprise, $year AS year,
                   p.ProductName AS indicator,
                   r.UnitPrice AS value, p.QuantityPerUnit AS unit
            ORDER BY r.UnitPrice DESC
        """,
        "params": ["indicator", "year"],
    },
    {
        "id": "data_004",
        "description": "查询某企业某年的所有可用指标",
        "examples": ["化工企业A2022年都有什么数据", "化工企业D2023全部指标"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE c.CompanyName CONTAINS $enterprise
              AND r.Quantity = $year
            RETURN c.CompanyName AS enterprise, $year AS year,
                   p.ProductName AS indicator, r.UnitPrice AS value,
                   p.QuantityPerUnit AS unit
            ORDER BY p.ProductID
        """,
        "params": ["enterprise", "year"],
    },
    {
        "id": "data_005",
        "description": "查询某企业的全部历史数据点",
        "examples": ["化工企业A全部数据", "化工企业D历年数据"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE c.CompanyName CONTAINS $enterprise
            RETURN c.CompanyName AS enterprise, r.Quantity AS year,
                   p.ProductName AS indicator, r.UnitPrice AS value,
                   p.QuantityPerUnit AS unit
            ORDER BY r.Quantity, p.ProductID
        """,
        "params": ["enterprise"],
    },

    # ==================== Comparisons & Trends ====================
    {
        "id": "compare_001",
        "description": "比较两家企业在某年某指标的数值",
        "examples": ["2023年化工企业A和化工企业DScope1对比", "化工企业A和煤炭企业A2022 直接排放"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE (c.CompanyName CONTAINS $enterprise_a OR c.CompanyName CONTAINS $enterprise_b)
              AND p.ProductName CONTAINS $indicator
              AND r.Quantity = $year
            RETURN c.CompanyName AS enterprise, $year AS year,
                   p.ProductName AS indicator,
                   r.UnitPrice AS value, p.QuantityPerUnit AS unit
            ORDER BY r.UnitPrice DESC
        """,
        "params": ["enterprise_a", "enterprise_b", "indicator", "year"],
    },
    {
        "id": "compare_002",
        "description": "比较某企业某指标在两个年份的变化",
        "examples": ["化工企业A2019和2023 Scope1变化", "化工企业D 2020 vs 2023直接排放"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE c.CompanyName CONTAINS $enterprise
              AND p.ProductName CONTAINS $indicator
              AND r.Quantity IN [$year_a, $year_b]
            RETURN c.CompanyName AS enterprise, p.ProductName AS indicator,
                   r.Quantity AS year, r.UnitPrice AS value,
                   p.QuantityPerUnit AS unit
            ORDER BY r.Quantity
        """,
        "params": ["enterprise", "indicator", "year_a", "year_b"],
    },
    {
        "id": "trend_001",
        "description": "查询某指标某年企业排名（TOP）",
        "examples": ["2023年Scope1排放最高的化工企业", "2022外购电力排放最低的企业"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE p.ProductName CONTAINS $indicator
              AND r.Quantity = $year
              AND c.CustomerID <> 'C011'
            RETURN c.CompanyName AS enterprise, r.UnitPrice AS value,
                   p.QuantityPerUnit AS unit
            ORDER BY r.UnitPrice DESC
        """,
        "params": ["indicator", "year"],
    },
    {
        "id": "trend_002",
        "description": "汇总某企业某指标的多年统计（最大、最小、平均）",
        "examples": ["化工企业AScope1峰值", "化工企业D历年Scope2平均"],
        "cypher": """
            MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
            WHERE c.CompanyName CONTAINS $enterprise
              AND p.ProductName CONTAINS $indicator
            RETURN c.CompanyName AS enterprise, p.ProductName AS indicator,
                   min(r.UnitPrice) AS min_value,
                   max(r.UnitPrice) AS max_value,
                   round(avg(r.UnitPrice) * 1000) / 1000.0 AS avg_value,
                   count(r) AS year_count,
                   p.QuantityPerUnit AS unit
        """,
        "params": ["enterprise", "indicator"],
    },

    # ==================== Source Lookups ====================
    {
        "id": "src_001",
        "description": "查询某数据来源所贡献的指标列表",
        "examples": ["生态环境部提供的指标", "CPCIF都给了什么数据", "中碳登的数据"],
        "cypher": """
            MATCH (p:Product)-[:SUPPLIED_BY]->(s:Supplier)
            WHERE s.CompanyName CONTAINS $source
            RETURN s.CompanyName AS source, p.ProductName AS indicator,
                   p.QuantityPerUnit AS unit
            ORDER BY p.ProductID
        """,
        "params": ["source"],
    },
]
