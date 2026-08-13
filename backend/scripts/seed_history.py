"""توليد تاريخ تشغيلي واقعي لفينيسيا — Historical operations generator.

بيولّد نزلاء وحجوزات وحسابات وفواتير وأوردرات نقاط بيع على مدى سنتين، بموسمية
حقيقية (الصيف مزدحم، أكتوبر ونوفمبر هادي، الويك إند أعلى من وسط الأسبوع).

الغرض مش «تعبئة» — الغرض إن الديمو يفتح قدام العميل على داتا بحجم حقيقي،
فالسرعة اللي هيشوفها تبقى إثبات مش وعد.

    python -m scripts.seed_history

ملاحظة عند النقل لـ PostgreSQL: السكربت بيحدد المفاتيح الأساسية بنفسه للسرعة،
فلازم تعيد ضبط الـ sequences بعد التشغيل.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, insert, select, update
from sqlalchemy.orm import Session, selectinload

from app.db.base import SessionLocal
from app.models.analytics import DailyOutletStatistics, DailyStatistics
from app.models.enums import (
    CREDIT_CHARGE_KINDS,
    BookingSource,
    ChargeKind,
    FolioStatus,
    FolioType,
    HousekeepingStatus,
    IdentificationType,
    PaymentMethod,
    PosOrderStatus,
    PosOrderType,
    ReservationStatus,
    SettlementType,
    UnitCondition,
)
from app.models.billing import DocumentSequence
from app.models.folio import Folio, FolioLine, Payment
from app.models.guests import Guest
from app.models.organization import Property
from app.models.pos import MenuItem, Outlet, PosOrder, PosOrderLine, PosTable
from app.models.rates import RateCalendarEntry, RatePlan
from app.models.reservations import (
    AvailabilityCalendar,
    Reservation,
    ReservationNight,
    ReservationUnit,
)
from app.models.security import User
from app.models.units import Unit, UnitCategory
from app.services import sequences

RNG = random.Random(20260812)  # ثابت — نفس الداتا في كل تشغيل

CAIRO = timezone(timedelta(hours=3))
TWO = Decimal("0.01")


def q(value) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWO)


# ═══════════════════════════════════════════════════════ أسماء واقعية
FIRST_M = [
    "محمد", "أحمد", "محمود", "مصطفى", "عمرو", "خالد", "كريم", "طارق", "شريف",
    "ياسر", "هشام", "عماد", "وليد", "أيمن", "باسم", "زياد", "عادل", "سامح",
    "إسلام", "مينا", "بيتر", "جورج", "حسام", "رامي", "تامر", "عمر", "يوسف",
]
FIRST_F = [
    "سارة", "منى", "هالة", "نورهان", "دينا", "ياسمين", "مريم", "هدى", "أميرة",
    "رانيا", "شيماء", "نهى", "سلمى", "فاطمة", "إيمان", "مي", "لمياء", "جيهان",
    "نرمين", "مروة", "آية", "حنان", "سمية", "ندى", "رشا",
]
LAST = [
    "عبد الرحمن", "الشناوي", "منصور", "فؤاد", "الديب", "بدر", "سليم", "الصاوي",
    "عبد العزيز", "الشربيني", "رأفت", "سامي", "فتحي", "عبد الله", "منير",
    "جمال", "لطفي", "زكي", "الحسيني", "عثمان", "قنديل", "المصري", "السيد",
    "نصار", "الجندي", "عبد الحميد", "شكري", "رضوان", "الطوخي", "باشا",
]
FOREIGN = [
    ("Anna", "Kowalski", "PL"), ("Marco", "Rossi", "IT"), ("Kevin", "Brooks", "GB"),
    ("Sophie", "Dubois", "FR"), ("Hans", "Müller", "DE"), ("Elena", "Petrova", "RU"),
    ("James", "Carter", "US"), ("Laura", "Bianchi", "IT"), ("Erik", "Hansen", "DK"),
    ("Nadia", "Haddad", "LB"), ("Omar", "Al-Rashid", "SA"), ("Fatima", "Al-Zahra", "AE"),
]

CITIES = ["القاهرة", "الجيزة", "الإسكندرية", "المنصورة", "طنطا", "أسيوط", "بورسعيد", "الفيوم"]


# ═══════════════════════════════════════════════════════════ الموسمية
#: نسبة الإشغال المستهدفة لكل شهر
MONTH_OCCUPANCY = {
    1: 0.62, 2: 0.55, 3: 0.63, 4: 0.74, 5: 0.71, 6: 0.82,
    7: 0.91, 8: 0.94, 9: 0.78, 10: 0.52, 11: 0.46, 12: 0.80,
}

#: توزيع مصادر الحجز والعمولة المصاحبة
SOURCES: list[tuple[BookingSource, float, Decimal]] = [
    (BookingSource.BOOKING_COM, 0.34, Decimal("17")),
    (BookingSource.WEBSITE, 0.18, Decimal("0")),
    (BookingSource.DIRECT, 0.14, Decimal("0")),
    (BookingSource.AGODA, 0.11, Decimal("15")),
    (BookingSource.EXPEDIA, 0.07, Decimal("16")),
    (BookingSource.AIRBNB, 0.05, Decimal("14")),
    (BookingSource.TRAVEL_AGENT, 0.06, Decimal("10")),
    (BookingSource.WALK_IN, 0.03, Decimal("0")),
    (BookingSource.CORPORATE, 0.02, Decimal("0")),
]

#: توزيع عدد الليالي
NIGHT_WEIGHTS = [(1, 0.10), (2, 0.24), (3, 0.26), (4, 0.16), (5, 0.10), (7, 0.11), (10, 0.03)]


def weighted_choice(options):
    total = sum(w for _, w in options)
    roll = RNG.random() * total
    upto = 0.0
    for value, weight in options:
        upto += weight
        if roll <= upto:
            return value
    return options[-1][0]


def pick_source() -> tuple[BookingSource, Decimal]:
    total = sum(w for _, w, _ in SOURCES)
    roll = RNG.random() * total
    upto = 0.0
    for source, weight, commission in SOURCES:
        upto += weight
        if roll <= upto:
            return source, commission
    return SOURCES[0][0], SOURCES[0][2]


def occupancy_for(day: date) -> float:
    base = MONTH_OCCUPANCY[day.month]
    if day.weekday() in (3, 4, 5):        # خميس، جمعة، سبت
        base *= 1.12
    elif day.weekday() in (6, 0):          # أحد، اثنين
        base *= 0.90
    base *= RNG.uniform(0.93, 1.07)
    return min(0.99, max(0.15, base))


# ═══════════════════════════════════════════════════════════ السياق
@dataclass
class Ctx:
    prop: Property
    categories: list[UnitCategory]
    units_by_cat: dict[int, list[Unit]]
    sellable_by_cat: dict[int, list[Unit]]
    plans: list[RatePlan]
    plan_weights: list[float]
    rates: dict[tuple[int, int, date], Decimal]
    outlets: dict[str, Outlet]
    tables_by_outlet: dict[int, list[PosTable]]
    items_by_outlet: dict[int, list[MenuItem]]
    users: dict[str, User]
    guest_ids: list[int] = field(default_factory=list)


def load_context(db: Session) -> Ctx:
    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    categories = list(
        db.execute(
            select(UnitCategory)
            .where(UnitCategory.property_id == prop.id)
            .order_by(UnitCategory.sort_order)
        ).scalars().all()
    )
    units = list(
        db.execute(select(Unit).where(Unit.property_id == prop.id)).scalars().all()
    )
    units_by_cat: dict[int, list[Unit]] = defaultdict(list)
    sellable_by_cat: dict[int, list[Unit]] = defaultdict(list)
    for unit in units:
        units_by_cat[unit.category_id].append(unit)
        # الوحدات خارج الخدمة مش بتتباع — لو اتحجزت هيطلع إشغال فوق 100%
        if unit.condition == UnitCondition.OPERATIONAL:
            sellable_by_cat[unit.category_id].append(unit)

    plans = list(
        db.execute(
            select(RatePlan).where(RatePlan.property_id == prop.id).order_by(RatePlan.sort_order)
        ).scalars().all()
    )
    plan_weights = [0.42, 0.24, 0.14, 0.14, 0.06][: len(plans)]

    rates = {
        (r.unit_category_id, r.rate_plan_id, r.stay_date): r.rate
        for r in db.execute(select(RateCalendarEntry)).scalars().all()
    }

    outlets = {
        o.code: o
        for o in db.execute(select(Outlet).where(Outlet.property_id == prop.id))
        .scalars().all()
    }
    tables_by_outlet: dict[int, list[PosTable]] = defaultdict(list)
    for table in db.execute(select(PosTable)).scalars().all():
        tables_by_outlet[table.outlet_id].append(table)

    items_by_outlet: dict[int, list[MenuItem]] = defaultdict(list)
    # العلاقة معرّفة noload في النموذج (عشان القوائم متجرّش أصناف معاها)،
    # فلازم نطلبها صراحة هنا.
    menu_items = (
        db.execute(select(MenuItem).options(selectinload(MenuItem.outlets)))
        .scalars()
        .unique()
        .all()
    )
    for item in menu_items:
        for outlet in item.outlets:
            items_by_outlet[outlet.id].append(item)
    if not items_by_outlet:
        raise RuntimeError("مفيش أصناف مربوطة بمنافذ البيع — شغّل seed_master الأول")

    users = {
        u.username: u for u in db.execute(select(User)).scalars().all()
    }

    return Ctx(
        prop=prop,
        categories=categories,
        units_by_cat=units_by_cat,
        sellable_by_cat=sellable_by_cat,
        plans=plans,
        plan_weights=plan_weights,
        rates=rates,
        outlets=outlets,
        tables_by_outlet=tables_by_outlet,
        items_by_outlet=items_by_outlet,
        users=users,
    )


# ═══════════════════════════════════════════════════════════ النزلاء
def create_guests(db: Session, ctx: Ctx, count: int) -> list[int]:
    start_id = (db.execute(select(func.max(Guest.id))).scalar() or 0) + 1
    now = datetime.now(timezone.utc)
    rows = []

    for i in range(count):
        gid = start_id + i
        if RNG.random() < 0.14:
            first, last, nat = RNG.choice(FOREIGN)
            id_type = IdentificationType.PASSPORT
            id_number = f"{RNG.randint(100000000, 999999999)}"
            full_en = f"{first} {last}"
        else:
            nat = "EG"
            if RNG.random() < 0.55:
                first = RNG.choice(FIRST_M)
            else:
                first = RNG.choice(FIRST_F)
            last = RNG.choice(LAST)
            id_type = IdentificationType.NATIONAL_ID
            id_number = f"{RNG.randint(28000000000000, 30599999999999)}"
            full_en = None

        rows.append(
            {
                "id": gid,
                "property_id": ctx.prop.id,
                "first_name": first,
                "last_name": last,
                "full_name_en": full_en,
                "nationality": nat,
                "id_type": id_type,
                "id_number": id_number,
                "phone": f"01{RNG.choice('0125')}{RNG.randint(10000000, 99999999)}",
                "email": f"guest{gid}@example.com" if RNG.random() < 0.7 else None,
                "city": RNG.choice(CITIES) if nat == "EG" else None,
                "country": nat,
                "whatsapp_opt_in": RNG.random() < 0.62,
                "marketing_opt_in": RNG.random() < 0.41,
                "is_vip": RNG.random() < 0.05,
                "loyalty_points": 0,
                "is_blacklisted": RNG.random() < 0.004,
                "is_active": True,
                "total_stays": 0,
                "total_nights": 0,
                "total_revenue": Decimal("0"),
                "total_cancellations": 0,
                "total_no_shows": 0,
                "created_at": now,
                "updated_at": now,
            }
        )

    db.execute(insert(Guest), rows)
    db.flush()
    return [r["id"] for r in rows]


# ═══════════════════════════════════════════════════════ توليد الحجوزات
@dataclass
class Counters:
    reservation: int = 0
    reservation_unit: int = 0
    reservation_night: int = 0
    folio: int = 0
    folio_line: int = 0
    payment: int = 0
    pos_order: int = 0
    pos_order_line: int = 0


def generate(db: Session, ctx: Ctx, start: date, end: date) -> dict[str, int]:
    prop = ctx.prop
    today = date.today()
    service_pct = prop.service_charge_percent
    vat_pct = prop.vat_percent

    # مفاتيح صريحة — أسرع بكتير من الإدراج صف صف
    def next_id(model) -> int:
        return (db.execute(select(func.max(model.id))).scalar() or 0) + 1

    res_id = next_id(Reservation)
    ru_id = next_id(ReservationUnit)
    rn_id = next_id(ReservationNight)
    folio_id = next_id(Folio)
    line_id = next_id(FolioLine)
    pay_id = next_id(Payment)
    order_id = next_id(PosOrder)
    oline_id = next_id(PosOrderLine)

    reservations: list[dict] = []
    res_units: list[dict] = []
    res_nights: list[dict] = []
    folios: list[dict] = []
    folio_lines: list[dict] = []
    payments: list[dict] = []
    pos_orders: list[dict] = []
    pos_lines: list[dict] = []

    #: الوحدة مشغولة لحد إمتى (تاريخ المغادرة، غير شامل) — الصالحة للبيع بس
    busy_until: dict[int, date] = {
        u.id: start for units in ctx.sellable_by_cat.values() for u in units
    }
    #: الحجوزات النازلة حالياً — عشان نرحّل عليها أوردرات المطعم
    in_house: dict[date, list[tuple[int, str]]] = defaultdict(list)  # day -> [(folio_id, unit_label)]

    sold_counter: dict[tuple[int, date], int] = defaultdict(int)
    daily: dict[date, dict] = defaultdict(
        lambda: {
            "arrivals": 0, "departures": 0, "no_shows": 0, "cancellations": 0,
            "sold": 0, "room_revenue": Decimal("0"), "new_bookings": 0,
            "walk_ins": 0, "direct": 0, "ota": 0, "commission": Decimal("0"),
            "by_source": defaultdict(Decimal),
        }
    )

    front_desk = [ctx.users[u].id for u in ("ahmed", "mona", "nourhan") if u in ctx.users]

    day = start
    while day < end:
        target_ratio = occupancy_for(day)

        for cat in ctx.categories:
            units = ctx.sellable_by_cat[cat.id]
            if not units:
                continue
            free = [u for u in units if busy_until[u.id] <= day]
            occupied = len(units) - len(free)
            target = int(round(len(units) * target_ratio))
            to_add = max(0, min(target - occupied, len(free)))

            RNG.shuffle(free)
            for unit in free[:to_add]:
                nights = weighted_choice(NIGHT_WEIGHTS)
                departure = day + timedelta(days=nights)
                if departure > end:
                    continue

                plan = RNG.choices(ctx.plans, weights=ctx.plan_weights, k=1)[0]
                source, commission_pct = pick_source()
                guest_id = RNG.choice(ctx.guest_ids)

                adults = RNG.choices([1, 2, 3, 4], weights=[0.08, 0.62, 0.18, 0.12])[0]
                children = RNG.choices([0, 1, 2], weights=[0.68, 0.20, 0.12])[0]

                # --- تسعير الليالي من التقويم المنشور ---
                night_rows = []
                room_total = Decimal("0")
                for n in range(nights):
                    stay_day = day + timedelta(days=n)
                    rate = ctx.rates.get((cat.id, plan.id, stay_day), cat.base_rate)
                    if stay_day.weekday() in (4, 5):
                        rate = q(rate * Decimal("1.25"))
                    extra_adults = max(0, adults - cat.base_occupancy)
                    extra = q(extra_adults * cat.extra_adult_rate + children * cat.extra_child_rate)
                    room_total += rate + extra
                    night_rows.append((stay_day, q(rate), extra))

                room_total = q(room_total)
                discount = q(room_total * Decimal(str(RNG.choice([0, 0, 0, 0, 5, 10])))/100)
                net = q(room_total - discount)
                service = q(net * service_pct / 100)
                tax = q((net + service) * vat_pct / 100)
                grand = q(net + service + tax)
                commission = q(net * commission_pct / 100)

                # --- الحالة حسب موقع التاريخ من النهاردة ---
                lead = RNG.randint(2, 95)
                booked_at = datetime.combine(
                    day - timedelta(days=lead), time(RNG.randint(8, 22), RNG.randint(0, 59)), CAIRO
                )
                roll = RNG.random()
                if departure <= today:
                    if roll < 0.045:
                        status = ReservationStatus.CANCELLED
                    elif roll < 0.062:
                        status = ReservationStatus.NO_SHOW
                    else:
                        status = ReservationStatus.CHECKED_OUT
                elif day <= today < departure:
                    status = ReservationStatus.CHECKED_IN
                else:
                    status = (
                        ReservationStatus.TENTATIVE if roll < 0.17
                        else ReservationStatus.CONFIRMED
                    )

                blocks = status in (
                    ReservationStatus.CONFIRMED,
                    ReservationStatus.TENTATIVE,
                    ReservationStatus.CHECKED_IN,
                    ReservationStatus.CHECKED_OUT,
                )
                if blocks:
                    busy_until[unit.id] = departure

                paid = grand if status == ReservationStatus.CHECKED_OUT else (
                    q(grand * Decimal("0.25")) if status in (
                        ReservationStatus.CONFIRMED, ReservationStatus.CHECKED_IN
                    ) else Decimal("0")
                )

                reservations.append(
                    {
                        "id": res_id,
                        "code": f"VNC-{day.year}-{res_id:06d}",
                        "property_id": prop.id,
                        "status": status,
                        "source": source,
                        "external_reference": (
                            f"{source.value[:3]}{RNG.randint(1000000, 9999999)}"
                            if commission_pct > 0 else None
                        ),
                        "channel_commission_percent": commission_pct,
                        "channel_commission_amount": commission if blocks else Decimal("0"),
                        "guest_id": guest_id,
                        "arrival_date": day,
                        "departure_date": departure,
                        "nights": nights,
                        "adults": adults,
                        "children": children,
                        "infants": 0,
                        "room_total": room_total,
                        "extras_total": Decimal("0"),
                        "discount_total": discount,
                        "service_charge_total": service,
                        "tax_total": tax,
                        "grand_total": grand,
                        "deposit_required": q(grand * Decimal("0.25")),
                        "deposit_paid": paid if paid < grand else q(grand * Decimal("0.25")),
                        "paid_total": paid,
                        "balance": q(grand - paid),
                        "checked_in_at": (
                            datetime.combine(day, time(15, RNG.randint(0, 59)), CAIRO)
                            if status in (ReservationStatus.CHECKED_IN, ReservationStatus.CHECKED_OUT)
                            else None
                        ),
                        "checked_out_at": (
                            datetime.combine(departure, time(11, RNG.randint(0, 59)), CAIRO)
                            if status == ReservationStatus.CHECKED_OUT else None
                        ),
                        "cancelled_at": (
                            booked_at + timedelta(days=RNG.randint(1, max(1, lead - 1)))
                            if status == ReservationStatus.CANCELLED else None
                        ),
                        "is_group": False,
                        "created_by_user_id": RNG.choice(front_desk) if front_desk else None,
                        "created_at": booked_at,
                        "updated_at": booked_at,
                    }
                )

                res_units.append(
                    {
                        "id": ru_id,
                        "reservation_id": res_id,
                        "property_id": prop.id,
                        "unit_category_id": cat.id,
                        "unit_id": unit.id if blocks else None,
                        "rate_plan_id": plan.id,
                        "meal_plan": plan.meal_plan,
                        "arrival_date": day,
                        "departure_date": departure,
                        "nights": nights,
                        "adults": adults,
                        "children": children,
                        "status": status,
                        "room_total": room_total,
                        "discount_total": discount,
                        "created_at": booked_at,
                        "updated_at": booked_at,
                    }
                )

                for stay_day, rate, extra in night_rows:
                    res_nights.append(
                        {
                            "id": rn_id,
                            "reservation_unit_id": ru_id,
                            "reservation_id": res_id,
                            "property_id": prop.id,
                            "unit_category_id": cat.id,
                            "stay_date": stay_day,
                            "published_rate": rate,
                            "rate": rate,
                            "extra_person_amount": extra,
                            "discount_amount": Decimal("0"),
                            "is_overridden": False,
                            "is_posted": status in (
                                ReservationStatus.CHECKED_IN, ReservationStatus.CHECKED_OUT
                            ),
                        }
                    )
                    rn_id += 1

                    if blocks:
                        sold_counter[(cat.id, stay_day)] += 1
                        daily[stay_day]["sold"] += 1
                        daily[stay_day]["room_revenue"] += rate + extra

                # --- الحساب المفتوح ---
                if status in (ReservationStatus.CHECKED_IN, ReservationStatus.CHECKED_OUT):
                    opened = datetime.combine(day, time(15, 0), CAIRO)
                    folios.append(
                        {
                            "id": folio_id,
                            "code": f"F-{day.year}-{folio_id:06d}",
                            "property_id": prop.id,
                            "folio_type": FolioType.GUEST,
                            "status": (
                                FolioStatus.CLOSED
                                if status == ReservationStatus.CHECKED_OUT
                                else FolioStatus.OPEN
                            ),
                            "reservation_id": res_id,
                            "reservation_unit_id": ru_id,
                            "guest_id": guest_id,
                            "unit_label": unit.label,
                            "charges_total": net,
                            "payments_total": paid,
                            "discount_total": discount,
                            "service_charge_total": service,
                            "tax_total": tax,
                            "balance": q(grand - paid),
                            "opened_at": opened,
                            "closed_at": (
                                datetime.combine(departure, time(11, 30), CAIRO)
                                if status == ReservationStatus.CHECKED_OUT else None
                            ),
                            "created_at": opened,
                            "updated_at": opened,
                        }
                    )

                    # سطر لكل ليلة إقامة
                    for stay_day, rate, extra in night_rows:
                        amount = q(rate + extra)
                        line_service = q(amount * service_pct / 100)
                        line_tax = q((amount + line_service) * vat_pct / 100)
                        folio_lines.append(
                            {
                                "id": line_id,
                                "created_at": datetime.combine(stay_day, time(3, 0), CAIRO),
                                "folio_id": folio_id,
                                "property_id": prop.id,
                                "business_date": stay_day,
                                "charge_kind": ChargeKind.ROOM,
                                "description_ar": f"إقامة ليلة {stay_day.isoformat()} — {unit.label}",
                                "description_en": f"Room night {stay_day.isoformat()} — {unit.label}",
                                "quantity": Decimal("1"),
                                "unit_price": amount,
                                "amount": amount,
                                "service_charge_amount": line_service,
                                "tax_amount": line_tax,
                                "tax_percent": vat_pct,
                                "total_amount": q(amount + line_service + line_tax),
                                "is_transferred": False,
                                "is_void": False,
                            }
                        )
                        line_id += 1

                    for n in range(nights):
                        in_house[day + timedelta(days=n)].append((folio_id, unit.label))

                    if paid > 0:
                        pay_day = departure if status == ReservationStatus.CHECKED_OUT else day
                        method = RNG.choices(
                            [PaymentMethod.CASH, PaymentMethod.CARD, PaymentMethod.OTA_PREPAID,
                             PaymentMethod.INSTAPAY],
                            weights=[0.34, 0.44, 0.14, 0.08],
                        )[0]
                        payment_id = pay_id
                        payments.append(
                            {
                                "id": payment_id,
                                "code": f"P-{pay_day.year}-{pay_id:06d}",
                                "property_id": prop.id,
                                "business_date": pay_day,
                                "folio_id": folio_id,
                                "reservation_id": res_id,
                                "guest_id": guest_id,
                                "method": method,
                                "amount": paid,
                                "currency": "EGP",
                                "exchange_rate": Decimal("1"),
                                "amount_base": paid,
                                "is_deposit": status != ReservationStatus.CHECKED_OUT,
                                "is_refund": False,
                                "received_by_user_id": RNG.choice(front_desk) if front_desk else None,
                                "is_void": False,
                                "created_at": datetime.combine(pay_day, time(11, 0), CAIRO),
                                "updated_at": datetime.combine(pay_day, time(11, 0), CAIRO),
                            }
                        )
                        pay_id += 1

                        # الدفعة لازم تظهر في كشف الحساب كمان — وإلا مجموع
                        # السطور ميطابقش الرصيد قدام النزيل.
                        is_deposit = status != ReservationStatus.CHECKED_OUT
                        folio_lines.append(
                            {
                                "id": line_id,
                                "created_at": datetime.combine(pay_day, time(11, 0), CAIRO),
                                "folio_id": folio_id,
                                "property_id": prop.id,
                                "business_date": pay_day,
                                "charge_kind": (
                                    ChargeKind.DEPOSIT if is_deposit else ChargeKind.PAYMENT
                                ),
                                "description_ar": (
                                    "عربون محوّل من الحجز" if is_deposit
                                    else f"دفعة — {method.value}"
                                ),
                                "description_en": (
                                    "Booking deposit" if is_deposit
                                    else f"Payment — {method.value}"
                                ),
                                "quantity": Decimal("1"),
                                "unit_price": -paid,
                                "amount": -paid,
                                "service_charge_amount": Decimal("0"),
                                "tax_amount": Decimal("0"),
                                "tax_percent": Decimal("0"),
                                "total_amount": -paid,
                                "payment_id": payment_id,
                                "is_transferred": False,
                                "is_void": False,
                            }
                        )
                        line_id += 1

                    folio_id += 1

                # --- إحصاءات اليوم ---
                stat = daily[day]
                stat["new_bookings"] += 1
                if status == ReservationStatus.NO_SHOW:
                    stat["no_shows"] += 1
                elif status == ReservationStatus.CANCELLED:
                    stat["cancellations"] += 1
                else:
                    stat["arrivals"] += 1
                    daily[departure]["departures"] += 1
                if source == BookingSource.WALK_IN:
                    stat["walk_ins"] += 1
                if commission_pct > 0:
                    stat["ota"] += 1
                    stat["commission"] += commission
                else:
                    stat["direct"] += 1
                stat["by_source"][source.value] += net

                res_id += 1
                ru_id += 1

        day += timedelta(days=1)

    # ═════════════════════════════════════════════ أوردرات نقاط البيع
    outlet_list = [
        ctx.outlets[c] for c in ("REST", "BAR", "CAFE", "SPA", "BEACH") if c in ctx.outlets
    ]
    outlet_weights = [0.42, 0.18, 0.20, 0.08, 0.12][: len(outlet_list)]
    waiters = [ctx.users[u].id for u in ("karim", "sayed", "tarek") if u in ctx.users]
    outlet_daily: dict[tuple[int, date], dict] = defaultdict(
        lambda: {"orders": 0, "covers": 0, "gross": Decimal("0"), "discount": Decimal("0"),
                 "service": Decimal("0"), "tax": Decimal("0"), "cost": Decimal("0"),
                 "room_charge": Decimal("0"), "voids": 0, "void_total": Decimal("0"),
                 "void_after_send": 0}
    )

    day = start
    while day < min(end, today + timedelta(days=1)):
        guests_today = daily[day]["sold"]
        order_count = max(4, int(guests_today * RNG.uniform(0.9, 1.6)))
        residents = in_house.get(day, [])

        for _ in range(order_count):
            outlet = RNG.choices(outlet_list, weights=outlet_weights, k=1)[0]
            items = ctx.items_by_outlet.get(outlet.id, [])
            if not items:
                continue

            tables = ctx.tables_by_outlet.get(outlet.id, [])
            table = RNG.choice(tables) if tables else None
            covers = RNG.choices([1, 2, 3, 4, 6], weights=[0.12, 0.38, 0.18, 0.22, 0.10])[0]

            # ترحيل على الغرفة لو فيه نزلاء نازلين
            room_charge = residents and RNG.random() < 0.38
            folio_ref, unit_label = RNG.choice(residents) if room_charge else (None, None)

            line_count = RNG.randint(1, 6)
            chosen = RNG.sample(items, min(line_count, len(items)))
            subtotal = Decimal("0")
            cost_total = Decimal("0")
            order_lines = []
            opened_at = datetime.combine(
                day, time(RNG.randint(9, 23), RNG.randint(0, 59)), CAIRO
            )

            is_void = RNG.random() < 0.018

            for item in chosen:
                qty = Decimal(RNG.choices([1, 2, 3], weights=[0.68, 0.26, 0.06])[0])
                line_total = q(item.price * qty)
                subtotal += line_total
                cost_total += q(item.cost * qty)
                line_void = (not is_void) and RNG.random() < 0.012
                voided_after_send = line_void and RNG.random() < 0.45
                order_lines.append(
                    {
                        "id": oline_id,
                        "created_at": opened_at,
                        "order_id": order_id,
                        "property_id": prop.id,
                        "outlet_id": outlet.id,
                        "business_date": day,
                        "menu_item_id": item.id,
                        "item_name_ar": item.name_ar,
                        "item_name_en": item.name_en,
                        "kitchen_station_id": item.kitchen_station_id,
                        "quantity": qty,
                        "unit_price": item.price,
                        "unit_cost": item.cost,
                        "line_discount": Decimal("0"),
                        "line_total": line_total,
                        "kot_status": "SERVED",
                        "sent_at": opened_at + timedelta(minutes=RNG.randint(1, 6)),
                        "is_void": line_void,
                        "voided_after_send": voided_after_send,
                    }
                )
                oline_id += 1
                if line_void:
                    subtotal -= line_total
                    cost_total -= q(item.cost * qty)
                    stat_key = (outlet.id, day)
                    outlet_daily[stat_key]["voids"] += 1
                    outlet_daily[stat_key]["void_total"] += line_total
                    if voided_after_send:
                        outlet_daily[stat_key]["void_after_send"] += 1

            subtotal = q(max(Decimal("0"), subtotal))
            disc_pct = Decimal(str(RNG.choice([0, 0, 0, 0, 0, 5, 10, 15])))
            discount = q(subtotal * disc_pct / 100)
            net = q(subtotal - discount)
            service = q(net * outlet.service_charge_percent / 100)
            tax = q((net + service) * outlet.vat_percent / 100)
            grand = q(net + service + tax)

            settlement = (
                SettlementType.ROOM_CHARGE if room_charge
                else RNG.choices(
                    [SettlementType.CASH, SettlementType.CARD], weights=[0.42, 0.58]
                )[0]
            )

            pos_orders.append(
                {
                    "id": order_id,
                    "code": f"{outlet.order_prefix}-{day.year}-{order_id:06d}",
                    "property_id": prop.id,
                    "outlet_id": outlet.id,
                    "business_date": day,
                    "order_type": (
                        PosOrderType.ROOM_SERVICE if outlet.code == "RSVC"
                        else PosOrderType.DINE_IN
                    ),
                    "status": PosOrderStatus.VOID if is_void else PosOrderStatus.SETTLED,
                    "table_id": table.id if table else None,
                    "covers": covers,
                    "folio_id": folio_ref,
                    "unit_label": unit_label,
                    "subtotal": subtotal,
                    "discount_total": discount,
                    "discount_percent": disc_pct,
                    "discount_approved_by_user_id": (
                        ctx.users["tarek"].id if disc_pct > 0 and "tarek" in ctx.users else None
                    ),
                    "service_charge_total": service,
                    "tax_total": tax,
                    "grand_total": grand,
                    "paid_total": Decimal("0") if is_void else grand,
                    "settlement_type": settlement,
                    "waiter_user_id": RNG.choice(waiters) if waiters else None,
                    "cashier_user_id": ctx.users["sayed"].id if "sayed" in ctx.users else None,
                    "opened_at": opened_at,
                    "settled_at": opened_at + timedelta(minutes=RNG.randint(20, 110)),
                    "is_void": is_void,
                    "void_reason": "إلغاء بواسطة المدير" if is_void else None,
                    "created_at": opened_at,
                    "updated_at": opened_at,
                }
            )
            pos_lines.extend(order_lines)

            if not is_void:
                stat_key = (outlet.id, day)
                agg = outlet_daily[stat_key]
                agg["orders"] += 1
                agg["covers"] += covers
                agg["gross"] += subtotal
                agg["discount"] += discount
                agg["service"] += service
                agg["tax"] += tax
                agg["cost"] += cost_total

                # ترحيل الأوردر على حساب النزيل
                if room_charge and folio_ref:
                    folio_lines.append(
                        {
                            "id": line_id,
                            "created_at": opened_at,
                            "folio_id": folio_ref,
                            "property_id": prop.id,
                            "business_date": day,
                            "charge_kind": (
                                ChargeKind.SPA if outlet.code == "SPA" else ChargeKind.FNB
                            ),
                            "description_ar": f"{outlet.name_ar} — أوردر {order_id}",
                            "description_en": f"{outlet.name_en} — order {order_id}",
                            "quantity": Decimal("1"),
                            "unit_price": net,
                            "amount": net,
                            "service_charge_amount": service,
                            "tax_amount": tax,
                            "tax_percent": outlet.vat_percent,
                            "total_amount": grand,
                            "outlet_id": outlet.id,
                            "pos_order_id": order_id,
                            "is_transferred": False,
                            "is_void": False,
                        }
                    )
                    line_id += 1
                    agg["room_charge"] += grand
                    daily[day]["by_source"]["POS"] += net

            order_id += 1

        day += timedelta(days=1)

    # ═══════════════════════════════════════════════════ الإدراج المجمّع
    def bulk(model, rows: list[dict], chunk: int = 4000) -> int:
        for i in range(0, len(rows), chunk):
            db.execute(insert(model), rows[i : i + chunk])
        db.flush()
        return len(rows)

    counts = {
        "reservations": bulk(Reservation, reservations),
        "reservation_units": bulk(ReservationUnit, res_units),
        "reservation_nights": bulk(ReservationNight, res_nights),
        "folios": bulk(Folio, folios),
        "folio_lines": bulk(FolioLine, folio_lines),
        "payments": bulk(Payment, payments),
        "pos_orders": bulk(PosOrder, pos_orders),
        "pos_order_lines": bulk(PosOrderLine, pos_lines),
    }

    # ═══════════════════════════════════════ تحديث عدّاد الإتاحة دفعة واحدة
    now = datetime.now(timezone.utc)
    updates = [
        {"_cat": cat_id, "_day": stay_day, "sold": sold}
        for (cat_id, stay_day), sold in sold_counter.items()
    ]
    for i in range(0, len(updates), 2000):
        for row in updates[i : i + 2000]:
            db.execute(
                update(AvailabilityCalendar)
                .where(
                    AvailabilityCalendar.unit_category_id == row["_cat"],
                    AvailabilityCalendar.stay_date == row["_day"],
                )
                .values(sold_units=row["sold"], updated_at=now)
            )
        db.flush()
    counts["availability_updated"] = len(updates)

    # ═══════════════════════════════════════════════ جداول الملخّص اليومية
    total_units = sum(len(u) for u in ctx.units_by_cat.values())
    sellable_units = sum(len(u) for u in ctx.sellable_by_cat.values())
    ooo_units = total_units - sellable_units
    stats_rows = []
    stat_id = (db.execute(select(func.max(DailyStatistics.id))).scalar() or 0) + 1

    outlet_totals: dict[date, dict] = defaultdict(
        lambda: {"fnb": Decimal("0"), "spa": Decimal("0"), "covers": 0, "orders": 0,
                 "net": Decimal("0")}
    )
    for (outlet_id, sday), agg in outlet_daily.items():
        bucket = outlet_totals[sday]
        net = agg["gross"] - agg["discount"]
        bucket["net"] += net
        bucket["covers"] += agg["covers"]
        bucket["orders"] += agg["orders"]
        outlet_code = next(
            (o.code for o in ctx.outlets.values() if o.id == outlet_id), "REST"
        )
        if outlet_code == "SPA":
            bucket["spa"] += net
        else:
            bucket["fnb"] += net

    day = start
    while day < min(end, today + timedelta(days=1)):
        stat = daily[day]
        pos = outlet_totals.get(day, {"fnb": Decimal("0"), "spa": Decimal("0"),
                                      "covers": 0, "orders": 0, "net": Decimal("0")})
        sold = stat["sold"]
        room_rev = q(stat["room_revenue"])
        total_rev = q(room_rev + pos["net"])
        adr = q(room_rev / sold) if sold else Decimal("0")
        # مؤشرات الفنادق بتتحسب على الوحدات **المتاحة للبيع** مش الإجمالي
        revpar = q(room_rev / sellable_units) if sellable_units else Decimal("0")
        trevpar = q(total_rev / sellable_units) if sellable_units else Decimal("0")
        avg_check = q(pos["net"] / pos["orders"]) if pos["orders"] else Decimal("0")

        stats_rows.append(
            {
                "id": stat_id,
                "property_id": prop.id,
                "business_date": day,
                "total_units": total_units,
                "out_of_order_units": ooo_units,
                "available_units": sellable_units - sold,
                "sold_units": sold,
                "complimentary_units": 0,
                "occupancy_percent": (
                    q(Decimal(sold) / sellable_units * 100) if sellable_units else Decimal("0")
                ),
                "guests_in_house": int(sold * 2.3),
                "arrivals": stat["arrivals"],
                "departures": stat["departures"],
                "walk_ins": stat["walk_ins"],
                "no_shows": stat["no_shows"],
                "cancellations": stat["cancellations"],
                "new_bookings": stat["new_bookings"],
                "room_revenue": room_rev,
                "fnb_revenue": q(pos["fnb"]),
                "spa_revenue": q(pos["spa"]),
                "activity_revenue": Decimal("0"),
                "other_revenue": Decimal("0"),
                "total_revenue": total_rev,
                "discount_total": Decimal("0"),
                "service_charge_total": Decimal("0"),
                "tax_total": Decimal("0"),
                "adr": adr,
                "revpar": revpar,
                "trevpar": trevpar,
                "average_check": avg_check,
                "covers": pos["covers"],
                "ota_commission_total": q(stat["commission"]),
                "direct_bookings": stat["direct"],
                "ota_bookings": stat["ota"],
                "revenue_by_source": {k: str(q(v)) for k, v in stat["by_source"].items()},
                "cash_total": Decimal("0"),
                "card_total": Decimal("0"),
                "city_ledger_total": Decimal("0"),
                "computed_at": now,
            }
        )
        stat_id += 1
        day += timedelta(days=1)

    counts["daily_statistics"] = bulk(DailyStatistics, stats_rows)

    ostat_id = (db.execute(select(func.max(DailyOutletStatistics.id))).scalar() or 0) + 1
    ostats = []
    for (outlet_id, sday), agg in outlet_daily.items():
        net = q(agg["gross"] - agg["discount"])
        ostats.append(
            {
                "id": ostat_id,
                "property_id": prop.id,
                "outlet_id": outlet_id,
                "business_date": sday,
                "orders_count": agg["orders"],
                "covers": agg["covers"],
                "gross_sales": q(agg["gross"]),
                "discount_total": q(agg["discount"]),
                "net_sales": net,
                "service_charge_total": q(agg["service"]),
                "tax_total": q(agg["tax"]),
                "cost_of_sales": q(agg["cost"]),
                "average_check": q(net / agg["orders"]) if agg["orders"] else Decimal("0"),
                "room_charge_total": q(agg["room_charge"]),
                "void_count": agg["voids"],
                "void_total": q(agg["void_total"]),
                "void_after_send_count": agg["void_after_send"],
            }
        )
        ostat_id += 1
    counts["daily_outlet_statistics"] = bulk(DailyOutletStatistics, ostats)

    return counts


# ═══════════════════════════════════════════════ إحصاءات النزلاء وحالة الوحدات
def refresh_guest_stats(db: Session) -> int:
    rows = db.execute(
        select(
            Reservation.guest_id,
            func.count(Reservation.id),
            func.sum(Reservation.nights),
            func.sum(Reservation.paid_total),
            func.min(Reservation.arrival_date),
            func.max(Reservation.arrival_date),
        )
        .where(Reservation.status == ReservationStatus.CHECKED_OUT)
        .group_by(Reservation.guest_id)
    ).all()

    for guest_id, stays, nights, revenue, first_stay, last_stay in rows:
        db.execute(
            update(Guest)
            .where(Guest.id == guest_id)
            .values(
                total_stays=stays or 0,
                total_nights=nights or 0,
                total_revenue=q(revenue or 0),
                first_stay_date=first_stay,
                last_stay_date=last_stay,
                loyalty_points=int((revenue or 0) / 100),
            )
        )
    db.flush()
    return len(rows)


def refresh_folio_totals(db: Session) -> int:
    """إعادة حساب أرصدة كل الحسابات من سطورها.

    لازم تتنفّذ بعد ترحيل أوردرات نقاط البيع، وإلا الرصيد المعروض ميطابقش
    كشف الحساب — وده أول حاجة العميل هيلاحظها.
    """
    credit_kinds = [k.value for k in CREDIT_CHARGE_KINDS]

    rows = db.execute(
        select(
            FolioLine.folio_id,
            # المدين: كل ما هو مش دفعة أو خصم
            func.sum(
                case((FolioLine.charge_kind.in_(credit_kinds), 0), else_=FolioLine.amount)
            ),
            # الدائن: الدفعات والخصومات (متخزّنة بالسالب، فبنعكسها)
            func.sum(
                case((FolioLine.charge_kind.in_(credit_kinds), -FolioLine.amount), else_=0)
            ),
            func.sum(FolioLine.service_charge_amount),
            func.sum(FolioLine.tax_amount),
        )
        .where(FolioLine.is_void.is_(False), FolioLine.is_transferred.is_(False))
        .group_by(FolioLine.folio_id)
    ).all()

    for folio_id, debit, credit, service, tax in rows:
        charges = q(Decimal(str(debit or 0)))
        paid = q(Decimal(str(credit or 0)))
        service_total = q(Decimal(str(service or 0)))
        tax_total = q(Decimal(str(tax or 0)))
        db.execute(
            update(Folio)
            .where(Folio.id == folio_id)
            .values(
                charges_total=charges,
                service_charge_total=service_total,
                tax_total=tax_total,
                payments_total=paid,
                balance=q(charges + service_total + tax_total - paid),
            )
        )
    db.flush()
    return len(rows)


# ═══════════════════════════════════════════ ضبط عدّادات الترقيم
#: نوع المستند ← العمود اللي فيه الكود
CODE_SOURCES: list[tuple[str, object]] = [
    ("RESERVATION", Reservation.code),
    ("FOLIO", Folio.code),
    ("PAYMENT", Payment.code),
    ("POS_ORDER", PosOrder.code),
]


def prime_sequences(db: Session, property_id: int) -> int:
    """بيوصّل عدّادات الترقيم لآخر رقم موجود فعلاً في الداتا.

    السكربت بيولّد الأكواد بنفسه للسرعة، فجدول العدّادات بيفضل فاضي. من غير
    الخطوة دي أول حجز يتعمل من الشاشة بياخد ``VNC-2026-000001`` جنب حجوزات
    وصلت لـ 016829 — شكل غلط قدام العميل، وفي الآخر تصادم في كود مكرّر.
    """
    updated = 0
    for doc_type, column in CODE_SOURCES:
        prefix_default, padding = sequences.DEFAULTS[doc_type]
        highest: dict[int, int] = {}
        prefixes: dict[int, str] = {}

        for code in db.execute(select(column)).scalars():
            if not code:
                continue
            head, _, tail = code.rpartition("-")
            prefix, _, year_part = head.rpartition("-")
            if not tail.isdigit() or not year_part.isdigit():
                continue
            year = int(year_part)
            number = int(tail)
            if number > highest.get(year, 0):
                highest[year] = number
            prefixes.setdefault(year, prefix or prefix_default)

        for year, last in highest.items():
            row = db.execute(
                select(DocumentSequence).where(
                    DocumentSequence.property_id == property_id,
                    DocumentSequence.doc_type == doc_type,
                    DocumentSequence.period_year == year,
                )
            ).scalar_one_or_none()
            if row is None:
                row = DocumentSequence(
                    property_id=property_id,
                    doc_type=doc_type,
                    prefix=prefix_default,
                    period_year=year,
                    padding=padding,
                    last_number=0,
                )
                db.add(row)
            if last > row.last_number:
                row.last_number = last
                updated += 1
    db.flush()
    return updated


# ═══════════════════════════════════════════════════════════ التشغيل
def run(years_back: int = 2, days_forward: int = 90, guest_count: int = 3500) -> None:
    db = SessionLocal()
    try:
        ctx = load_context(db)
        today = date.today()
        start = date(today.year - years_back, 1, 1)
        end = today + timedelta(days=days_forward)

        existing = db.execute(select(func.count(Reservation.id))).scalar() or 0
        if existing:
            print(f"فيه {existing:,} حجز موجود بالفعل — امسح venicia.db وشغّل seed_master تاني.")
            return

        print(f"توليد {guest_count:,} نزيل...")
        ctx.guest_ids = create_guests(db, ctx, guest_count)
        db.commit()

        print(f"توليد الحركة من {start} إلى {end} — ممكن ياخد دقيقة أو اتنين...")
        counts = generate(db, ctx, start, end)
        db.commit()

        print("تحديث إحصاءات النزلاء وأرصدة الحسابات...")
        guests_updated = refresh_guest_stats(db)
        folios_balanced = refresh_folio_totals(db)
        counters = prime_sequences(db, ctx.prop.id)
        db.commit()

        print()
        print("─" * 52)
        print(f"  النزلاء                {guest_count:,}")
        for key, value in counts.items():
            print(f"  {key:<22} {value:,}")
        print(f"  نزلاء بإحصاءات محدّثة  {guests_updated:,}")
        print(f"  حسابات اتظبطت أرصدتها  {folios_balanced:,}")
        print(f"  عدّادات ترقيم اتظبطت   {counters:,}")
        total = sum(counts.values()) + guest_count
        print("─" * 52)
        print(f"  إجمالي الصفوف          {total:,}")
        print("─" * 52)
    finally:
        db.close()


if __name__ == "__main__":
    run()
