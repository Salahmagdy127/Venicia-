"""سجل التدقيق — Audit trail helper.

كل عملية بتغيّر فلوس أو حالة حجز لازم تسيب أثر. الجدول إضافة فقط ومفيهوش
تعديل ولا حذف — ده اللي بيخلّيه دليل ضد التلاعب.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.enums import AuditAction
from app.models.security import AuditLog, User

#: الحقول اللي ممنوع تتسجّل في الفروق
REDACTED = {"hashed_password", "pos_pin_hash", "id_number", "eta_client_id"}


def _clean(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any] | None:
    """الفروق بين حالتين — بيسجّل المتغيّر بس."""
    if not before and not after:
        return None
    before = before or {}
    after = after or {}
    changes: dict[str, Any] = {}
    for key in set(before) | set(after):
        if key in REDACTED:
            continue
        old, new = before.get(key), after.get(key)
        if old != new:
            changes[key] = {"from": _clean(old), "to": _clean(new)}
    return changes or None


def record(
    db: Session,
    *,
    action: AuditAction,
    entity_type: str,
    entity_id: int | None = None,
    user: User | None = None,
    property_id: int | None = None,
    summary_ar: str | None = None,
    summary_en: str | None = None,
    changes: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    entry = AuditLog(
        created_at=datetime.now(timezone.utc),
        user_id=user.id if user else None,
        username=user.username if user else None,
        property_id=property_id or (user.property_id if user else None),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary_ar=summary_ar,
        summary_en=summary_en,
        changes=changes,
        ip_address=(request.client.host if request and request.client else None),
        user_agent=(request.headers.get("user-agent", "")[:300] or None) if request else None,
    )
    db.add(entry)
    return entry
