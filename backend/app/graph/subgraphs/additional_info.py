"""Additional-query subgraph — guides user to provide missing information."""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.graph.user_context import build_user_context_block
from app.models.state import AdditionalInfoSubState
from app.prompts.guardrails_prompt import GUARDRAILS_SYSTEM_PROMPT, SCOPE_DESCRIPTION
from app.knowledge.schema_manager import get_cached_schema
from app.utils.llm import get_chat_model, safe_ainvoke, strip_thinking, structured_output, to_openai_messages


# ---------- Nodes ----------

async def additional_guardrails(state: AdditionalInfoSubState) -> dict:
    """Safety guardrails: check if the question is within business scope."""
    neo4j_schema = await get_cached_schema()

    class GuardrailsOutput(BaseModel):
        decision: Literal["continue", "end"]
        reason: str

    user_ctx = await build_user_context_block(
        state.get("user_role"),
        state.get("accessible_enterprises"),
    )

    model = get_chat_model(temperature=0)
    base = GUARDRAILS_SYSTEM_PROMPT.format(
        scope_description=SCOPE_DESCRIPTION,
        neo4j_schema=neo4j_schema,
    )
    prompt = f"{base}\n\n{user_ctx}" if user_ctx else base
    messages = [
        {"role": "system", "content": prompt},
        *to_openai_messages(state["messages"][-6:]),
    ]
    result = await structured_output(model, GuardrailsOutput, messages)

    if result.decision == "end":
        return {
            "guardrails_decision": "end",
            "messages": [
                AIMessage(content=(
                    "您的问题看起来不在本平台的数据范围内。本平台仅覆盖**地区A化工/石油化工/光伏/煤炭"
                    "行业**的企业碳排放、能源、污染物与履约数据。\n\n"
                    "您可以试着问：\n"
                    "- 我过去总共排放了多少？\n"
                    "- 我们公司 2023 年 Scope1 排放是多少？\n"
                    "- 2019 到 2026 我公司 Scope2 怎么变化的？\n"
                    "- 配额履约缺口是多少？"
                ))
            ],
        }
    return {"guardrails_decision": "continue"}


async def guide_user_for_info(state: AdditionalInfoSubState) -> dict:
    """Analyze what info is missing and guide the user to provide it."""
    model = get_chat_model(temperature=0.3)

    user_ctx = await build_user_context_block(
        state.get("user_role"),
        state.get("accessible_enterprises"),
    )

    system_prompt = """\
你是地区A化工/石油化工/光伏/煤炭行业碳合规客服的信息补充助手。用户的问题缺少关键信息，请礼貌地引导用户补充。

## 引导策略
- 优先利用已知信息：如果"当前用户身份"中已有绑定企业，则**默认企业已知**，不要再问"哪家企业"
- 一次只追问一项最关键的缺失信息（年份 / 指标 / Scope 范围）
- 给出具体可选项（例如"2019 / 2020 / 2021 / 2022 / 2023"），降低用户心智负担
- 如果绑定企业 + 用户语句已经足够触发查询（如"我去年的 Scope1"或"我累计排放"），就明确告知用户"我可以直接帮您查询"，并给出确认按钮式的措辞

## 回复风格
- 专业、克制，避免营销腔；不要使用"亲～"、emoji 滥用
- 末尾给一个示例的完整提问，帮助用户掌握查询模板
"""
    if user_ctx:
        system_prompt += "\n" + user_ctx

    messages = [
        {"role": "system", "content": system_prompt},
        *to_openai_messages(state["messages"][-6:]),
    ]

    response = await safe_ainvoke(model, messages)
    return {"messages": [AIMessage(content=strip_thinking(response.content))]}


# ---------- Routing ----------

def additional_route(state: AdditionalInfoSubState) -> str:
    if state.get("guardrails_decision") == "end":
        return END
    return "guide_user_for_info"


# ---------- Build sub-graph ----------

def build_additional_info_subgraph() -> StateGraph:
    workflow = StateGraph(AdditionalInfoSubState)

    workflow.add_node("guardrails", additional_guardrails)
    workflow.add_node("guide_user_for_info", guide_user_for_info)

    workflow.add_edge(START, "guardrails")
    workflow.add_conditional_edges("guardrails", additional_route, {
        "guide_user_for_info": "guide_user_for_info",
        END: END,
    })
    workflow.add_edge("guide_user_for_info", END)

    return workflow.compile()


additional_query_subgraph = build_additional_info_subgraph()
