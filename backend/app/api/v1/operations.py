"""واجهات التشغيل — Housekeeping, guests, inventory setup, availability & quotes."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.core.pagination import paginate
from app.models.enums import (
    AuditAction,
    HousekeepingStatus,
    IdentificationType,
    UnitCondition,
)
from app.models.analytics import NightAuditRun
from app.models.guests import Guest
from app.models.rates import RatePlan
from app.models.reservations import Reservation, ReservationNight, ReservationUnit
from app.models.units import Unit, UnitCategory, UnitStatusLog
from app.schemas.common import ApiModel
from app.services import audit
from app.services import availability as av
from app.services import night_audit as na
from app.services import pricing

router = APIRouter(tags=["التشغيل — Operations"])


# ═════════════════════════════════════════════════════ الهاوس كيبينج
class UnitStatusOut(ApiModel):
    id: int
    label: str
    category_id: int
    category_name_ar: str
    zone_ar: str | None = None
    zone_en: str | None = None
    housekeeping_status: HousekeepingStatus
    condition: UnitCondition
    block_reason: str | None = None
    is_occupied: bool = False
    departs_today: bool = False
    arrives_today: bool = False


class HousekeepingBoard(ApiModel):
    business_date: date
    clean: int
    dirty: int
    cleaning: int
    inspected: int
    out_of_order: int
    units: list[UnitStatusOut]


class UpdateUnitStatusIn(ApiModel):
    housekeeping_status: HousekeepingStatus | None = None
    condition: UnitCondition | None = None
    note: str | None = None


@router.get(
    "/housekeeping",
    response_model=HousekeepingBoard,
    summary="لوحة الهاوس كيبينج",
    dependencies=[Depends(require("housekeeping.view"))],
)
def housekeeping_board(
    db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> HousekeepingBoard:
    from app.models.enums import BLOCKING_RESERVATION_STATUSES
    from app.models.reservations import ReservationUnit

    today = date.today()
    units = db.execute(
        select(Unit, UnitCategory)
        .join(UnitCategory, UnitCategory.id == Unit.category_id)
        .where(Unit.property_id == prop.id, Unit.is_active.is_(True))
        .order_by(UnitCategory.sort_order, Unit.sort_order)
    ).all()

    occupancy = db.execute(
        select(ReservationUnit.unit_id, ReservationUnit.arrival_date, ReservationUnit.departure_date)
        .where(
            ReservationUnit.property_id == prop.id,
            ReservationUnit.unit_id.isnot(None),
            ReservationUnit.arrival_date <= today,
            ReservationUnit.departure_date >= today,
            ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
        )
    ).all()
    occupied = {r[0] for r in occupancy if r[1] <= today < r[2]}
    departing = {r[0] for r in occupancy if r[2] == today}
    arriving = {
        r[0]
        for r in db.execute(
            select(ReservationUnit.unit_id).where(
                ReservationUnit.property_id == prop.id,
                ReservationUnit.unit_id.isnot(None),
                ReservationUnit.arrival_date == today,
                ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
            )
        ).all()
    }

    rows = [
        UnitStatusOut(
            id=u.id,
            label=u.label,
            category_id=u.category_id,
            category_name_ar=c.name_ar,
            zone_ar=u.zone_ar,
            zone_en=u.zone_en,
            housekeeping_status=u.housekeeping_status,
            condition=u.condition,
            block_reason=u.block_reason,
            is_occupied=u.id in occupied,
            departs_today=u.id in departing,
            arrives_today=u.id in arriving,
        )
        for u, c in units
    ]

    def count(statuses: set) -> int:
        return sum(1 for r in rows if r.housekeeping_status in statuses)

    return HousekeepingBoard(
        business_date=today,
        clean=count({HousekeepingStatus.CLEAN}),
        dirty=count({HousekeepingStatus.DIRTY}),
        cleaning=count({HousekeepingStatus.CLEANING}),
        inspected=count({HousekeepingStatus.INSPECTED}),
        out_of_order=sum(1 for r in rows if r.condition != UnitCondition.OPERATIONAL),
        units=rows,
    )


@router.patch(
    "/units/{unit_id}/status",
    response_model=UnitStatusOut,
    summary="تغيير حالة وحدة",
    dependencies=[Depends(require("housekeeping.update"))],
)
def update_unit_status(
    unit_id: int,
    payload: UpdateUnitStatusIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> UnitStatusOut:
    unit = db.get(Unit, unit_id)
    if unit is None or unit.property_id != prop.id:
        raise HTTPException(404, {"ar": "الوحدة غير موجودة", "en": "Unit not found"})

    before_hk, before_cond = unit.housekeeping_status, unit.condition

    if payload.housekeeping_status:
        unit.housekeeping_status = payload.housekeeping_status
    if payload.condition:
        unit.condition = payload.condition
        unit.block_reason = payload.note if payload.condition != UnitCondition.OPERATIONAL else None

    db.add(
        UnitStatusLog(
            created_at=datetime.now(timezone.utc),
            unit_id=unit.id,
            property_id=prop.id,
            from_housekeeping=before_hk,
            to_housekeeping=unit.housekeeping_status,
            from_condition=before_cond,
            to_condition=unit.condition,
            changed_by_user_id=user.id,
            source="APP",
            note=payload.note,
        )
    )

    # تعطيل وحدة أو رجوعها بيغيّر السعة — لازم العدّاد يعرف
    if before_cond != unit.condition:
        today = date.today()
        av.sync_totals(db, prop.id, today, today + timedelta(days=365))
        audit.record(
            db,
            action=AuditAction.UPDATE,
            entity_type="Unit",
            entity_id=unit.id,
            user=user,
            property_id=prop.id,
            summary_ar=f"الوحدة {unit.label}: {before_cond} ← {unit.condition}",
            summary_en=f"Unit {unit.label}: {before_cond} -> {unit.condition}",
            changes={"condition": {"from": before_cond, "to": unit.condition}},
            request=request,
        )

    db.flush()
    category = db.get(UnitCategory, unit.category_id)
    return UnitStatusOut(
        id=unit.id, label=unit.label, category_id=unit.category_id,
        category_name_ar=category.name_ar if category else "—",
        zone_ar=unit.zone_ar, zone_en=unit.zone_en,
        housekeeping_status=unit.housekeeping_status, condition=unit.condition,
        block_reason=unit.block_reason,
    )


# ═══════════════════════════════════════════════════════════ النزلاء
class GuestOut(ApiModel):
    id: int
    first_name: str
    last_name: str
    full_name: str
    nationality: str
    id_type: IdentificationType
    id_number: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    is_vip: bool
    is_blacklisted: bool
    total_stays: int
    total_nights: int
    total_revenue: Decimal
    last_stay_date: date | None = None
    loyalty_points: int
    whatsapp_opt_in: bool
    marketing_opt_in: bool = False
    #: تفضيلات النزيل ومناسباته — ده اللي بيميّز النزيل الراجع
    preferences: dict[str, Any] | None = None
    occasions: dict[str, Any] | None = None
    dietary_notes: str | None = None
    notes: str | None = None


class GuestPage(ApiModel):
    items: list[GuestOut]
    next_cursor: str | None = None
    has_more: bool = False


class CreateGuestIn(ApiModel):
    first_name: str
    last_name: str
    nationality: str = "EG"
    id_type: IdentificationType = IdentificationType.NATIONAL_ID
    id_number: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    whatsapp_opt_in: bool = False


@router.get("/guests", response_model=GuestPage, summary="النزلاء")
def list_guests(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    search: str | None = Query(default=None, description="اسم · تليفون · رقم هوية"),
    returning_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> GuestPage:
    stmt = select(Guest).where(Guest.is_active.is_(True))
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            Guest.first_name.ilike(term)
            | Guest.last_name.ilike(term)
            | Guest.phone.ilike(term)
            | Guest.id_number.ilike(term)
            | Guest.email.ilike(term)
        )
    if returning_only:
        stmt = stmt.where(Guest.total_stays > 1)

    page = paginate(db, stmt, key_column=Guest.id, limit=limit, cursor=cursor)
    return GuestPage(
        items=[
            GuestOut(**{**g.__dict__, "full_name": g.full_name})
            for g in page.items
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.post(
    "/guests",
    response_model=GuestOut,
    status_code=status.HTTP_201_CREATED,
    summary="نزيل جديد",
    dependencies=[Depends(require("guest.edit"))],
)
def create_guest(
    payload: CreateGuestIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> GuestOut:
    if payload.id_number:
        existing = db.execute(
            select(Guest).where(
                Guest.property_id == prop.id, Guest.id_number == payload.id_number
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                409,
                {"ar": f"فيه نزيل مسجّل بنفس رقم الهوية: {existing.full_name}",
                 "en": f"A guest with this ID already exists: {existing.full_name}",
                 "guest_id": existing.id},
            )

    guest = Guest(property_id=prop.id, **payload.model_dump())
    db.add(guest)
    db.flush()
    return GuestOut(**{**guest.__dict__, "full_name": guest.full_name})


@router.get("/guests/{guest_id}", response_model=GuestOut, summary="ملف النزيل")
def get_guest(guest_id: int, db: DbSession, user: CurrentUser) -> GuestOut:
    guest = db.get(Guest, guest_id)
    if guest is None:
        raise HTTPException(404, {"ar": "النزيل غير موجود", "en": "Guest not found"})
    return GuestOut(**{**guest.__dict__, "full_name": guest.full_name})


class UpdateGuestIn(ApiModel):
    """تعديل ملف النزيل — كل الحقول اختيارية، بنعدّل اللي اتبعت بس."""

    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    nationality: str | None = None
    id_type: IdentificationType | None = None
    id_number: str | None = None
    is_vip: bool | None = None
    whatsapp_opt_in: bool | None = None
    marketing_opt_in: bool | None = None
    #: تفضيلات حرة: دور عالي، بعيد عن الأسانسير، وسادة إضافية...
    preferences: dict[str, Any] | None = None
    #: مناسبات متكررة: عيد جواز، عيد ميلاد
    occasions: dict[str, Any] | None = None
    dietary_notes: str | None = None
    notes: str | None = None


@router.patch(
    "/guests/{guest_id}",
    response_model=GuestOut,
    summary="تعديل ملف النزيل",
    dependencies=[Depends(require("guest.edit"))],
)
def update_guest(
    guest_id: int,
    payload: UpdateGuestIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> GuestOut:
    guest = db.get(Guest, guest_id)
    if guest is None:
        raise HTTPException(404, {"ar": "النزيل غير موجود", "en": "Guest not found"})

    changes = payload.model_dump(exclude_unset=True)

    # الرقم القومي لازم يفضل فريد — ده اللي بيمنع النزيل المكرر
    new_id = changes.get("id_number")
    if new_id and new_id != guest.id_number:
        clash = db.execute(
            select(Guest).where(
                Guest.property_id == guest.property_id,
                Guest.id_number == new_id,
                Guest.id != guest.id,
            )
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(
                409,
                {"ar": f"فيه نزيل تاني بنفس رقم الهوية: {clash.full_name}",
                 "en": f"Another guest already has this ID: {clash.full_name}",
                 "guest_id": clash.id},
            )

    before = {key: getattr(guest, key) for key in changes}
    for key, value in changes.items():
        setattr(guest, key, value)
    db.flush()

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="Guest",
        entity_id=guest.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تعديل ملف النزيل {guest.full_name}",
        summary_en=f"Updated guest profile {guest.full_name}",
        changes=audit.diff(before, changes),
        request=request,
    )
    return GuestOut(**{**guest.__dict__, "full_name": guest.full_name})


# ═══════════════════════════════════════════════ تدقيق الليلة
class AuditWarnings(ApiModel):
    open_folios: int = 0
    open_pos_orders: int = 0
    open_shifts: int = 0
    in_house_without_unit: int = 0
    overdue_checkouts: int = 0


class NightAuditOut(ApiModel):
    id: int
    business_date: date
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    nights_posted: int
    room_revenue_posted: Decimal
    no_shows_marked: int
    open_folios_remaining: int
    warnings: AuditWarnings | None = None
    error_message: str | None = None
    is_automatic: bool


class AuditPreview(ApiModel):
    """اللي هيحصل لو قفّلت — من غير ما نكتب حاجة."""

    business_date: date
    already_done: bool
    pending_no_shows: int
    pending_nights: int
    warnings: AuditWarnings


class RunAuditIn(ApiModel):
    business_date: date | None = None
    #: إعادة التقفيل على يوم اتقفل قبل كده — بيعيد حساب الملخّص بس
    force: bool = False


def _audit_out(run) -> NightAuditOut:
    return NightAuditOut(
        id=run.id,
        business_date=run.business_date,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        nights_posted=run.nights_posted,
        room_revenue_posted=run.room_revenue_posted,
        no_shows_marked=run.no_shows_marked,
        open_folios_remaining=run.open_folios_remaining,
        warnings=AuditWarnings(**(run.warnings or {})),
        error_message=run.error_message,
        is_automatic=run.is_automatic,
    )


@router.get(
    "/night-audit",
    response_model=list[NightAuditOut],
    summary="سجل التقفيلات اليومية",
    dependencies=[Depends(require("report.operational"))],
)
def list_audits(
    db: DbSession, user: CurrentUser, prop: CurrentProperty, limit: int = Query(default=30, le=90)
) -> list[NightAuditOut]:
    runs = db.execute(
        select(NightAuditRun)
        .where(NightAuditRun.property_id == prop.id)
        .order_by(NightAuditRun.business_date.desc(), NightAuditRun.id.desc())
        .limit(limit)
    ).scalars().all()
    return [_audit_out(r) for r in runs]


@router.get(
    "/night-audit/preview",
    response_model=AuditPreview,
    summary="معاينة التقفيل قبل تنفيذه",
    dependencies=[Depends(require("report.operational"))],
)
def preview_audit(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    business_date: date | None = None,
) -> AuditPreview:
    target = business_date or na.business_date_for(prop)

    done = db.execute(
        select(NightAuditRun).where(
            NightAuditRun.property_id == prop.id,
            NightAuditRun.business_date == target,
            NightAuditRun.status == "COMPLETED",
        )
    ).scalar_one_or_none()

    pending_no_shows = db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.property_id == prop.id,
            Reservation.arrival_date == target,
            Reservation.status.in_(["CONFIRMED", "TENTATIVE"]),
        )
    ).scalar_one()

    pending_nights = db.execute(
        select(func.count(ReservationNight.id))
        .join(ReservationUnit, ReservationUnit.id == ReservationNight.reservation_unit_id)
        .where(
            ReservationNight.property_id == prop.id,
            ReservationNight.stay_date <= target,
            ReservationNight.is_posted.is_(False),
            ReservationUnit.status == "CHECKED_IN",
        )
    ).scalar_one()

    return AuditPreview(
        business_date=target,
        already_done=done is not None,
        pending_no_shows=int(pending_no_shows),
        pending_nights=int(pending_nights),
        warnings=AuditWarnings(**na.collect_warnings(db, prop.id, target)),
    )


@router.post(
    "/night-audit/run",
    response_model=NightAuditOut,
    summary="تشغيل تقفيل اليوم",
    dependencies=[Depends(require("nightaudit.run"))],
)
def run_audit(
    payload: RunAuditIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> NightAuditOut:
    try:
        run = na.run(
            db,
            property_id=prop.id,
            business_date=payload.business_date,
            user_id=user.id,
            force=payload.force,
        )
    except na.NightAuditError as exc:
        code = status.HTTP_409_CONFLICT if exc.code == "already_done" else 400
        raise HTTPException(
            code, {"ar": exc.message_ar, "en": exc.message_en, "code": exc.code}
        ) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="NightAuditRun",
        entity_id=run.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تقفيل يوم {run.business_date} — {run.nights_posted} ليلة مرحّلة",
        summary_en=f"Night audit for {run.business_date} — {run.nights_posted} nights posted",
        request=request,
    )
    return _audit_out(run)


# ═══════════════════════════════════════════ الفئات وخطط الأسعار
class CategoryOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    kind: str
    base_occupancy: int
    max_occupancy: int
    base_rate: Decimal
    extra_adult_rate: Decimal
    extra_child_rate: Decimal
    unit_count: int = 0


class RatePlanOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    meal_plan: str
    is_public: bool


@router.get("/unit-categories", response_model=list[CategoryOut], summary="فئات الوحدات")
def categories(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[CategoryOut]:
    counts = dict(
        db.execute(
            select(Unit.category_id, func.count(Unit.id))
            .where(Unit.property_id == prop.id, Unit.is_active.is_(True))
            .group_by(Unit.category_id)
        ).all()
    )
    rows = db.execute(
        select(UnitCategory)
        .where(UnitCategory.property_id == prop.id, UnitCategory.is_active.is_(True))
        .order_by(UnitCategory.sort_order)
    ).scalars().all()
    return [
        CategoryOut(**{**c.__dict__, "unit_count": counts.get(c.id, 0)}) for c in rows
    ]


@router.get("/rate-plans", response_model=list[RatePlanOut], summary="خطط الأسعار")
def rate_plans(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[RatePlanOut]:
    rows = db.execute(
        select(RatePlan)
        .where(RatePlan.property_id == prop.id, RatePlan.is_active.is_(True))
        .order_by(RatePlan.sort_order)
    ).scalars().all()
    return [RatePlanOut.model_validate(r) for r in rows]


# ═══════════════════════════════════════════════ الإتاحة والتسعير
class AvailabilityRow(ApiModel):
    unit_category_id: int
    category_name_ar: str
    stay_date: date
    total: int
    sold: int
    available: int
    occupancy_percent: float
    is_closed: bool


class NightQuoteOut(ApiModel):
    stay_date: date
    published_rate: Decimal
    rate: Decimal
    extra_person_amount: Decimal
    applied_rules: list[str]


class QuoteOut(ApiModel):
    unit_category_id: int
    rate_plan_id: int
    arrival_date: date
    departure_date: date
    nights: int
    available: int
    is_available: bool
    room_total: Decimal
    extras_total: Decimal
    discount_total: Decimal
    service_charge_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    average_nightly_rate: Decimal
    nights_detail: list[NightQuoteOut]


@router.get("/availability", response_model=list[AvailabilityRow], summary="الإتاحة")
def availability(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    start: date | None = None,
    days: int = Query(default=30, ge=1, le=120),
) -> list[AvailabilityRow]:
    start_date = start or date.today()
    end_date = start_date + timedelta(days=days)

    names = {
        c.id: c.name_ar
        for c in db.execute(
            select(UnitCategory).where(UnitCategory.property_id == prop.id)
        ).scalars().all()
    }
    rows = av.get_availability(db, prop.id, start_date, end_date)
    return [
        AvailabilityRow(
            unit_category_id=r.unit_category_id,
            category_name_ar=names.get(r.unit_category_id, "—"),
            stay_date=r.stay_date,
            total=r.total_units,
            sold=r.sold_units,
            available=r.available,
            occupancy_percent=r.occupancy_percent,
            is_closed=r.is_closed,
        )
        for r in rows
    ]


@router.get("/quote", response_model=QuoteOut, summary="تسعيرة إقامة")
def quote(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    unit_category_id: int,
    rate_plan_id: int,
    arrival_date: date,
    departure_date: date,
    adults: int = Query(default=2, ge=1),
    children: int = Query(default=0, ge=0),
) -> QuoteOut:
    """تسعيرة قبل الحجز — بتوري السعر ليلة بليلة والقواعد اللي اتطبقت."""
    try:
        result = pricing.quote_stay(
            db,
            property_id=prop.id,
            unit_category_id=unit_category_id,
            rate_plan_id=rate_plan_id,
            arrival=arrival_date,
            departure=departure_date,
            adults=adults,
            children=children,
        )
    except pricing.PricingError as exc:
        raise HTTPException(
            400, {"ar": exc.message_ar, "en": exc.message_en, "code": "pricing_error"}
        ) from exc

    available = av.min_available(
        db, prop.id, unit_category_id, arrival_date, departure_date
    )

    return QuoteOut(
        unit_category_id=unit_category_id,
        rate_plan_id=rate_plan_id,
        arrival_date=arrival_date,
        departure_date=departure_date,
        nights=result.nights,
        available=available,
        is_available=available > 0,
        room_total=result.room_total,
        extras_total=result.extras_total,
        discount_total=result.discount_total,
        service_charge_total=result.service_charge_total,
        tax_total=result.tax_total,
        grand_total=result.grand_total,
        average_nightly_rate=result.average_nightly_rate,
        nights_detail=[
            NightQuoteOut(
                stay_date=n.stay_date,
                published_rate=n.published_rate,
                rate=n.rate,
                extra_person_amount=n.extra_person_amount,
                applied_rules=n.applied_rules,
            )
            for n in result.nights_detail
        ],
    )
