"""منطق حساب النزيل — Folio business logic.

قاعدة أساسية: **مفيش تعديل ولا حذف لحركة**. التصحيح بيتم بحركة عكسية،
عشان كشف الحساب يفضل دليل محاسبي كامل.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    CREDIT_CHARGE_KINDS,
    ChargeKind,
    FolioStatus,
    FolioType,
    PaymentMethod,
)
from app.models.folio import Folio, FolioLine, Payment
from app.models.organization import Property
from app.services.pricing import money
from app.services.sequences import next_number


class FolioError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "folio_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_open(db: Session, folio_id: int) -> Folio:
    folio = db.get(Folio, folio_id)
    if folio is None:
        raise FolioError("الحساب غير موجود", "Folio not found", "not_found")
    if folio.status != FolioStatus.OPEN:
        raise FolioError(
            "الحساب مقفول — مينفعش تعديل عليه",
            "The folio is closed and cannot be modified",
            "closed",
        )
    return folio


def recalculate(db: Session, folio: Folio) -> Folio:
    """إعادة حساب أرصدة الحساب من سطوره — مصدر الحقيقة هو السطور."""
    rows = db.execute(
        select(
            FolioLine.charge_kind,
            func.sum(FolioLine.amount),
            func.sum(FolioLine.service_charge_amount),
            func.sum(FolioLine.tax_amount),
        )
        .where(
            FolioLine.folio_id == folio.id,
            FolioLine.is_void.is_(False),
            FolioLine.is_transferred.is_(False),
        )
        .group_by(FolioLine.charge_kind)
    ).all()

    charges = Decimal("0")
    payments = Decimal("0")
    discounts = Decimal("0")
    service = Decimal("0")
    tax = Decimal("0")

    for kind, amount, svc_amount, tax_amount in rows:
        amount = Decimal(str(amount or 0))
        service += Decimal(str(svc_amount or 0))
        tax += Decimal(str(tax_amount or 0))
        if kind in CREDIT_CHARGE_KINDS:
            # المبالغ الدائنة متخزّنة بالسالب
            if kind == ChargeKind.DISCOUNT:
                discounts += abs(amount)
            else:
                payments += abs(amount)
        else:
            charges += amount

    folio.charges_total = money(charges)
    folio.payments_total = money(payments)
    folio.discount_total = money(discounts)
    folio.service_charge_total = money(service)
    folio.tax_total = money(tax)
    folio.balance = money(charges + service + tax - payments - discounts)
    db.flush()
    return folio


# ──────────────────────────────────────────────────────── الترحيل
def post_charge(
    db: Session,
    folio_id: int,
    *,
    charge_kind: ChargeKind,
    description_ar: str,
    description_en: str | None = None,
    amount: Decimal,
    quantity: Decimal = Decimal("1"),
    apply_service_charge: bool = True,
    apply_tax: bool = True,
    outlet_id: int | None = None,
    user_id: int | None = None,
    business_date: date | None = None,
) -> FolioLine:
    """ترحيل حركة على حساب النزيل."""
    folio = _require_open(db, folio_id)
    prop = db.get(Property, folio.property_id)

    if amount == 0:
        raise FolioError("المبلغ لازم يكون مختلف عن صفر", "Amount must be non-zero", "zero_amount")

    is_credit = charge_kind in CREDIT_CHARGE_KINDS
    signed = -abs(amount) if is_credit else abs(amount)

    service = Decimal("0")
    tax = Decimal("0")
    if not is_credit:
        if apply_service_charge:
            service = money(abs(amount) * prop.service_charge_percent / 100)
        if apply_tax:
            taxable = abs(amount) + service if prop.service_charge_before_tax else abs(amount)
            tax = money(taxable * prop.vat_percent / 100)

    line = FolioLine(
        created_at=utcnow(),
        folio_id=folio.id,
        property_id=folio.property_id,
        business_date=business_date or date.today(),
        charge_kind=charge_kind,
        description_ar=description_ar,
        description_en=description_en,
        quantity=quantity,
        unit_price=money(signed / quantity) if quantity else money(signed),
        amount=money(signed),
        service_charge_amount=service,
        tax_amount=tax,
        tax_percent=prop.vat_percent if not is_credit else Decimal("0"),
        total_amount=money(signed + service + tax),
        outlet_id=outlet_id,
        posted_by_user_id=user_id,
    )
    db.add(line)
    db.flush()
    recalculate(db, folio)
    return line


def void_line(
    db: Session, line_id: int, *, reason: str, user_id: int | None = None
) -> FolioLine:
    """إلغاء حركة بحركة عكسية — الأصل بيفضل مكتوب."""
    line = db.get(FolioLine, line_id)
    if line is None:
        raise FolioError("الحركة غير موجودة", "Charge not found", "not_found")
    if line.is_void:
        raise FolioError("الحركة ملغاة بالفعل", "Charge is already void", "already_void")
    if not reason or not reason.strip():
        raise FolioError("لازم تكتب سبب الإلغاء", "A void reason is required", "reason_required")

    folio = _require_open(db, line.folio_id)

    line.is_void = True
    line.void_reason = reason.strip()
    line.voided_by_user_id = user_id

    reversal = FolioLine(
        created_at=utcnow(),
        folio_id=folio.id,
        property_id=folio.property_id,
        business_date=date.today(),
        charge_kind=line.charge_kind,
        description_ar=f"عكس حركة — {line.description_ar}",
        description_en=f"Reversal — {line.description_en or line.description_ar}",
        quantity=line.quantity,
        unit_price=-line.unit_price,
        amount=-line.amount,
        service_charge_amount=-line.service_charge_amount,
        tax_amount=-line.tax_amount,
        tax_percent=line.tax_percent,
        total_amount=-line.total_amount,
        reverses_line_id=line.id,
        is_void=True,  # مستبعدة من الحساب — دورها توثيقي
        posted_by_user_id=user_id,
    )
    db.add(reversal)
    db.flush()
    recalculate(db, folio)
    return line


def transfer_line(
    db: Session, line_id: int, target_folio_id: int, *, user_id: int | None = None
) -> FolioLine:
    """تحويل حركة لحساب تاني — Transfer charges بين الغرف."""
    line = db.get(FolioLine, line_id)
    if line is None:
        raise FolioError("الحركة غير موجودة", "Charge not found", "not_found")
    if line.is_void or line.is_transferred:
        raise FolioError(
            "الحركة ملغاة أو محوّلة بالفعل", "Charge is void or already transferred", "invalid"
        )

    source = _require_open(db, line.folio_id)
    target = _require_open(db, target_folio_id)
    if source.id == target.id:
        raise FolioError(
            "مينفعش تحوّل الحركة لنفس الحساب", "Cannot transfer to the same folio", "same_folio"
        )

    line.is_transferred = True
    line.transferred_to_folio_id = target.id
    line.transferred_by_user_id = user_id

    copy = FolioLine(
        created_at=utcnow(),
        folio_id=target.id,
        property_id=target.property_id,
        business_date=line.business_date,
        charge_kind=line.charge_kind,
        description_ar=f"{line.description_ar} (محوّلة من {source.unit_label or source.code})",
        description_en=(
            f"{line.description_en or line.description_ar} "
            f"(transferred from {source.unit_label or source.code})"
        ),
        quantity=line.quantity,
        unit_price=line.unit_price,
        amount=line.amount,
        service_charge_amount=line.service_charge_amount,
        tax_amount=line.tax_amount,
        tax_percent=line.tax_percent,
        total_amount=line.total_amount,
        outlet_id=line.outlet_id,
        pos_order_id=line.pos_order_id,
        transferred_from_folio_id=source.id,
        transferred_by_user_id=user_id,
        posted_by_user_id=user_id,
    )
    db.add(copy)
    db.flush()
    recalculate(db, source)
    recalculate(db, target)
    return copy


def split_folio(
    db: Session,
    folio_id: int,
    line_ids: list[int],
    *,
    user_id: int | None = None,
    label: str | None = None,
) -> Folio:
    """تقسيم الفاتورة — بينقل السطور المختارة لحساب جديد."""
    source = _require_open(db, folio_id)
    if not line_ids:
        raise FolioError("اختار حركة واحدة على الأقل", "Select at least one charge", "empty")

    new_folio = Folio(
        code=next_number(db, source.property_id, "FOLIO"),
        property_id=source.property_id,
        folio_type=FolioType.GUEST,
        status=FolioStatus.OPEN,
        reservation_id=source.reservation_id,
        reservation_unit_id=source.reservation_unit_id,
        guest_id=source.guest_id,
        unit_label=label or source.unit_label,
        opened_at=utcnow(),
    )
    db.add(new_folio)
    db.flush()

    for line_id in line_ids:
        transfer_line(db, line_id, new_folio.id, user_id=user_id)

    return new_folio


# ──────────────────────────────────────────────────────── التحصيل
def settle(
    db: Session,
    folio_id: int,
    *,
    method: PaymentMethod,
    amount: Decimal,
    user_id: int | None = None,
    reference: str | None = None,
    shift_id: int | None = None,
) -> Payment:
    """تحصيل دفعة على الحساب."""
    folio = _require_open(db, folio_id)
    if amount <= 0:
        raise FolioError("المبلغ لازم يكون أكبر من صفر", "Amount must be positive", "bad_amount")
    if amount > folio.balance:
        raise FolioError(
            f"المبلغ أكبر من الرصيد المستحق ({folio.balance} ج.م)",
            f"Amount exceeds the outstanding balance ({folio.balance})",
            "over_payment",
        )

    payment = Payment(
        code=next_number(db, folio.property_id, "PAYMENT"),
        property_id=folio.property_id,
        business_date=date.today(),
        folio_id=folio.id,
        reservation_id=folio.reservation_id,
        guest_id=folio.guest_id,
        method=method,
        amount=money(amount),
        currency="EGP",
        exchange_rate=Decimal("1"),
        amount_base=money(amount),
        gateway_reference=reference,
        shift_id=shift_id,
        received_by_user_id=user_id,
    )
    db.add(payment)
    db.flush()

    line = FolioLine(
        created_at=utcnow(),
        folio_id=folio.id,
        property_id=folio.property_id,
        business_date=date.today(),
        charge_kind=ChargeKind.PAYMENT,
        description_ar=f"دفعة — {_method_label_ar(method)}",
        description_en=f"Payment — {method.value}",
        quantity=Decimal("1"),
        unit_price=-money(amount),
        amount=-money(amount),
        total_amount=-money(amount),
        payment_id=payment.id,
        posted_by_user_id=user_id,
    )
    db.add(line)
    db.flush()
    recalculate(db, folio)

    # تحديث الحجز المرتبط
    if folio.reservation_id:
        from app.models.reservations import Reservation

        reservation = db.get(Reservation, folio.reservation_id)
        if reservation:
            reservation.paid_total = money(reservation.paid_total + amount)
            reservation.balance = money(reservation.grand_total - reservation.paid_total)
            db.flush()

    return payment


_METHOD_AR = {
    PaymentMethod.CASH: "نقدي",
    PaymentMethod.CARD: "فيزا / ماستر",
    PaymentMethod.FAWRY: "فوري",
    PaymentMethod.PAYMOB: "باي موب",
    PaymentMethod.INSTAPAY: "إنستا باي",
    PaymentMethod.BANK_TRANSFER: "تحويل بنكي",
    PaymentMethod.CHEQUE: "شيك",
    PaymentMethod.CITY_LEDGER: "آجل على حساب شركة",
    PaymentMethod.OTA_PREPAID: "محصّل من القناة",
    PaymentMethod.COMPLIMENTARY: "ضيافة",
}


def _method_label_ar(method: PaymentMethod) -> str:
    return _METHOD_AR.get(method, method.value)


def close_folio(db: Session, folio_id: int, *, user_id: int | None = None) -> Folio:
    folio = _require_open(db, folio_id)
    if folio.balance != 0:
        raise FolioError(
            f"فيه رصيد {folio.balance} ج.م لازم يتصفّى قبل القفل",
            f"A balance of {folio.balance} must be settled first",
            "outstanding",
        )
    folio.status = FolioStatus.CLOSED
    folio.closed_at = utcnow()
    folio.closed_by_user_id = user_id
    db.flush()
    return folio
