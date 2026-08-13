"""واجهات الحجوزات — Reservation endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.core.pagination import paginate
from app.models.enums import (
    AuditAction,
    BookingSource,
    ReservationStatus,
)
from app.models.guests import Guest
from app.models.reservations import Reservation, ReservationUnit
from app.models.units import Unit
from app.schemas.common import ApiModel
from app.services import audit
from app.services import reservations as svc
from app.services.availability import AvailabilityError
from app.services.pricing import PricingError

router = APIRouter(prefix="/reservations", tags=["الحجوزات — Reservations"])


# ═══════════════════════════════════════════════════════════ النماذج
class ReservationLineOut(ApiModel):
    id: int
    unit_category_id: int
    unit_id: int | None
    unit_label: str | None = None
    rate_plan_id: int
    arrival_date: date
    departure_date: date
    nights: int
    adults: int
    children: int
    status: ReservationStatus
    room_total: Decimal


class ReservationOut(ApiModel):
    id: int
    code: str
    status: ReservationStatus
    source: BookingSource
    external_reference: str | None = None
    guest_id: int
    guest_name: str | None = None
    guest_phone: str | None = None
    arrival_date: date
    departure_date: date
    nights: int
    adults: int
    children: int
    room_total: Decimal
    discount_total: Decimal
    service_charge_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    paid_total: Decimal
    balance: Decimal
    channel_commission_amount: Decimal
    special_requests: str | None = None
    units: list[ReservationLineOut] = []


class ReservationListItem(ApiModel):
    id: int
    code: str
    status: ReservationStatus
    source: BookingSource
    guest_name: str
    arrival_date: date
    departure_date: date
    nights: int
    adults: int
    children: int
    grand_total: Decimal
    balance: Decimal


class ReservationPage(ApiModel):
    items: list[ReservationListItem]
    next_cursor: str | None = None
    has_more: bool = False


class CreateReservationIn(ApiModel):
    guest_id: int
    unit_category_id: int
    rate_plan_id: int
    arrival_date: date
    departure_date: date
    adults: int = 2
    children: int = 0
    source: BookingSource = BookingSource.DIRECT
    unit_id: int | None = None
    external_reference: str | None = None
    special_requests: str | None = None
    #: عربون محصّل وقت الحجز — بيتخصم من المستحق على طول
    deposit_paid: Decimal = Decimal("0")


class AssignUnitIn(ApiModel):
    unit_id: int


class MoveIn(ApiModel):
    """نقل شريط في شاشة الحجوزات."""

    unit_id: int | None = None
    arrival_date: date | None = None
    departure_date: date | None = None


class CancelIn(ApiModel):
    reason: str | None = None
    charge_penalty: bool = True


class CheckOutIn(ApiModel):
    #: تجاهل الرصيد المستحق — محتاج صلاحية أعلى
    force: bool = False


class ActionResult(ApiModel):
    ok: bool = True
    message_ar: str
    message_en: str
    reservation: ReservationOut | None = None
    penalty: Decimal | None = None
    folio_ids: list[int] = []


# ═══════════════════════════════════════════════════════════ مساعدات
def _fail(exc: Exception) -> HTTPException:
    """تحويل أخطاء الخدمات لردود HTTP مفهومة بالعربي والإنجليزي."""
    if isinstance(exc, svc.ReservationError):
        code = status.HTTP_409_CONFLICT if exc.code == "conflict" else status.HTTP_400_BAD_REQUEST
        if exc.code == "not_found":
            code = status.HTTP_404_NOT_FOUND
        return HTTPException(
            status_code=code,
            detail={"ar": exc.message_ar, "en": exc.message_en, "code": exc.code},
        )
    if isinstance(exc, AvailabilityError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "ar": exc.message_ar,
                "en": exc.message_en,
                "code": "no_availability",
                "blocking_dates": [d.isoformat() for d in exc.blocking_dates],
            },
        )
    if isinstance(exc, PricingError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ar": exc.message_ar, "en": exc.message_en, "code": "pricing_error"},
        )
    raise exc


def _to_out(db, reservation: Reservation) -> ReservationOut:
    guest = db.get(Guest, reservation.guest_id)
    lines = list(
        db.execute(
            select(ReservationUnit).where(ReservationUnit.reservation_id == reservation.id)
        ).scalars().all()
    )
    unit_labels = {
        u.id: u.label
        for u in db.execute(
            select(Unit).where(Unit.id.in_([l.unit_id for l in lines if l.unit_id]))
        ).scalars().all()
    } if any(l.unit_id for l in lines) else {}

    return ReservationOut(
        id=reservation.id,
        code=reservation.code,
        status=reservation.status,
        source=reservation.source,
        external_reference=reservation.external_reference,
        guest_id=reservation.guest_id,
        guest_name=guest.full_name if guest else None,
        guest_phone=guest.phone if guest else None,
        arrival_date=reservation.arrival_date,
        departure_date=reservation.departure_date,
        nights=reservation.nights,
        adults=reservation.adults,
        children=reservation.children,
        room_total=reservation.room_total,
        discount_total=reservation.discount_total,
        service_charge_total=reservation.service_charge_total,
        tax_total=reservation.tax_total,
        grand_total=reservation.grand_total,
        paid_total=reservation.paid_total,
        balance=reservation.balance,
        channel_commission_amount=reservation.channel_commission_amount,
        special_requests=reservation.special_requests,
        units=[
            ReservationLineOut(
                id=l.id,
                unit_category_id=l.unit_category_id,
                unit_id=l.unit_id,
                unit_label=unit_labels.get(l.unit_id),
                rate_plan_id=l.rate_plan_id,
                arrival_date=l.arrival_date,
                departure_date=l.departure_date,
                nights=l.nights,
                adults=l.adults,
                children=l.children,
                status=l.status,
                room_total=l.room_total,
            )
            for l in lines
        ],
    )


# ═══════════════════════════════════════════════════════════ القراءة
@router.get("", response_model=ReservationPage, summary="قائمة الحجوزات")
def list_reservations(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    status_filter: ReservationStatus | None = Query(default=None, alias="status"),
    source: BookingSource | None = None,
    arrival_from: date | None = None,
    arrival_to: date | None = None,
    search: str | None = Query(default=None, description="رقم الحجز أو اسم النزيل"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> ReservationPage:
    stmt = select(Reservation).where(Reservation.property_id == prop.id)

    if status_filter:
        stmt = stmt.where(Reservation.status == status_filter)
    if source:
        stmt = stmt.where(Reservation.source == source)
    if arrival_from:
        stmt = stmt.where(Reservation.arrival_date >= arrival_from)
    if arrival_to:
        stmt = stmt.where(Reservation.arrival_date <= arrival_to)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.join(Guest, Guest.id == Reservation.guest_id).where(
            Reservation.code.ilike(term)
            | Guest.first_name.ilike(term)
            | Guest.last_name.ilike(term)
            | Guest.phone.ilike(term)
        )

    page = paginate(db, stmt, key_column=Reservation.id, limit=limit, cursor=cursor)

    guests = {
        g.id: g
        for g in db.execute(
            select(Guest).where(Guest.id.in_([r.guest_id for r in page.items]))
        ).scalars().all()
    } if page.items else {}

    return ReservationPage(
        items=[
            ReservationListItem(
                id=r.id,
                code=r.code,
                status=r.status,
                source=r.source,
                guest_name=guests[r.guest_id].full_name if r.guest_id in guests else "—",
                arrival_date=r.arrival_date,
                departure_date=r.departure_date,
                nights=r.nights,
                adults=r.adults,
                children=r.children,
                grand_total=r.grand_total,
                balance=r.balance,
            )
            for r in page.items
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/arrivals", response_model=list[ReservationListItem], summary="وصول اليوم")
def arrivals(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    on: date | None = Query(default=None, description="افتراضياً النهاردة"),
) -> list[ReservationListItem]:
    day = on or date.today()
    rows = db.execute(
        select(Reservation, Guest)
        .join(Guest, Guest.id == Reservation.guest_id)
        .where(
            Reservation.property_id == prop.id,
            Reservation.arrival_date == day,
            Reservation.status.in_(
                [ReservationStatus.CONFIRMED, ReservationStatus.TENTATIVE,
                 ReservationStatus.CHECKED_IN]
            ),
        )
        .order_by(Reservation.expected_arrival_time, Reservation.id)
    ).all()

    return [
        ReservationListItem(
            id=r.id, code=r.code, status=r.status, source=r.source,
            guest_name=g.full_name, arrival_date=r.arrival_date,
            departure_date=r.departure_date, nights=r.nights, adults=r.adults,
            children=r.children, grand_total=r.grand_total, balance=r.balance,
        )
        for r, g in rows
    ]


@router.get("/departures", response_model=list[ReservationListItem], summary="مغادرة اليوم")
def departures(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    on: date | None = None,
) -> list[ReservationListItem]:
    day = on or date.today()
    rows = db.execute(
        select(Reservation, Guest)
        .join(Guest, Guest.id == Reservation.guest_id)
        .where(
            Reservation.property_id == prop.id,
            Reservation.departure_date == day,
            Reservation.status.in_(
                [ReservationStatus.CHECKED_IN, ReservationStatus.CHECKED_OUT]
            ),
        )
        .order_by(Reservation.id)
    ).all()

    return [
        ReservationListItem(
            id=r.id, code=r.code, status=r.status, source=r.source,
            guest_name=g.full_name, arrival_date=r.arrival_date,
            departure_date=r.departure_date, nights=r.nights, adults=r.adults,
            children=r.children, grand_total=r.grand_total, balance=r.balance,
        )
        for r, g in rows
    ]


@router.get("/{reservation_id}", response_model=ReservationOut, summary="تفاصيل حجز")
def get_reservation(
    reservation_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> ReservationOut:
    reservation = db.get(Reservation, reservation_id)
    if reservation is None or reservation.property_id != prop.id:
        raise HTTPException(
            status_code=404,
            detail={"ar": "الحجز غير موجود", "en": "Reservation not found"},
        )
    return _to_out(db, reservation)


# ═══════════════════════════════════════════════════════════ الكتابة
@router.post(
    "",
    response_model=ReservationOut,
    status_code=status.HTTP_201_CREATED,
    summary="حجز جديد",
    dependencies=[Depends(require("reservation.create"))],
)
def create(
    payload: CreateReservationIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ReservationOut:
    try:
        reservation = svc.create_reservation(
            db,
            property_id=prop.id,
            guest_id=payload.guest_id,
            unit_category_id=payload.unit_category_id,
            rate_plan_id=payload.rate_plan_id,
            arrival=payload.arrival_date,
            departure=payload.departure_date,
            adults=payload.adults,
            children=payload.children,
            source=payload.source,
            unit_id=payload.unit_id,
            external_reference=payload.external_reference,
            special_requests=payload.special_requests,
            created_by_user_id=user.id,
            deposit_paid=payload.deposit_paid,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="Reservation",
        entity_id=reservation.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"حجز جديد {reservation.code} — {reservation.nights} ليالي",
        summary_en=f"New reservation {reservation.code} — {reservation.nights} nights",
        changes={"total": {"from": None, "to": str(reservation.grand_total)}},
        request=request,
    )
    return _to_out(db, reservation)


@router.post(
    "/lines/{reservation_unit_id}/assign",
    response_model=ActionResult,
    summary="تخصيص وحدة",
    dependencies=[Depends(require("reservation.assign_unit"))],
)
def assign(
    reservation_unit_id: int,
    payload: AssignUnitIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionResult:
    try:
        line = svc.assign_unit(db, reservation_unit_id, payload.unit_id)
    except Exception as exc:
        raise _fail(exc) from exc

    unit = db.get(Unit, line.unit_id)
    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="ReservationUnit",
        entity_id=line.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تخصيص الوحدة {unit.label if unit else ''}",
        summary_en=f"Assigned unit {unit.label if unit else ''}",
        request=request,
    )
    reservation = db.get(Reservation, line.reservation_id)
    return ActionResult(
        message_ar=f"تم تخصيص الوحدة {unit.label if unit else ''}",
        message_en=f"Unit {unit.label if unit else ''} assigned",
        reservation=_to_out(db, reservation),
    )


@router.post(
    "/lines/{reservation_unit_id}/move",
    response_model=ActionResult,
    summary="نقل حجز (سحب وإفلات)",
    dependencies=[Depends(require("reservation.edit"))],
)
def move(
    reservation_unit_id: int,
    payload: MoveIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionResult:
    line = db.get(ReservationUnit, reservation_unit_id)
    if line is None:
        raise HTTPException(
            status_code=404, detail={"ar": "السطر غير موجود", "en": "Line not found"}
        )
    before = {
        "unit_id": line.unit_id,
        "arrival": line.arrival_date,
        "departure": line.departure_date,
    }

    try:
        line = svc.move_reservation_unit(
            db,
            reservation_unit_id,
            unit_id=payload.unit_id,
            arrival=payload.arrival_date,
            departure=payload.departure_date,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    after = {
        "unit_id": line.unit_id,
        "arrival": line.arrival_date,
        "departure": line.departure_date,
    }
    unit = db.get(Unit, line.unit_id) if line.unit_id else None

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="ReservationUnit",
        entity_id=line.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"نقل الحجز للوحدة {unit.label if unit else '—'}",
        summary_en=f"Moved reservation to unit {unit.label if unit else '—'}",
        changes=audit.diff(before, after),
        request=request,
    )
    reservation = db.get(Reservation, line.reservation_id)
    return ActionResult(
        message_ar="تم نقل الحجز",
        message_en="Reservation moved",
        reservation=_to_out(db, reservation),
    )


@router.post(
    "/{reservation_id}/check-in",
    response_model=ActionResult,
    summary="تسجيل النزول",
    dependencies=[Depends(require("reservation.checkin"))],
)
def do_check_in(
    reservation_id: int,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionResult:
    try:
        reservation, folios = svc.check_in(db, reservation_id, user_id=user.id)
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CHECK_IN,
        entity_type="Reservation",
        entity_id=reservation.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تسجيل نزول {reservation.code}",
        summary_en=f"Check-in {reservation.code}",
        request=request,
    )
    return ActionResult(
        message_ar="تم تسجيل النزول وفتح الحساب",
        message_en="Checked in and folio opened",
        reservation=_to_out(db, reservation),
        folio_ids=[f.id for f in folios],
    )


@router.post(
    "/{reservation_id}/check-out",
    response_model=ActionResult,
    summary="تسجيل المغادرة",
    dependencies=[Depends(require("reservation.checkout"))],
)
def do_check_out(
    reservation_id: int,
    payload: CheckOutIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionResult:
    # تجاهل الرصيد المستحق محتاج صلاحية أعلى
    if payload.force and not user.has_permission("folio.void"):
        raise HTTPException(
            status_code=403,
            detail={
                "ar": "تجاهل الرصيد المستحق محتاج موافقة مدير",
                "en": "Forcing check-out with a balance requires manager approval",
            },
        )
    try:
        reservation, folios = svc.check_out(
            db, reservation_id, user_id=user.id, force=payload.force
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CHECK_OUT,
        entity_type="Reservation",
        entity_id=reservation.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تسجيل مغادرة {reservation.code}"
        + (" (بتجاهل الرصيد)" if payload.force else ""),
        summary_en=f"Check-out {reservation.code}" + (" (forced)" if payload.force else ""),
        request=request,
    )
    return ActionResult(
        message_ar="تم تسجيل المغادرة وقفل الحساب",
        message_en="Checked out and folio closed",
        reservation=_to_out(db, reservation),
        folio_ids=[f.id for f in folios],
    )


@router.post(
    "/{reservation_id}/cancel",
    response_model=ActionResult,
    summary="إلغاء حجز",
    dependencies=[Depends(require("reservation.cancel"))],
)
def do_cancel(
    reservation_id: int,
    payload: CancelIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ActionResult:
    try:
        reservation, penalty = svc.cancel(
            db,
            reservation_id,
            reason=payload.reason,
            user_id=user.id,
            charge_penalty=payload.charge_penalty,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="Reservation",
        entity_id=reservation.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إلغاء الحجز {reservation.code}"
        + (f" — غرامة {penalty} ج.م" if penalty else ""),
        summary_en=f"Cancelled {reservation.code}"
        + (f" — penalty {penalty}" if penalty else ""),
        changes={"reason": {"from": None, "to": payload.reason}},
        request=request,
    )
    return ActionResult(
        message_ar="تم إلغاء الحجز" + (f" مع غرامة {penalty} ج.م" if penalty else ""),
        message_en="Reservation cancelled" + (f" with a {penalty} penalty" if penalty else ""),
        reservation=_to_out(db, reservation),
        penalty=penalty,
    )
