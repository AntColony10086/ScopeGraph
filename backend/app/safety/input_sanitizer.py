"""Input sanitizer for the chat pipeline.

This module screens user-supplied text for two broad classes of abuse before
the message is forwarded to the LLM-driven graph:

1. **Prompt-injection** — phrases that try to override the system prompt or
   re-cast the assistant's role (e.g. ``ignore previous instructions``,
   ``you are now``).
2. **System-prompt-leak attempts** — probes that try to extract internal
   configuration such as the system prompt, the API key, or the LLM's
   own bootstrapping instructions, including a few common Chinese
   formulations (``初始指令``, ``提示词``).

The sanitizer is intentionally non-destructive: when a violation is detected
the offending text is *not* rewritten or stripped — only the violation name is
recorded so that downstream policy code (graph routing, audit log, fallback
prompts) can decide what to do. The single transformation we *do* perform is
length-capping at :data:`MAX_INPUT_LEN`, which both prevents resource abuse
and ensures the prompt template stays within the model context budget.

Public surface:
    * :func:`sanitize` — main entry point.
    * :data:`MAX_INPUT_LEN` — character cap applied before LLM dispatch.
"""

from __future__ import annotations

import re
from typing import Final, Pattern


MAX_INPUT_LEN: Final[int] = 4000
"""Maximum number of characters forwarded to the LLM per user turn.

Any input longer than this is truncated to this length and tagged with the
``length_exceeded`` violation, so observability layers can flag abusive or
runaway clients.
"""


def _compile(pattern: str) -> Pattern[str]:
    """Compile *pattern* with case-insensitive + Unicode flags.

    Centralising flag selection keeps the rule table below readable and makes
    it trivial to extend with new patterns later.

    Args:
        pattern: Raw regex source.

    Returns:
        A compiled :class:`re.Pattern` honouring case-insensitive matching.
    """
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


# Each entry is (rule_name, compiled_regex). Order matters for readability
# only — every rule is evaluated independently and all triggered names are
# returned.
_RULES: Final[tuple[tuple[str, Pattern[str]], ...]] = (
    # --- Prompt-injection family -------------------------------------------------
    (
        "prompt_injection_ignore_previous",
        _compile(r"ignore\s+(?:the\s+|all\s+)?(?:previous|prior|above)\s+instructions?"),
    ),
    (
        "prompt_injection_disregard_above",
        _compile(r"disregard\s+(?:the\s+|all\s+)?(?:above|previous|prior)"),
    ),
    (
        "prompt_injection_forget_everything",
        _compile(r"forget\s+(?:everything|all)\s+(?:before|above|prior)"),
    ),
    (
        "prompt_injection_role_override",
        _compile(r"\byou\s+are\s+now\b"),
    ),
    (
        "prompt_injection_act_as",
        _compile(r"\b(?:act|behave|pretend)\s+as\b.*?(?:dan|jailbreak|developer\s+mode)"),
    ),
    (
        "prompt_injection_new_instructions",
        _compile(r"\bnew\s+instructions?\s*:"),
    ),
    # --- System-prompt-leak family ----------------------------------------------
    (
        "system_prompt_leak_en",
        _compile(r"\bsystem\s+prompt\b"),
    ),
    (
        "system_prompt_leak_message",
        _compile(r"\bsystem\s+message\b"),
    ),
    (
        "system_prompt_leak_apikey",
        _compile(r"\bapi[\s_-]?key\b"),
    ),
    (
        "system_prompt_leak_zh_initial",
        _compile(r"初始指令"),
    ),
    (
        "system_prompt_leak_zh_prompt",
        _compile(r"提示词"),
    ),
)


def sanitize(text: str) -> tuple[str, list[str]]:
    """Screen *text* for prompt-injection and system-prompt-leak attempts.

    The function is **purely defensive**: it never raises on malformed input.
    Non-``str`` arguments are coerced via :class:`str`, so a caller that
    accidentally passes ``None`` or a number gets a clean empty-violations
    result instead of a 500.

    Args:
        text: Raw user-supplied message to inspect.

    Returns:
        A 2-tuple ``(cleaned_text, violations)``:

        * ``cleaned_text`` — the input as-is, except truncated to
          :data:`MAX_INPUT_LEN` characters when oversized.
        * ``violations`` — list of triggered rule names (deduplicated, in
          declaration order). Empty when the input is clean.

    Examples:
        >>> sanitize("hello there")
        ('hello there', [])
        >>> _, names = sanitize("Please ignore previous instructions")
        >>> "prompt_injection_ignore_previous" in names
        True
    """
    if not isinstance(text, str):
        # Boundary defence: callers from FastAPI/JSON layers occasionally
        # forward ``None`` or other primitives; coerce instead of raising.
        text = "" if text is None else str(text)

    violations: list[str] = []

    # Length check first so the cap also applies to inputs that happen to
    # match nothing else.
    if len(text) > MAX_INPUT_LEN:
        text = text[:MAX_INPUT_LEN]
        violations.append("length_exceeded")

    for name, pattern in _RULES:
        if pattern.search(text):
            violations.append(name)

    return text, violations


def sanitize_input(text: str) -> dict:
    """Dict-shaped façade over :func:`sanitize`.

    Older API call sites (notably ``app.api.chat``) read the result as a
    mapping with ``safe`` / ``cleaned`` / ``violations`` keys. This thin
    wrapper preserves that contract without forcing the underlying
    rule-engine into a specific return shape.

    Args:
        text: Raw user-supplied message.

    Returns:
        ``{"safe": bool, "cleaned": str, "violations": list[str]}`` —
        ``safe`` is ``True`` when no rules fired.
    """
    cleaned, violations = sanitize(text)
    return {
        "safe": not violations,
        "cleaned": cleaned,
        "text": cleaned,
        "violations": violations,
    }


__all__ = ["MAX_INPUT_LEN", "sanitize", "sanitize_input"]
