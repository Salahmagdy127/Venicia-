"""واجهات حساب النزيل — Folio endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import (
    CREDIT_CHARGE_KINDS,
    AuditAction,
    ChargeKind,
    FolioStatus,
    PaymentMethod,
)
from app.models.folio import Folio, FolioLine
from app.models.guests import Guest
from app.models.reservations import Reservation
from app.schemas.common import ApiModel
from app.services import audit
from app.services import folio as svc

router = APIRouter(prefix="/folios", tags=["حساب النزيل — Folio"])

CHARGE_LABELS_AR = {
    ChargeKind.ROOM: "إقامة",
    ChargeKind.FNB: "مأكولات ومشروبات",
    ChargeKind.SPA: "سبا",
    ChargeKind.ACTIVITY: "أنشطة ورحلات",
    ChargeKind.MINIBAR: "ميني بار",
    ChargeKind.LAUNDRY: "مغسلة",
    ChargeKind.SERVICE_CHARGE: "خدمة",
    ChargeKind.TAX: "ضريبة",
    ChargeKind.DISCOUNT: "خصم",
    ChargeKind.PAYMENT: "دفعة",
    ChargeKind.DEPOSIT: "عربون",
    ChargeKind.REFUND: "استرداد",
    ChargeKind.ADJUSTMENT: "تسوية",
    ChargeKind.CANCELLATION_FEE: "غرامة إلغاء",
    ChargeKind.NO_SHOW_FEE: "غرامة عدم حضور",
}


# ═══════════════════════════════════════════════════════════ النماذج
class StatementLine(ApiModel):
    id: int
    created_at: datetime
    business_date: date
    charge_kind: ChargeKind
    charge_label_ar: str
    description_ar: str
    description_en: str | None = None
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    service_charge_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    is_credit: bool
    is_void: bool
    is_transferred: bool
    transferred_from_folio_id: int | None = None
    outlet_id: int | None = None
    pos_order_id: int | None = None


class DayGroup(ApiModel):
    business_date: date
    lines: list[StatementLine]
    day_total: Decimal


class FolioOut(ApiModel):
    id: int
    code: str
    status: FolioStatus
    unit_label: str | None = None
    guest_id: int | None = None
    guest_name: str | None = None
    guest_phone: str | None = None
    is_vip: bool = False
    is_returning: bool = False
    total_stays: int = 0
    reservation_id: int | None = None
    reservation_code: str | None = None
    arrival_date: date | None = None
    departure_date: date | None = None
    nights: int | None = None
    source: str | None = None
    charges_total: Decimal
    payments_total: Decimal
    discount_total: Decimal
    service_charge_total: Decimal
    tax_total: Decimal
    balance: Decimal
    opened_at: datetime
    closed_at: datetime | None = None
    days: list[DayGroup] = []


class FolioListItem(ApiModel):
    id: int
    code: str
    status: FolioStatus
    unit_label: str | None = None
    guest_name: str
    balance: Decimal
    opened_at: datetime


class PostChargeIn(ApiModel):
    charge_kind: ChargeKind
    description_ar: str
    description_en: str | None = None
    amount: Decimal
    quantity: Decimal = Decimal("1")
    apply_service_charge: bool = True
    apply_tax: bool = True


class VoidIn(ApiModel):
    reason: str


class TransferIn(ApiModel):
    target_folio_id: int


class SplitIn(ApiModel):
    line_ids: list[int]
    label: str | None = None


class SettleIn(ApiModel):
    method: PaymentMethod
    amount: Decimal
    reference: str | None = None
    shift_id: int | None = None


class ActionOut(ApiModel):
    ok: bool = True
    message_ar: str
    message_en: str
    folio: FolioOut | None = None
    new_folio_id: int | None = None


# ═══════════════════════════════════════════════════════════ مساعدات
def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.FolioError):
        code = status.HTTP_400_BAD_REQUEST
        if exc.code == "not_found":
            code = status.HTTP_404_NOT_FOUND
        elif exc.code in ("closed", "outstanding"):
            code = status.HTTP_409_CONFLICT
        return HTTPException(
            status_code=code,
            detail={"ar": exc.message_ar, "en": exc.message_en, "code": exc.code},
        )
    raise exc


def _build(db, folio: Folio, *, with_lines: bool = True) -> FolioOut:
    guest = db.get(Guest, folio.guest_id) if folio.guest_id else None
    reservation = db.get(Reservation, folio.reservation_id) if folio.reservation_id else None

    days: list[DayGroup] = []
    if with_lines:
        lines = db.execute(
            select(FolioLine)
            .where(FolioLine.folio_id == folio.id)
            .order_by(FolioLine.business_date, FolioLine.id)
        ).scalars().all()

        grouped: dict[date, list[StatementLine]] = {}
        for line in lines:
            grouped.setdefault(line.business_date, []).append(
                StatementLine(
                    id=line.id,
                    created_at=line.created_at,
                    business_date=line.business_date,
                    charge_kind=line.charge_kind,
                    charge_label_ar=CHARGE_LABELS_AR.get(line.charge_kind, line.charge_kind),
                    description_ar=line.description_ar,
                    description_en=line.description_en,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=line.amount,
                    service_charge_amount=line.service_charge_amount,
                    tax_amount=line.tax_amount,
                    total_amount=line.total_amount,
                    is_credit=line.charge_kind in CREDIT_CHARGE_KINDS,
                    is_void=line.is_void,
                    is_transferred=line.is_transferred,
                    transferred_from_folio_id=line.transferred_from_folio_id,
                    outlet_id=line.outlet_id,
                    pos_order_id=line.pos_order_id,
                )
            )
        for day in sorted(grouped):
            entries = grouped[day]
            total = sum(
                (e.total_amount for e in entries if not e.is_void and not e.is_transferred),
                Decimal("0"),
            )
            days.append(DayGroup(business_date=day, lines=entries, day_total=total))

    return FolioOut(
        id=folio.id,
        code=folio.code,
        status=folio.status,
        unit_label=folio.unit_label,
        guest_id=folio.guest_id,
        guest_name=guest.full_name if guest else None,
        guest_phone=guest.phone if guest else None,
        is_vip=bool(guest.is_vip) if guest else False,
        is_returning=bool(guest.is_returning) if guest else False,
        total_stays=guest.total_stays if guest else 0,
        reservation_id=folio.reservation_id,
        reservation_code=reservation.code if reservation else None,
        arrival_date=reservation.arrival_date if reservation else None,
        departure_date=reservation.departure_date if reservation else None,
        nights=reservation.nights if reservation else None,
        source=reservation.source if reservation else None,
        charges_total=folio.charges_total,
        payments_total=folio.payments_total,
        discount_total=folio.discount_total,
        service_charge_total=folio.service_charge_total,
        tax_total=folio.tax_total,
        balance=folio.balance,
        opened_at=folio.opened_at,
        closed_at=folio.closed_at,
        days=days,
    )


# ═══════════════════════════════════════════════════════════ القراءة
@router.get("", response_model=list[FolioListItem], summary="الحسابات المفتوحة")
def list_folios(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    status_filter: FolioStatus = Query(default=FolioStatus.OPEN, alias="status"),
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[FolioListItem]:
    stmt = (
        select(Folio, Guest)
        .join(Guest, Guest.id == Folio.guest_id)
        .where(Folio.property_id == prop.id, Folio.status == status_filter)
        .order_by(Folio.unit_label, Folio.id)
        .limit(limit)
    )
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            Folio.unit_label.ilike(term)
            | Folio.code.ilike(term)
            | Guest.first_name.ilike(term)
            | Guest.last_name.ilike(term)
        )
    return [
        FolioListItem(
            id=f.id, code=f.code, status=f.status, unit_label=f.unit_label,
            guest_name=g.full_name, balance=f.balance, opened_at=f.opened_at,
        )
        for f, g in db.execute(stmt).all()
    ]


@router.get("/{folio_id}", response_model=FolioOut, summary="كشف حساب النزيل")
def get_folio(
    folio_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> FolioOut:
    folio = db.get(Folio, folio_id)
    if folio is None or folio.property_id != prop.id:
        raise HTTPException(404, {"ar": "الحساب غير موجود", "en": "Folio not found"})
    return _build(db, folio)


# ═══════════════════════════════════════════════════════════ الكتابة
@router.post(
    "/{folio_id}/charges",
    response_model=ActionOut,
    summary="ترحيل حركة",
    dependencies=[Depends(require("folio.post"))],
)
def post_charge(
    folio_id: int,
    payload: PostChargeIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionOut:
    try:
        line = svc.post_charge(
            db,
            folio_id,
            charge_kind=payload.charge_kind,
            description_ar=payload.description_ar,
            description_en=payload.description_en,
            amount=payload.amount,
            quantity=payload.quantity,
            apply_service_charge=payload.apply_service_charge,
            apply_tax=payload.apply_tax,
            user_id=user.id,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="FolioLine",
        entity_id=line.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"ترحيل {payload.description_ar} — {line.total_amount} ج.م",
        summary_en=f"Posted {payload.description_ar} — {line.total_amount}",
        request=request,
    )
    return ActionOut(
        message_ar="تم ترحيل الحركة",
        message_en="Charge posted",
        folio=_build(db, db.get(Folio, folio_id)),
    )


@router.post(
    "/{folio_id}/charges/{line_id}/void",
    response_model=ActionOut,
    summary="إلغاء حركة",
    dependencies=[Depends(require("folio.void"))],
)
def void_charge(
    folio_id: int,
    line_id: int,
    payload: VoidIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionOut:
    try:
        line = svc.void_line(db, line_id, reason=payload.reason, user_id=user.id)
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.VOID,
        entity_type="FolioLine",
        entity_id=line.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إلغاء حركة {line.description_ar} — {payload.reason}",
        summary_en=f"Voided charge {line.description_ar} — {payload.reason}",
        request=request,
    )
    return ActionOut(
        message_ar="تم إلغاء الحركة بحركة عكسية",
        message_en="Charge reversed",
        folio=_build(db, db.get(Folio, folio_id)),
    )


@router.post(
    "/{folio_id}/charges/{line_id}/transfer",
    response_model=ActionOut,
    summary="تحويل حركة لغرفة تانية",
    dependencies=[Depends(require("folio.transfer"))],
)
def transfer(
    folio_id: int,
    line_id: int,
    payload: TransferIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionOut:
    try:
        copy = svc.transfer_line(db, line_id, payload.target_folio_id, user_id=user.id)
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="FolioLine",
        entity_id=line_id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تحويل حركة لحساب {payload.target_folio_id}",
        summary_en=f"Transferred charge to folio {payload.target_folio_id}",
        changes={"to_folio": {"from": folio_id, "to": payload.target_folio_id}},
        request=request,
    )
    return ActionOut(
        message_ar="تم تحويل الحركة",
        message_en="Charge transferred",
        folio=_build(db, db.get(Folio, folio_id)),
    )


@router.post(
    "/{folio_id}/split",
    response_model=ActionOut,
    summary="تقسيم الفاتورة",
    dependencies=[Depends(require("folio.split"))],
)
def split(
    folio_id: int,
    payload: SplitIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionOut:
    try:
        new_folio = svc.split_folio(
            db, folio_id, payload.line_ids, user_id=user.id, label=payload.label
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="Folio",
        entity_id=new_folio.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تقسيم الفاتورة — {len(payload.line_ids)} حركة لحساب {new_folio.code}",
        summary_en=f"Split folio — {len(payload.line_ids)} charges to {new_folio.code}",
        request=request,
    )
    return ActionOut(
        message_ar=f"تم إنشاء حساب جديد {new_folio.code}",
        message_en=f"New folio {new_folio.code} created",
        folio=_build(db, db.get(Folio, folio_id)),
        new_folio_id=new_folio.id,
    )


@router.post(
    "/{folio_id}/settle",
    response_model=ActionOut,
    summary="تحصيل دفعة",
    dependencies=[Depends(require("folio.settle"))],
)
def settle(
    folio_id: int,
    payload: SettleIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionOut:
    try:
        payment = svc.settle(
            db,
            folio_id,
            method=payload.method,
            amount=payload.amount,
            user_id=user.id,
            reference=payload.reference,
            shift_id=payload.shift_id,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="Payment",
        entity_id=payment.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تحصيل {payment.amount} ج.م — {payload.method.value}",
        summary_en=f"Received {payment.amount} — {payload.method.value}",
        request=request,
    )
    folio = db.get(Folio, folio_id)
    return ActionOut(
        message_ar=f"تم تحصيل {payment.amount} ج.م — الرصيد {folio.balance} ج.م",
        message_en=f"Received {payment.amount} — balance {folio.balance}",
        folio=_build(db, folio),
    )


@router.post(
    "/{folio_id}/close",
    response_model=ActionOut,
    summary="قفل الحساب",
    dependencies=[Depends(require("folio.settle"))],
)
def close(
    folio_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> ActionOut:
    try:
        folio = svc.close_folio(db, folio_id, user_id=user.id)
    except Exception as exc:
        raise _fail(exc) from exc
    return ActionOut(
        message_ar="تم قفل الحساب", message_en="Folio closed", folio=_build(db, folio)
    )
