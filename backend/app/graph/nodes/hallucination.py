"""Output-side hallucination & grounding check.

Runs as the final node before END so every assistant turn is screened.
The check is two-staged:

1. A fast rule-engine pass — PII masking via :func:`redact_pii` plus a
   cross-tenant leak check via :func:`audit_output`. If the reply mentions
   companies the current caller is not authorised to see, we replace the
   reply with a neutral apology rather than letting the leak through.
2. A light LLM call that compares the (possibly redacted) reply to
   whatever evidence accumulated in shared state — Cypher rows, retrieved
   passages, ``agent_results.data`` blobs. If the reply contains claims
   not supported by the evidence we *append* a transparent warning line
   rather than rewriting the answer wholesale — the user keeps the
   substantive reply, but is alerted to the suspect spans.

The node is fault-tolerant: any exception in the LLM stage degrades to
"return the rule-audited message unchanged".
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.models.state import SharedState as AgentState
from app.safety.output_audit import audit_output, redact_pii
from app.utils.llm import get_light_model, structured_output

_log = logging.getLogger(__name__)

_WARNING_PREFIX = "⚠️ 提示：以下表述可能未在证据中得到支持："
_MAX_EVIDENCE_CHARS = 4000
_MAX_REPLY_CHARS = 3000


class HallucinationVerdict(BaseModel):
    """Structured output of the grounding judge.

    Attributes:
        grounded: ``True`` when every quantitative / factual claim in the
            reply is plausibly supported by the evidence.
        suspicious_claims: Short Chinese excerpts (<= 80 chars each) of any
            spans the judge cannot back up. Empty when ``grounded`` is True.
    """

    grounded: bool = Field(..., description="Reply is fully grounded in evidence.")
    suspicious_claims: list[str] = Field(
        default_factory=list,
        description="Spans of the reply that cannot be backed up.",
    )


def _gather_evidence(state: AgentState) -> str:
    """Concatenate any evidence the upstream nodes left in state.

    Looks at common keys produced by the graphrag / additional-info
    subgraphs: cypher results, agent_results data blobs, and the rolling
    context summary. Returns at most :data:`_MAX_EVIDENCE_CHARS` characters.
    """
    chunks: list[str] = []

    summary = state.get("context_summary")
    if summary:
        chunks.append(f"[summary]\n{summary}")

    agent_results = state.get("agent_results") or {}
    for agent_name, payload in agent_results.items():
        if not isinstance(payload, dict):
            continue
        data = payload.get("data") or {}
        if not data:
            continue
        try:
            rendered = json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            rendered = str(data)
        chunks.append(f"[{agent_name}]\n{rendered}")

    cypher_results = cast(Any, state).get("cypher_results")
    if cypher_results:
        try:
            chunks.append(
                f"[cypher_results]\n{json.dumps(cypher_results, ensure_ascii=False, default=str)}"
            )
        except (TypeError, ValueError):
            chunks.append(f"[cypher_results]\n{cypher_results}")

    blob = "\n\n".join(c for c in chunks if c).strip()
    if len(blob) > _MAX_EVIDENCE_CHARS:
        blob = blob[:_MAX_EVIDENCE_CHARS] + "\n... (evidence truncated)"
    return blob


async def _judge_grounded(reply: str, evidence: str) -> HallucinationVerdict:
    """Ask a light model whether the reply is grounded in the evidence."""
    if not evidence:
        # No evidence means we have nothing to verify against. Be permissive.
        return HallucinationVerdict(grounded=True, suspicious_claims=[])

    model = get_light_model(temperature=0, max_tokens=512)
    system_prompt = (
        "你是一个回答-证据一致性判官。你将得到 1) 助手对用户的回答；"
        "2) 系统在回答之前检索到的证据。任务：判断回答中的所有数值与事实主张"
        "是否在证据中都能得到支持。\n"
        "若每一条主张都受支持，输出 grounded=true、suspicious_claims=[]；\n"
        "若存在无法支持的具体主张，输出 grounded=false，并把那些原文片段（≤80字）"
        "放进 suspicious_claims。不要把口语化、非事实性句子（如客套语、行动建议）"
        "标记为可疑。"
    )
    user_prompt = (
        f"## 证据\n{evidence}\n\n## 助手回答\n{reply[:_MAX_REPLY_CHARS]}\n"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    default = HallucinationVerdict(grounded=True, suspicious_claims=[])
    try:
        verdict = await structured_output(
            model,
            HallucinationVerdict,
            messages,
            default=default,
        )
    except Exception as e:  # noqa: BLE001 — we never want this node to crash
        _log.warning("hallucination judge failed, treating as grounded: %s", e)
        return default
    return cast(HallucinationVerdict, verdict)


def _augment_with_warning(reply: str, suspicious: list[str]) -> str:
    """Append a transparent warning line listing suspect spans."""
    cleaned = [s.strip() for s in suspicious if s and s.strip()]
    if not cleaned:
        return reply
    snippet_join = "; ".join(cleaned[:5])
    return f"{reply}\n\n{_WARNING_PREFIX} {snippet_join}"


def _rule_audit(reply: str, allowed_enterprises: list[str]) -> tuple[str, bool, bool]:
    """Run PII redaction and cross-tenant leak detection.

    Returns:
        ``(text, blocked, modified)``:

        * ``text`` — the (possibly redacted) reply,
        * ``blocked`` — ``True`` if a hard violation was detected and the
          caller should substitute a neutral fallback,
        * ``modified`` — ``True`` if redaction changed the text.
    """
    redacted = redact_pii(reply)
    safe, leaks = audit_output(redacted, allowed_enterprises)
    blocked = not safe
    modified = redacted != reply
    if blocked:
        _log.warning("hallucination_check: cross-tenant leak detected: %s", leaks)
    return redacted, blocked, modified


async def hallucination_check_node(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Audit the latest assistant reply and return a state update.

    Pipeline:

    1. Locate the most recent :class:`AIMessage`. If absent, return ``{}``.
    2. Rule-engine audit (PII redaction + cross-tenant leak detection).
       Hard violations are replaced with a neutral fallback.
    3. LLM grounding judge against accumulated evidence. If not grounded,
       append a warning line to the rule-audited reply.

    Args:
        state: Shared graph state.
        config: LangGraph runnable config (unused).

    Returns:
        ``{}`` when nothing needs to change, otherwise a dict carrying a
        new :class:`AIMessage` in ``messages``.
    """
    del config

    messages = state.get("messages") or []
    if not messages:
        return {}

    last = messages[-1]
    if not isinstance(last, AIMessage):
        return {}

    reply_text = last.content if isinstance(last.content, str) else str(last.content)
    if not reply_text.strip():
        return {}

    allowed = state.get("accessible_enterprises") or []
    working_text, blocked, modified = _rule_audit(reply_text, list(allowed))

    if blocked:
        return {
            "messages": [
                AIMessage(
                    content=(
                        "抱歉，您当前权限范围内不包含上述企业的数据，"
                        "建议您联系管理员开通对应权限或换一个查询对象。"
                    )
                )
            ]
        }

    evidence = _gather_evidence(state)
    verdict = await _judge_grounded(working_text, evidence)

    if not verdict.grounded and verdict.suspicious_claims:
        warned = _augment_with_warning(working_text, verdict.suspicious_claims)
        _log.info(
            "hallucination warning appended (%d suspicious claims)",
            len(verdict.suspicious_claims),
        )
        return {"messages": [AIMessage(content=warned)]}

    if modified:
        return {"messages": [AIMessage(content=working_text)]}

    return {}
