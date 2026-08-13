"""واجهات الإتاحة وقائمة الانتظار — Inventory control & waitlist.

الشاشة دي بتجاوب على سؤالين بيتسألوا كل يوم:

* **أبيع أكتر من اللي عندي ولا لأ؟** حد التجاوز وإغلاق البيع، مع عمود
  بيقول بالظبط كام وحدة اتباعت فوق السعة في كل يوم.
* **مين أكلّمه لما حجز يتلغي؟** قائمة الانتظار مرتّبة بالأولوية، وقدام كل
  طلب علامة إن التواريخ بقت متاحة فعلاً.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import (
    AuditAction,
    BookingSource,
    WaitlistPriority,
    WaitlistStatus,
)
from app.models.guests import Guest
from app.models.reservations import Reservation, WaitlistEntry
from app.models.units import Unit, UnitCategory
from app.schemas.common import ApiModel
from app.services import audit
from app.services import availability as av
from app.services import reservations as res_svc
from app.services import waitlist as wl
from app.services.availability import AvailabilityError
from app.services.pricing import PricingError

router = APIRouter(tags=["الإتاحة والانتظار — Inventory & Waitlist"])

#: أقصى حد تجاوز مسموح بيه إدارياً — فوق كده بقى مقامرة مش إدارة إيراد
MAX_OVERBOOKING = 10
#: أطول مدى يتعدّل مرة واحدة
MAX_CONTROL_DAYS = 365


# ═══════════════════════════════════════════════════════════ مساعدات
def _fail(exc: Exception) -> HTTPException:
    """تحويل أخطاء الخدمات لردود HTTP مفهومة بالعربي والإنجليزي."""
    if isinstance(exc, wl.WaitlistError):
        code = status.HTTP_400_BAD_REQUEST
        if exc.code == "not_found":
            code = status.HTTP_404_NOT_FOUND
        elif exc.code in {"duplicate", "already_offered", "closed", "no_availability"}:
            code = status.HTTP_409_CONFLICT
        return HTTPException(
            status_code=code,
            detail={"ar": exc.message_ar, "en": exc.message_en, "code": exc.code},
        )
    if isinstance(exc, res_svc.ReservationError):
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


# ═══════════════════════════════════════════════════════ لوحة الإتاحة
class InventoryCategory(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    total_units: int


class InventoryCell(ApiModel):
    unit_category_id: int
    stay_date: date
    total: int
    out_of_order: int
    sold: int
    held: int
    overbooking_limit: int
    is_closed: bool
    available: int
    #: كام وحدة اتباعت فوق السعة الحقيقية — فوق الصفر يعني في نزلاء بلا مكان
    oversold_by: int
    occupancy_percent: float


class InventorySummary(ApiModel):
    #: خانات فيها بيع زايد فعلي — دي اللي محتاجة تدخّل بشري
    oversold_cells: int
    closed_cells: int
    #: خانات مفعّل عليها حد تجاوز
    limited_cells: int
    #: خانات مفيش فيها ولا وحدة للبيع
    sold_out_cells: int
    waiting_count: int
    offered_count: int
    #: طلبات انتظار التواريخ بتاعتها بقت متاحة دلوقتي
    ready_count: int


class InventoryBoard(ApiModel):
    start_date: date
    end_date: date
    categories: list[InventoryCategory]
    cells: list[InventoryCell]
    summary: InventorySummary


class InventoryControlIn(ApiModel):
    start_date: date
    end_date: date
    #: فاضية = كل الفئات
    category_ids: list[int] = []
    overbooking_limit: int | None = None
    is_closed: bool | None = None


class ControlResult(ApiModel):
    ok: bool = True
    message_ar: str
    message_en: str
    rows_changed: int = 0


@router.get(
    "/inventory",
    response_model=InventoryBoard,
    summary="لوحة الإتاحة وحد التجاوز",
    dependencies=[Depends(require("rate.view"))],
)
def inventory_board(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    start: date | None = Query(default=None, description="افتراضياً النهاردة"),
    days: int = Query(default=30, ge=1, le=90),
    category_id: int | None = None,
) -> InventoryBoard:
    begin = start or date.today()
    end = begin + timedelta(days=days)

    cat_stmt = select(UnitCategory).where(
        UnitCategory.property_id == prop.id, UnitCategory.is_active.is_(True)
    )
    if category_id:
        cat_stmt = cat_stmt.where(UnitCategory.id == category_id)
    cats = list(db.execute(cat_stmt.order_by(UnitCategory.sort_order)).scalars().all())
    cat_ids = [c.id for c in cats]

    unit_counts = dict(
        db.execute(
            select(Unit.category_id, func.count(Unit.id))
            .where(Unit.property_id == prop.id, Unit.is_active.is_(True))
            .group_by(Unit.category_id)
        ).all()
    )

    # الصفوف الناقصة بتتعمل هنا — أول فتح لشهر جديد بيبقى جاهز
    av.ensure_calendar(db, prop.id, begin, end, cat_ids)
    rows = av.get_availability(db, prop.id, begin, end, cat_ids)

    cells = [
        InventoryCell(
            unit_category_id=r.unit_category_id,
            stay_date=r.stay_date,
            total=r.total_units,
            out_of_order=r.out_of_order,
            sold=r.sold_units,
            held=r.held_units,
            overbooking_limit=r.overbooking_limit,
            is_closed=r.is_closed,
            available=r.available,
            oversold_by=r.oversold_by,
            occupancy_percent=r.occupancy_percent,
        )
        for r in rows
    ]

    # عدّادات قائمة الانتظار — نفس الأرقام اللي بتظهر في التبويب التاني
    wl.expire_offers(db, prop.id)
    wl.expire_stale(db, prop.id)
    open_entries = wl.list_entries(db, prop.id)
    waiting = [e for e in open_entries if e.status == WaitlistStatus.WAITING]
    offered = [e for e in open_entries if e.status == WaitlistStatus.OFFERED]
    matches = wl.match_all(db, prop.id, waiting)

    return InventoryBoard(
        start_date=begin,
        end_date=end,
        categories=[
            InventoryCategory(
                id=c.id,
                code=c.code,
                name_ar=c.name_ar,
                name_en=c.name_en,
                total_units=unit_counts.get(c.id, 0),
            )
            for c in cats
        ],
        cells=cells,
        summary=InventorySummary(
            oversold_cells=sum(1 for c in cells if c.oversold_by > 0),
            closed_cells=sum(1 for c in cells if c.is_closed),
            limited_cells=sum(1 for c in cells if c.overbooking_limit > 0),
            sold_out_cells=sum(1 for c in cells if c.available == 0 and not c.is_closed),
            waiting_count=len(waiting),
            offered_count=len(offered),
            ready_count=sum(1 for m in matches.values() if m is not None),
        ),
    )


@router.patch(
    "/inventory",
    response_model=ControlResult,
    summary="ضبط حد التجاوز وإغلاق البيع",
    dependencies=[Depends(require("rate.edit"))],
)
def set_controls(
    payload: InventoryControlIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ControlResult:
    if payload.end_date <= payload.start_date:
        raise HTTPException(
            status_code=400,
            detail={
                "ar": "تاريخ النهاية لازم يكون بعد البداية",
                "en": "End date must be after the start date",
            },
        )
    if (payload.end_date - payload.start_date).days > MAX_CONTROL_DAYS:
        raise HTTPException(
            status_code=400,
            detail={
                "ar": f"أطول مدى مسموح بيه {MAX_CONTROL_DAYS} يوم",
                "en": f"The longest range allowed is {MAX_CONTROL_DAYS} days",
            },
        )
    if payload.overbooking_limit is None and payload.is_closed is None:
        raise HTTPException(
            status_code=400,
            detail={"ar": "محدّدتش أي تعديل", "en": "Nothing to change"},
        )

    cat_stmt = select(UnitCategory).where(
        UnitCategory.property_id == prop.id, UnitCategory.is_active.is_(True)
    )
    if payload.category_ids:
        cat_stmt = cat_stmt.where(UnitCategory.id.in_(payload.category_ids))
    cats = list(db.execute(cat_stmt).scalars().all())
    if not cats:
        raise HTTPException(
            status_code=404,
            detail={"ar": "مفيش فئات مطابقة", "en": "No matching categories"},
        )
    cat_ids = [c.id for c in cats]

    if payload.overbooking_limit is not None:
        limit = payload.overbooking_limit
        if not 0 <= limit <= MAX_OVERBOOKING:
            raise HTTPException(
                status_code=400,
                detail={
                    "ar": f"حد التجاوز لازم يكون بين صفر و{MAX_OVERBOOKING}",
                    "en": f"Overbooking limit must be between 0 and {MAX_OVERBOOKING}",
                },
            )
        # حد تجاوز أكبر من عدد وحدات الفئة نفسها مالوش أي معنى
        smallest = min(
            db.execute(
                select(func.count(Unit.id))
                .where(
                    Unit.property_id == prop.id,
                    Unit.is_active.is_(True),
                    Unit.category_id == cid,
                )
            ).scalar_one()
            for cid in cat_ids
        )
        if limit > smallest:
            raise HTTPException(
                status_code=400,
                detail={
                    "ar": f"أصغر فئة في اختيارك فيها {smallest} وحدة بس — الحد لازم يكون أقل",
                    "en": f"The smallest selected category has {smallest} units — the limit must be lower",
                },
            )

    av.ensure_calendar(db, prop.id, payload.start_date, payload.end_date, cat_ids)

    changed = 0
    parts_ar: list[str] = []
    parts_en: list[str] = []

    if payload.overbooking_limit is not None:
        changed += av.set_overbooking(
            db, prop.id, payload.start_date, payload.end_date,
            payload.overbooking_limit, cat_ids,
        )
        parts_ar.append(f"حد التجاوز {payload.overbooking_limit}")
        parts_en.append(f"overbooking limit {payload.overbooking_limit}")

    if payload.is_closed is not None:
        changed += av.set_closed(
            db, prop.id, payload.start_date, payload.end_date, payload.is_closed, cat_ids
        )
        parts_ar.append("قفل البيع" if payload.is_closed else "فتح البيع")
        parts_en.append("stop sell" if payload.is_closed else "open sell")

    names = "، ".join(c.name_ar for c in cats)
    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="AvailabilityCalendar",
        entity_id=prop.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"{' و'.join(parts_ar)} — {names} من {payload.start_date} لـ {payload.end_date}",
        summary_en=f"{' and '.join(parts_en)} — {payload.start_date} to {payload.end_date}",
        changes={
            "overbooking_limit": {"from": None, "to": payload.overbooking_limit},
            "is_closed": {"from": None, "to": payload.is_closed},
        },
        request=request,
    )
    return ControlResult(
        message_ar=f"تم تطبيق {' و'.join(parts_ar)} على {len(cats)} فئة",
        message_en=f"Applied {' and '.join(parts_en)} to {len(cats)} categories",
        rows_changed=changed,
    )


# ═══════════════════════════════════════════════════════ قائمة الانتظار
class WaitlistOut(ApiModel):
    id: int
    guest_id: int
    guest_name: str
    guest_phone: str | None = None
    is_vip: bool = False
    unit_category_id: int
    category_name_ar: str
    category_name_en: str
    rate_plan_id: int | None = None
    arrival_date: date
    departure_date: date
    nights: int
    adults: int
    children: int
    flexible_days: int
    status: WaitlistStatus
    priority: WaitlistPriority
    source: BookingSource
    quoted_total: Decimal
    contact_note: str | None = None
    offered_at: datetime | None = None
    offer_expires_at: datetime | None = None
    offered_arrival: date | None = None
    offered_departure: date | None = None
    converted_reservation_id: int | None = None
    converted_reservation_code: str | None = None
    created_at: datetime | None = None
    #: محسوب لحظياً — هل فيه مكان فاضي دلوقتي؟
    has_match: bool = False
    match_arrival: date | None = None
    match_departure: date | None = None
    #: بكام يوم زحلقنا التواريخ عن طلبه — صفر يعني بالظبط
    match_shift_days: int | None = None


class WaitlistPage(ApiModel):
    items: list[WaitlistOut]
    waiting_count: int
    offered_count: int
    ready_count: int


class AddWaitlistIn(ApiModel):
    guest_id: int
    unit_category_id: int
    arrival_date: date
    departure_date: date
    adults: int = 2
    children: int = 0
    rate_plan_id: int | None = None
    flexible_days: int = 0
    priority: WaitlistPriority = WaitlistPriority.NORMAL
    source: BookingSource = BookingSource.DIRECT
    contact_note: str | None = None


class OfferIn(ApiModel):
    hours: int = wl.DEFAULT_OFFER_HOURS


class ConvertIn(ApiModel):
    rate_plan_id: int | None = None
    unit_id: int | None = None
    deposit_paid: Decimal = Decimal("0")


class ReasonIn(ApiModel):
    reason: str | None = None


class WaitlistResult(ApiModel):
    ok: bool = True
    message_ar: str
    message_en: str
    entry: WaitlistOut | None = None
    reservation_id: int | None = None
    reservation_code: str | None = None


def _to_out(
    entry: WaitlistEntry,
    guest: Guest | None,
    category: UnitCategory | None,
    match: wl.Match | None = None,
    reservation_code: str | None = None,
) -> WaitlistOut:
    return WaitlistOut(
        id=entry.id,
        guest_id=entry.guest_id,
        guest_name=guest.full_name if guest else "—",
        guest_phone=guest.phone if guest else None,
        is_vip=bool(guest.is_vip) if guest else False,
        unit_category_id=entry.unit_category_id,
        category_name_ar=category.name_ar if category else "—",
        category_name_en=category.name_en if category else "—",
        rate_plan_id=entry.rate_plan_id,
        arrival_date=entry.arrival_date,
        departure_date=entry.departure_date,
        nights=entry.nights,
        adults=entry.adults,
        children=entry.children,
        flexible_days=entry.flexible_days,
        status=entry.status,
        priority=entry.priority,
        source=entry.source,
        quoted_total=entry.quoted_total,
        contact_note=entry.contact_note,
        offered_at=entry.offered_at,
        offer_expires_at=entry.offer_expires_at,
        offered_arrival=entry.offered_arrival,
        offered_departure=entry.offered_departure,
        converted_reservation_id=entry.converted_reservation_id,
        converted_reservation_code=reservation_code,
        created_at=entry.created_at,
        has_match=match is not None,
        match_arrival=match.arrival if match else None,
        match_departure=match.departure if match else None,
        match_shift_days=match.shift_days if match else None,
    )


def _lookup(db, entries: list[WaitlistEntry]) -> tuple[dict[int, Guest], dict[int, UnitCategory]]:
    if not entries:
        return {}, {}
    guests = {
        g.id: g
        for g in db.execute(
            select(Guest).where(Guest.id.in_({e.guest_id for e in entries}))
        ).scalars().all()
    }
    cats = {
        c.id: c
        for c in db.execute(
            select(UnitCategory).where(
                UnitCategory.id.in_({e.unit_category_id for e in entries})
            )
        ).scalars().all()
    }
    return guests, cats


def _single(db, entry: WaitlistEntry, reservation: Reservation | None = None) -> WaitlistOut:
    guests, cats = _lookup(db, [entry])
    return _to_out(
        entry,
        guests.get(entry.guest_id),
        cats.get(entry.unit_category_id),
        reservation_code=reservation.code if reservation else None,
    )


@router.get(
    "/waitlist",
    response_model=WaitlistPage,
    summary="قائمة الانتظار",
    dependencies=[Depends(require("reservation.view"))],
)
def list_waitlist(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    status_filter: WaitlistStatus | None = Query(default=None, alias="status"),
    unit_category_id: int | None = None,
    arrival_from: date | None = None,
    arrival_to: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> WaitlistPage:
    # العروض اللي عدّت مهلتها بترجع الوحدة للبيع قبل أي قراءة
    wl.expire_offers(db, prop.id)
    wl.expire_stale(db, prop.id)
    entries = wl.list_entries(
        db,
        prop.id,
        statuses=[status_filter] if status_filter else None,
        unit_category_id=unit_category_id,
        arrival_from=arrival_from,
        arrival_to=arrival_to,
        limit=limit,
    )
    guests, cats = _lookup(db, entries)

    # الطلب المعروض حاجز الوحدة بنفسه، فحساب المطابقة له ملوش لازمة
    pending = [e for e in entries if e.status == WaitlistStatus.WAITING]
    matches = wl.match_all(db, prop.id, pending)

    codes = {}
    converted_ids = {e.converted_reservation_id for e in entries if e.converted_reservation_id}
    if converted_ids:
        codes = dict(
            db.execute(
                select(Reservation.id, Reservation.code).where(Reservation.id.in_(converted_ids))
            ).all()
        )

    items = [
        _to_out(
            e,
            guests.get(e.guest_id),
            cats.get(e.unit_category_id),
            match=matches.get(e.id),
            reservation_code=codes.get(e.converted_reservation_id),
        )
        for e in entries
    ]

    return WaitlistPage(
        items=items,
        waiting_count=sum(1 for e in entries if e.status == WaitlistStatus.WAITING),
        offered_count=sum(1 for e in entries if e.status == WaitlistStatus.OFFERED),
        ready_count=sum(1 for m in matches.values() if m is not None),
    )


@router.post(
    "/waitlist",
    response_model=WaitlistOut,
    status_code=status.HTTP_201_CREATED,
    summary="تسجيل طلب في الانتظار",
    dependencies=[Depends(require("reservation.create"))],
)
def add_to_waitlist(
    payload: AddWaitlistIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> WaitlistOut:
    try:
        entry = wl.add(
            db,
            property_id=prop.id,
            guest_id=payload.guest_id,
            unit_category_id=payload.unit_category_id,
            arrival=payload.arrival_date,
            departure=payload.departure_date,
            adults=payload.adults,
            children=payload.children,
            rate_plan_id=payload.rate_plan_id,
            flexible_days=payload.flexible_days,
            priority=payload.priority,
            source=payload.source,
            contact_note=payload.contact_note,
            created_by_user_id=user.id,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="WaitlistEntry",
        entity_id=entry.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"طلب انتظار من {entry.arrival_date} لـ {entry.departure_date}",
        summary_en=f"Waitlisted {entry.arrival_date} → {entry.departure_date}",
        request=request,
    )
    return _single(db, entry)


@router.post(
    "/waitlist/{entry_id}/offer",
    response_model=WaitlistResult,
    summary="عرض المكان وحجزه مؤقتاً",
    dependencies=[Depends(require("reservation.edit"))],
)
def offer_place(
    entry_id: int,
    payload: OfferIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> WaitlistResult:
    try:
        entry = wl.offer(db, entry_id, hours=payload.hours, user_id=user.id)
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="WaitlistEntry",
        entity_id=entry.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"عرض مكان {entry.offered_arrival} → {entry.offered_departure} لمدة {payload.hours} ساعة",
        summary_en=f"Offered {entry.offered_arrival} → {entry.offered_departure} for {payload.hours}h",
        request=request,
    )
    return WaitlistResult(
        message_ar=f"تم حجز المكان مؤقتاً لمدة {payload.hours} ساعة",
        message_en=f"Place held for {payload.hours} hours",
        entry=_single(db, entry),
    )


@router.post(
    "/waitlist/{entry_id}/withdraw",
    response_model=WaitlistResult,
    summary="سحب العرض",
    dependencies=[Depends(require("reservation.edit"))],
)
def withdraw(
    entry_id: int,
    payload: ReasonIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> WaitlistResult:
    try:
        entry = wl.withdraw_offer(db, entry_id, reason=payload.reason)
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="WaitlistEntry",
        entity_id=entry.id,
        user=user,
        property_id=prop.id,
        summary_ar="سحب العرض ورجوع الوحدة للبيع",
        summary_en="Offer withdrawn, unit returned to sale",
        request=request,
    )
    return WaitlistResult(
        message_ar="تم سحب العرض والوحدة رجعت للبيع",
        message_en="Offer withdrawn and the unit is back on sale",
        entry=_single(db, entry),
    )


@router.post(
    "/waitlist/{entry_id}/convert",
    response_model=WaitlistResult,
    summary="تحويل الطلب لحجز",
    dependencies=[Depends(require("reservation.create"))],
)
def convert_entry(
    entry_id: int,
    payload: ConvertIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> WaitlistResult:
    try:
        entry, reservation = wl.convert(
            db,
            entry_id,
            rate_plan_id=payload.rate_plan_id,
            deposit_paid=payload.deposit_paid,
            unit_id=payload.unit_id,
            user_id=user.id,
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
        summary_ar=f"تحويل طلب انتظار لحجز {reservation.code}",
        summary_en=f"Converted waitlist entry to reservation {reservation.code}",
        changes={"waitlist_entry_id": {"from": None, "to": entry.id}},
        request=request,
    )
    return WaitlistResult(
        message_ar=f"تم تحويل الطلب للحجز {reservation.code}",
        message_en=f"Converted to reservation {reservation.code}",
        entry=_single(db, entry, reservation),
        reservation_id=reservation.id,
        reservation_code=reservation.code,
    )


@router.post(
    "/waitlist/{entry_id}/cancel",
    response_model=WaitlistResult,
    summary="شطب الطلب",
    dependencies=[Depends(require("reservation.edit"))],
)
def cancel_entry(
    entry_id: int,
    payload: ReasonIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> WaitlistResult:
    try:
        entry = wl.cancel(db, entry_id, reason=payload.reason, user_id=user.id)
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="WaitlistEntry",
        entity_id=entry.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"شطب طلب انتظار — {payload.reason or 'بدون سبب'}",
        summary_en=f"Waitlist entry cancelled — {payload.reason or 'no reason'}",
        request=request,
    )
    return WaitlistResult(
        message_ar="تم شطب الطلب",
        message_en="Waitlist entry cancelled",
        entry=_single(db, entry),
    )
