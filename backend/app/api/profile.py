"""User profile endpoints — read profile, update fields, upload avatar."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.auth import get_current_user
from app.models.database import UserProfile, get_async_session_factory
from app.models.schemas import (
    TokenPayload,
    UserProfileResponse,
    UserProfileUpdateRequest,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])
logger = logging.getLogger(__name__)

_AVATAR_DIR = Path(__file__).parent.parent.parent / "uploads" / "avatars"
_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
_AVATAR_MAX_SIZE = 5 * 1024 * 1024  # 5 MB
_AVATAR_ALLOWED = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _user_to_response(u: UserProfile) -> UserProfileResponse:
    return UserProfileResponse(
        user_id=u.user_id,
        username=u.username,
        nickname=u.nickname,
        member_level=u.member_level or "normal",
        total_orders=u.total_orders or 0,
        total_spend=float(u.total_spend or 0),
        favorite_categories=list(u.favorite_categories or []),
        role=u.role or "user",
        accessible_enterprises=list(u.accessible_enterprises or []),
        avatar_url=u.avatar_url,
        bio=u.bio,
        phone=u.phone,
    )


@router.get("", response_model=UserProfileResponse)
async def get_profile(user: TokenPayload = Depends(get_current_user)):
    """Return the current user's full profile."""
    factory = get_async_session_factory()
    async with factory() as session:
        u = await session.get(UserProfile, user.user_id)
    if not u:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return _user_to_response(u)


@router.put("", response_model=UserProfileResponse)
async def update_profile(
    req: UserProfileUpdateRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """Update current user's editable profile fields (nickname / bio / phone)."""
    factory = get_async_session_factory()
    async with factory() as session:
        u = await session.get(UserProfile, user.user_id)
        if not u:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        if req.nickname is not None:
            u.nickname = req.nickname
        if req.bio is not None:
            u.bio = req.bio
        if req.phone is not None:
            u.phone = req.phone
        await session.commit()
        await session.refresh(u)
    return _user_to_response(u)


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: TokenPayload = Depends(get_current_user),
):
    """Upload an avatar image and persist its URL on the user's profile."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _AVATAR_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的图片格式：{suffix}（允许：{', '.join(sorted(_AVATAR_ALLOWED))}）",
        )

    body = await file.read()
    if len(body) > _AVATAR_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"头像不能超过 {_AVATAR_MAX_SIZE // 1024 // 1024} MB",
        )

    filename = f"{user.user_id}_{uuid.uuid4().hex[:8]}{suffix}"
    target = _AVATAR_DIR / filename
    target.write_bytes(body)

    avatar_url = f"/static/avatars/{filename}"

    factory = get_async_session_factory()
    async with factory() as session:
        u = await session.get(UserProfile, user.user_id)
        if not u:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        # Optionally remove the previous avatar file
        old = (u.avatar_url or "").lstrip("/")
        if old.startswith("static/avatars/"):
            old_path = _AVATAR_DIR.parent.parent / old
            try:
                if old_path.exists() and old_path.is_file():
                    old_path.unlink()
            except Exception as e:
                logger.warning("Failed to remove old avatar %s: %s", old_path, e)
        u.avatar_url = avatar_url
        await session.commit()

    return {"avatar_url": avatar_url}
