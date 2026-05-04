"""Shared LLM client factory — centralizes API key, role mapping, and structured output config."""

from __future__ import annotations

import re

from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings

# Reasoning models (e.g. MiniMax-M2.x) emit a <think>...</think> block at the start
# of the assistant content. Strip it for any user-facing free-text reply.
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str | None) -> str:
    if not text:
        return ""
    cleaned = _THINK_RE.sub("", text)
    # Also handle the case where </think> exists without the opening tag
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[-1]
    return cleaned.strip()

# LangChain message type → OpenAI API role
_ROLE_MAP = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "tool",
}


def get_chat_model(temperature: float = 0, max_tokens: int | None = None) -> ChatOpenAI:
    """Create a ChatOpenAI instance pointing at the configured OpenAI-compatible server.

    `timeout=None` disables the per-request timeout — long reasoning-model
    responses (M2.5-highspeed often >60s on hard prompts) won't be cut off.
    `max_retries=5` covers transient 5xx/429 from the upstream provider.
    """
    settings = get_settings()
    kwargs: dict = {
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "api_key": settings.llm_api_key,
        "temperature": temperature,
        "timeout": None,
        "max_retries": 5,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)


def get_light_model(temperature: float = 0.7, max_tokens: int = 256) -> ChatOpenAI:
    """Lighter model for simple tasks. Same upstream server; no timeout."""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.llm_light_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=None,
        max_retries=5,
    )


def to_openai_messages(messages: list[AnyMessage]) -> list[dict]:
    """Convert LangChain messages → OpenAI dicts with strict alternation.

    MiniMax (and several other OpenAI-compatible providers) reject requests
    with consecutive `assistant` messages or empty `content`. LangGraph state
    can accumulate multiple AI messages in a row when subgraphs append
    intermediate replies, so we:
      1. drop messages with empty content
      2. merge consecutive same-role messages by joining their content
    A single optional system message is allowed at index 0.
    """
    raw: list[dict] = []
    for m in messages:
        role = _ROLE_MAP.get(m.type, "user")
        content = m.content if isinstance(m.content, str) else str(m.content or "")
        if not content.strip():
            continue
        raw.append({"role": role, "content": content})

    if not raw:
        return raw

    merged: list[dict] = [raw[0]]
    for msg in raw[1:]:
        prev = merged[-1]
        if msg["role"] == prev["role"] and msg["role"] != "system":
            prev["content"] = f"{prev['content']}\n\n{msg['content']}"
        else:
            merged.append(msg)

    # If the final message is `assistant`, MiniMax wants the *last* message
    # to be a `user` turn for non-streaming chat. In our pipelines the user
    # turn is always last; this is a defensive trim.
    while merged and merged[-1]["role"] == "assistant":
        merged.pop()
    return merged


def _extract_first_json(text: str) -> str | None:
    """Find the first balanced JSON object/array in text, ignoring code fences."""
    if not text:
        return None
    s = text.strip()
    # Strip markdown code fences if present
    if s.startswith("```"):
        s = s.split("```", 2)[-1]
        if s.startswith("json"):
            s = s[4:]
    # Find first { or [
    starts = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    open_ch = s[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _is_minimax_2013(err: Exception) -> bool:
    """Detect MiniMax's intermittent 'invalid chat setting (2013)' 400."""
    s = str(err)
    return "invalid chat setting" in s or "2013" in s


def _is_retryable(err: Exception) -> bool:
    """Decide if an exception class+message looks worth retrying."""
    msg = str(err).lower()
    if _is_minimax_2013(err):
        return True
    # Transient HTTP/network conditions
    for marker in ("timeout", "connection", "rate limit", "429", "500", "502", "503", "504"):
        if marker in msg:
            return True
    code = str(getattr(err, "status_code", "") or "")
    if code.startswith("5") or code == "429":
        return True
    return False


async def _retry_with_backoff(coro_factory, *, attempts: int = 4, base: float = 0.6):
    """Run an async callable up to `attempts` times with exponential backoff
    on retryable errors. Sleeps 0.6s, 1.2s, 2.4s, 4.8s, 9.6s ..."""
    import asyncio
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            return await coro_factory()
        except Exception as e:
            last_err = e
            if not _is_retryable(e) or i == attempts - 1:
                raise
            await asyncio.sleep(base * (2 ** i))
    raise last_err  # type: ignore[misc]


async def safe_ainvoke(model: ChatOpenAI, messages: list[dict]):
    """Plain-text `model.ainvoke` with retry-on-transient-error.

    Use this in free-text paths (general_chat / file_query / graphrag answer
    generation) so MiniMax 2013 hiccups don't blow up a whole chat turn.
    """
    async def _call():
        return await model.ainvoke(messages)
    return await _retry_with_backoff(_call, attempts=4)


async def structured_output(
    model: ChatOpenAI,
    schema,
    messages: list[dict],
    *,
    default=None,
):
    """Robust structured output for any OpenAI-compatible chat model.

    Strategy (each step retried 3× on retryable errors):
      1. langchain's native `function_calling`
      2. langchain's native `json_schema`
      3. Manual: prompt for raw JSON, strip <think>, parse
      4. Last resort: return `default` if provided, else raise

    Reasoning models (e.g. MiniMax-M2) emit `<think>...</think>` inside content,
    which can break the built-in parsers; the manual path strips them.
    """
    import json
    from pydantic import BaseModel

    last_err: Exception | None = None

    # Try json_schema FIRST — it's a simpler payload (no parallel_tool_calls
    # field) that MiniMax M2.7 accepts more reliably than function_calling.
    for method in ("json_schema", "function_calling"):
        try:
            async def _try_method():
                return await model.with_structured_output(
                    schema, method=method
                ).ainvoke(messages)

            result = await _retry_with_backoff(_try_method, attempts=3)
            if result is not None:
                return result
            last_err = RuntimeError(f"structured_output returned None via {method}")
        except Exception as e:
            last_err = e

    # Manual fallback: ask for JSON in plain text mode (no tools, no response_format)
    try:
        schema_hint = ""
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            except Exception:
                schema_hint = ""

        sys_text = (
            "You must reply with ONLY a valid JSON object that matches this schema. "
            "No prose, no code fences, no <think> tags around it.\n"
            f"Schema: {schema_hint}"
        )
        # MiniMax rejects two consecutive system messages with "invalid chat
        # setting (2013)". If the caller already starts with a system message,
        # merge our JSON-shape directive into it instead of pushing a second.
        if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
            merged_first = {
                "role": "system",
                "content": f"{messages[0].get('content', '')}\n\n{sys_text}",
            }
            prompt_messages = [merged_first, *messages[1:]]
        else:
            prompt_messages = [{"role": "system", "content": sys_text}, *messages]

        async def _manual():
            return await model.ainvoke(prompt_messages)

        raw = await _retry_with_backoff(_manual, attempts=3)
        content = strip_thinking(raw.content if hasattr(raw, "content") else str(raw))
        json_str = _extract_first_json(content) or content
        data = json.loads(json_str)
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema.model_validate(data)
        return data
    except Exception as e:
        last_err = e

    if default is not None:
        import logging
        logging.getLogger(__name__).warning(
            "structured_output exhausted all methods, returning default. last_err=%s",
            last_err,
        )
        return default
    raise last_err if last_err else RuntimeError("structured_output exhausted all methods")
