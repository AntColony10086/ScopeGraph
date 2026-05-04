# Neo4j 数据模型

本文档描述 ScopeGraph 在 Neo4j 中的图谱设计。
该设计**复用了一套通用的 e-commerce 图模型**（Customer / Product / Order / Supplier ...），
仅在语义层做了重映射以承载碳数据观测，避免重新设计图结构带来的工程成本。

> **匿名化提示**：仓库中所有数值均填充为占位符 `123`；企业名称、地区、人员均为
> `化工企业A` / `地区A` / `员工 1` 等抽象表述。本节示例 Cypher 同样使用这些匿名名。

---

## 1. 节点（Node Labels）

### 1.1 `Customer` —— 化工企业 / 区域聚合主体

| 字段 | 类型 | 说明 |
|------|------|------|
| `CustomerID` | string (PK) | 主键，如 `C001` |
| `CompanyName` | string | 企业名（含子行业标签），如 `化工企业A（地区A·PVC）` |
| `City` | string | 所在城市，如 `城市1` |
| `Country` | string | 国家 / 行政区，如 `地区A` |
| `Region` | string | 大区，如 `西部` |
| `ContactName` | string | 联系人 |
| `Phone` | string | 联系方式（已脱敏） |

**语义重映射**：原 e-commerce 图中的 "Customer" 在本仓库中表示**碳排观测主体**，
可以是单个化工企业、产业园聚合、跨省对标主体或全国基线。

### 1.2 `Product` —— 碳/能源/污染指标

| 字段 | 类型 | 说明 |
|------|------|------|
| `ProductID` | int (PK) | 主键 |
| `ProductName` | string | 指标名，如 `厂区Scope1 CO2排放总量`、`外购电力Scope2`、`SO2排放` |
| `QuantityPerUnit` | string | 计量单位，如 `万吨CO2/年`、`tce`、`kg` |
| `UnitsInStock` | int | 占位字段（未使用） |
| `Discontinued` | bool | 是否停用 |

**语义重映射**：`Product` 表示一个**指标定义**，例如 "厂区 Scope1 CO2 排放总量"。
具体某企业某年的取值不在 `Product` 上，而是在 `(Order)-[:CONTAINS]->(Product)` 关系的属性里。

### 1.3 `Category` —— 指标大类

| 字段 | 类型 | 说明 |
|------|------|------|
| `CategoryID` | int (PK) | 主键 |
| `CategoryName` | string | `Scope1` / `Scope2` / `Scope3` / `能源` / `污染` / `减排履约` |
| `Description` | string | 大类说明 |

### 1.4 `Supplier` —— 数据来源

| 字段 | 类型 | 说明 |
|------|------|------|
| `SupplierID` | int (PK) | 主键 |
| `CompanyName` | string | 数据出处机构名（已抽象，如 `行业协会 A`、`监管单位 B`） |
| `Country` | string | 来源所属地区 |

**语义重映射**：`Supplier` 表示某项指标定义的**权威数据来源**，
在回答中作为引用脚注呈现（"数据来源：xxx"）。

### 1.5 `Order` —— (企业, 年份) 观测实例

| 字段 | 类型 | 说明 |
|------|------|------|
| `OrderID` | int (PK) | 主键，约定单调递增 |
| `OrderDate` | string | 上报日期（仅用于排序；真正的"数据年份"在 `r.Quantity` 上） |
| `RequiredDate` | string | 占位字段 |
| `ShippedDate` | string | 占位字段 |
| `Freight` | float | 占位字段 |

**语义重映射**：一条 `Order` 表示**一个企业在一个年度上报的观测包**，
该观测包内可包含若干指标（多条 `:CONTAINS` 关系），每条指标都是一个数据点。

### 1.6 `Employee` —— 碳合规分析师

| 字段 | 类型 | 说明 |
|------|------|------|
| `EmployeeID` | int (PK) | 主键 |
| `FirstName` / `LastName` | string | 已抽象为 `员工 1` / `员工 2` 等 |
| `Title` | string | 职称，如 `碳合规分析师` |
| `HireDate` | string | 入职日期 |

### 1.7 `Shipper` —— 数据上报渠道

| 字段 | 类型 | 说明 |
|------|------|------|
| `ShipperID` | int (PK) | 主键 |
| `CompanyName` | string | 上报渠道，如 `登记平台 A`、`在线申报系统 B`（已抽象） |
| `Phone` | string | 占位字段 |

---

## 2. 关系（Relationships）

```
(Customer)-[:PLACED_BY]->(Order)-[r:CONTAINS]->(Product)
                          │
                          ├─ r.UnitPrice  : float  数据值（指标取值，仓库中统一为 123）
                          ├─ r.Quantity   : int    数据年份（关键字段，例如 2024）
                          └─ r.Discount   : float  占位字段

(Product)-[:BELONGS_TO]->(Category)
(Product)-[:SUPPLIED_BY]->(Supplier)
(Order)-[:PROCESSED_BY]->(Employee)
(Order)-[:SHIPPED_VIA]->(Shipper)
```

| 关系 | 起点 → 终点 | 关键属性 | 含义 |
|------|--------------|----------|------|
| `:PLACED_BY` | `Customer → Order` | （无） | 企业上报了一次观测 |
| `:CONTAINS` | `Order → Product` | `UnitPrice`（数值）<br>`Quantity`（年份） | **数据点本体**：某企业某年某指标的取值 |
| `:BELONGS_TO` | `Product → Category` | （无） | 指标归属大类 |
| `:SUPPLIED_BY` | `Product → Supplier` | （无） | 指标定义出处 |
| `:PROCESSED_BY` | `Order → Employee` | （无） | 哪位分析师审核了该次上报 |
| `:SHIPPED_VIA` | `Order → Shipper` | （无） | 通过哪个渠道上报 |

