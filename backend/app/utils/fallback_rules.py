"""FAQ cache and rule-engine fallback for degradation scenarios.

Keyword→response rules covering frequent **meta** queries about the Region A
chemical-industry carbon database. The keys are intentionally specific phrases
(not single ambiguous words like "Scope") so they don't pre-empt data queries
that legitimately should go through the GraphRAG pipeline.
"""

from __future__ import annotations


FALLBACK_RULES: dict[str, str] = {
    # Platform meta
    "数据从哪来": "您好～平台数据来源于生态环境部、自治区生态环境厅、CPCIF（石化联合会）、CQC/CEC 第三方核查报告、上海环交所、全国碳排放权交易市场（中碳登）等渠道～",
    "数据来源是": "您好～平台数据来源于生态环境部、自治区生态环境厅、CPCIF（石化联合会）、CQC/CEC 第三方核查报告、上海环交所、全国碳排放权交易市场（中碳登）等渠道～",
    "数据多久更新": "您好～企业排放与能源数据按年发布，每年 Q1 完成上一年度的 MRV 核查与上报；履约相关数据在配额清缴窗口（年中）后更新～",
    "更新频率": "您好～企业碳数据按年更新，配额履约清缴窗口后会有补充更新～",
    "数据范围": "您好～当前覆盖 2019-2026 共 8 个年度，10 家地区A主力化工企业 + 自治区聚合 + 4 个对标省份 + 4 个产业园～",
    "覆盖年份": "您好～当前数据覆盖 2019、2020、2021、2022、2023、2024、2025、2026 共 8 个年度～",
    "覆盖企业": "您好～目前覆盖 10 家地区A主力化工企业：化工企业A、化工企业B、化工企业C、化工企业D、化工企业E、化工企业F、化工企业G、化工企业H、化工企业I、炼化企业A～",
    "覆盖哪些企业": "您好～目前覆盖 10 家地区A主力化工企业：化工企业A、化工企业B、化工企业C、化工企业D、化工企业E、化工企业F、化工企业G、化工企业H、化工企业I、炼化企业A～",
    "都有哪些企业": "您好～目前覆盖 10 家地区A主力化工企业：化工企业A、化工企业B、化工企业C、化工企业D、化工企业E、化工企业F、化工企业G、化工企业H、化工企业I、炼化企业A～",
    "哪些企业": "您好～目前覆盖 10 家地区A主力化工企业：化工企业A、化工企业B、化工企业C、化工企业D、化工企业E、化工企业F、化工企业G、化工企业H、化工企业I、炼化企业A～",
    "数据涵盖": "您好～涵盖 Scope1/Scope2/Scope3 排放、能源消耗、SO2/NOx/COD 等污染物、配额履约缺口、CCER、绿证、节能投资共 6 大类 35 个指标～",

    # Service meta
    "联系人工": "好的，正在为您转接人工碳合规顾问，请稍等～",
    "转人工": "好的，正在为您转接人工碳合规顾问，请稍等～",
    "营业时间": "您好～AI 助手 24 小时在线，人工碳合规顾问工作时间 9:00-21:00～",
    "服务时间": "您好～AI 助手 24 小时在线，人工碳合规顾问工作时间 9:00-21:00～",
    "怎么收费": "您好～标准查询完全免费；MRV 现场核查、配额履约方案、CCER 项目开发等定制服务按合同约定收费～",
    "收费标准": "您好～标准查询完全免费；MRV 现场核查、配额履约方案、CCER 项目开发等定制服务按合同约定收费～",
    "数据怎么导出": "您好～支持 CSV/Excel/JSON 三种格式导出，结构化字段含 enterprise/year/indicator/value/unit/source～",
    "API 接口": "您好～平台提供 RESTful API，支持按企业/年份/指标过滤，可在个人中心申请 API Key～",
    "怎么获取API": "您好～可在个人中心申请 API Key，按企业/年份/指标过滤调用～",
}


def faq_cache_lookup(message: str) -> str | None:
    """Look up a message in the FAQ cache. Returns response if matched, None otherwise.

    Note: keys are deliberately specific phrases. Single-word knowledge concepts
    (Scope/CCER/MRV/CBAM/电石法...) are NOT in the FAQ cache — they go through
    GraphRAG so they can use the methodology Markdown knowledge base or the
    structured graph data.
    """
    for keyword, response in FALLBACK_RULES.items():
        if keyword in message:
            return response
    return None


def rule_engine_fallback(user_message: str) -> str | None:
    """Rule engine fallback for degradation scenarios (LLM unavailable)."""
    return faq_cache_lookup(user_message)
