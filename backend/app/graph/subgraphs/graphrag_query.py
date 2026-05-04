"""GraphRAG-query subgraph — the core business processing pipeline.

Flow: guardrails → planner → tool_selection → (parallel Map) → collect → answer
"""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send
from pydantic import BaseModel

from app.graph.user_context import build_user_context_block
from app.models.state import GraphRAGSubState
from app.prompts.guardrails_prompt import GUARDRAILS_SYSTEM_PROMPT, SCOPE_DESCRIPTION
from app.prompts.planner_prompt import PLANNER_SYSTEM_PROMPT, TOOL_SELECTION_PROMPT
from app.knowledge.schema_manager import get_cached_schema
from app.utils.llm import get_chat_model, safe_ainvoke, strip_thinking, structured_output, to_openai_messages


# ---------- Permission helpers ----------

# Cached map: CustomerID -> a short keyword that uniquely identifies the
# enterprise's CompanyName. Used to filter Cypher results post-hoc.
_ENTERPRISE_KEYWORDS: dict[str, str] | None = None


async def _get_enterprise_keywords() -> dict[str, str]:
    """Lazy-load CustomerID → name keyword from Neo4j.

    The keyword is a substring of CompanyName that's distinctive enough to
    detect whether a row belongs to that enterprise (e.g. C001 → '化工企业A').
    """
    global _ENTERPRISE_KEYWORDS
    if _ENTERPRISE_KEYWORDS is not None:
        return _ENTERPRISE_KEYWORDS

    from app.knowledge.neo4j_client import execute_cypher as neo4j_exec

    try:
        records = await neo4j_exec(
            "MATCH (c:Customer) RETURN c.CustomerID AS id, c.CompanyName AS name",
            params={},
            database="structured",
        )
    except Exception as e:
        logger.warning("Failed to load enterprise keyword map: %s", e)
        return {}

    # Pick a stable keyword: the part before the first parenthesis (Chinese full/half),
    # truncated to 8 chars, with city/role suffixes stripped.
    mapping: dict[str, str] = {}
    for r in records:
        cid = r.get("id")
        name = r.get("name") or ""
        # Strip the parenthesised role tag at the end if present
        head = name.split("（", 1)[0].split("(", 1)[0].strip()
        # Strip common corporate suffixes for tighter matching
        for suffix in ("股份有限公司", "有限公司", "集团股份有限公司", "集团有限公司",
                       "煤化工有限公司", "能源化工有限公司"):
            if head.endswith(suffix):
                head = head[: -len(suffix)]
                break
        head = head.strip() or name[:6]
        mapping[cid] = head
    _ENTERPRISE_KEYWORDS = mapping
    logger.info("Enterprise keyword map loaded: %s", mapping)
    return mapping


async def _filter_records_by_permission(
    records: list[dict],
    accessible: list[str],
    user_role: str,
) -> list[dict]:
    """Drop rows whose enterprise is not in the user's whitelist.

    Admins (role='admin' or '*' in whitelist) bypass the filter. For other
    users, a row is kept iff:
      - it has a `customer_id` field that's in the whitelist, OR
      - one of its string fields contains a whitelisted enterprise keyword
    Rows that contain neither field are kept (we cannot tell — we rely on
    the Cypher having been pre-filtered by the WHERE injector).
    """
    if user_role == "admin" or "*" in (accessible or []):
        return records
    if not accessible:
        return []

    keyword_map = await _get_enterprise_keywords()
    allowed_keywords = [keyword_map.get(cid, "") for cid in accessible]
    allowed_keywords = [k for k in allowed_keywords if k]
    allowed_ids = set(accessible)

    def row_allowed(row: dict) -> bool:
        # Prefer explicit ID match
        cid = row.get("customer_id") or row.get("CustomerID")
        if cid and cid in allowed_ids:
            return True
        # Fallback: keyword match on any string field
        any_string = False
        for v in row.values():
            if isinstance(v, str):
                any_string = True
                for kw in allowed_keywords:
                    if kw in v:
                        return True
        # If the row carries no string fields at all (pure aggregate output),
        # we can't tell — keep it. The Cypher should have been pre-filtered.
        return not any_string

    filtered = [r for r in records if row_allowed(r)]
    if len(filtered) != len(records):
        logger.info(
            "[permission_filter] %d → %d rows (ids=%s, kw=%s)",
            len(records), len(filtered), allowed_ids, allowed_keywords,
        )
    return filtered


