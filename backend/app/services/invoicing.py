"""الفاتورة الإلكترونية — E-invoice generation and ETA submission.

التصميم بيفصل **إنشاء المستند** عن **إرساله**، وده مش تفصيلة تقنية:

النزيل واقف قدام الكاشير عايز إيصاله. لو ربطنا الطباعة بالإرسال لمنظومة
الضرائب، أول انقطاع نت بيوقّف الكاشير كله. فالمستند بيتولّد ويتطبع فوراً
برقمه المتسلسل، والإرسال بيدخل طابور بإعادة محاولة بتباعد متزايد.

المستند نفسه **مش بيتعدّل ولا بيتمسح أبداً**. الغلط بيتصحّح بإشعار خصم
(credit note) بيشاور على الأصل — ده مطلب قانوني، وكمان بيخلّي كل تصحيح
له أثر مكتوب.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing import Invoice, InvoiceLine
from app.models.enums import CREDIT_CHARGE_KINDS, EtaStatus, InvoiceType
from app.models.folio import Folio, FolioLine
from app.models.guests import Guest
from app.models.organization import Property
from app.models.pos import Outlet, PosOrder, PosOrderLine
from app.models.security import User
from app.services import sequences
from app.services.pricing import money

#: تباعد إعادة المحاولة بالدقايق — بيوسّع عشان مانضربش المنظومة وهي واقعة
RETRY_BACKOFF = [2, 10, 30, 120, 360]
MAX_RETRIES = len(RETRY_BACKOFF)
#: كود الضريبة في المنظومة: T1 قيمة مضافة · V009 النسبة العامة
TAX_TYPE = "T1"
TAX_SUBTYPE = "V009"


class InvoiceError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "invoice_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════ إصدار المستند
def _customer_from_guest(guest: Guest | None) -> dict[str, str | None]:
    """بيانات المستلم لقطة وقت الإصدار — مش مرجع للنزيل.

    لو النزيل غيّر عنوانه بعد سنة، الفاتورة القديمة لازم تفضل زي ما
    اتطبعت. عشان كده بننسخ مش بنربط.
    """
    if guest is None:
        return {"name": "نزيل نقدي", "tax_number": None, "national_id": None, "address": None,
                "type": "P"}
    return {
        "name": guest.full_name,
        "tax_number": getattr(guest, "tax_number", None),
        "national_id": guest.id_number,
        "address": guest.city,
        # B لو عنده رقم ضريبي (شركة) · P فرد · F أجنبي
        "type": "B" if getattr(guest, "tax_number", None) else
                ("F" if (guest.nationality or "EG") != "EG" else "P"),
    }


def _qr(invoice: Invoice, prop: Property) -> str:
    """حمولة الـ QR المطبوع — بتخلّي أي حد يتحقق من الفاتورة من موبايله."""
    parts = [
        prop.tax_registration_number or "—",
        invoice.number,
        invoice.issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        f"{invoice.grand_total:.2f}",
        f"{invoice.tax_total:.2f}",
        invoice.eta_uuid or "",
    ]
    return "|".join(parts)


def _finalize(db: Session, invoice: Invoice, prop: Property) -> Invoice:
    """بيحسب الإجماليات من السطور ويجهّز المستند للطابور."""
    lines = invoice.lines
    invoice.subtotal = money(sum((l.sales_total for l in lines), Decimal("0")))
    invoice.discount_total = money(sum((l.discount_amount for l in lines), Decimal("0")))
    invoice.service_charge_total = money(
        sum((l.service_charge_amount for l in lines), Decimal("0"))
    )
    invoice.tax_total = money(sum((l.tax_amount for l in lines), Decimal("0")))
    invoice.grand_total = money(sum((l.total for l in lines), Decimal("0")))

    # المعرّف الداخلي لازم يبقى فريد على مستوى المنشأة عمر المنظومة كلها
    invoice.eta_internal_id = f"{prop.code}-{invoice.number}"
    invoice.eta_hash_key = hashlib.sha256(
        f"{invoice.eta_internal_id}|{invoice.grand_total}|{invoice.issued_at.isoformat()}".encode()
    ).hexdigest()[:40]
    invoice.qr_payload = _qr(invoice, prop)

    if prop.eta_enabled:
        invoice.eta_status = EtaStatus.QUEUED
        invoice.eta_next_retry_at = utcnow()
    else:
        # المنظومة مش مفعّلة — المستند صالح للطباعة وبس، والحالة بتقول كده
        invoice.eta_status = EtaStatus.DRAFT

    db.flush()
    return invoice


def issue_for_folio(
    db: Session,
    folio_id: int,
    *,
    user: User | None = None,
    business_date: date | None = None,
) -> Invoice:
    """فاتورة إقامة من حساب النزيل — سطر لكل بند مرحّل غير ملغي."""
    folio = db.get(Folio, folio_id)
    if folio is None:
        raise InvoiceError("الحساب غير موجود", "Folio not found", "not_found")

    existing = db.execute(
        select(Invoice).where(
            Invoice.folio_id == folio_id, Invoice.is_cancelled.is_(False)
        ).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        raise InvoiceError(
            f"الحساب ده متعملّه فاتورة بالفعل ({existing.number})",
            f"This folio already has invoice {existing.number}",
            "already_issued",
        )

    prop = db.get(Property, folio.property_id)
    guest = db.get(Guest, folio.guest_id) if folio.guest_id else None
    customer = _customer_from_guest(guest)

    charges = list(
        db.execute(
            select(FolioLine)
            .where(
                FolioLine.folio_id == folio_id,
                FolioLine.is_void.is_(False),
                # الدفعات مش بنود فاتورة — الفاتورة بتقول «عليك كام»
                # مش «دفعت كام». الاتنين بيتخلطوا كتير وبيطلّعوا فاتورة بصفر.
                FolioLine.charge_kind.not_in(list(CREDIT_CHARGE_KINDS)),
            )
            .order_by(FolioLine.id)
        ).scalars().all()
    )
    if not charges:
        raise InvoiceError(
            "مفيش بنود على الحساب", "The folio has no chargeable lines", "empty"
        )

    invoice = Invoice(
        number=sequences.next_number(db, prop.id, "INVOICE"),
        property_id=prop.id,
        invoice_type=InvoiceType.INVOICE,
        business_date=business_date or date.today(),
        issued_at=utcnow(),
        folio_id=folio.id,
        reservation_id=folio.reservation_id,
        customer_name=customer["name"],
        customer_tax_number=customer["tax_number"],
        customer_national_id=customer["national_id"],
        customer_address=customer["address"],
        customer_type=customer["type"],
        currency=prop.currency,
        issued_by_user_id=user.id if user else None,
    )
    db.add(invoice)
    db.flush()

    for index, line in enumerate(charges, start=1):
        invoice.lines.append(
            InvoiceLine(
                invoice_id=invoice.id,
                line_number=index,
                description_ar=line.description_ar,
                description_en=line.description_en,
                item_code=line.charge_kind,
                unit_type="EA",
                quantity=line.quantity,
                unit_price=line.unit_price,
                sales_total=money(line.quantity * line.unit_price),
                discount_amount=Decimal("0"),
                net_total=line.amount,
                tax_type=TAX_TYPE,
                tax_subtype=TAX_SUBTYPE,
                tax_percent=prop.vat_percent,
                tax_amount=line.tax_amount,
                service_charge_amount=line.service_charge_amount,
                total=line.total_amount,
            )
        )
    return _finalize(db, invoice, prop)


def issue_for_pos_order(
    db: Session, order_id: int, *, user: User | None = None
) -> Invoice:
    """إيصال إلكتروني من أوردر كاشير."""
    order = db.get(PosOrder, order_id)
    if order is None:
        raise InvoiceError("الأوردر غير موجود", "Order not found", "not_found")
    if order.is_void:
        raise InvoiceError("الأوردر ملغي", "Order is void", "void")

    existing = db.execute(
        select(Invoice).where(
            Invoice.pos_order_id == order_id, Invoice.is_cancelled.is_(False)
        ).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        raise InvoiceError(
            f"الأوردر ده متعملّه إيصال بالفعل ({existing.number})",
            f"This order already has receipt {existing.number}",
            "already_issued",
        )

    prop = db.get(Property, order.property_id)
    outlet = db.get(Outlet, order.outlet_id)
    guest = None
    if order.folio_id:
        folio = db.get(Folio, order.folio_id)
        if folio and folio.guest_id:
            guest = db.get(Guest, folio.guest_id)
    customer = _customer_from_guest(guest)

    lines = list(
        db.execute(
            select(PosOrderLine)
            .where(PosOrderLine.order_id == order_id, PosOrderLine.is_void.is_(False))
            .order_by(PosOrderLine.id)
        ).scalars().all()
    )
    if not lines:
        raise InvoiceError("مفيش أصناف على الأوردر", "Order has no lines", "empty")

    invoice = Invoice(
        number=sequences.next_number(db, prop.id, "RECEIPT"),
        property_id=prop.id,
        invoice_type=InvoiceType.RECEIPT,
        business_date=order.business_date,
        issued_at=utcnow(),
        pos_order_id=order.id,
        folio_id=order.folio_id,
        outlet_id=order.outlet_id,
        customer_name=customer["name"],
        customer_tax_number=customer["tax_number"],
        customer_national_id=customer["national_id"],
        customer_type=customer["type"],
        currency=prop.currency,
        issued_by_user_id=user.id if user else None,
    )
    db.add(invoice)
    db.flush()

    # الخدمة والضريبة على الأوردر إجمالية، فبنوزّعها على السطور بالتناسب
    subtotal = money(sum((l.line_total for l in lines), Decimal("0")))
    service_rate = (
        (order.service_charge_total / subtotal) if subtotal > 0 else Decimal("0")
    )
    tax_rate = (order.tax_total / subtotal) if subtotal > 0 else Decimal("0")

    for index, line in enumerate(lines, start=1):
        service = money(line.line_total * service_rate)
        tax = money(line.line_total * tax_rate)
        invoice.lines.append(
            InvoiceLine(
                invoice_id=invoice.id,
                line_number=index,
                description_ar=line.item_name_ar,
                description_en=line.item_name_en,
                item_code=str(line.menu_item_id) if line.menu_item_id else None,
                unit_type="EA",
                quantity=line.quantity,
                unit_price=line.unit_price,
                sales_total=line.line_total,
                discount_amount=Decimal("0"),
                net_total=line.line_total,
                tax_type=TAX_TYPE,
                tax_subtype=TAX_SUBTYPE,
                tax_percent=outlet.vat_percent if outlet else prop.vat_percent,
                tax_amount=tax,
                service_charge_amount=service,
                total=money(line.line_total + service + tax),
            )
        )
    return _finalize(db, invoice, prop)


# ═══════════════════════════════════════════════════ الإلغاء بالتصحيح
def cancel(
    db: Session, invoice_id: int, reason: str, *, user: User | None = None
) -> Invoice:
    """إشعار خصم بيعكس الفاتورة — الأصل بيفضل موجود زي ما هو.

    مفيش تعديل ولا مسح للمستند الضريبي: ده مطلب قانوني، وكمان بيخلّي
    كل تصحيح له ورقة تشاور على اللي اتصحّح.
    """
    original = db.get(Invoice, invoice_id)
    if original is None:
        raise InvoiceError("الفاتورة غير موجودة", "Invoice not found", "not_found")
    if original.is_cancelled:
        raise InvoiceError("الفاتورة ملغية بالفعل", "Already cancelled", "already_cancelled")
    if not reason.strip():
        raise InvoiceError("سبب الإلغاء مطلوب", "A reason is required", "no_reason")

    prop = db.get(Property, original.property_id)
    note = Invoice(
        number=sequences.next_number(db, prop.id, "CREDIT_NOTE"),
        property_id=prop.id,
        invoice_type=InvoiceType.CREDIT_NOTE,
        business_date=date.today(),
        issued_at=utcnow(),
        folio_id=original.folio_id,
        pos_order_id=original.pos_order_id,
        reservation_id=original.reservation_id,
        outlet_id=original.outlet_id,
        customer_name=original.customer_name,
        customer_tax_number=original.customer_tax_number,
        customer_national_id=original.customer_national_id,
        customer_address=original.customer_address,
        customer_type=original.customer_type,
        currency=original.currency,
        credit_note_for_invoice_id=original.id,
        issued_by_user_id=user.id if user else None,
    )
    db.add(note)
    db.flush()

    for line in original.lines:
        note.lines.append(
            InvoiceLine(
                invoice_id=note.id,
                line_number=line.line_number,
                description_ar=line.description_ar,
                description_en=line.description_en,
                item_code=line.item_code,
                unit_type=line.unit_type,
                quantity=-line.quantity,
                unit_price=line.unit_price,
                sales_total=-line.sales_total,
                discount_amount=-line.discount_amount,
                net_total=-line.net_total,
                tax_type=line.tax_type,
                tax_subtype=line.tax_subtype,
                tax_percent=line.tax_percent,
                tax_amount=-line.tax_amount,
                service_charge_amount=-line.service_charge_amount,
                total=-line.total,
            )
        )

    original.is_cancelled = True
    original.cancelled_at = utcnow()
    original.cancellation_reason = reason.strip()[:500]
    return _finalize(db, note, prop)


# ═══════════════════════════════════════════════ الإرسال للمنظومة
def _simulated_submit(invoice: Invoice, document: dict) -> dict:
    """ناقل محاكاة لمنظومة الضرائب.

    مكانه هنا مقصود: ده الملف الوحيد اللي بيتغيّر لما تتوقّع الاعتماد
    مع المصلحة. الطابور وإعادة المحاولة وأرقام المستندات شغّالين زي ما هم.
    """
    return {
        "accepted": True,
        "uuid": hashlib.sha256(invoice.eta_internal_id.encode()).hexdigest()[:64],
        "longId": hashlib.sha256(
            f"{invoice.eta_internal_id}-long".encode()
        ).hexdigest()[:64].upper(),
        "submissionUUID": hashlib.sha256(
            f"{invoice.eta_internal_id}-sub".encode()
        ).hexdigest()[:32],
        "simulated": True,
    }


#: نقطة تبديل الناقل — بتتغيّر في الاختبارات وعند الربط الحقيقي
SUBMIT: Callable[[Invoice, dict], dict] = _simulated_submit


def build_document(db: Session, invoice: Invoice) -> dict:
    """المستند بصيغة المنظومة — بيتبني وقت الإرسال من آخر حالة."""
    prop = db.get(Property, invoice.property_id)
    return {
        "issuer": {
            "type": "B",
            "id": prop.tax_registration_number,
            "name": prop.legal_name or prop.name_ar,
            "address": {
                "country": prop.country,
                "governate": prop.city,
                "regionCity": prop.city,
                "street": prop.address,
                "branchId": prop.eta_branch_code or "0",
            },
        },
        "receiver": {
            "type": invoice.customer_type,
            "id": invoice.customer_tax_number or invoice.customer_national_id,
            "name": invoice.customer_name,
        },
        "documentType": invoice.invoice_type,
        "documentTypeVersion": "1.0",
        "dateTimeIssued": invoice.issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "taxpayerActivityCode": prop.eta_activity_code or "5510",
        "internalID": invoice.eta_internal_id,
        "totalSalesAmount": float(invoice.subtotal),
        "totalDiscountAmount": float(invoice.discount_total),
        "netAmount": float(invoice.subtotal - invoice.discount_total),
        "totalAmount": float(invoice.grand_total),
        "taxTotals": [{"taxType": TAX_TYPE, "amount": float(invoice.tax_total)}],
        "invoiceLines": [
            {
                "description": line.description_ar,
                "itemType": line.item_code_type,
                "itemCode": line.item_code or "0000",
                "unitType": line.unit_type,
                "quantity": float(line.quantity),
                "unitValue": {"currencySold": invoice.currency,
                              "amountEGP": float(line.unit_price)},
                "salesTotal": float(line.sales_total),
                "netTotal": float(line.net_total),
                "total": float(line.total),
                "taxableItems": [
                    {
                        "taxType": line.tax_type,
                        "subType": line.tax_subtype,
                        "rate": float(line.tax_percent),
                        "amount": float(line.tax_amount),
                    }
                ],
            }
            for line in invoice.lines
        ],
    }


@dataclass(slots=True)
class SubmitResult:
    accepted: int = 0
    failed: int = 0
    skipped: int = 0


def submit_pending(db: Session, property_id: int, *, limit: int = 100) -> SubmitResult:
    """طابور الإرسال — اللي حان وقته بس، بإعادة محاولة متباعدة."""
    result = SubmitResult()
    now = utcnow()

    prop = db.get(Property, property_id)
    if prop is None or not prop.eta_enabled:
        return result

    rows = list(
        db.execute(
            select(Invoice)
            .where(
                Invoice.property_id == property_id,
                Invoice.eta_status.in_([EtaStatus.QUEUED, EtaStatus.FAILED]),
                Invoice.eta_next_retry_at.is_not(None),
                Invoice.eta_next_retry_at <= now,
            )
            .order_by(Invoice.id)
            .limit(limit)
        ).scalars().all()
    )

    for invoice in rows:
        document = build_document(db, invoice)
        invoice.eta_submitted_at = now
        try:
            answer = SUBMIT(invoice, document)
            if not answer.get("accepted"):
                raise InvoiceError(
                    answer.get("error_ar") or "المنظومة رفضت المستند",
                    answer.get("error_en") or "Rejected by ETA",
                )
            invoice.eta_status = EtaStatus.VALID
            invoice.eta_uuid = answer.get("uuid")
            invoice.eta_long_id = answer.get("longId")
            invoice.eta_submission_uuid = answer.get("submissionUUID")
            invoice.eta_accepted_at = now
            invoice.eta_error_message = None
            invoice.eta_next_retry_at = None
            invoice.eta_response = answer
            invoice.qr_payload = _qr(invoice, prop)
            result.accepted += 1
        except Exception as exc:
            invoice.eta_retry_count += 1
            invoice.eta_error_message = str(exc)[:2000]
            if invoice.eta_retry_count >= MAX_RETRIES:
                invoice.eta_status = EtaStatus.REJECTED
                invoice.eta_next_retry_at = None
            else:
                invoice.eta_status = EtaStatus.FAILED
                minutes = RETRY_BACKOFF[min(invoice.eta_retry_count - 1, MAX_RETRIES - 1)]
                invoice.eta_next_retry_at = now + timedelta(minutes=minutes)
            result.failed += 1

    db.flush()
    return result


def retry_rejected(db: Session, property_id: int) -> int:
    """رجّع المرفوض للطابور — بعد ما السبب يتصلّح."""
    rows = db.execute(
        select(Invoice).where(
            Invoice.property_id == property_id,
            Invoice.eta_status == EtaStatus.REJECTED,
        )
    ).scalars().all()
    for invoice in rows:
        invoice.eta_status = EtaStatus.QUEUED
        invoice.eta_retry_count = 0
        invoice.eta_error_message = None
        invoice.eta_next_retry_at = utcnow()
    if rows:
        db.flush()
    return len(rows)


# ═══════════════════════════════════════════════════════════ الحالة
@dataclass(slots=True)
class InvoiceStats:
    total: int
    accepted: int
    pending: int
    failed: int
    rejected: int
    draft: int
    cancelled: int
    today_total: Decimal
    today_tax: Decimal


def stats(db: Session, property_id: int, *, on_date: date | None = None) -> InvoiceStats:
    day = on_date or date.today()
    counts = dict(
        db.execute(
            select(Invoice.eta_status, func.count(Invoice.id))
            .where(Invoice.property_id == property_id)
            .group_by(Invoice.eta_status)
        ).all()
    )
    total = db.execute(
        select(func.count(Invoice.id)).where(Invoice.property_id == property_id)
    ).scalar_one()
    cancelled = db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.property_id == property_id, Invoice.is_cancelled.is_(True)
        )
    ).scalar_one()
    today = db.execute(
        select(
            func.coalesce(func.sum(Invoice.grand_total), 0),
            func.coalesce(func.sum(Invoice.tax_total), 0),
        ).where(Invoice.property_id == property_id, Invoice.business_date == day)
    ).one()

    return InvoiceStats(
        total=int(total),
        accepted=int(counts.get(EtaStatus.VALID, 0)),
        pending=int(counts.get(EtaStatus.QUEUED, 0)),
        failed=int(counts.get(EtaStatus.FAILED, 0)),
        rejected=int(counts.get(EtaStatus.REJECTED, 0)),
        draft=int(counts.get(EtaStatus.DRAFT, 0)),
        cancelled=int(cancelled),
        today_total=money(Decimal(str(today[0]))),
        today_tax=money(Decimal(str(today[1]))),
    )
