"""التشفير والتوكن — Password hashing and JWT issuing/verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

#: ``hold`` توكن سلة الحجز الإلكتروني — عمره قصير ومنفصل عن توكن الدخول
TokenType = Literal["access", "refresh", "hold"]


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        # هاش تالف أو بصيغة قديمة — بيتعامل كمحاولة فاشلة مش استثناء
        return False


def create_token(
    subject: str | int,
    token_type: TokenType = "access",
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    now = datetime.now(timezone.utc)
    if token_type == "access":
        expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    elif token_type == "hold":
        expires = now + timedelta(minutes=settings.BOOKING_HOLD_MINUTES)
    else:
        expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any] | None:
    """بيرجع الحمولة أو ``None`` لو التوكن باطل أو منتهي."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None

    if expected_type and payload.get("typ") != expected_type:
        return None
    return payload