def _inject_customer_filter(cypher: str, allowed_ids: list[str]) -> str:
    """Hard-constrain non-admin Cypher to the user's bound enterprises.

    Strategy:
      1. Strip out any `c.CompanyName CONTAINS '...'` and `c.CompanyName = '...'`
         clauses that the LLM may have added — they may target an enterprise
         outside the whitelist.
      2. Append `c.CustomerID IN [...]` as the authoritative filter.

    This makes越权 queries return empty rather than wrong-enterprise data.
    """
    if not allowed_ids or "(c:Customer" not in cypher:
        return cypher

    import re

    # 1. Drop CompanyName-on-c constraints (CONTAINS / equality / IN)
    #    Pattern variants: "c.CompanyName CONTAINS 'xxx'", "c.CompanyName = 'xxx'"
    cypher = re.sub(
        r"\bc\.CompanyName\s+(CONTAINS|=|STARTS\s+WITH|ENDS\s+WITH)\s+'[^']*'\s*(AND\s+|OR\s+)?",
        "",
        cypher,
        flags=re.IGNORECASE,
    )
    # Clean up any leftover dangling AND/OR right after WHERE
    cypher = re.sub(r"\bWHERE\s+(AND|OR)\s+", "WHERE ", cypher, flags=re.IGNORECASE)
    # Or trailing AND/OR before RETURN/ORDER/LIMIT
    cypher = re.sub(
        r"\s+(AND|OR)\s+(?=(RETURN|ORDER|LIMIT|WITH|MATCH)\b)",
        " ",
        cypher,
        flags=re.IGNORECASE,
    )

    # 2. Inject the whitelist
    ids_literal = "[" + ", ".join(f"'{cid}'" for cid in allowed_ids) + "]"
    constraint = f"c.CustomerID IN {ids_literal}"

    m = re.search(r"\bWHERE\b", cypher, flags=re.IGNORECASE)
    if m:
        idx = m.end()
        cypher = cypher[:idx] + f" {constraint} AND " + cypher[idx:]
    else:
        m2 = re.search(r"\bRETURN\b", cypher, flags=re.IGNORECASE)
        if m2:
            idx = m2.start()
            cypher = cypher[:idx] + f"WHERE {constraint}\n" + cypher[idx:]
    return cypher


# ---------- Nodes ----------

async def guardrails_check(state: GraphRAGSubState) -> dict:
    """Safety guardrails: check if question is within business scope."""
    neo4j_schema = await get_cached_schema()

    class GuardrailsOutput(BaseModel):
        decision: Literal["continue", "end"]
        reason: str

    user_ctx = await build_user_context_block(
        state.get("user_role"),
        state.get("accessible_enterprises"),
    )

    model = get_chat_model(temperature=0)
    base_prompt = GUARDRAILS_SYSTEM_PROMPT.format(
        scope_description=SCOPE_DESCRIPTION,
        neo4j_schema=neo4j_schema,
    )
    prompt = f"{base_prompt}\n\n{user_ctx}" if user_ctx else base_prompt
    messages = [
        {"role": "system", "content": prompt},
        *to_openai_messages(state["messages"][-6:]),
    ]
    result = await structured_output(
        model, GuardrailsOutput, messages,
        default=GuardrailsOutput(decision="continue", reason="LLM unavailable, default to continue"),
    )

    if result.decision == "end":
        return {
            "guardrails_decision": "end",
            "messages": [
                AIMessage(content=(
                    "您的问题看起来不在本平台的数据范围内。本平台仅覆盖**地区A化工/石油化工/光伏/煤炭"
                    "行业**的企业碳排放、能源、污染物与履约数据。"
                ))
            ],
        }
    return {"guardrails_decision": "continue"}


async def task_decomposition(state: GraphRAGSubState) -> dict:
    """Decompose compound question into independent sub-tasks."""

    class PlannerOutput(BaseModel):
        tasks: list[str]

    user_ctx = await build_user_context_block(
        state.get("user_role"),
        state.get("accessible_enterprises"),
    )

    model = get_chat_model(temperature=0)
    system_prompt = PLANNER_SYSTEM_PROMPT
    if user_ctx:
        system_prompt = f"{PLANNER_SYSTEM_PROMPT}\n\n{user_ctx}"
    messages = [
        {"role": "system", "content": system_prompt},
        *to_openai_messages(state["messages"][-6:]),
    ]
    last_msg = state["messages"][-1].content
    result = await structured_output(
        model, PlannerOutput, messages,
        default=PlannerOutput(tasks=[last_msg]),
    )

    tasks = result.tasks if result.tasks else [last_msg]
    return {"tasks": tasks}


