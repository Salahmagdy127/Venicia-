"""منطق الحجوزات — Reservation business logic.

كل عملية هنا بتشتغل جوه معاملة واحدة: الإتاحة والحجز والحساب بيتحركوا مع بعض
أو ميتحركوش خالص. مفيش حالة نص نص.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    BLOCKING_RESERVATION_STATUSES,
    BookingSource,
    ChargeKind,
    FolioStatus,
    FolioType,
    HousekeepingStatus,
    ReservationStatus,
)
from app.models.folio import Folio, FolioLine
from app.models.guests import Guest
from app.models.organization import Property
from app.models.rates import RatePlan
from app.models.reservations import Reservation, ReservationNight, ReservationUnit
from app.models.units import Unit, UnitCategory
from app.services import availability as av
from app.services import pricing
from app.services.pricing import money
from app.services.sequences import next_number

#: عمولات القنوات الافتراضية — بتظهر للمالك بالجنيه في الداشبورد
CHANNEL_COMMISSION: dict[BookingSource, Decimal] = {
    BookingSource.BOOKING_COM: Decimal("17"),
    BookingSource.AGODA: Decimal("15"),
    BookingSource.EXPEDIA: Decimal("16"),
    BookingSource.AIRBNB: Decimal("14"),
    BookingSource.TRAVEL_AGENT: Decimal("10"),
}


class ReservationError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "reservation_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ────────────────────────────────────────────────────── فحص تعارض الوحدة
def find_conflict(
    db: Session,
    unit_id: int,
    arrival: date,
    departure: date,
    exclude_reservation_unit_id: int | None = None,
) -> ReservationUnit | None:
    """بيرجّع أول حجز متعارض على الوحدة دي في المدى ده، أو ``None``.

    شرط التقاطع: ``arrival < other.departure`` و ``departure > other.arrival``.
    ليلة المغادرة مش محسوبة، فنزيل ماشي يوم 12 وواحد جاي يوم 12 مفيش بينهم تعارض.
    """
    stmt = select(ReservationUnit).where(
        ReservationUnit.unit_id == unit_id,
        ReservationUnit.arrival_date < departure,
        ReservationUnit.departure_date > arrival,
        ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
    )
    if exclude_reservation_unit_id:
        stmt = stmt.where(ReservationUnit.id != exclude_reservation_unit_id)
    return db.execute(stmt.limit(1)).scalar_one_or_none()


# ──────────────────────────────────────────────────────────── الإنشاء
def create_reservation(
    db: Session,
    *,
    property_id: int,
    guest_id: int,
    unit_category_id: int,
    rate_plan_id: int,
    arrival: date,
    departure: date,
    adults: int = 2,
    children: int = 0,
    source: BookingSource = BookingSource.DIRECT,
    unit_id: int | None = None,
    external_reference: str | None = None,
    special_requests: str | None = None,
    created_by_user_id: int | None = None,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
    deposit_paid: Decimal | None = None,
) -> Reservation:
    """حجز جديد: تسعير + خصم إتاحة + ليالي مفصّلة — كله في معاملة واحدة."""
    if departure <= arrival:
        raise ReservationError(
            "تاريخ المغادرة لازم يكون بعد الوصول",
            "Departure must be after arrival",
            "invalid_dates",
        )

    prop = db.get(Property, property_id)
    guest = db.get(Guest, guest_id)
    category = db.get(UnitCategory, unit_category_id)
    plan = db.get(RatePlan, rate_plan_id)

    if not all((prop, guest, category, plan)):
        raise ReservationError("بيانات ناقصة أو غير صحيحة", "Invalid references", "not_found")
    if guest.is_blacklisted:
        raise ReservationError(
            "النزيل ده على القايمة السودة", "Guest is blacklisted", "blacklisted"
        )
    if adults + children > category.max_occupancy:
        raise ReservationError(
            f"الفئة دي بتستوعب {category.max_occupancy} أفراد كحد أقصى",
            f"Category holds a maximum of {category.max_occupancy} guests",
            "over_capacity",
        )

    # 1) التسعير — بيرمي PricingError لو مفيش سعر أو البيع مقفول
    quote = pricing.quote_stay(
        db,
        property_id=property_id,
        unit_category_id=unit_category_id,
        rate_plan_id=rate_plan_id,
        arrival=arrival,
        departure=departure,
        adults=adults,
        children=children,
    )

    # 2) لو الموظف اختار وحدة بعينها، نتأكد إنها فاضية فعلاً
    if unit_id is not None:
        unit = db.get(Unit, unit_id)
        if unit is None or unit.category_id != unit_category_id:
            raise ReservationError(
                "الوحدة مش من الفئة المطلوبة", "Unit is not in the selected category", "unit_mismatch"
            )
        if not unit.is_sellable:
            raise ReservationError(
                "الوحدة دي خارج الخدمة", "Unit is out of service", "unit_unavailable"
            )
        conflict = find_conflict(db, unit_id, arrival, departure)
        if conflict is not None:
            raise ReservationError(
                "الوحدة محجوزة في التواريخ دي", "Unit is already booked for these dates", "conflict"
            )

    # 3) خصم الإتاحة — الحارس الذرّي ضد الحجز الزائد
    av.ensure_calendar(db, property_id, arrival, departure, [unit_category_id])
    av.reserve(db, property_id, unit_category_id, arrival, departure)

    commission_pct = CHANNEL_COMMISSION.get(source, Decimal("0"))
    net = money(quote.room_total + quote.extras_total - quote.discount_total)
    nights = (departure - arrival).days

    # العربون المحصّل وقت الحجز — بيتخصم من المستحق فوراً، ومبيعديش الإجمالي
    deposit = money(deposit_paid or Decimal("0"))
    if deposit < 0:
        raise ReservationError("العربون مينفعش يكون بالسالب", "Deposit cannot be negative", "invalid_deposit")
    if deposit > quote.grand_total:
        raise ReservationError(
            "العربون أكبر من إجمالي الحجز",
            "Deposit exceeds the reservation total",
            "invalid_deposit",
        )

    reservation = Reservation(
        code=next_number(db, property_id, "RESERVATION", on_date=arrival),
        property_id=property_id,
        status=status,
        source=source,
        external_reference=external_reference,
        channel_commission_percent=commission_pct,
        channel_commission_amount=money(net * commission_pct / 100),
        guest_id=guest_id,
        arrival_date=arrival,
        departure_date=departure,
        nights=nights,
        adults=adults,
        children=children,
        room_total=quote.room_total,
        extras_total=quote.extras_total,
        discount_total=quote.discount_total,
        service_charge_total=quote.service_charge_total,
        tax_total=quote.tax_total,
        grand_total=quote.grand_total,
        deposit_required=money(quote.grand_total * Decimal("0.25")),
        deposit_paid=deposit,
        paid_total=deposit,
        balance=money(quote.grand_total - deposit),
        special_requests=special_requests,
        created_by_user_id=created_by_user_id,
    )
    db.add(reservation)
    db.flush()

    res_unit = ReservationUnit(
        reservation_id=reservation.id,
        property_id=property_id,
        unit_category_id=unit_category_id,
        unit_id=unit_id,
        rate_plan_id=rate_plan_id,
        meal_plan=plan.meal_plan,
        arrival_date=arrival,
        departure_date=departure,
        nights=nights,
        adults=adults,
        children=children,
        status=status,
        room_total=quote.room_total,
        discount_total=quote.discount_total,
    )
    db.add(res_unit)
    db.flush()

    for night in quote.nights_detail:
        db.add(
            ReservationNight(
                reservation_unit_id=res_unit.id,
                reservation_id=reservation.id,
                property_id=property_id,
                unit_category_id=unit_category_id,
                stay_date=night.stay_date,
                published_rate=night.published_rate,
                rate=night.rate,
                extra_person_amount=night.extra_person_amount,
                discount_amount=night.discount_amount,
            )
        )
    db.flush()
    return reservation


# ─────────────────────────────────────────── التخصيص والنقل بالسحب
def assign_unit(
    db: Session, reservation_unit_id: int, unit_id: int
) -> ReservationUnit:
    """تخصيص وحدة لحجز لسه متخصصش."""
    res_unit = db.get(ReservationUnit, reservation_unit_id)
    if res_unit is None:
        raise ReservationError("الحجز غير موجود", "Reservation line not found", "not_found")

    unit = db.get(Unit, unit_id)
    if unit is None:
        raise ReservationError("الوحدة غير موجودة", "Unit not found", "not_found")
    if unit.category_id != res_unit.unit_category_id:
        raise ReservationError(
            "الوحدة مش من نفس الفئة", "Unit belongs to a different category", "unit_mismatch"
        )
    if not unit.is_sellable:
        raise ReservationError(
            "الوحدة خارج الخدمة", "Unit is out of service", "unit_unavailable"
        )

    conflict = find_conflict(
        db, unit_id, res_unit.arrival_date, res_unit.departure_date, res_unit.id
    )
    if conflict is not None:
        raise ReservationError(
            "الوحدة محجوزة في التواريخ دي", "Unit is already booked", "conflict"
        )

    res_unit.unit_id = unit_id
    db.flush()
    return res_unit


def move_reservation_unit(
    db: Session,
    reservation_unit_id: int,
    *,
    unit_id: int | None = None,
    arrival: date | None = None,
    departure: date | None = None,
) -> ReservationUnit:
    """نقل حجز بالسحب والإفلات — تغيير الوحدة و/أو التواريخ.

    ده قلب شاشة الحجوزات. الترتيب مهم: بنحجز الجديد قبل ما نفضّي القديم، عشان
    لو الجديد مش متاح يفضل الحجز مكانه.
    """
    res_unit = db.get(ReservationUnit, reservation_unit_id)
    if res_unit is None:
        raise ReservationError("الحجز غير موجود", "Reservation line not found", "not_found")

    if res_unit.status in (
        ReservationStatus.CHECKED_OUT,
        ReservationStatus.CANCELLED,
        ReservationStatus.NO_SHOW,
    ):
        raise ReservationError(
            "مينفعش تحرّك حجز منتهي أو ملغي",
            "Cannot move a closed or cancelled reservation",
            "immutable",
        )

    old_unit_id = res_unit.unit_id
    old_arrival = res_unit.arrival_date
    old_departure = res_unit.departure_date
    old_category = res_unit.unit_category_id

    new_arrival = arrival or old_arrival
    new_departure = departure or old_departure
    if new_departure <= new_arrival:
        raise ReservationError(
            "تاريخ المغادرة لازم يكون بعد الوصول", "Departure must be after arrival", "invalid_dates"
        )

    # النزيل النازل مينفعش يتغيّر تاريخ وصوله
    if res_unit.status == ReservationStatus.CHECKED_IN and new_arrival != old_arrival:
        raise ReservationError(
            "مينفعش تغيّر تاريخ وصول نزيل نازل بالفعل",
            "Cannot change arrival date of an in-house guest",
            "checked_in",
        )

    new_unit_id = unit_id if unit_id is not None else old_unit_id
    new_category = old_category

    if new_unit_id is not None:
        unit = db.get(Unit, new_unit_id)
        if unit is None:
            raise ReservationError("الوحدة غير موجودة", "Unit not found", "not_found")
        if not unit.is_sellable:
            raise ReservationError(
                "الوحدة خارج الخدمة", "Unit is out of service", "unit_unavailable"
            )
        new_category = unit.category_id

        conflict = find_conflict(db, new_unit_id, new_arrival, new_departure, res_unit.id)
        if conflict is not None:
            raise ReservationError(
                "فيه حجز تاني على الوحدة دي في التواريخ دي",
                "Another reservation already occupies this unit",
                "conflict",
            )

    dates_changed = (new_arrival, new_departure) != (old_arrival, old_departure)
    category_changed = new_category != old_category

    # تحريك الإتاحة لو الفئة أو التواريخ اتغيّرت
    if dates_changed or category_changed:
        av.ensure_calendar(db, res_unit.property_id, new_arrival, new_departure, [new_category])
        av.move(
            db,
            res_unit.property_id,
            from_category_id=old_category,
            from_arrival=old_arrival,
            from_departure=old_departure,
            to_category_id=new_category,
            to_arrival=new_arrival,
            to_departure=new_departure,
        )

    res_unit.unit_id = new_unit_id
    res_unit.unit_category_id = new_category
    res_unit.arrival_date = new_arrival
    res_unit.departure_date = new_departure
    res_unit.nights = (new_departure - new_arrival).days

    # إعادة تسعير الليالي لو التواريخ أو الفئة اتغيّرت
    if dates_changed or category_changed:
        db.query(ReservationNight).filter(
            ReservationNight.reservation_unit_id == res_unit.id
        ).delete(synchronize_session=False)

        quote = pricing.quote_stay(
            db,
            property_id=res_unit.property_id,
            unit_category_id=new_category,
            rate_plan_id=res_unit.rate_plan_id,
            arrival=new_arrival,
            departure=new_departure,
            adults=res_unit.adults,
            children=res_unit.children,
        )
        for night in quote.nights_detail:
            db.add(
                ReservationNight(
                    reservation_unit_id=res_unit.id,
                    reservation_id=res_unit.reservation_id,
                    property_id=res_unit.property_id,
                    unit_category_id=new_category,
                    stay_date=night.stay_date,
                    published_rate=night.published_rate,
                    rate=night.rate,
                    extra_person_amount=night.extra_person_amount,
                    discount_amount=night.discount_amount,
                )
            )
        res_unit.room_total = quote.room_total
        _recalculate_reservation(db, res_unit.reservation_id)

    db.flush()
    return res_unit


def _recalculate_reservation(db: Session, reservation_id: int) -> None:
    """إعادة حساب إجماليات الحجز من سطوره."""
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        return
    prop = db.get(Property, reservation.property_id)

    lines = list(
        db.execute(
            select(ReservationUnit).where(ReservationUnit.reservation_id == reservation_id)
        ).scalars().all()
    )
    room_total = money(sum((l.room_total for l in lines), Decimal("0")))
    discount = money(sum((l.discount_total for l in lines), Decimal("0")))
    net = money(room_total - discount)
    service = money(net * prop.service_charge_percent / 100)
    taxable = net + service if prop.service_charge_before_tax else net
    tax = money(taxable * prop.vat_percent / 100)

    reservation.room_total = room_total
    reservation.discount_total = discount
    reservation.service_charge_total = service
    reservation.tax_total = tax
    reservation.grand_total = money(net + service + tax)
    reservation.balance = money(reservation.grand_total - reservation.paid_total)
    reservation.channel_commission_amount = money(
        net * reservation.channel_commission_percent / 100
    )
    if lines:
        reservation.arrival_date = min(l.arrival_date for l in lines)
        reservation.departure_date = max(l.departure_date for l in lines)
        reservation.nights = (reservation.departure_date - reservation.arrival_date).days
    db.flush()


# ─────────────────────────────────────────── ترحيل الإقامة على الحساب
def post_room_charges(
    db: Session, folio: Folio, res_unit: ReservationUnit, prop: Property
) -> Decimal:
    """ترحيل ليالي الإقامة على حساب النزيل — سطر لكل ليلة.

    بيتنفّذ لحظة النزول عشان كشف الحساب يبقى صحيح من أول دقيقة، ومحاولة
    المغادرة برصيد مستحق تترفض فعلاً. الليالي المرحّلة بتتعلّم عشان الـ
    Night Audit ميكرّرهاش.
    """
    nights = list(
        db.execute(
            select(ReservationNight)
            .where(
                ReservationNight.reservation_unit_id == res_unit.id,
                ReservationNight.is_posted.is_(False),
            )
            .order_by(ReservationNight.stay_date)
        ).scalars().all()
    )
    if not nights:
        return Decimal("0")

    unit = db.get(Unit, res_unit.unit_id) if res_unit.unit_id else None
    label = unit.label if unit else "—"

    charges = Decimal("0")
    service_total = Decimal("0")
    tax_total = Decimal("0")

    for night in nights:
        amount = money(night.rate + night.extra_person_amount - night.discount_amount)
        service = money(amount * prop.service_charge_percent / 100)
        taxable = amount + service if prop.service_charge_before_tax else amount
        tax = money(taxable * prop.vat_percent / 100)

        db.add(
            FolioLine(
                created_at=utcnow(),
                folio_id=folio.id,
                property_id=folio.property_id,
                business_date=night.stay_date,
                charge_kind=ChargeKind.ROOM,
                description_ar=f"إقامة ليلة {night.stay_date.isoformat()} — {label}",
                description_en=f"Room night {night.stay_date.isoformat()} — {label}",
                quantity=Decimal("1"),
                unit_price=amount,
                amount=amount,
                service_charge_amount=service,
                tax_amount=tax,
                tax_percent=prop.vat_percent,
                total_amount=money(amount + service + tax),
                reservation_night_id=night.id,
            )
        )
        night.is_posted = True
        charges += amount
        service_total += service
        tax_total += tax

    folio.charges_total = money(folio.charges_total + charges)
    folio.service_charge_total = money(folio.service_charge_total + service_total)
    folio.tax_total = money(folio.tax_total + tax_total)
    folio.balance = money(
        folio.charges_total
        + folio.service_charge_total
        + folio.tax_total
        - folio.payments_total
        - folio.discount_total
    )
    db.flush()
    return money(charges + service_total + tax_total)


# ─────────────────────────────────────────────── النزول والمغادرة
def check_in(
    db: Session, reservation_id: int, *, user_id: int | None = None
) -> tuple[Reservation, list[Folio]]:
    """تسجيل النزول — بيفتح حساب لكل وحدة ويعلّم الوحدة مشغولة."""
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise ReservationError("الحجز غير موجود", "Reservation not found", "not_found")

    if reservation.status == ReservationStatus.CHECKED_IN:
        raise ReservationError("النزيل نازل بالفعل", "Guest is already checked in", "already_in")
    if reservation.status not in (ReservationStatus.CONFIRMED, ReservationStatus.TENTATIVE):
        raise ReservationError(
            "مينفعش تسجّل نزول لحجز في الحالة دي",
            "Reservation is not in a check-in-able state",
            "invalid_status",
        )

    guest = db.get(Guest, reservation.guest_id)
    if guest and not guest.id_number:
        raise ReservationError(
            "لازم تسجّل الرقم القومي أو الباسبور قبل النزول",
            "National ID or passport is required before check-in",
            "missing_id",
        )

    lines = list(
        db.execute(
            select(ReservationUnit).where(ReservationUnit.reservation_id == reservation_id)
        ).scalars().all()
    )
    unassigned = [l for l in lines if l.unit_id is None]
    if unassigned:
        raise ReservationError(
            "لازم تخصّص وحدة لكل سطر في الحجز الأول",
            "Every reservation line must have a unit assigned",
            "unassigned",
        )

    now = utcnow()
    prop = db.get(Property, reservation.property_id)
    folios: list[Folio] = []

    for line in lines:
        unit = db.get(Unit, line.unit_id)
        line.status = ReservationStatus.CHECKED_IN
        if unit:
            unit.housekeeping_status = HousekeepingStatus.DIRTY

        folio = Folio(
            code=next_number(db, reservation.property_id, "FOLIO"),
            property_id=reservation.property_id,
            folio_type=FolioType.GUEST,
            status=FolioStatus.OPEN,
            reservation_id=reservation.id,
            reservation_unit_id=line.id,
            guest_id=reservation.guest_id,
            unit_label=unit.label if unit else None,
            opened_at=now,
        )
        db.add(folio)
        db.flush()

        # ترحيل الإقامة فوراً — الحساب لازم يعكس المستحق من أول لحظة
        post_room_charges(db, folio, line, prop)

        # العربون المدفوع مسبقاً يتحوّل للحساب كدفعة
        if reservation.deposit_paid > 0 and line is lines[0]:
            folio.payments_total = money(folio.payments_total + reservation.deposit_paid)
            folio.balance = money(folio.balance - reservation.deposit_paid)
            db.add(
                FolioLine(
                    created_at=now,
                    folio_id=folio.id,
                    property_id=folio.property_id,
                    business_date=date.today(),
                    charge_kind=ChargeKind.DEPOSIT,
                    description_ar="عربون محوّل من الحجز",
                    description_en="Deposit transferred from booking",
                    quantity=Decimal("1"),
                    unit_price=-reservation.deposit_paid,
                    amount=-reservation.deposit_paid,
                    total_amount=-reservation.deposit_paid,
                    posted_by_user_id=user_id,
                )
            )

        folios.append(folio)

    reservation.status = ReservationStatus.CHECKED_IN
    reservation.checked_in_at = now
    reservation.checked_in_by_user_id = user_id
    db.flush()
    return reservation, folios


def check_out(
    db: Session, reservation_id: int, *, user_id: int | None = None, force: bool = False
) -> tuple[Reservation, list[Folio]]:
    """تسجيل المغادرة — بيقفل الحسابات ويرجّع الإتاحة ويحدّث ملف النزيل."""
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise ReservationError("الحجز غير موجود", "Reservation not found", "not_found")
    if reservation.status != ReservationStatus.CHECKED_IN:
        raise ReservationError(
            "النزيل مش نازل أصلاً", "Guest is not checked in", "invalid_status"
        )

    folios = list(
        db.execute(select(Folio).where(Folio.reservation_id == reservation_id)).scalars().all()
    )
    outstanding = money(sum((f.balance for f in folios), Decimal("0")))
    if outstanding > 0 and not force:
        raise ReservationError(
            f"فيه رصيد مستحق {outstanding} ج.م لازم يتحصّل الأول",
            f"An outstanding balance of {outstanding} must be settled first",
            "outstanding_balance",
        )

    now = utcnow()
    today = date.today()

    for line in db.execute(
        select(ReservationUnit).where(ReservationUnit.reservation_id == reservation_id)
    ).scalars().all():
        line.status = ReservationStatus.CHECKED_OUT
        unit = db.get(Unit, line.unit_id) if line.unit_id else None
        if unit:
            unit.housekeeping_status = HousekeepingStatus.DIRTY

        # مغادرة مبكرة: نرجّع الليالي اللي مش هتتستهلك للإتاحة
        if today < line.departure_date:
            av.release(
                db,
                line.property_id,
                line.unit_category_id,
                max(today, line.arrival_date),
                line.departure_date,
            )

    for folio in folios:
        folio.status = FolioStatus.CLOSED
        folio.closed_at = now
        folio.closed_by_user_id = user_id

    reservation.status = ReservationStatus.CHECKED_OUT
    reservation.checked_out_at = now
    reservation.checked_out_by_user_id = user_id

    guest = db.get(Guest, reservation.guest_id)
    if guest:
        guest.total_stays += 1
        guest.total_nights += reservation.nights
        guest.total_revenue = money(guest.total_revenue + reservation.paid_total)
        guest.last_stay_date = today
        if guest.first_stay_date is None:
            guest.first_stay_date = reservation.arrival_date
        guest.loyalty_points += int(reservation.paid_total / 100)

    db.flush()
    return reservation, folios


# ──────────────────────────────────────────────────────────── الإلغاء
def cancel(
    db: Session,
    reservation_id: int,
    *,
    reason: str | None = None,
    user_id: int | None = None,
    charge_penalty: bool = True,
) -> tuple[Reservation, Decimal]:
    """إلغاء حجز — بيرجّع الإتاحة ويحسب الغرامة حسب السياسة."""
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise ReservationError("الحجز غير موجود", "Reservation not found", "not_found")
    if reservation.status in (
        ReservationStatus.CANCELLED,
        ReservationStatus.CHECKED_OUT,
        ReservationStatus.NO_SHOW,
    ):
        raise ReservationError(
            "الحجز ده متقفل بالفعل", "Reservation is already closed", "invalid_status"
        )
    if reservation.status == ReservationStatus.CHECKED_IN:
        raise ReservationError(
            "النزيل نازل — استخدم المغادرة مش الإلغاء",
            "Guest is in-house; use check-out instead",
            "checked_in",
        )

    lines = list(
        db.execute(
            select(ReservationUnit).where(ReservationUnit.reservation_id == reservation_id)
        ).scalars().all()
    )
    for line in lines:
        av.release(
            db,
            line.property_id,
            line.unit_category_id,
            line.arrival_date,
            line.departure_date,
        )
        line.status = ReservationStatus.CANCELLED

    # الغرامة: أول ليلة لو الإلغاء متأخر (أقل من 48 ساعة)
    penalty = Decimal("0")
    if charge_penalty:
        hours_to_arrival = (
            datetime.combine(reservation.arrival_date, datetime.min.time(), timezone.utc)
            - utcnow()
        ).total_seconds() / 3600
        if hours_to_arrival < 48:
            first_night = db.execute(
                select(ReservationNight)
                .where(ReservationNight.reservation_id == reservation_id)
                .order_by(ReservationNight.stay_date)
                .limit(1)
            ).scalar_one_or_none()
            if first_night:
                penalty = money(first_night.rate + first_night.extra_person_amount)

    reservation.status = ReservationStatus.CANCELLED
    reservation.cancelled_at = utcnow()
    reservation.cancellation_reason = reason

    guest = db.get(Guest, reservation.guest_id)
    if guest:
        guest.total_cancellations += 1

    if penalty > 0:
        folio = Folio(
            code=next_number(db, reservation.property_id, "FOLIO"),
            property_id=reservation.property_id,
            folio_type=FolioType.GUEST,
            status=FolioStatus.OPEN,
            reservation_id=reservation.id,
            guest_id=reservation.guest_id,
            opened_at=utcnow(),
            charges_total=penalty,
            balance=penalty,
        )
        db.add(folio)
        db.flush()
        db.add(
            FolioLine(
                created_at=utcnow(),
                folio_id=folio.id,
                property_id=reservation.property_id,
                business_date=date.today(),
                charge_kind=ChargeKind.CANCELLATION_FEE,
                description_ar=f"غرامة إلغاء متأخر — حجز {reservation.code}",
                description_en=f"Late cancellation fee — {reservation.code}",
                quantity=Decimal("1"),
                unit_price=penalty,
                amount=penalty,
                total_amount=penalty,
                posted_by_user_id=user_id,
            )
        )

    db.flush()
    return reservation, penalty


def mark_no_show(
    db: Session, reservation_id: int, *, user_id: int | None = None
) -> Reservation:
    """تعليم عدم الحضور — بيتنفّذ عادةً من الـ Night Audit."""
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise ReservationError("الحجز غير موجود", "Reservation not found", "not_found")
    if reservation.status not in (ReservationStatus.CONFIRMED, ReservationStatus.TENTATIVE):
        raise ReservationError(
            "الحالة مش مناسبة لعدم الحضور", "Invalid status for no-show", "invalid_status"
        )

    for line in db.execute(
        select(ReservationUnit).where(ReservationUnit.reservation_id == reservation_id)
    ).scalars().all():
        av.release(
            db, line.property_id, line.unit_category_id, line.arrival_date, line.departure_date
        )
        line.status = ReservationStatus.NO_SHOW

    reservation.status = ReservationStatus.NO_SHOW
    guest = db.get(Guest, reservation.guest_id)
    if guest:
        guest.total_no_shows += 1
    db.flush()
    return reservation
