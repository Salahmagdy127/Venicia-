"""الترقيم المتسلسل — Gap-free document numbering.

الأرقام لازم تكون متصلة ومتكرّرش: ده مطلب محاسبي وضريبي مش رفاهية.
بيتعمل بقفل صف العدّاد جوه المعاملة، فمحاولتين في نفس اللحظة بياخدوا رقمين
مختلفين ولا واحد فيهم بيتكرّر.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.billing import DocumentSequence

#: الافتراضات لكل نوع مستند: (البادئة، طول الترقيم)
DEFAULTS: dict[str, tuple[str, int]] = {
    "RESERVATION": ("VNC", 6),
    "FOLIO": ("F", 6),
    "PAYMENT": ("P", 6),
    "INVOICE": ("INV", 6),
    "RECEIPT": ("RCT", 6),
    "CREDIT_NOTE": ("CN", 6),
    "POS_ORDER": ("O", 6),
    "KOT": ("K", 5),
    "SHIFT": ("SH", 5),
    "TICKET": ("MT", 5),
    "PURCHASE": ("PO", 5),
}


def next_number(
    db: Session,
    property_id: int,
    doc_type: str,
    *,
    on_date: date | None = None,
    prefix: str | None = None,
) -> str:
    """بيرجّع الرقم التالي بالصيغة ``PREFIX-YYYY-000123``."""
    today = on_date or date.today()
    year = today.year
    default_prefix, padding = DEFAULTS.get(doc_type, (doc_type[:3].upper(), 6))
    use_prefix = prefix or default_prefix

    stmt = select(DocumentSequence).where(
        DocumentSequence.property_id == property_id,
        DocumentSequence.doc_type == doc_type,
        DocumentSequence.period_year == year,
    )
    # القفل بيمنع إن اتنين ياخدوا نفس الرقم (SQLite بيسلسل الكتابة أصلاً)
    if db.bind is not None and db.bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()

    row = db.execute(stmt).scalar_one_or_none()

    if row is None:
        row = DocumentSequence(
            property_id=property_id,
            doc_type=doc_type,
            prefix=use_prefix,
            period_year=year,
            last_number=0,
            padding=padding,
        )
        db.add(row)
        db.flush()

    row.last_number += 1
    db.flush()

    # البادئة اللي المنادي طلبها بتكسب: أوردرات المطعم والبار بتاخد بادئة
    # المنفذ بتاعها، لكن العدّاد يفضل واحد فمفيش رقمين متكررين بين المنافذ.
    label = prefix or row.prefix or default_prefix
    return f"{label}-{year}-{row.last_number:0{row.padding}d}"