async def tool_selection(state: GraphRAGSubState) -> Command:
    """Select the best tool for each sub-task and dispatch via Send (Map).

    Forwards the caller's permission whitelist (`accessible_enterprises`) so
    Cypher executors can filter Neo4j results to only the enterprises the
    user is authorized to view (admins get ['*'] = unrestricted).
    """
    sends = []
    accessible = state.get("accessible_enterprises", []) or []
    user_role = state.get("user_role", "user")

    for task in state.get("tasks", []):
        tool_choice = await _classify_tool(task)

        target_node = {
            "cypher": "cypher_query",
            "predefined": "predefined_cypher",
            "graphrag": "graphrag_search",
            "vector": "vector_search",
        }[tool_choice]

        sends.append(Send(target_node, {
            "task": task,
            "tool_name": tool_choice,
            "accessible_enterprises": accessible,
            "user_role": user_role,
        }))

    return Command(goto=sends)


async def cypher_query(state: dict) -> dict:
    """Execute a Text2Cypher query — generate Cypher via LLM, then run on Neo4j."""
    from app.knowledge.neo4j_client import execute_cypher as neo4j_exec
    from app.knowledge.schema_manager import get_cached_schema

    task = state.get("task", "")
    logger.info(f"[cypher_query] task: {task}")

    try:
        # Generate Cypher directly (skip the full subgraph for reliability)
        neo4j_schema = await get_cached_schema()
        user_ctx = await build_user_context_block(
            state.get("user_role"),
            state.get("accessible_enterprises"),
        )
        user_ctx_block = f"\n{user_ctx}\n" if user_ctx else ""
        model = get_chat_model(temperature=0)
        messages = [
            {"role": "system", "content": (
                f"你是 Neo4j Cypher 查询生成器。根据用户问题生成 Cypher 查询。\n"
                f"{user_ctx_block}"
                f"Schema:\n{neo4j_schema}\n\n"
                f"重要：本库是地区A高排放行业（化工/石油化工/光伏/煤炭）的碳排放/能耗/污染/履约时间序列。语义映射：\n"
                f"- Customer 节点 = 企业 / 自治区聚合 / 对标省份 / 产业园\n"
                f"  化工：'化工企业A（地区A·PVC）'、'化工企业D（地区A 城市4·煤化工/煤制气）'、\n"
                f"        '化工企业H（地区A 工业园 3·煤制烯烃）'、'炼化企业A（地区A 城市1·炼化）'\n"
                f"  石油化工：'石化企业A（地区A 城市7·石油化工·油气勘探与炼化）'\n"
                f"  光伏：'光伏企业A（地区A 城市5·光伏·多晶硅与组件）'\n"
                f"  煤炭：'煤炭企业A（地区A 城市1·煤炭·煤矿与坑口电厂）'\n"
                f"  聚合：'地区A（化工行业聚合）'、'地区B（化工行业聚合·对标）'\n"
                f"- Category 节点 = 指标大类（如 '直接排放Scope1'、'间接排放Scope2'、'能源消耗'、'污染物排放'、'减排与履约'）\n"
                f"- Product 节点 = 具体指标（如 '厂区Scope1 CO2排放总量'、'外购电力间接CO2排放'、'标煤消费总量'、'SO2排放'、'配额履约缺口'）\n"
                f"  注意：节点上的 UnitPrice/UnitsInStock 字段恒为 0，没有业务含义，请勿使用\n"
                f"- Order 节点 = 一次（企业/区域, 年份）观测\n"
                f"- (Order)-[r:CONTAINS]->(Product) 关系上：r.UnitPrice 是数值，r.Quantity 是年份（整数 2019~2026）\n"
                f"- Supplier 节点 = 数据来源（生态环境部、自治区生态环境厅、CPCIF、CQC、CEC、上海环交所、中碳登等）\n\n"
                f"规则：\n"
                f"1. 只生成读操作（MATCH/RETURN/WHERE）\n"
                f"2. 字符串值直接内联，不要用 $ 参数\n"
                f"3. 用 CompanyName 字段做企业/区域匹配时，CONTAINS 用最简短关键词，例如：\n"
                f"   CONTAINS '化工企业A'、CONTAINS '化工企业D'、CONTAINS '煤炭企业A'（与 '煤炭企业A' 区分）、\n"
                f"   CONTAINS '石化企业A'、CONTAINS '光伏企业A'、CONTAINS '煤炭企业A'、\n"
                f"   CONTAINS '地区A维吾尔'、CONTAINS '地区B'\n"
                f"4. 用 ProductName CONTAINS 匹配指标，例如 CONTAINS 'Scope1'、CONTAINS 'Scope2'、CONTAINS 'SO2'、\n"
                f"   CONTAINS '配额履约缺口'、CONTAINS '标煤'\n"
                f"5. **数据值与年份取自 [:CONTAINS] 关系上的属性**：r.UnitPrice 是数值，r.Quantity 是年份\n"
                f"6. **按年份过滤时只能用 r.Quantity = <year>（整数），例如 r.Quantity = 2022 或 r.Quantity IN [2019,2026]。**\n"
                f"   严禁使用 o.OrderDate、date()、datetime()、toString() 等做年份过滤——OrderDate 只是上报时间，不是数据年份\n"
                f"7. **聚合查询**：用户问『总共/累计/合计/全部/历史/历年』时，使用 sum(r.UnitPrice) 按企业/指标聚合；\n"
                f"   问『平均/均值』用 avg；问『最高/最低/最大/最小』用 max/min。聚合 RETURN 别名仍用 ASCII（如 total / avg_value / peak_value）\n"
                f"8. **RETURN 必须始终包含 c.CompanyName AS enterprise 与 c.CustomerID AS customer_id 字段**（上层用它们做权限过滤），\n"
                f"   其他字段用 ASCII 别名（region/year/value/unit/indicator/total/diff），不要用中文别名\n"
                f"9. 标准查询模板（请按需修改）：\n"
                f"   MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)\n"
                f"   WHERE c.CompanyName CONTAINS '化工企业A'\n"
                f"     AND p.ProductName CONTAINS 'Scope1'\n"
                f"     AND r.Quantity = 2022\n"
                f"   RETURN c.CompanyName AS enterprise, r.Quantity AS year,\n"
                f"          p.ProductName AS indicator, r.UnitPrice AS value,\n"
                f"          p.QuantityPerUnit AS unit\n"
                f"   聚合示例（用户问『过去总共』）：\n"
                f"   MATCH (c:Customer)-[:PLACED_BY]->(o:Order)-[r:CONTAINS]->(p:Product)\n"
                f"   WHERE c.CompanyName CONTAINS '化工企业A'\n"
                f"     AND p.ProductName CONTAINS 'Scope1'\n"
                f"   RETURN c.CompanyName AS enterprise, p.ProductName AS indicator,\n"
                f"          sum(r.UnitPrice) AS total, p.QuantityPerUnit AS unit\n"
                f"10. 仅输出 Cypher 语句，不要任何 markdown 代码块或解释文字"
            )},
            {"role": "user", "content": task},
        ]
        response = await safe_ainvoke(model, messages)
        cypher = strip_thinking(response.content).strip()
        # Remove ```cypher ... ``` or ``` ... ``` fences if present
        if cypher.startswith("```"):
            cypher = cypher.split("```", 2)[-1] if cypher.count("```") >= 1 else cypher
            if cypher.lstrip().lower().startswith("cypher"):
                cypher = cypher.lstrip()[6:]
            cypher = cypher.rsplit("```", 1)[0] if "```" in cypher else cypher
        cypher = cypher.strip().strip("`").strip()
        if cypher.lower().startswith("cypher"):
            cypher = cypher[6:].strip()

        # Inject a permission constraint into the Cypher BEFORE execution so
        # the DB itself drops unauthorized rows even when the LLM forgot to
        # RETURN a string-typed enterprise column (e.g. for pure aggregates).
        accessible_state = state.get("accessible_enterprises", []) or []
        user_role_state = state.get("user_role", "user")
        logger.info(
            "[cypher_query] permission state: role=%r accessible=%r",
            user_role_state, accessible_state,
        )
        if user_role_state != "admin" and "*" not in accessible_state and accessible_state:
            cypher = _inject_customer_filter(cypher, accessible_state)
        logger.info(f"[cypher_query] generated cypher: {cypher}")

        records = await neo4j_exec(cypher, params={}, database="structured")
        logger.info(f"[cypher_query] got {len(records)} records")

        records = await _filter_records_by_permission(
            records,
            accessible_state,
            user_role_state,
        )

        if records:
            answer = str(records[:10])
        else:
            allowed = state.get("accessible_enterprises", []) or []
            if allowed and "*" not in allowed and state.get("user_role") != "admin":
                answer = "未查询到您有权访问的企业的相关数据。如需查询其他企业，请联系管理员开通权限。"
            else:
                answer = "未查询到相关数据"
    except Exception as e:
        logger.error(f"[cypher_query] error: {e}", exc_info=True)
        answer = "结构化数据查询暂时不可用"

    return {
        "tool_results": [{
            "task": task,
            "tool": "cypher",
            "result": answer,
        }]
    }


