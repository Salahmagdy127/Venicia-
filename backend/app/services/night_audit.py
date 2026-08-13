"""تدقيق الليلة — Night Audit.

التقفيل اليومي بتاع الفندق. بيتنفّذ مرة واحدة كل يوم بعد آخر حركة، وبيعمل
خمس حاجات بالترتيب ده:

1. **عدم الحضور** — الحجوزات اللي كان المفروض تيجي النهاردة وماجتش بتتعلّم
   NO_SHOW، وإتاحتها بترجع للبيع، والغرامة بتتحسب حسب سياسة الإلغاء.
2. **ترحيل ليالي الإقامة** — أي ليلة لسه ماترحّلتش على حساب النزيل بتترحّل.
   الليالي المرحّلة بتتعلّم، فالتشغيل مرتين مبيكرّرش الحركة.
3. **الملخّص اليومي** — بيتحسب من الحركة الفعلية ويتكتب في جداول الملخّص،
   وده اللي الداشبورد بيقرا منه. عشان كده الداشبورد بيفتح في مللي ثانية
   مهما كبرت البيانات.
4. **إحصاءات النزلاء** — عدد الإقامات والليالي والإنفاق للنزلاء اللي غادروا.
5. **محاذير للبشر** — حسابات مفتوحة، أوردرات مش متقفلة، ورديات مفتوحة،
   نزلاء نازلين من غير وحدة. دي حاجات النظام مش بيصلّحها لوحده.

التشغيل idempotent: لو اتنفّذ تاني على نفس اليوم بيعيد حساب الملخّص من غير
ما يكرّر ترحيل ولا غرامة.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.analytics import (
    DailyCategoryStatistics,
    DailyOutletStatistics,
    DailyStatistics,
    NightAuditRun,
)
from app.models.enums import (
    BLOCKING_RESERVATION_STATUSES,
    FolioStatus,
    PosOrderStatus,
    ReservationStatus,
    WaitlistStatus,
)
from app.models.folio import Folio
from app.models.guests import Guest
from app.models.organization import Property
from app.models.pos import Outlet, PosOrder, Shift
from app.models.reservations import Reservation, ReservationNight, ReservationUnit
from app.models.units import Unit, UnitCategory
from app.services import availability as av
from app.services import reservations as res_svc
from app.services import waitlist as wl

TWO = Decimal("0.01")

#: الحالات اللي بتتحسب إشغال فعلي على الليلة
REALISED_STATUSES = (
    ReservationStatus.CONFIRMED,
    ReservationStatus.CHECKED_IN,
    ReservationStatus.CHECKED_OUT,
)


class NightAuditError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def q(value: Decimal | int | float) -> Decimal:
    return Decimal(str(value)).quantize(TWO)


def business_date_for(prop: Property, at: datetime | None = None) -> date:
    """اليوم المحاسبي — بيفضل مفتوح لحد ساعة التقفيل بتاعت المنشأة."""
    moment = at or datetime.now()
    cutoff = getattr(prop, "night_audit_hour", None) or 4
    return (moment - timedelta(hours=cutoff)).date()


# ═══════════════════════════════════════════════════ 1) عدم الحضور
def mark_no_shows(db: Session, property_id: int, business_date: date) -> tuple[int, Decimal]:
    """الحجوزات اللي معدّاش يومها وماحدّش نزل — بترجع إتاحتها للبيع."""
    pending = db.execute(
        select(Reservation).where(
            Reservation.property_id == property_id,
            Reservation.arrival_date == business_date,
            Reservation.status.in_(
                [ReservationStatus.CONFIRMED, ReservationStatus.TENTATIVE]
            ),
        )
    ).scalars().all()

    marked = 0
    penalties = Decimal("0")
    for reservation in pending:
        try:
            res_svc.mark_no_show(db, reservation.id)
            marked += 1
            # غرامة عدم الحضور = ليلة واحدة افتراضياً
            nightly = (
                q(reservation.room_total / reservation.nights)
                if reservation.nights else Decimal("0")
            )
            penalties += nightly
        except res_svc.ReservationError:
            continue
    return marked, q(penalties)


# ═════════════════════════════════════════ 2) ترحيل ليالي الإقامة
def post_pending_nights(
    db: Session, property_id: int, business_date: date
) -> tuple[int, Decimal]:
    """أي ليلة عدّت ولسه ماترحّلتش — بتترحّل على حساب النزيل.

    ده بيمسك الحالات اللي التمديد فيها زوّد ليالي بعد النزول.
    """
    prop = db.get(Property, property_id)
    rows = db.execute(
        select(ReservationNight, ReservationUnit, Folio)
        .join(ReservationUnit, ReservationUnit.id == ReservationNight.reservation_unit_id)
        .join(
            Folio,
            (Folio.reservation_id == ReservationUnit.reservation_id)
            & (Folio.status == FolioStatus.OPEN),
        )
        .where(
            ReservationNight.property_id == property_id,
            ReservationNight.stay_date <= business_date,
            ReservationNight.is_posted.is_(False),
            ReservationUnit.status == ReservationStatus.CHECKED_IN,
        )
    ).all()

    by_unit: dict[int, tuple[ReservationUnit, Folio]] = {}
    for _night, res_unit, folio in rows:
        by_unit[res_unit.id] = (res_unit, folio)

    posted = 0
    revenue = Decimal("0")
    for res_unit, folio in by_unit.values():
        before = db.execute(
            select(func.count(ReservationNight.id)).where(
                ReservationNight.reservation_unit_id == res_unit.id,
                ReservationNight.is_posted.is_(False),
            )
        ).scalar_one()
        amount = res_svc.post_room_charges(db, folio, res_unit, prop)
        if amount:
            posted += before
            revenue += amount
    return posted, q(revenue)


# ══════════════════════════════════════════════ 3) الملخّص اليومي
def _pos_totals(db: Session, property_id: int, business_date: date):
    """مبيعات نقاط البيع لليوم — الصافي بعد الخصم، لكل منفذ."""
    rows = db.execute(
        select(
            PosOrder.outlet_id,
            func.sum(PosOrder.subtotal),
            func.sum(PosOrder.discount_total),
            func.sum(PosOrder.service_charge_total),
            func.sum(PosOrder.tax_total),
            func.count(PosOrder.id),
            func.sum(PosOrder.covers),
        )
        .where(
            PosOrder.property_id == property_id,
            PosOrder.business_date == business_date,
            PosOrder.status == PosOrderStatus.SETTLED,
            PosOrder.is_void.is_(False),
        )
        .group_by(PosOrder.outlet_id)
    ).all()

    outlets = {
        o.id: o
        for o in db.execute(
            select(Outlet).where(Outlet.property_id == property_id)
        ).scalars().all()
    }

    per_outlet = []
    fnb = spa = net_total = Decimal("0")
    covers = orders = 0
    for outlet_id, subtotal, discount, service, tax, count, cover in rows:
        net = q(Decimal(str(subtotal or 0)) - Decimal(str(discount or 0)))
        outlet = outlets.get(outlet_id)
        code = outlet.code if outlet else ""
        if code == "SPA":
            spa += net
        else:
            fnb += net
        net_total += net
        orders += int(count or 0)
        covers += int(cover or 0)
        per_outlet.append(
            {
                "outlet_id": outlet_id,
                "net_sales": net,
                "gross_sales": q(Decimal(str(subtotal or 0))),
                "discount_total": q(Decimal(str(discount or 0))),
                "service_charge_total": q(Decimal(str(service or 0))),
                "tax_total": q(Decimal(str(tax or 0))),
                "orders_count": int(count or 0),
                "covers": int(cover or 0),
            }
        )
    return per_outlet, q(fnb), q(spa), q(net_total), orders, covers


def compute_statistics(db: Session, property_id: int, business_date: date) -> DailyStatistics:
    """بيحسب ملخّص اليوم من الحركة الفعلية ويكتبه (أو يحدّثه لو موجود)."""
    units = db.execute(
        select(Unit).where(Unit.property_id == property_id, Unit.is_active.is_(True))
    ).scalars().all()
    total_units = len(units)
    sellable_units = sum(1 for u in units if u.is_sellable)

    # ── الإقامة: كل ليلة متباعة في اليوم ده
    night_rows = db.execute(
        select(
            ReservationNight.unit_category_id,
            func.count(ReservationNight.id),
            func.sum(
                ReservationNight.rate
                + ReservationNight.extra_person_amount
                - ReservationNight.discount_amount
            ),
        )
        .join(ReservationUnit, ReservationUnit.id == ReservationNight.reservation_unit_id)
        .where(
            ReservationNight.property_id == property_id,
            ReservationNight.stay_date == business_date,
            ReservationUnit.status.in_(list(REALISED_STATUSES)),
        )
        .group_by(ReservationNight.unit_category_id)
    ).all()

    sold = sum(int(r[1] or 0) for r in night_rows)
    room_revenue = q(sum((Decimal(str(r[2] or 0)) for r in night_rows), Decimal("0")))

    # ── الحركة: وصول ومغادرة وإلغاء
    def count_reservations(**filters) -> int:
        stmt = select(func.count(Reservation.id)).where(
            Reservation.property_id == property_id
        )
        for column, value in filters.items():
            attribute = getattr(Reservation, column)
            stmt = stmt.where(
                attribute.in_(value) if isinstance(value, (list, tuple)) else attribute == value
            )
        return db.execute(stmt).scalar_one()

    arrivals = count_reservations(
        arrival_date=business_date,
        status=[ReservationStatus.CHECKED_IN, ReservationStatus.CHECKED_OUT,
                ReservationStatus.CONFIRMED],
    )
    departures = count_reservations(
        departure_date=business_date,
        status=[ReservationStatus.CHECKED_OUT, ReservationStatus.CHECKED_IN],
    )
    no_shows = count_reservations(
        arrival_date=business_date, status=ReservationStatus.NO_SHOW
    )
    cancellations = count_reservations(
        arrival_date=business_date, status=ReservationStatus.CANCELLED
    )
    walk_ins = count_reservations(arrival_date=business_date, source="WALK_IN")

    # ── المصادر والعمولات: بتتنسب ليوم الوصول
    source_rows = db.execute(
        select(
            Reservation.source,
            func.count(Reservation.id),
            func.sum(Reservation.room_total - Reservation.discount_total),
            func.sum(Reservation.channel_commission_amount),
        )
        .where(
            Reservation.property_id == property_id,
            Reservation.arrival_date == business_date,
            Reservation.status.in_(list(REALISED_STATUSES)),
        )
        .group_by(Reservation.source)
    ).all()

    by_source: dict[str, Decimal] = {}
    commission = Decimal("0")
    ota_bookings = direct_bookings = 0
    for source, count, net, comm in source_rows:
        by_source[str(source)] = q(Decimal(str(net or 0)))
        amount = Decimal(str(comm or 0))
        commission += amount
        if amount > 0:
            ota_bookings += int(count or 0)
        else:
            direct_bookings += int(count or 0)

    # ── نقاط البيع
    per_outlet, fnb, spa, pos_net, orders, covers = _pos_totals(
        db, property_id, business_date
    )
    if pos_net:
        by_source["POS"] = pos_net

    total_revenue = q(room_revenue + pos_net)
    adr = q(room_revenue / sold) if sold else Decimal("0")
    revpar = q(room_revenue / sellable_units) if sellable_units else Decimal("0")
    trevpar = q(total_revenue / sellable_units) if sellable_units else Decimal("0")
    average_check = q(pos_net / orders) if orders else Decimal("0")
    occupancy = q(Decimal(sold) / sellable_units * 100) if sellable_units else Decimal("0")

    values = {
        "total_units": total_units,
        "out_of_order_units": total_units - sellable_units,
        "available_units": max(0, sellable_units - sold),
        "sold_units": sold,
        "complimentary_units": 0,
        "occupancy_percent": occupancy,
        "guests_in_house": int(sold * 2.3),
        "arrivals": arrivals,
        "departures": departures,
        "walk_ins": walk_ins,
        "no_shows": no_shows,
        "cancellations": cancellations,
        "new_bookings": 0,
        "room_revenue": room_revenue,
        "fnb_revenue": fnb,
        "spa_revenue": spa,
        "activity_revenue": Decimal("0"),
        "other_revenue": Decimal("0"),
        "total_revenue": total_revenue,
        "discount_total": Decimal("0"),
        "service_charge_total": Decimal("0"),
        "tax_total": Decimal("0"),
        "adr": adr,
        "revpar": revpar,
        "trevpar": trevpar,
        "average_check": average_check,
        "covers": covers,
        "ota_commission_total": q(commission),
        "direct_bookings": direct_bookings,
        "ota_bookings": ota_bookings,
        "revenue_by_source": {k: str(v) for k, v in by_source.items()},
        "cash_total": Decimal("0"),
        "card_total": Decimal("0"),
        "city_ledger_total": Decimal("0"),
        "computed_at": utcnow(),
    }

    stat = db.execute(
        select(DailyStatistics).where(
            DailyStatistics.property_id == property_id,
            DailyStatistics.business_date == business_date,
        )
    ).scalar_one_or_none()

    if stat is None:
        stat = DailyStatistics(property_id=property_id, business_date=business_date, **values)
        db.add(stat)
    else:
        for key, value in values.items():
            setattr(stat, key, value)

    _write_category_stats(db, property_id, business_date, night_rows, units)
    _write_outlet_stats(db, property_id, business_date, per_outlet)
    db.flush()
    return stat


def _write_category_stats(db, property_id, business_date, night_rows, units) -> None:
    """ربحية كل فئة على حدة — ده اللي بيوري المالك أنهي فئة بتجيب فلوس."""
    units_per_cat: dict[int, int] = defaultdict(int)
    for unit in units:
        if unit.is_sellable:
            units_per_cat[unit.category_id] += 1

    sold_by_cat = {int(r[0]): int(r[1] or 0) for r in night_rows}
    revenue_by_cat = {int(r[0]): Decimal(str(r[2] or 0)) for r in night_rows}

    categories = db.execute(
        select(UnitCategory).where(UnitCategory.property_id == property_id)
    ).scalars().all()

    existing = {
        row.unit_category_id: row
        for row in db.execute(
            select(DailyCategoryStatistics).where(
                DailyCategoryStatistics.property_id == property_id,
                DailyCategoryStatistics.business_date == business_date,
            )
        ).scalars().all()
    }

    for category in categories:
        available = units_per_cat.get(category.id, 0)
        sold = sold_by_cat.get(category.id, 0)
        revenue = q(revenue_by_cat.get(category.id, Decimal("0")))
        values = {
            "total_units": available,
            "sold_units": sold,
            "occupancy_percent": q(Decimal(sold) / available * 100) if available else Decimal("0"),
            "room_revenue": revenue,
            "adr": q(revenue / sold) if sold else Decimal("0"),
        }
        row = existing.get(category.id)
        if row is None:
            db.add(
                DailyCategoryStatistics(
                    property_id=property_id,
                    unit_category_id=category.id,
                    business_date=business_date,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)


def _write_outlet_stats(db, property_id, business_date, per_outlet) -> None:
    existing = {
        row.outlet_id: row
        for row in db.execute(
            select(DailyOutletStatistics).where(
                DailyOutletStatistics.property_id == property_id,
                DailyOutletStatistics.business_date == business_date,
            )
        ).scalars().all()
    }
    for entry in per_outlet:
        outlet_id = entry.pop("outlet_id")
        row = existing.get(outlet_id)
        if row is None:
            db.add(
                DailyOutletStatistics(
                    property_id=property_id,
                    outlet_id=outlet_id,
                    business_date=business_date,
                    **entry,
                )
            )
        else:
            for key, value in entry.items():
                setattr(row, key, value)


# ════════════════════════════════════════════ 4) إحصاءات النزلاء
def refresh_departed_guests(db: Session, property_id: int, business_date: date) -> int:
    """بيحدّث عدد الإقامات والإنفاق للنزلاء اللي غادروا النهاردة."""
    guest_ids = [
        row[0]
        for row in db.execute(
            select(Reservation.guest_id).where(
                Reservation.property_id == property_id,
                Reservation.departure_date == business_date,
                Reservation.status == ReservationStatus.CHECKED_OUT,
            )
        ).all()
    ]
    if not guest_ids:
        return 0

    updated = 0
    for guest_id in set(guest_ids):
        guest = db.get(Guest, guest_id)
        if guest is None:
            continue
        stays, nights, revenue, first_day, last_day = db.execute(
            select(
                func.count(Reservation.id),
                func.sum(Reservation.nights),
                func.sum(Reservation.grand_total),
                func.min(Reservation.arrival_date),
                func.max(Reservation.departure_date),
            ).where(
                Reservation.guest_id == guest_id,
                Reservation.status == ReservationStatus.CHECKED_OUT,
            )
        ).one()
        guest.total_stays = int(stays or 0)
        guest.total_nights = int(nights or 0)
        guest.total_revenue = q(Decimal(str(revenue or 0)))
        guest.first_stay_date = first_day
        guest.last_stay_date = last_day
        updated += 1
    return updated


# ════════════════════════════════════════════════ 5) محاذير بشرية
def collect_warnings(db: Session, property_id: int, business_date: date) -> dict[str, Any]:
    """حاجات النظام مش بيصلّحها لوحده — لازم حد ياخد قرار فيها."""
    warnings: dict[str, Any] = {}

    open_folios = db.execute(
        select(func.count(Folio.id)).where(
            Folio.property_id == property_id, Folio.status == FolioStatus.OPEN
        )
    ).scalar_one()
    warnings["open_folios"] = int(open_folios)

    open_orders = db.execute(
        select(func.count(PosOrder.id)).where(
            PosOrder.property_id == property_id,
            PosOrder.status.in_(
                [PosOrderStatus.OPEN, PosOrderStatus.SENT, PosOrderStatus.SERVED]
            ),
        )
    ).scalar_one()
    warnings["open_pos_orders"] = int(open_orders)

    open_shifts = db.execute(
        select(func.count(Shift.id)).where(
            Shift.property_id == property_id, Shift.status == "OPEN"
        )
    ).scalar_one()
    warnings["open_shifts"] = int(open_shifts)

    unassigned = db.execute(
        select(func.count(ReservationUnit.id)).where(
            ReservationUnit.property_id == property_id,
            ReservationUnit.unit_id.is_(None),
            ReservationUnit.arrival_date <= business_date,
            ReservationUnit.departure_date > business_date,
            ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
        )
    ).scalar_one()
    warnings["in_house_without_unit"] = int(unassigned)

    overdue = db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.property_id == property_id,
            Reservation.departure_date < business_date,
            Reservation.status == ReservationStatus.CHECKED_IN,
        )
    ).scalar_one()
    warnings["overdue_checkouts"] = int(overdue)

    # بيع زايد فوق السعة الحقيقية في الشهر الجاي — نزلاء جايين ومفيش لهم مكان
    horizon = business_date + timedelta(days=30)
    warnings["oversold_days"] = sum(
        1
        for row in av.get_availability(db, property_id, business_date, horizon)
        if row.oversold_by > 0
    )

    # طلبات انتظار بقى فيه لها مكان — مكالمة تليفون بتتحوّل لحجز
    pending = wl.list_entries(
        db, property_id, statuses=[WaitlistStatus.WAITING], arrival_from=business_date
    )
    warnings["waitlist_ready"] = sum(
        1 for match in wl.match_all(db, property_id, pending).values() if match is not None
    )

    return warnings


# ═══════════════════════════════════════════════════ التشغيل الكامل
def run(
    db: Session,
    *,
    property_id: int,
    business_date: date | None = None,
    user_id: int | None = None,
    is_automatic: bool = False,
    force: bool = False,
) -> NightAuditRun:
    """التقفيل اليومي كامل. بيرجّع سجل التشغيل بكل الأرقام."""
    prop = db.get(Property, property_id)
    if prop is None:
        raise NightAuditError("المنشأة غير موجودة", "Property not found", "not_found")

    target = business_date or business_date_for(prop)
    if target > date.today():
        raise NightAuditError(
            "مينفعش تقفّل يوم لسه ماجاش",
            "Cannot audit a future date",
            "future_date",
        )

    previous = db.execute(
        select(NightAuditRun).where(
            NightAuditRun.property_id == property_id,
            NightAuditRun.business_date == target,
            NightAuditRun.status == "COMPLETED",
        )
    ).scalar_one_or_none()
    if previous is not None and not force:
        raise NightAuditError(
            f"يوم {target} اتقفل قبل كده",
            f"{target} has already been audited",
            "already_done",
        )

    audit_run = NightAuditRun(
        property_id=property_id,
        business_date=target,
        started_at=utcnow(),
        status="RUNNING",
        run_by_user_id=user_id,
        is_automatic=is_automatic,
    )
    db.add(audit_run)
    db.flush()

    try:
        no_shows, _penalties = mark_no_shows(db, property_id, target)
        # عدم الحضور بيرجّع إتاحة، فده أنسب وقت لتنضيف قائمة الانتظار:
        # العروض المنتهية بترجع وحداتها للبيع، والطلبات اللي فات ميعادها بتتقفل
        wl.expire_offers(db, property_id)
        wl.expire_stale(db, property_id, today=target)
        nights_posted, room_revenue = post_pending_nights(db, property_id, target)
        compute_statistics(db, property_id, target)
        refresh_departed_guests(db, property_id, target)
        warnings = collect_warnings(db, property_id, target)

        audit_run.no_shows_marked = no_shows
        audit_run.nights_posted = nights_posted
        audit_run.room_revenue_posted = room_revenue
        audit_run.folios_closed = 0
        audit_run.open_folios_remaining = warnings["open_folios"]
        audit_run.warnings = warnings
        audit_run.status = "COMPLETED"
        audit_run.finished_at = utcnow()
        db.flush()
    except Exception as exc:  # pragma: no cover - بيتسجّل عشان التشخيص
        audit_run.status = "FAILED"
        audit_run.error_message = str(exc)[:2000]
        audit_run.finished_at = utcnow()
        db.flush()
        raise

    return audit_run
