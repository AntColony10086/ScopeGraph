"""Output audit and PII redaction for assistant replies.

Two responsibilities live here:

1. :func:`redact_pii` — coarse-grained, regex-driven masking of phone
   numbers, email addresses, and Chinese-style ID-like sequences. The
   replacements are deliberately conservative (placeholder tokens rather
   than partial reveals) because the redacted text may end up in logs.

2. :func:`audit_output` — multi-tenant data-leakage check. Operators in
   this system are authorised to see only their own enterprise data.
   The audit walks the assistant's draft reply, looks up every company
   name from the Neo4j seed catalogue (``data/neo4j/customers.csv``),
   and flags any whose ``CustomerID`` is *not* in the caller's
   ``allowed_enterprises`` list. ``["*"]`` is the admin sentinel and
   bypasses the scan.

Failure modes are deliberately fail-open with a logged warning: missing or
empty CSV must not brick chat. Real production deployments back this up
with row-level checks at the data-layer; the audit here is the *belt* part
of belt-and-braces.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from threading import Lock
from typing import Final, Pattern


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------


# Order matters: more specific/restrictive patterns first. The Chinese
# 18-digit ID regex must run before the generic phone regex, otherwise the
# leading 17 digits would be partially consumed by the phone matcher.
_ID_PATTERN: Final[Pattern[str]] = re.compile(r"\d{17}[\dXx]")
_EMAIL_PATTERN: Final[Pattern[str]] = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_MOBILE_PATTERN: Final[Pattern[str]] = re.compile(r"1[3-9]\d{9}")
# Landline-style separator pattern (e.g. ``010-12345678``). Bounded by word
# boundaries to avoid mis-matching inside longer numeric strings already
# rewritten by the ID/mobile matchers above.
_LANDLINE_PATTERN: Final[Pattern[str]] = re.compile(r"\b\d{3,4}-\d{7,8}\b")

_PHONE_REPLACEMENT: Final[str] = "***-********"
_EMAIL_REPLACEMENT: Final[str] = "<email>"
_ID_REPLACEMENT: Final[str] = "<id>"


def redact_pii(text: str) -> str:
    """Mask phones, emails, and Chinese-style ID numbers in *text*.

    The function is intentionally non-locale-aware: it matches on shape
    rather than checksums, so callers should treat its output as
    **best-effort masking**, not regulatory-grade redaction.

    Args:
        text: Text to scan and redact.

    Returns:
        A new string with sensitive numeric/email shapes replaced by
        placeholder tokens. Non-``str`` inputs are coerced to string first
        so the function never raises at the boundary.

    Examples:
        >>> redact_pii("call me at 13800138000")
        'call me at ***-********'
        >>> redact_pii("write to alice@example.com")
        'write to <email>'
    """
    if not isinstance(text, str):
        text = "" if text is None else str(text)

    # IDs first so they're not eaten by the phone regex.
    text = _ID_PATTERN.sub(_ID_REPLACEMENT, text)
    text = _EMAIL_PATTERN.sub(_EMAIL_REPLACEMENT, text)
    text = _MOBILE_PATTERN.sub(_PHONE_REPLACEMENT, text)
    text = _LANDLINE_PATTERN.sub(_PHONE_REPLACEMENT, text)
    return text


# ---------------------------------------------------------------------------
# Cross-tenant data-leakage audit
# ---------------------------------------------------------------------------


_ADMIN_SENTINEL: Final[str] = "*"

# Resolve the customers.csv path relative to the package layout:
#   .../backend/app/safety/output_audit.py  →  parents[3] = repo root
_CUSTOMERS_CSV_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "data" / "neo4j" / "customers.csv"
)

_company_index: dict[str, str] | None = None
_company_index_lock: Lock = Lock()


def _load_company_index() -> dict[str, str]:
    """Load and memoise the ``CompanyName → CustomerID`` mapping.

    The CSV is assumed to have a header row containing at minimum the
    columns ``CustomerID`` and ``CompanyName``; extra columns are ignored.
    Loads are cached for the lifetime of the process and protected by a
    lock so concurrent first-callers don't race on file I/O.

    Returns:
        Mapping from canonical company name (whitespace-stripped) to its
        customer-ID. An empty dict on missing/empty CSV — the caller is
        responsible for treating "no index" as fail-open.
    """
    global _company_index

    if _company_index is not None:
        return _company_index

    with _company_index_lock:
        # Double-checked lock: another thread may have populated while we
        # were blocked on lock acquisition.
        if _company_index is not None:
            return _company_index

        index: dict[str, str] = {}

        if not _CUSTOMERS_CSV_PATH.is_file():
            logger.warning(
                "output_audit: customers.csv not found at %s; "
                "cross-tenant leak audit will be a no-op.",
                _CUSTOMERS_CSV_PATH,
            )
            _company_index = index
            return index

        try:
            with _CUSTOMERS_CSV_PATH.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    name = (row.get("CompanyName") or "").strip()
                    cid = (row.get("CustomerID") or "").strip()
                    if name and cid:
                        index[name] = cid
        except OSError as exc:
            # Unreadable file (permissions, mid-deploy swap, etc.): log
            # loudly and fall back to empty index — never break chat.
            logger.warning(
                "output_audit: failed to read %s (%s); cross-tenant leak "
                "audit will be a no-op.",
                _CUSTOMERS_CSV_PATH,
                exc,
            )

        if not index:
            logger.warning(
                "output_audit: customers.csv at %s yielded no company "
                "entries; cross-tenant leak audit will be a no-op.",
                _CUSTOMERS_CSV_PATH,
            )

        _company_index = index
        return index


def _is_admin(allowed_enterprises: list[str]) -> bool:
    """Return ``True`` when *allowed_enterprises* is the admin wildcard.

    A list containing exactly the single string ``"*"`` denotes the admin
    bypass per the public contract.
    """
    return len(allowed_enterprises) == 1 and allowed_enterprises[0] == _ADMIN_SENTINEL


def audit_output(
    text: str, allowed_enterprises: list[str]
) -> tuple[bool, list[str]]:
    """Detect cross-tenant company-name leaks in *text*.

    Walks every ``CompanyName`` from the customers catalogue and checks
    whether it appears in *text*. If a name is found whose ``CustomerID``
    is not in the caller's allow-list, it is reported as a leak.

    Args:
        text: Assistant output to audit.
        allowed_enterprises: List of ``CustomerID`` strings the caller is
            authorised to see, or the singleton ``["*"]`` for admin.

    Returns:
        Tuple ``(safe, leaks)``:

        * ``safe`` — ``True`` iff no disallowed CustomerIDs were detected.
        * ``leaks`` — list of leaked CustomerIDs, in catalogue order.

    Notes:
        Fails open on missing/unreadable CSV: the function returns
        ``(True, [])`` and emits a warning so a misconfigured environment
        does not silently brick the chat path.
    """
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    if not isinstance(allowed_enterprises, list):
        # Boundary defence: empty list is the safest interpretation of
        # "no permissions declared".
        allowed_enterprises = []

    # Admin bypass: skip the scan entirely.
    if _is_admin(allowed_enterprises):
        return True, []

    index = _load_company_index()
    if not index:
        # Fail-open path with the warning already logged inside the loader.
        return True, []

    allowed_set = set(allowed_enterprises)
    leaks: list[str] = []
    for name, cid in index.items():
        if cid in allowed_set:
            continue
        if name and name in text:
            leaks.append(cid)

    return len(leaks) == 0, leaks


__all__ = ["audit_output", "redact_pii"]
