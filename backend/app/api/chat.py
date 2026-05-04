"""Chat endpoint — main entry point for user conversations.

Supports both REST (POST) and SSE streaming (true token-level via
``astream_events``). All SSE-frame formatting is delegated to
:func:`app.api._sse.sse`; whole-turn retry logic is in
:func:`_run_with_retry` so the streaming and non-streaming code paths share
a single, testable retry shape.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Final
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.api._jwt import decode_token
from app.api._sse import sse
from app.api.auth import get_current_user
from app.graph.main_graph import build_main_graph
from app.memory.session_lifecycle import post_session_process
from app.memory.session_manager import (
    append_message,
    cache_data,
    generate_session_id,
    get_cached_data,
    get_messages,
    get_session_auth,
    init_session,
)
from app.memory.user_profile import get_user_profile
from app.models.schemas import ChatRequest, ChatResponse, ConfirmActionRequest, TokenPayload
from app.safety.input_sanitizer import sanitize_input

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)

# Lazy-initialized graph — building it eagerly imports the whole LangGraph
# stack at module-load time, which slows server cold-start to a crawl.
_graph: Any = None
_UPLOAD_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "uploads"
_MAX_UPLOAD_BYTES: Final[int] = 10 * 1024 * 1024
_ALLOWED_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx", ".xlsx", ".csv", ".txt"}
)
_IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset({".png", ".jpg", ".jpeg", ".webp"})

# Only stream the *answer-generating* nodes — intermediate steps (router,
# guardrails, etc.) emit token noise the user shouldn't see.
_STREAM_NODES: Final[frozenset[str]] = frozenset(
    {"respond_to_general_query", "generate_answer", "summarize_result"}
)

# Friendly status labels surfaced to the UI as the graph progresses.
_NODE_STATUS: Final[dict[str, str]] = {
    "analyze_and_route_query": "分析问题中...",
    "guardrails": "安全检查中...",
    "planner": "规划查询策略...",
    "tool_selection": "选择查询工具...",
    "cypher_query": "查询数据库...",
    "graphrag_search": "搜索知识库...",
    "vector_search": "检索文档...",
    "generate_answer": "生成回答中...",
    "respond_to_general_query": "生成回答中...",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _extract_inline_attachment(text: str) -> tuple[str, dict[str, str | None] | None]:
    """Parse inline upload tokens like ``[文件: /uploads/xxx.pdf]`` from user text."""
    match = re.search(r"\[\s*[^:\]]+:\s*(/uploads/[^\]\s]+)\s*\]", text)
    if not match:
        return text, None

    upload_url = match.group(1)
    local_path = _UPLOAD_DIR / Path(upload_url).name
    if not local_path.exists():
        # Keep the message unchanged if the file doesn't exist locally.
        return text, None

    suffix = local_path.suffix.lower()
    is_image = suffix in _IMAGE_SUFFIXES
    cleaned = re.sub(r"\[\s*[^:\]]+:\s*/uploads/[^\]\s]+\s*\]\s*", "", text).strip()
    return cleaned or text, {
        "image_path": str(local_path) if is_image else None,
        "file_path": None if is_image else str(local_path),
    }


def get_graph() -> Any:
    """Return the (lazily-built) main LangGraph graph."""
    global _graph
    if _graph is None:
        _graph = build_main_graph()
    return _graph


async def _run_with_retry(
    coro_factory: Callable[[int], Awaitable[Any]],
    attempts: int,
    *,
    label: str = "graph",
) -> tuple[Any, Exception | None]:
    """Invoke ``coro_factory(attempt_idx)`` up to ``attempts`` times.

    Args:
        coro_factory: A *factory* that returns a fresh awaitable per attempt.
            Must be a factory (not a coroutine object) because awaitables
            are single-use.
        attempts: Total attempts; backoff is ``1.2 * (i + 1)`` seconds.
        label: Used only in log lines.

    Returns:
        ``(result, None)`` on success, or ``(None, last_exception)`` if every
        attempt failed.
    """
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            result = await coro_factory(i)
            return result, None
        except Exception as exc:  # noqa: BLE001 — we deliberately retry anything
            last_err = exc
            logger.warning(
                "%s attempt %d/%d failed: %s: %s",
                label, i + 1, attempts, type(exc).__name__, str(exc)[:200],
            )
            if i < attempts - 1:
                await asyncio.sleep(1.2 * (i + 1))
    return None, last_err


async def _prepare_session(
    message: str,
    session_id: str | None,
    user: TokenPayload,
    attachment_config: dict[str, str | None] | None = None,
) -> tuple[str, dict[str, Any], list[BaseMessage], dict[str, Any] | None]:
    """Sanitize, init session, load history, build the LangGraph initial state."""
    normalized_message, inline_attachment = _extract_inline_attachment(message)
    effective_attachment = attachment_config or inline_attachment

    sanitized = sanitize_input(normalized_message)
    if not sanitized["safe"]:
        raise HTTPException(status_code=400, detail="消息内容不合规，请修改后重试")

    session_id = session_id or generate_session_id()
    auth = await get_session_auth(session_id)
    profile = await get_user_profile(user.user_id)
    if not auth:
        await init_session(
            session_id,
            user.user_id,
            {
                "username": user.username,
                "member_level": profile.get("member_level", "normal") if profile else "normal",
            },
        )

    # Reuse the most recent attachment if the follow-up message has none.
    if not effective_attachment:
        cached_attachment = await get_cached_data(session_id, "last_attachment")
        if isinstance(cached_attachment, dict) and (
            cached_attachment.get("image_path") or cached_attachment.get("file_path")
        ):
            effective_attachment = cached_attachment
            logger.info("[chat] reused last_attachment from session cache: %s", session_id)

    past_messages = await get_messages(session_id, last_n=10)
    history: list[BaseMessage] = []
    for msg in past_messages:
        if msg["role"] == "human":
            history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "ai":
            history.append(AIMessage(content=msg["content"]))

    await append_message(session_id, "human", sanitized["text"])

    if effective_attachment:
        await cache_data(session_id, "last_attachment", effective_attachment)
        logger.info("[chat] cached last_attachment for session: %s", session_id)
    history.append(HumanMessage(content=sanitized["text"]))

    initial_state: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user.user_id,
        "auth_level": "authenticated",
        "user_role": user.role or "user",
        "accessible_enterprises": list(user.accessible_enterprises or []),
        "messages": history,
        "context_summary": None,
        "turn_count": 0,
        "user_profile": profile,
        "router": {},
        "current_intents": [],
        "execution_plan": None,
        "agent_results": {},
        "pending_confirmation": None,
        "order_cache": {},
        "product_cache": {},
        "escalation_flag": False,
        "escalation_reason": None,
        "sentiment_score": 0.0,
        "consecutive_dissatisfied": 0,
        "config": effective_attachment or None,
    }

    return session_id, initial_state, history, profile


def _fallback_reply(message: str, last_err: Exception | None, attempts: int) -> tuple[str, bool]:
    """Build the user-visible reply when every retry has failed.

    Returns ``(reply, escalate)`` — ``escalate`` is True if no rule-engine
    fallback fired, signalling we should hand off to a human.
    """
    from app.utils.fallback_rules import rule_engine_fallback

    fallback = rule_engine_fallback(message)
    if fallback:
        return fallback, False

    err_type = type(last_err).__name__ if last_err else "Unknown"
    err_msg = str(last_err)[:300] if last_err else ""
    reply = (
        f"上游 LLM 调用失败（{err_type}），已自动重试 {attempts} 次仍失败。\n"
        f"```\n{err_msg}\n```"
    )
    return reply, True


# --------------------------------------------------------------------------- #
# REST endpoint
# --------------------------------------------------------------------------- #
@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: TokenPayload = Depends(get_current_user),
) -> ChatResponse:
    """Process a chat message and return the AI response in a single shot."""
    attachment_config: dict[str, str | None] = {
        key: value
        for key, value in {
            "image_path": req.image_path,
            "file_path": req.file_path,
        }.items()
        if value
    }

    session_id, initial_state, history, _profile = await _prepare_session(
        req.message,
        req.session_id,
        user,
        attachment_config=attachment_config or None,
    )

    graph = get_graph()

    async def _attempt(_idx: int) -> Any:
        return await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": session_id}},
        )

    result, last_err = await _run_with_retry(_attempt, attempts=3, label="Graph")

    if result is None:
        logger.error("Graph execution error after retries: %s", last_err, exc_info=True)
        reply, escalate = _fallback_reply(req.message, last_err, attempts=3)
        return ChatResponse(session_id=session_id, reply=reply, escalation=escalate)

    messages = result.get("messages", [])
    reply = messages[-1].content if messages else "我没太理解你的意思，可以再说一遍吗？"

    await append_message(session_id, "ai", reply)

    escalation = result.get("escalation_flag", False)
    pending = result.get("pending_confirmation")

    asyncio.create_task(
        post_session_process(
            session_id=session_id,
            user_id=user.user_id,
            turn_count=len(history),
            escalated=escalation,
        )
    )

    return ChatResponse(
        session_id=session_id,
        reply=reply,
        intent=result.get("router", {}).get("type"),
        need_confirmation=pending is not None,
        confirmation_summary=pending.get("summary") if pending else None,
        escalation=escalation,
    )


# --------------------------------------------------------------------------- #
# SSE streaming endpoint
# --------------------------------------------------------------------------- #
@router.get("/stream")
async def chat_stream(
    message: str,
    session_id: str | None = None,
    token: str | None = None,
) -> StreamingResponse:
    """SSE streaming endpoint with true token-level streaming."""
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证Token")

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="无效或过期的Token")
    try:
        user = TokenPayload(
            user_id=payload["user_id"],
            username=payload.get("username", ""),
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="无效或过期的Token") from exc

    async def event_generator() -> AsyncIterator[str]:
        try:
            sid, initial_state, history, _profile = await _prepare_session(
                message, session_id, user
            )
        except HTTPException as e:
            yield sse("error", e.detail)
            yield sse("done", "")
            return

        yield sse("session", sid)
        yield sse("thinking", "正在思考...")

        graph = get_graph()
        full_reply = ""
        last_err: Exception | None = None
        stream_attempts = 3

        for attempt in range(stream_attempts):
            full_reply = ""
            last_node = ""
            try:
                async for event in graph.astream_events(
                    initial_state,
                    config={"configurable": {"thread_id": f"{sid}_{attempt}"}},
                    version="v2",
                ):
                    kind = event["event"]
                    node = event.get("metadata", {}).get("langgraph_node", "")

                    if kind == "on_chain_start" and node and node != last_node:
                        last_node = node
                        if node in _NODE_STATUS:
                            yield sse("status", _NODE_STATUS[node])

                    if kind == "on_chat_model_stream" and node in _STREAM_NODES:
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            full_reply += chunk.content
                            yield sse("token", chunk.content)
                # Stream finished cleanly — exit retry loop.
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning(
                    "Stream attempt %d/%d failed: %s: %s",
                    attempt + 1, stream_attempts, type(exc).__name__, str(exc)[:200],
                )
                if attempt < stream_attempts - 1:
                    yield sse(
                        "status",
                        f"上游瞬时异常，正在重试（{attempt + 2}/{stream_attempts}）...",
                    )
                    await asyncio.sleep(1.2 * (attempt + 1))

        # If streaming failed altogether, try a non-streaming graph call twice.
        if not full_reply:
            async def _fallback(idx: int) -> Any:
                return await graph.ainvoke(
                    initial_state,
                    config={"configurable": {"thread_id": f"{sid}_fb_{idx}"}},
                )

            result, last_err = await _run_with_retry(
                _fallback, attempts=2, label="Non-stream fallback"
            )
            if result is not None:
                msgs = result.get("messages", [])
                full_reply = (
                    msgs[-1].content if msgs else "我没太理解你的意思，可以再说一遍吗？"
                )
                yield sse("message", full_reply)

        # Last resort: surface a deterministic rule-engine reply or the error.
        if not full_reply:
            full_reply, _escalate = _fallback_reply(message, last_err, attempts=5)
            yield sse("message", full_reply)

        await append_message(sid, "ai", full_reply)
        asyncio.create_task(
            post_session_process(
                session_id=sid,
                user_id=user.user_id,
                turn_count=len(history),
            )
        )

        yield sse("done", "")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Tier-2 confirmation
# --------------------------------------------------------------------------- #
@router.post("/confirm")
async def confirm_action(
    req: ConfirmActionRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, str]:
    """Handle user confirmation/rejection for Tier-2 operations."""
    is_confirmed: bool | None = req.confirmed
    if is_confirmed is None and req.action is not None:
        is_confirmed = req.action == "confirm"

    if is_confirmed is None:
        raise HTTPException(status_code=400, detail="缺少确认参数，请传 confirmed 或 action")

    if is_confirmed:
        return {"message": "操作已确认，正在执行...", "session_id": req.session_id}
    return {"message": "操作已取消", "session_id": req.session_id}


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, str | None]:
    """Receive a user attachment and return a local-path token for follow-up chat."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件大小不能超过10MB")

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}{suffix}"
    save_path = _UPLOAD_DIR / safe_name
    save_path.write_bytes(content)

    is_image = suffix in _IMAGE_SUFFIXES
    return {
        "message": "上传成功",
        "url": f"/uploads/{safe_name}",
        "image_path": str(save_path) if is_image else None,
        "file_path": None if is_image else str(save_path),
    }
