"""Server-Sent Events helpers.

A single, well-tested formatter for SSE frames. The wire format is fixed by the
HTML5 spec (one ``event:`` line, one ``data:`` line, terminated by a blank
line); centralizing it here means we can change the *encoding* of the data
payload (JSON shape, Unicode normalization) without auditing every handler.
"""

from __future__ import annotations

import json
from typing import Any


def sse(event: str, data: Any) -> str:
    """Format a single SSE message line.

    Args:
        event: Event type (``token``, ``status``, ``error``, ``done``, etc.)
            Anything client-side wants to dispatch on.
        data:  Either a string (passed through) or any JSON-serializable value
            (will be JSON-encoded with ``ensure_ascii=False`` so CJK characters
            stay readable on the wire).

    Returns:
        A complete SSE frame ending with the required double newline. Yield
        the result straight from a ``StreamingResponse`` generator.
    """
    payload = {"event": event, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
