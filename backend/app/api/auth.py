"""Authentication endpoints — login, register, refresh, current-user.

This module is the HTTP shell. All token / password crypto lives in
:mod:`app.api._jwt`; persistence lives in :mod:`app.models.database`.

Endpoints
---------

* ``POST /api/auth/login`` — exchange username + password for a JWT.
* ``POST /api/auth/register`` — create a development account (disable in prod).
* ``POST /api/auth/refresh`` — exchange a still-valid token for a fresh one.
* ``GET  /api/auth/me`` — echo the caller's token claims (cheap auth-check).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.api._jwt import decode_token, encode_token, hash_password, verify_password
from app.models.database import UserProfile, get_async_session_factory
from app.models.schemas import LoginRequest, LoginResponse, TokenPayload

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()

# User-facing strings — kept here so they can be swapped for i18n later.
_MSG_BAD_CREDENTIALS: Final[str] = "用户名或密码错误"
_MSG_TOKEN_INVALID: Final[str] = "无效或过期的Token，请重新登录"
_MSG_TOKEN_REFRESH_FAILED: Final[str] = "Token 刷新失败，请重新登录"
_MSG_USERNAME_TAKEN: Final[str] = "用户名已存在"
_MSG_ADMIN_ONLY: Final[str] = "该操作需要管理员权限"


def _claims_from_payload(payload: dict[str, Any]) -> TokenPayload:
    """Map a decoded JWT dict into the strongly-typed :class:`TokenPayload`."""
    return TokenPayload(
        user_id=payload["user_id"],
        username=payload.get("username", ""),
        role=payload.get("role", "user"),
        accessible_enterprises=payload.get("accessible_enterprises", []) or [],
        exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Dependencies / helpers used by this and other routers
# --------------------------------------------------------------------------- #
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    """Dependency: decode the bearer token and return its claims."""
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_MSG_TOKEN_INVALID,
        )
    try:
        return _claims_from_payload(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_MSG_TOKEN_INVALID,
        ) from exc


def is_admin(user: TokenPayload) -> bool:
    """True if the user's role is exactly ``admin``."""
    return (user.role or "user") == "admin"


def can_access_enterprise(user: TokenPayload, customer_id: str) -> bool:
    """Whether the authenticated user is allowed to view data for ``customer_id``.

    Rules: admins see everything; the wildcard ``"*"`` in the per-user allowlist
    grants access to all enterprises (super-tenant); otherwise, exact match.
    """
    if is_admin(user):
        return True
    allowed = user.accessible_enterprises or []
    if "*" in allowed:
        return True
    return customer_id in allowed


def require_admin(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
    """Dependency: 403 unless the caller is an admin."""
    if not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_MSG_ADMIN_ONLY,
        )
    return user


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    """Authenticate a user and return a fresh JWT plus profile snapshot."""
    factory = get_async_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.username == req.username)
        )
        user = result.scalar_one_or_none()

    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_MSG_BAD_CREDENTIALS,
        )

    accessible = list(user.accessible_enterprises or [])
    role = user.role or "user"
    token = encode_token(
        user_id=user.user_id,
        role=role,
        accessible_enterprises=accessible,
        username=user.username,
    )

    return LoginResponse(
        access_token=token,
        user_id=user.user_id,
        username=user.username,
        nickname=user.nickname,
        avatar_url=user.avatar_url,
        member_level=user.member_level,
        role=role,
        accessible_enterprises=accessible,
    )


@router.post("/register")
async def register(req: LoginRequest) -> dict[str, str]:
    """Register a new user — intended for local dev / demos only."""
    factory = get_async_session_factory()
    async with factory() as session:
        existing = await session.execute(
            select(UserProfile).where(UserProfile.username == req.username)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_MSG_USERNAME_TAKEN,
            )

        user = UserProfile(
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            username=req.username,
            password_hash=hash_password(req.password),
            member_level="normal",
            registered_at=datetime.now(timezone.utc),
        )
        session.add(user)
        await session.commit()

    return {"message": "注册成功", "user_id": user.user_id}


@router.post("/refresh")
async def refresh(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, str]:
    """Exchange a still-valid token for a fresh one.

    The new token preserves all original claims — including the username and
    the per-user enterprise allowlist — so a sliding session never silently
    upgrades or downgrades a user's permissions.
    """
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_MSG_TOKEN_REFRESH_FAILED,
        )

    try:
        new_token = encode_token(
            user_id=payload["user_id"],
            role=payload.get("role", "user"),
            accessible_enterprises=payload.get("accessible_enterprises", []) or [],
            username=payload.get("username"),
        )
    except KeyError as exc:
        # Malformed payload (no user_id) — refuse rather than mint a junk token.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_MSG_TOKEN_REFRESH_FAILED,
        ) from exc

    return {"access_token": new_token, "token_type": "bearer"}


@router.get("/me", response_model=TokenPayload)
async def me(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
    """Return the caller's token claims — handy for client auth-check pings."""
    return user