> **关键约定**：`r.Quantity` 不是数量，而是**数据年份**。
> `r.UnitPrice` 不是单价，而是**指标取值**。
> 这是为了不修改原 e-commerce 图模型而做的语义复用。

---

## 3. 示例查询

### 3.1 单点查询：化工企业A 2024 年 Scope1

```cypher
MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
WHERE c.CompanyName CONTAINS '化工企业A'
  AND p.ProductName CONTAINS 'Scope1'
  AND r.Quantity = 2024
RETURN c.CompanyName       AS enterprise,
       r.Quantity          AS year,
       p.ProductName       AS indicator,
       r.UnitPrice         AS value,
       p.QuantityPerUnit   AS unit;
```

### 3.2 行业排名：2023 年地区A 化工 Scope1 排放最高

```cypher
MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
WHERE c.Country = '地区A'
  AND p.ProductName CONTAINS 'Scope1'
  AND r.Quantity = 2023
RETURN c.CompanyName AS enterprise, r.UnitPrice AS scope1_value
ORDER BY scope1_value DESC
LIMIT 10;
```

### 3.3 时间趋势：化工企业A 2019–2024 年 Scope1

```cypher
MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
WHERE c.CompanyName CONTAINS '化工企业A'
  AND p.ProductName CONTAINS 'Scope1'
  AND r.Quantity >= 2019 AND r.Quantity <= 2024
RETURN r.Quantity AS year, r.UnitPrice AS value
ORDER BY year ASC;
```

### 3.4 横向对比：化工企业D vs 化工企业H 2023 直接排放

```cypher
MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
WHERE c.CompanyName IN ['化工企业D', '化工企业H']
  AND p.ProductName CONTAINS 'Scope1'
  AND r.Quantity = 2023
RETURN c.CompanyName AS enterprise, r.UnitPrice AS scope1_value;
```

### 3.5 区域聚合：地区A 化工行业近五年标煤消费总量

```cypher
MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)
WHERE c.CompanyName CONTAINS '化工行业'
  AND p.ProductName CONTAINS '标煤'
  AND r.Quantity >= 2020
RETURN r.Quantity AS year, r.UnitPrice AS coal_eq_total
ORDER BY year ASC;
```

---

## 4. 引导数据（Bootstrap）与日常维护

### 4.1 Bootstrap 时机

`data/neo4j/*.csv` 仅在**首次部署**时使用，由 `scripts/import_neo4j.py` 一次性
读入 Neo4j。CSV 文件包含：

| CSV 文件 | 行数（演示） | 内容 |
|----------|------|------|
| `categories.csv` | 8 | 指标大类 |
| `products.csv` | 35 | 指标定义（连同单位） |
| `customers.csv` | 23 | 企业 + 区域聚合主体 |
| `suppliers.csv` | 多个 | 数据来源 |
| `employees.csv` | 多个 | 分析师 |
| `shippers.csv` | 多个 | 上报渠道 |
| `orders.csv` | 多个 | 历史观测头 |
| `order_details.csv` | 多个 | 历史数据点（含 `UnitPrice` 与 `Quantity`） |

> **数据真相源是 Neo4j**，不是 CSV。CSV 仅是首次种子。

### 4.2 日常增删改

仓库提供三条等价路径，按推荐顺序：

1. **前端 UI**：登录后进入 "碳数据查询" 页，点击 "新增数据" / "修改" / "删除"。
   后端走 `POST /api/data/observations` / `DELETE /api/data/observations/{id}` 等
   REST 接口（见 [api.md](api.md)）。
2. **脚本批量**：调用 `POST /api/data/observations` 接口；适合一次导入数十/上百条。
3. **Cypher 直写**（仅高级用户）：

```cypher
// 新增一条 (企业, 年份, 指标) 观测
MATCH (c:Customer {CustomerID: 'C001'})
MATCH (p:Product   {ProductID: 1})
MERGE (c)-[:PLACED_BY]->(o:Order {OrderID: $new_oid, OrderDate: '2026-12-31'})
MERGE (o)-[:CONTAINS  {UnitPrice: $value, Quantity: 2026, Discount: 0}]->(p);
```

### 4.3 新增指标 / 新增企业

- **新增指标**：`CREATE (p:Product {ProductID, ProductName, QuantityPerUnit, ...})`
  并通过 `:BELONGS_TO` 挂到对应 `Category`。如果希望幂等地参与下次 bootstrap，
  把同一行也写入 `data/neo4j/products.csv`。
- **新增企业**：`CREATE (c:Customer {CustomerID, CompanyName, City, Country, ...})`
  即可立刻参与查询；后续每年的指标值通过 `POST /api/data/observations` 录入。

### 4.4 索引建议

生产环境推荐建立以下索引（demo 数据量较小可省略）：

```cypher
CREATE INDEX customer_name_idx IF NOT EXISTS
  FOR (c:Customer) ON (c.CompanyName);

CREATE INDEX product_name_idx  IF NOT EXISTS
  FOR (p:Product)  ON (p.ProductName);

CREATE INDEX order_year_idx    IF NOT EXISTS
  FOR ()-[r:CONTAINS]-() ON (r.Quantity);
```
