"""تسجيل الدخول — Authentication endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import create_token, verify_password
from app.models.enums import AuditAction
from app.models.security import AuditLog, LoginAttempt, Role, User
from app.schemas.common import ApiModel

router = APIRouter(prefix="/auth", tags=["المصادقة — Authentication"])

MAX_FAILED = 6
LOCK_MINUTES = 10


class TokenPair(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RoleOut(ApiModel):
    code: str
    name_ar: str
    name_en: str
    max_discount_percent: int


class UserOut(ApiModel):
    id: int
    username: str
    full_name_ar: str
    full_name_en: str
    email: str | None = None
    preferred_locale: str
    is_superuser: bool
    property_id: int | None = None
    roles: list[RoleOut] = []
    permissions: list[str] = []


def _record_attempt(db, username: str, ok: bool, ip: str | None, reason: str | None) -> None:
    db.add(
        LoginAttempt(
            created_at=datetime.now(timezone.utc),
            username=username[:60],
            succeeded=ok,
            ip_address=ip,
            reason=reason,
        )
    )


@router.post("/login", response_model=TokenPair, summary="تسجيل الدخول")
def login(
    db: DbSession,
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenPair:
    ip = request.client.host if request.client else None
    now = datetime.now(timezone.utc)

    user = db.execute(
        select(User).where(User.username == form.username)
    ).scalar_one_or_none()

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"ar": "اسم المستخدم أو كلمة المرور غير صحيحة",
                "en": "Incorrect username or password"},
    )

    if user is None:
        _record_attempt(db, form.username, False, ip, "unknown_user")
        raise invalid

    if user.locked_until and user.locked_until > now:
        _record_attempt(db, form.username, False, ip, "locked")
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={"ar": "الحساب متوقف مؤقتاً بسبب محاولات دخول خاطئة",
                    "en": "Account temporarily locked after failed attempts"},
        )

    if not user.is_active:
        _record_attempt(db, form.username, False, ip, "inactive")
        raise invalid

    if not verify_password(form.password, user.hashed_password):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_login_count = 0
        _record_attempt(db, form.username, False, ip, "bad_password")
        db.add(
            AuditLog(
                created_at=now,
                user_id=user.id,
                username=user.username,
                property_id=user.property_id,
                action=AuditAction.LOGIN_FAILED,
                entity_type="User",
                entity_id=user.id,
                summary_ar="محاولة دخول فاشلة",
                summary_en="Failed login attempt",
                ip_address=ip,
            )
        )
        raise invalid

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    _record_attempt(db, form.username, True, ip, None)
    db.add(
        AuditLog(
            created_at=now,
            user_id=user.id,
            username=user.username,
            property_id=user.property_id,
            action=AuditAction.LOGIN,
            entity_type="User",
            entity_id=user.id,
            summary_ar=f"تسجيل دخول: {user.full_name_ar}",
            summary_en=f"Login: {user.full_name_en}",
            ip_address=ip,
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
    )

    return TokenPair(
        access_token=create_token(user.id, "access", {"usr": user.username}),
        refresh_token=create_token(user.id, "refresh"),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserOut, summary="بيانات المستخدم الحالي")
def me(user: CurrentUser) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        full_name_ar=user.full_name_ar,
        full_name_en=user.full_name_en,
        email=user.email,
        preferred_locale=user.preferred_locale,
        is_superuser=user.is_superuser,
        property_id=user.property_id,
        roles=[RoleOut.model_validate(r) for r in user.roles],
        permissions=sorted(user.permission_codes),
    )
