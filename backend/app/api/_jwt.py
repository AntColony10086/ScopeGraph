"""JWT and password helpers — single source of truth for auth crypto.

The rest of the codebase should never reach for ``jwt`` or ``bcrypt`` directly;
go through the helpers here so we can swap libraries (e.g. argon2id, ed25519)
without touching the API surface.

All helpers are pure functions: they read configuration via
:func:`app.config.get_settings` but do **not** read or mutate global state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Final

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from app.config import get_settings

# bcrypt's reference cost is 12 — fast enough for an HTTP request, slow enough
# to make rainbow-table attacks impractical on a stolen hash.
_BCRYPT_ROUNDS: Final[int] = 12


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password``.

    The salt is generated per-call, so calling this twice with the same input
    produces different ciphertexts (verified via :func:`verify_password`).
    """
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    digest = bcrypt.hashpw(password.encode("utf-8"), salt)
    return digest.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time comparison of ``password`` against a bcrypt hash.

    Returns ``False`` (rather than raising) for malformed hashes — the caller
    should treat any failure as an authentication miss.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT encode / decode
# --------------------------------------------------------------------------- #
def encode_token(
    user_id: str,
    role: str,
    accessible_enterprises: list[str],
    *,
    username: str | None = None,
) -> str:
    """Encode a signed JWT for an authenticated user.

    Args:
        user_id: Stable internal user id.
        role: Role string — ``"user"`` or ``"admin"``.
        accessible_enterprises: List of CustomerIDs the user may read; ``["*"]``
            means "all enterprises" (admin or super-tenant).
        username: Optional display username; preserved across refresh.

    Returns:
        A serialized JWT string. Expiry comes from
        :attr:`Settings.jwt_expire_hours`.
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "role": role,
        "accessible_enterprises": list(accessible_enterprises),
        "exp": expire,
    }
    if username is not None:
        payload["username"] = username
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT.

    Returns the payload as a dict, or ``None`` if the token is malformed,
    expired, or signed with the wrong key. Caller MUST treat ``None`` as
    "not authenticated".
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except InvalidTokenError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload
