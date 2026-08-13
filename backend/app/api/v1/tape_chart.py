"""شاشة الحجوزات — Tape chart endpoint.

استدعاء واحد بيرجّع كل اللي الشاشة محتاجاه: الأعمدة، الفئات، الوحدات، شرائط
الحجوزات، الإتاحة، والحجوزات اللي لسه متخصصتش. الواجهة بتعمل طلب واحد بس.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession
from app.models.enums import BLOCKING_RESERVATION_STATUSES, ReservationStatus
from app.models.guests import Guest
from app.models.reservations import (
    AvailabilityCalendar,
    Reservation,
    ReservationUnit,
)
from app.models.units import Unit, UnitCategory
from app.schemas.common import ApiModel, DayCell, build_day

router = APIRouter(prefix="/tape-chart", tags=["شاشة الحجوزات — Tape Chart"])

MAX_DAYS = 60


class UnitRow(ApiModel):
    id: int
    label: str
    zone_ar: str | None = None
    zone_en: str | None = None
    housekeeping_status: str
    condition: str
    is_sellable: bool


class CategoryGroup(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    unit_count: int
    sold_today: int = 0
    units: list[UnitRow]


class Bar(ApiModel):
    """شريط حجز على الشبكة."""

    id: int
    reservation_id: int
    code: str
    unit_id: int | None
    unit_category_id: int
    guest_name: str
    guest_id: int
    arrival_date: date
    departure_date: date
    nights: int
    adults: int
    children: int
    status: ReservationStatus
    source: str
    balance: Decimal
    is_vip: bool = False
    #: موضع الشريط على الشبكة — الواجهة مبتحسبش تواريخ
    start_index: int
    span: int


class DayAvailabilityOut(ApiModel):
    date: date
    unit_category_id: int
    available: int
    sold: int
    total: int
    occupancy_percent: float
    is_closed: bool


class Summary(ApiModel):
    occupancy_percent: float
    total_units: int
    sold_units: int
    out_of_order: int
    arrivals_today: int
    departures_today: int
    in_house: int
    unassigned_count: int


class TapeChartOut(ApiModel):
    start_date: date
    end_date: date
    today: date
    days: list[DayCell]
    categories: list[CategoryGroup]
    bars: list[Bar]
    unassigned: list[Bar]
    availability: list[DayAvailabilityOut]
    summary: Summary


@router.get("", response_model=TapeChartOut, summary="بيانات شاشة الحجوزات كاملة")
def get_tape_chart(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    start: date | None = Query(default=None, description="أول يوم — افتراضياً النهاردة"),
    days: int = Query(default=14, ge=1, le=MAX_DAYS, description="عدد الأيام المعروضة"),
) -> TapeChartOut:
    today = date.today()
    start_date = start or today
    end_date = start_date + timedelta(days=days)

    if days > MAX_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ar": f"أقصى مدى {MAX_DAYS} يوم", "en": f"Maximum range is {MAX_DAYS} days"},
        )

    day_list = [start_date + timedelta(days=i) for i in range(days)]
    day_index = {d: i for i, d in enumerate(day_list)}

    # ── الفئات والوحدات ─────────────────────────────────────────────
    categories = list(
        db.execute(
            select(UnitCategory)
            .where(UnitCategory.property_id == prop.id, UnitCategory.is_active.is_(True))
            .order_by(UnitCategory.sort_order, UnitCategory.id)
        ).scalars().all()
    )
    units = list(
        db.execute(
            select(Unit)
            .where(Unit.property_id == prop.id, Unit.is_active.is_(True))
            .order_by(Unit.category_id, Unit.sort_order, Unit.id)
        ).scalars().all()
    )

    units_by_cat: dict[int, list[Unit]] = {c.id: [] for c in categories}
    for unit in units:
        units_by_cat.setdefault(unit.category_id, []).append(unit)

    # ── شرائط الحجوزات المتقاطعة مع المدى ───────────────────────────
    rows = db.execute(
        select(
            ReservationUnit.id,
            ReservationUnit.reservation_id,
            ReservationUnit.unit_id,
            ReservationUnit.unit_category_id,
            ReservationUnit.arrival_date,
            ReservationUnit.departure_date,
            ReservationUnit.nights,
            ReservationUnit.adults,
            ReservationUnit.children,
            ReservationUnit.status,
            Reservation.code,
            Reservation.source,
            Reservation.balance,
            Guest.id.label("guest_id"),
            Guest.first_name,
            Guest.last_name,
            Guest.is_vip,
        )
        .join(Reservation, Reservation.id == ReservationUnit.reservation_id)
        .join(Guest, Guest.id == Reservation.guest_id)
        .where(
            ReservationUnit.property_id == prop.id,
            ReservationUnit.arrival_date < end_date,
            ReservationUnit.departure_date > start_date,
            ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
        )
        .order_by(ReservationUnit.unit_id, ReservationUnit.arrival_date)
    ).all()

    def to_bar(r) -> Bar:
        visible_start = max(r.arrival_date, start_date)
        visible_end = min(r.departure_date, end_date)
        return Bar(
            id=r.id,
            reservation_id=r.reservation_id,
            code=r.code,
            unit_id=r.unit_id,
            unit_category_id=r.unit_category_id,
            guest_name=f"{r.first_name} {r.last_name}".strip(),
            guest_id=r.guest_id,
            arrival_date=r.arrival_date,
            departure_date=r.departure_date,
            nights=r.nights,
            adults=r.adults,
            children=r.children,
            status=r.status,
            source=r.source,
            balance=r.balance,
            is_vip=bool(r.is_vip),
            start_index=day_index.get(visible_start, 0),
            span=max(1, (visible_end - visible_start).days),
        )

    bars = [to_bar(r) for r in rows if r.unit_id is not None]
    unassigned = [to_bar(r) for r in rows if r.unit_id is None]

    # ── الإتاحة ─────────────────────────────────────────────────────
    availability_rows = db.execute(
        select(AvailabilityCalendar)
        .where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.stay_date >= start_date,
            AvailabilityCalendar.stay_date < end_date,
        )
        .order_by(AvailabilityCalendar.unit_category_id, AvailabilityCalendar.stay_date)
    ).scalars().all()

    availability = [
        DayAvailabilityOut(
            date=row.stay_date,
            unit_category_id=row.unit_category_id,
            available=row.available_units,
            sold=row.sold_units,
            total=row.total_units,
            occupancy_percent=(
                round(row.sold_units / (row.total_units - row.out_of_order) * 100, 1)
                if (row.total_units - row.out_of_order) > 0 else 0.0
            ),
            is_closed=row.is_closed,
        )
        for row in availability_rows
    ]

    # ── الملخّص ─────────────────────────────────────────────────────
    sold_today_by_cat: dict[int, int] = {}
    for row in availability_rows:
        if row.stay_date == today:
            sold_today_by_cat[row.unit_category_id] = row.sold_units

    total_units = len(units)
    out_of_order = sum(1 for u in units if not u.is_sellable)
    sold_today = sum(sold_today_by_cat.values())
    sellable = max(0, total_units - out_of_order)

    arrivals_today = db.execute(
        select(Reservation.id)
        .where(
            Reservation.property_id == prop.id,
            Reservation.arrival_date == today,
            Reservation.status.in_(
                [ReservationStatus.CONFIRMED, ReservationStatus.TENTATIVE,
                 ReservationStatus.CHECKED_IN]
            ),
        )
    ).all()
    departures_today = db.execute(
        select(Reservation.id)
        .where(
            Reservation.property_id == prop.id,
            Reservation.departure_date == today,
            Reservation.status.in_(
                [ReservationStatus.CHECKED_IN, ReservationStatus.CHECKED_OUT]
            ),
        )
    ).all()

    group_list = [
        CategoryGroup(
            id=cat.id,
            code=cat.code,
            name_ar=cat.name_ar,
            name_en=cat.name_en,
            unit_count=len(units_by_cat.get(cat.id, [])),
            sold_today=sold_today_by_cat.get(cat.id, 0),
            units=[
                UnitRow(
                    id=u.id,
                    label=u.label,
                    zone_ar=u.zone_ar,
                    zone_en=u.zone_en,
                    housekeeping_status=u.housekeeping_status,
                    condition=u.condition,
                    is_sellable=u.is_sellable,
                )
                for u in units_by_cat.get(cat.id, [])
            ],
        )
        for cat in categories
    ]

    return TapeChartOut(
        start_date=start_date,
        end_date=end_date,
        today=today,
        days=[build_day(d, today) for d in day_list],
        categories=group_list,
        bars=bars,
        unassigned=unassigned,
        availability=availability,
        summary=Summary(
            occupancy_percent=round(sold_today / sellable * 100, 1) if sellable else 0.0,
            total_units=total_units,
            sold_units=sold_today,
            out_of_order=out_of_order,
            arrivals_today=len(arrivals_today),
            departures_today=len(departures_today),
            in_house=sold_today,
            unassigned_count=len(unassigned),
        ),
    )