async def predefined_cypher(state: dict) -> dict:
    """Match task against pre-built Cypher templates, then execute."""
    from app.knowledge.cypher_templates import CYPHER_TEMPLATES
    from app.knowledge.neo4j_client import execute_cypher as neo4j_exec

    task = state.get("task", "")

    # Use LLM to pick the best template and extract params
    class TemplateMatch(BaseModel):
        template_id: str
        params: dict

    descriptions = "\n".join(
        f"- {t['id']}: {t['description']} (例：{t['examples'][0]})"
        for t in CYPHER_TEMPLATES[:30]  # top 30 to keep prompt short
    )
    model = get_chat_model(temperature=0)
    try:
        match = await structured_output(model, TemplateMatch, [
            {
                "role": "system",
                "content": (
                    "从以下模板中选择最匹配用户问题的模板ID，并提取所需参数。\n"
                    "如果没有匹配的模板，返回 template_id='none', params={}。\n\n"
                    f"可用模板：\n{descriptions}"
                ),
            },
            {"role": "user", "content": task},
        ])
    except Exception:
        match = None

    if not match or match.template_id == "none":
        return {"tool_results": [{"task": task, "tool": "predefined", "result": "未找到匹配模板"}]}

    # Find the template
    template = next((t for t in CYPHER_TEMPLATES if t["id"] == match.template_id), None)
    if not template:
        return {"tool_results": [{"task": task, "tool": "predefined", "result": "模板不存在"}]}

    try:
        records = await neo4j_exec(template["cypher"], params=match.params, database="structured")
        records = await _filter_records_by_permission(
            records,
            state.get("accessible_enterprises", []) or [],
            state.get("user_role", "user"),
        )
        if not records:
            allowed = state.get("accessible_enterprises", []) or []
            if allowed and "*" not in allowed and state.get("user_role") != "admin":
                result_text = "未查询到您有权访问的企业的相关数据。"
            else:
                result_text = "未查询到相关数据"
        else:
            result_text = str(records[:10])
    except Exception as e:
        logger.error(f"predefined_cypher execution error: {e}")
        result_text = "模板查询失败"

    return {
        "tool_results": [{
            "task": task,
            "tool": "predefined",
            "result": result_text,
        }]
    }


