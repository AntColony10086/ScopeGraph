"""Build a Chinese natural-language block that tells the LLM who the
current user is, which enterprise(s) they are bound to, and how to resolve
first-person references in the user's question.

Plugged into the router, guardrails, planner, cypher-gen and answer-gen
prompts so that questions like "我过去总共排放了多少" are correctly
interpreted as "<bound enterprise> 历年累计 Scope1+Scope2 是多少".
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.knowledge.neo4j_client import execute_cypher

logger = logging.getLogger(__name__)

_NAME_CACHE: dict[str, str] | None = None


async def _customer_id_to_name() -> dict[str, str]:
    """Lazy-load CustomerID → CompanyName map from Neo4j (cached)."""
    global _NAME_CACHE
    if _NAME_CACHE is not None:
        return _NAME_CACHE
    try:
        rows = await execute_cypher(
            "MATCH (c:Customer) RETURN c.CustomerID AS id, c.CompanyName AS name",
            params={},
            database="structured",
        )
    except Exception as e:
        logger.warning("user_context: failed to load customer names: %s", e)
        return {}
    _NAME_CACHE = {r["id"]: r["name"] for r in rows if r.get("id")}
    return _NAME_CACHE


def _is_admin(user_role: str | None, accessible: Iterable[str] | None) -> bool:
    if (user_role or "").lower() == "admin":
        return True
    return "*" in (list(accessible or []))


async def build_user_context_block(
    user_role: str | None,
    accessible_enterprises: list[str] | None,
) -> str:
    """Return a Markdown block describing who the user is and how to resolve
    first-person references. Empty string when there is no useful context.
    """
    accessible = list(accessible_enterprises or [])
    if not accessible and (user_role or "user") != "admin":
        return ""

    if _is_admin(user_role, accessible):
        return (
            "## 当前用户身份\n"
            "- 角色：管理员（可查询全部企业）\n"
            "- 用户使用『我』『我们』『自家』时无具体绑定企业，按字面理解；"
            "若用户未指定企业但只有一类语义对象（如『各企业 Scope1 排名』），可遍历所有企业\n"
        )

    name_map = await _customer_id_to_name()
    bound_lines: list[str] = []
    for cid in accessible:
        name = name_map.get(cid)
        bound_lines.append(f"  - {cid}：{name}" if name else f"  - {cid}")
    bound_str = "\n".join(bound_lines) if bound_lines else "  - （无）"

    return (
        "## 当前用户身份\n"
        "- 角色：普通用户（仅能查询所绑定企业的数据）\n"
        f"- 已绑定企业：\n{bound_str}\n"
        "- **极重要的默认规则（路由 + 查询 + 答复都要遵守）**：\n"
        "  1. 用户使用『我』『我公司』『我们』『本公司』『自家』『过去』『累计』等\n"
        "     第一人称代词或泛指主语时，**默认指上述绑定企业**\n"
        "  2. 即使用户没有用第一人称、也没有显式指定企业，**只要问的是排放/能耗/污染/履约**\n"
        "     **类的数据问题（数值/对比/趋势/累计），主语就默认是上述绑定企业**——\n"
        "     绑定企业即是隐式的默认主语，不需要再问『请问您要查询的是哪家企业』\n"
        "  3. 如绑定多家，对所有绑定企业一并查询/汇总；如绑定一家，主语就是它\n"
        "- 路由分类：以上情况一律归类为 graphrag-query（信息已完整），**不要**归为\n"
        "  additional-query 让用户补充企业名\n"
    )
