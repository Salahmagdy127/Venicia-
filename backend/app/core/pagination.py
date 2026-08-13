"""الترقيم بالمؤشر — Keyset (cursor) pagination.

ليه مش ``OFFSET``؟ لأن ``OFFSET 100000`` معناه إن قاعدة البيانات بتقرا مية ألف
صف وترميهم قبل ما توصل للصفحة المطلوبة — فكل ما تتقدّم في القوائم كل ما تبطأ.
الترقيم بالمؤشر بيستخدم آخر مفتاح شفته كنقطة بداية، فالصفحة رقم 5000 بتفتح
بنفس سرعة الصفحة رقم 2.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import Select, asc, desc
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.config import settings

T = TypeVar("T")


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, default=str, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any] | None:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        data = json.loads(raw)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(slots=True)
class Page(Generic[T]):
    items: list[T]
    next_cursor: str | None
    has_more: bool

    def as_dict(self, serializer) -> dict[str, Any]:
        return {
            "items": [serializer(i) for i in self.items],
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
        }


def clamp_limit(limit: int | None) -> int:
    if not limit or limit < 1:
        return settings.DEFAULT_PAGE_SIZE
    return min(limit, settings.MAX_PAGE_SIZE)


def paginate(
    db: Session,
    stmt: Select,
    *,
    key_column: InstrumentedAttribute,
    limit: int | None = None,
    cursor: str | None = None,
    descending: bool = True,
) -> Page:
    """ترقيم بمفتاح واحد متزايد (عادةً المفتاح الأساسي).

    بيجيب ``limit + 1`` صف عشان يعرف لو فيه صفحة بعد كده من غير استعلام ``COUNT``
    تاني على الجدول كله.
    """
    size = clamp_limit(limit)

    if cursor:
        payload = decode_cursor(cursor)
        if payload and "k" in payload:
            last_key = payload["k"]
            stmt = stmt.where(key_column < last_key if descending else key_column > last_key)

    stmt = stmt.order_by(desc(key_column) if descending else asc(key_column)).limit(size + 1)

    rows: Sequence[Any] = db.execute(stmt).scalars().all()

    has_more = len(rows) > size
    items = list(rows[:size])

    next_cursor = None
    if has_more and items:
        next_cursor = encode_cursor({"k": getattr(items[-1], key_column.key)})

    return Page(items=items, next_cursor=next_cursor, has_more=has_more)