async def graphrag_search(state: dict) -> dict:
    """Knowledge base search — keyword retrieval over product manuals, policies, FAQ.

    Upgrade path: replace with Microsoft GraphRAG + Neo4j unstructured DB when available.
    """
    from app.knowledge.knowledge_search import search as kb_search

    task = state.get("task", "")
    try:
        hits = kb_search(task, top_k=3)
        if hits:
            context = "\n\n".join(
                f"[{h['source']} / {h['section']}]\n{h['text']}" for h in hits
            )
        else:
            context = "知识库中未找到相关内容"
    except Exception as e:
        logger.error(f"graphrag_search error: {e}")
        context = "知识库检索暂时不可用"

    return {
        "tool_results": [{
            "task": task,
            "tool": "graphrag",
            "result": context,
        }]
    }


async def vector_search(state: dict) -> dict:
    """Hybrid search — keyword retrieval (upgradeable to vector + BM25 + RRF).

    Upgrade path: Milvus/pgvector + Elasticsearch BM25 + RRF fusion when Docker available.
    """
    from app.knowledge.knowledge_search import search as kb_search

    task = state.get("task", "")
    try:
        hits = kb_search(task, top_k=5, min_score=0.05)
        if hits:
            context = "\n\n".join(
                f"[{h['source']} / {h['section']}]\n{h['text']}" for h in hits
            )
        else:
            context = "未找到相关文档片段"
    except Exception as e:
        logger.error(f"vector_search error: {e}")
        context = "向量检索暂时不可用"

    return {
        "tool_results": [{
            "task": task,
            "tool": "vector",
            "result": context,
        }]
    }


async def collect_results(state: GraphRAGSubState) -> dict:
    """Reduce step: collect all parallel tool results."""
    # tool_results are aggregated by the operator.add reducer
    return {}


