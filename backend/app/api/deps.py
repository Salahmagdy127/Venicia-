"""التبعيات المشتركة — Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import decode_token
from app.db.base import get_db
from app.models.organization import Property
from app.models.security import Role, User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False
)

DbSession = Annotated[Session, Depends(get_db)]


def get_locale(accept_language: str | None = Header(default=None)) -> str:
    """اللغة المطلوبة — بتتحدد من الهيدر وبترجع للعربي افتراضياً."""
    if accept_language:
        primary = accept_language.split(",")[0].strip().lower()[:2]
        if primary in settings.SUPPORTED_LOCALES:
            return primary
    return settings.DEFAULT_LOCALE


Locale = Annotated[str, Depends(get_locale)]


def get_current_user(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"ar": "الرجاء تسجيل الدخول", "en": "Authentication required"},
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error

    payload = decode_token(token, expected_type="access")
    if not payload:
        raise credentials_error

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise credentials_error

    user = db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(Role.permissions))
    ).scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(*permission_codes: str) -> Callable[[User], User]:
    """حارس صلاحيات — بيتحط على المسار مباشرة.

        @router.post("/", dependencies=[Depends(require("reservation.create"))])
    """

    def guard(user: CurrentUser) -> User:
        if any(user.has_permission(code) for code in permission_codes):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "ar": "مالكش صلاحية على العملية دي",
                "en": "You do not have permission for this action",
                "required": list(permission_codes),
            },
        )

    return guard


def get_property(db: DbSession, user: CurrentUser) -> Property:
    """المنشأة اللي المستخدم شغال عليها."""
    if user.property_id:
        prop = db.get(Property, user.property_id)
        if prop:
            return prop
    prop = db.execute(select(Property).order_by(Property.id).limit(1)).scalar_one_or_none()
    if prop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ar": "مفيش منشأة معرّفة", "en": "No property configured"},
        )
    return prop


CurrentProperty = Annotated[Property, Depends(get_property)]