async def generate_final_answer(state: GraphRAGSubState) -> dict:
    """Generate a coherent final answer from all tool results."""
    tool_results = state.get("tool_results", [])

    user_ctx = await build_user_context_block(
        state.get("user_role"),
        state.get("accessible_enterprises"),
    )

    model = get_chat_model(temperature=0.3, max_tokens=2048)

    context = "\n".join(
        f"- [{r['tool']}] {r['task']}: {r['result']}" for r in tool_results
    )

    base_system = (
        "你是ScopeGraph·地区A化工/石油化工/光伏/煤炭碳数据库的分析助手。根据以下检索结果回答用户关于"
        "企业碳排放/能耗/污染/履约的问题。\n"
        "规则：\n"
        "1. **只基于检索结果回答**，没有的信息明确说『暂无该数据』，不要编造任何数字\n"
        "2. 给出具体数值时务必带单位（万吨CO2/年、万tce、亿千瓦时、吨/年、%、亿元等）\n"
        "3. 用户问『总共/累计/全部』时，把检索结果中的多年数值相加并明示『2019-2026 年累计』\n"
        "4. 涉及对比/趋势时，主动算出绝对差和百分比变化\n"
        "5. 涉及配额、CCER、绿证等履约话题时，提醒用户结合最新政策与人工顾问确认\n"
        "6. 末尾可附一句简短解读，但不要做未来预测\n"
        "**严格权限规则**：\n"
        "- 如果用户问的企业不在『当前用户身份』的绑定企业列表里（比如绑定 C001 化工企业A，但问化工企业D），\n"
        "  即使检索结果中包含该企业数据也绝不可输出，必须明确告知：\n"
        "  『您当前账号仅可查询绑定企业（XXX）的数据，无权访问 YYY 的数据，请联系管理员开通权限。』\n"
        "- 严禁编造数字、引用公开报道、或建议用户去其他渠道查询非授权企业的数据\n"
        "风格：专业、严谨、克制，使用行业术语（PVC/煤化工/合成氨/多晶硅/坑口电厂/工艺过程排放等），"
        "可适度使用数据可视化语言（如『上升』『下降』『持平』）"
    )
    system_content = f"{base_system}\n\n{user_ctx}" if user_ctx else base_system
    messages = [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": f"检索结果:\n{context}\n\n用户问题: {state['messages'][-1].content}",
        },
    ]

    response = await safe_ainvoke(model, messages)
    answer = strip_thinking(response.content)
    return {
        "final_answer": answer,
        "messages": [AIMessage(content=answer)],
    }


# ---------- Routing ----------

def guardrails_route(state: GraphRAGSubState) -> str:
    if state.get("guardrails_decision") == "end":
        return END
    return "planner"


# ---------- Build sub-graph ----------

def build_graphrag_query_subgraph() -> StateGraph:
    workflow = StateGraph(GraphRAGSubState)

    # Register nodes
    workflow.add_node("guardrails", guardrails_check)
    workflow.add_node("planner", task_decomposition)
    workflow.add_node("tool_selection", tool_selection)
    workflow.add_node("cypher_query", cypher_query)
    workflow.add_node("predefined_cypher", predefined_cypher)
    workflow.add_node("graphrag_search", graphrag_search)
    workflow.add_node("vector_search", vector_search)
    workflow.add_node("collect_results", collect_results)
    workflow.add_node("generate_answer", generate_final_answer)

    # Edges
    workflow.add_edge(START, "guardrails")
    workflow.add_conditional_edges("guardrails", guardrails_route, {
        "planner": "planner",
        END: END,
    })
    workflow.add_edge("planner", "tool_selection")

    # Map-Reduce: tool nodes → collect → answer
    for node in ("cypher_query", "predefined_cypher", "graphrag_search", "vector_search"):
        workflow.add_edge(node, "collect_results")
    workflow.add_edge("collect_results", "generate_answer")
    workflow.add_edge("generate_answer", END)

    return workflow.compile()


graphrag_query_subgraph = build_graphrag_query_subgraph()


# ---------- Helpers ----------

async def _classify_tool(task: str) -> str:
    """Classify which tool a sub-task should use."""
    model = get_chat_model(temperature=0)

    class ToolChoice(BaseModel):
        tool: Literal["cypher", "predefined", "graphrag", "vector"]

    prompt = TOOL_SELECTION_PROMPT.format(task=task)
    # Default to cypher — that's the right call for almost any data question.
    result = await structured_output(
        model, ToolChoice,
        [{"role": "user", "content": prompt}],
        default=ToolChoice(tool="cypher"),
    )
    return result.tool
