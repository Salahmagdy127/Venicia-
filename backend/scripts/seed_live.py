"""الحالة اللحظية للعرض — Live-state seeder.

الداتا التاريخية بتخلّي الأرقام حقيقية، بس الشاشات التشغيلية بتفتح فاضية:
الصالة من غير أوردرات مفتوحة، وشاشة الحجوزات من غير حجوزات تستنى تخصيص.
السكربت ده بيحطّ الحالة اللحظية اللي بتخلي الشاشات تبان زي ما هي وسط اليوم.

    python -m scripts.seed_live

بيشتغل أكتر من مرة من غير ما يكرّر: لو لقى أوردرات مفتوحة بالفعل بيسيبها.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.base import SessionLocal
from app.models.channels import Channel, ChannelBooking
from app.models.maintenance import MaintenanceTicket
from app.models.enums import (
    BLOCKING_RESERVATION_STATUSES,
    ChannelBookingStatus,
    OutletType,
    PosOrderStatus,
    TicketCategory,
    TicketPriority,
    TicketSource,
    UnitCondition,
    WaitlistPriority,
    WaitlistStatus,
)
from app.models.guests import Guest
from app.models.organization import Property
from app.models.pos import MenuItem, Outlet, PosOrder, PosTable
from app.models.rates import RatePlan
from app.models.reservations import ReservationUnit, WaitlistEntry
from app.models.security import User
from app.models.units import Unit, UnitCategory
from app.services import availability as av
from app.services import channel_sync as cs
from app.services import maintenance as mt
from app.services import pos as pos_svc
from app.services import waitlist as wl

RNG = random.Random(20260812)

#: نسبة الطاولات المشغولة في كل منفذ — أرقام وقت الغدا في قرية على البحيرة
BUSY_RATIO = 0.45
#: كام حجز قادم نسيبه من غير تخصيص وحدة عشان شريط «لم تُخصص» يبان
UNASSIGNED_TARGET = 5
#: كام طلب في قائمة الانتظار — رقم واقعي لقرية بتترفض فيها طلبات كل ويك إند
WAITLIST_TARGET = 12


def pick_property(db: Session) -> Property:
    prop = db.execute(select(Property).order_by(Property.id)).scalars().first()
    if prop is None:
        raise SystemExit("مفيش منشأة — شغّل scripts.seed_master الأول")
    return prop


def pick_waiter(db: Session, prop: Property) -> User:
    user = db.execute(
        select(User).where(User.property_id == prop.id, User.username == "sayed")
    ).scalar_one_or_none()
    if user is None:
        user = db.execute(select(User).order_by(User.id)).scalars().first()
    if user is None:
        raise SystemExit("مفيش مستخدمين — شغّل scripts.seed_master الأول")
    return user


def open_live_orders(db: Session, prop: Property, waiter: User) -> tuple[int, int]:
    """يفتح أوردرات على جزء من طاولات كل منفذ، وبيبعت نص الأصناف للمطبخ."""
    existing = db.execute(
        select(func.count(PosOrder.id)).where(
            PosOrder.property_id == prop.id,
            PosOrder.status.in_(
                [PosOrderStatus.OPEN, PosOrderStatus.SENT, PosOrderStatus.SERVED]
            ),
        )
    ).scalar_one()
    if existing:
        return 0, 0

    outlets = db.execute(
        select(Outlet).where(Outlet.property_id == prop.id, Outlet.is_active.is_(True))
    ).scalars().all()

    orders = lines = 0
    for outlet in outlets:
        if outlet.outlet_type == OutletType.SPA:
            continue

        tables = db.execute(
            select(PosTable)
            .where(PosTable.outlet_id == outlet.id, PosTable.is_active.is_(True))
            .order_by(PosTable.id)
        ).scalars().all()
        if not tables:
            continue

        items = db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.outlets))
            .where(
                MenuItem.property_id == prop.id,
                MenuItem.is_available.is_(True),
                MenuItem.is_out_of_stock.is_(False),
            )
        ).scalars().unique().all()
        menu = [i for i in items if any(o.id == outlet.id for o in i.outlets)]
        if not menu:
            continue

        busy = RNG.sample(tables, k=max(1, round(len(tables) * BUSY_RATIO)))
        for table in busy:
            order = pos_svc.open_order(
                db,
                property_id=prop.id,
                outlet_id=outlet.id,
                user_id=waiter.id,
                table_id=table.id,
                covers=RNG.randint(1, max(1, table.seats)),
            )
            for item in RNG.sample(menu, k=min(len(menu), RNG.randint(2, 5))):
                pos_svc.add_line(
                    db,
                    order.id,
                    menu_item_id=item.id,
                    quantity=Decimal(RNG.choice([1, 1, 1, 2])),
                )
                lines += 1

            # تلت الطاولات لسه بتطلب، والباقي أكلهم في المطبخ
            if RNG.random() > 0.34:
                pos_svc.send_to_kitchen(db, order.id)
            orders += 1

    return orders, lines


def unassign_upcoming(db: Session, prop: Property) -> int:
    """بيسيب حجوزات قادمة من غير وحدة — زي اللي بيجي من القنوات ولسه محتاج تخصيص."""
    today = date.today()
    already = db.execute(
        select(func.count(ReservationUnit.id)).where(
            ReservationUnit.property_id == prop.id,
            ReservationUnit.unit_id.is_(None),
            ReservationUnit.arrival_date >= today,
            ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
        )
    ).scalar_one()
    if already >= UNASSIGNED_TARGET:
        return 0

    candidates = db.execute(
        select(ReservationUnit)
        .where(
            ReservationUnit.property_id == prop.id,
            ReservationUnit.unit_id.isnot(None),
            ReservationUnit.arrival_date > today + timedelta(days=1),
            ReservationUnit.arrival_date <= today + timedelta(days=10),
            ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
        )
        .order_by(ReservationUnit.arrival_date)
        .limit(60)
    ).scalars().all()
    if not candidates:
        return 0

    chosen = RNG.sample(candidates, k=min(UNASSIGNED_TARGET - already, len(candidates)))
    for line in chosen:
        line.unit_id = None
    return len(chosen)


def seed_waitlist(db: Session, prop: Property) -> int:
    """طلبات مستنية على الأيام المقفولة — ده الوضع الطبيعي في الويك إند.

    بنختار أيام إتاحتها صفر فعلاً، فالقايمة بتبان زي الواقع: ناس اتقالّهم
    «مفيش» وسايبين رقمهم. وبنخلي شوية منهم مرنين في التواريخ عشان يبان
    عمود «فيه مكان دلوقتي» شغّال.
    """
    existing = db.execute(
        select(func.count(WaitlistEntry.id)).where(
            WaitlistEntry.property_id == prop.id,
            WaitlistEntry.status.in_([WaitlistStatus.WAITING, WaitlistStatus.OFFERED]),
        )
    ).scalar_one()
    if existing >= WAITLIST_TARGET:
        return 0

    today = date.today()
    horizon = today + timedelta(days=45)
    rows = av.get_availability(db, prop.id, today + timedelta(days=1), horizon)
    # المقفول تماماً أول الأولوية، وبعدين اللي فاضل فيه وحدة واحدة
    full = [r for r in rows if r.available == 0] + [r for r in rows if r.available == 1]
    if not full:
        return 0

    guests = db.execute(
        select(Guest)
        .where(Guest.property_id == prop.id, Guest.is_blacklisted.is_(False))
        .order_by(Guest.total_stays.desc())
        .limit(400)
    ).scalars().all()
    if not guests:
        return 0

    plan_id = db.execute(
        select(RatePlan.id)
        .where(RatePlan.property_id == prop.id, RatePlan.is_active.is_(True))
        .order_by(RatePlan.sort_order)
        .limit(1)
    ).scalar_one_or_none()

    made = 0
    for slot in RNG.sample(full, k=min(WAITLIST_TARGET - existing, len(full))):
        guest = RNG.choice(guests)
        nights = RNG.choice([2, 2, 3, 4])
        priority = (
            WaitlistPriority.VIP
            if guest.is_vip
            else RNG.choice(
                [WaitlistPriority.NORMAL, WaitlistPriority.NORMAL, WaitlistPriority.HIGH]
            )
        )
        try:
            wl.add(
                db,
                property_id=prop.id,
                guest_id=guest.id,
                unit_category_id=slot.unit_category_id,
                arrival=slot.stay_date,
                departure=slot.stay_date + timedelta(days=nights),
                adults=RNG.choice([2, 2, 3, 4]),
                children=RNG.choice([0, 0, 1, 2]),
                rate_plan_id=plan_id,
                # التلت مرنين — دول اللي هيلاقولهم مكان أول ما حجز يتلغي
                flexible_days=RNG.choice([0, 0, 2, 3]),
                priority=priority,
                contact_note=RNG.choice(
                    [
                        "بيسأل على إطلالة البحيرة",
                        "عايز يقرب من الشاطئ",
                        "مناسبة عيد جواز",
                        None,
                        None,
                    ]
                ),
            )
            made += 1
        except wl.WaitlistError:
            continue  # نزيل متكرر على نفس التواريخ — بنعدّيه
    return made


def seed_overbooking(db: Session, prop: Property) -> int:
    """حد تجاوز بسيط على الويك إندات الجاية للفئات الكبيرة.

    مش بيعمل بيع زايد بنفسه — بيوسّع السعة المسموح بيها بس، عشان الشاشة
    تفتح والضبط شغّال بدل ما يبان زرار مالوش أثر.
    """
    today = date.today()
    big = db.execute(
        select(UnitCategory.id)
        .where(UnitCategory.property_id == prop.id, UnitCategory.is_active.is_(True))
        .order_by(UnitCategory.sort_order)
        .limit(2)
    ).scalars().all()
    if not big:
        return 0

    touched = 0
    for offset in range(1, 60):
        day = today + timedelta(days=offset)
        if day.weekday() not in (4, 5):  # الجمعة والسبت
            continue
        touched += av.set_overbooking(db, prop.id, day, day + timedelta(days=1), 1, big)
    return touched


#: أسماء بتوصل من القنوات — خليط مصري وأجنبي زي الواقع
CHANNEL_GUESTS: list[tuple[str, str, str]] = [
    ("Mohamed", "Fahmy", "+201001234501"),
    ("Sarah", "Whitfield", "+447700900123"),
    ("Andrea", "Rossi", "+393331234567"),
    ("ياسمين", "الشناوي", "+201112345602"),
    ("Dmitri", "Volkov", "+79161234567"),
    ("عمرو", "بدوي", "+201223456703"),
]


def _free_window(
    db: Session, prop: Property, category_id: int, nights: int, today: date
) -> tuple[date, date] | None:
    """أول مدى متتالي فاضي للفئة دي — القنوات مبتبعتش حجز على يوم مليان."""
    # بداية عشوائية عشان الحجوزات متتكوّمش كلها على نفس اليوم
    begin = today + timedelta(days=RNG.randint(3, 25))
    rows = av.get_availability(db, prop.id, begin, begin + timedelta(days=45), [category_id])
    free = {r.stay_date for r in rows if r.available >= 1}
    for row in rows:
        span = [row.stay_date + timedelta(days=i) for i in range(nights)]
        if all(day in free for day in span):
            return row.stay_date, row.stay_date + timedelta(days=nights)
    return None


def seed_channels(db: Session, prop: Property) -> tuple[int, int, int]:
    """حركة قنوات واقعية: مطابقة كاملة + حجوزات واردة فيها المقبول والمرفوض.

    الرفض مقصود يبان في السجل — عشان اللي بيتفرّج يشوف إن النظام بيمسك
    الحجز اللي مالوش مكان بدل ما يبلعه في صمت.
    """
    already = db.execute(
        select(func.count(ChannelBooking.id)).where(ChannelBooking.property_id == prop.id)
    ).scalar_one()
    if already:
        return 0, 0, 0

    channels = list(
        db.execute(
            select(Channel).where(
                Channel.property_id == prop.id, Channel.is_connected.is_(True)
            )
        ).scalars().all()
    )
    if not channels:
        return 0, 0, 0

    # الصورة الكاملة الأول — ده اللي بيحصل أول ما الربط يتظبط
    queued = cs.resync(db, prop.id, days=60)
    cs.flush(db, prop.id, limit=1000)

    today = date.today()
    accepted = rejected = 0

    categories = {
        c.id: c
        for c in db.execute(
            select(UnitCategory).where(UnitCategory.property_id == prop.id)
        ).scalars().all()
    }

    for index, (first, last, phone) in enumerate(CHANNEL_GUESTS):
        channel = channels[index % len(channels)]
        mapping = channel.mappings[index % len(channel.mappings)] if channel.mappings else None
        if mapping is None:
            continue

        nights = RNG.choice([2, 3, 3, 4])
        window = _free_window(db, prop, mapping.unit_category_id, nights, today)
        if window is None:
            continue
        arrival, departure = window

        category = categories.get(mapping.unit_category_id)
        capacity = category.max_occupancy if category else 4
        adults = min(2, capacity)
        children = 1 if capacity >= 3 and RNG.random() < 0.4 else 0

        # واحد من الستة بيجي برقم غرفة مش مربوط — الرفض ده مقصود عشان
        # اللي بيتفرّج يشوف إن السجل بيمسك الغلط بدل ما يبلعه
        room_id = mapping.external_room_id if index != 4 else "UNKNOWN-ROOM"

        row = cs.ingest(
            db,
            prop.id,
            channel.source,
            {
                "external_reference": f"{channel.source[:3]}-{2026}{index:05d}",
                "action": "NEW",
                "external_room_id": room_id,
                "arrival_date": arrival.isoformat(),
                "departure_date": departure.isoformat(),
                "adults": adults,
                "children": children,
                "guest": {
                    "first_name": first,
                    "last_name": last,
                    "phone": phone,
                    "nationality": "EG" if phone.startswith("+20") else "XX",
                },
                "notes": None,
            },
        )
        if row.status == ChannelBookingStatus.PROCESSED:
            accepted += 1
        else:
            rejected += 1

    # آخر واحد بيلغي — عشان مسار الإلغاء يبان في السجل برضه
    last_ok = db.execute(
        select(ChannelBooking)
        .where(
            ChannelBooking.property_id == prop.id,
            ChannelBooking.status == ChannelBookingStatus.PROCESSED,
        )
        .order_by(ChannelBooking.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if last_ok is not None:
        channel = db.get(Channel, last_ok.channel_id)
        cs.ingest(
            db,
            prop.id,
            channel.source,
            {"external_reference": last_ok.external_reference, "action": "CANCEL"},
        )

    cs.flush(db, prop.id, limit=1000)
    return queued, accepted, rejected


#: بلاغات واقعية — (العنوان، النوع، الأولوية، بيحجب الوحدة، مين بلّغ)
TICKETS: list[tuple[str, TicketCategory, TicketPriority, bool, TicketSource]] = [
    ("التكييف مش بيبرّد", TicketCategory.AC, TicketPriority.URGENT, True,
     TicketSource.GUEST),
    ("تسريب مياه تحت الحوض", TicketCategory.PLUMBING, TicketPriority.HIGH, True,
     TicketSource.HOUSEKEEPING),
    ("لمبة السقف محروقة", TicketCategory.ELECTRICAL, TicketPriority.LOW, False,
     TicketSource.HOUSEKEEPING),
    ("ريموت التليفزيون ضايع", TicketCategory.APPLIANCE, TicketPriority.LOW, False,
     TicketSource.HOUSEKEEPING),
    ("الواي فاي ضعيف في الدور الأخير", TicketCategory.NETWORK, TicketPriority.NORMAL, False,
     TicketSource.GUEST),
    ("كرسي الشرفة مكسور", TicketCategory.FURNITURE, TicketPriority.NORMAL, False,
     TicketSource.INSPECTION),
    ("سخان المياه بيفصل", TicketCategory.PLUMBING, TicketPriority.HIGH, True,
     TicketSource.GUEST),
    ("باب البلكونة مش بيقفل كويس", TicketCategory.FURNITURE, TicketPriority.NORMAL, False,
     TicketSource.HOUSEKEEPING),
]


def seed_tickets(db: Session, prop: Property) -> tuple[int, int]:
    """بلاغات صيانة واقعية: منها مفتوح ومسند وشغّال وواحد اتقفل.

    التنوّع مقصود — اللوحة لازم توري كل الحالات مش حالة واحدة.
    """
    already = db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.property_id == prop.id
        )
    ).scalar_one()
    if already:
        return 0, 0

    # وحدات شغّالة مش مقفولة أصلاً.
    #
    # بنبدأ من آخر القايمة عن قصد: الوحدات الأولى في كل فئة هي اللي
    # سكربتات الاختبار بتشتغل عليها، ولو حجبناها الاختبارات بتفشل على
    # داتا سليمة — وده أسوأ من إن البلاغات تبان على وحدات تانية.
    units = list(
        db.execute(
            select(Unit)
            .where(
                Unit.property_id == prop.id,
                Unit.is_active.is_(True),
                Unit.condition == UnitCondition.OPERATIONAL,
            )
            .order_by(Unit.sort_order.desc(), Unit.id.desc())
            .limit(40)
        ).scalars().all()
    )
    techs = list(
        db.execute(
            select(User).where(User.property_id == prop.id, User.is_active.is_(True))
        ).scalars().all()
    )
    if not units or not techs:
        return 0, 0

    made = closed = 0
    for index, (title, category, priority, blocks, source) in enumerate(TICKETS):
        unit = units[index * 3 % len(units)]
        ticket = mt.open_ticket(
            db,
            prop.id,
            title=title,
            unit_id=unit.id,
            category=category,
            priority=priority,
            source=source,
            blocks_unit=blocks,
            description=None,
            user=RNG.choice(techs),
        )
        made += 1

        # التوزيع: واحد من كل تلاتة بيتقفل، والباقي في مراحل مختلفة
        if index % 3 == 0:
            mt.assign(db, ticket.id, RNG.choice(techs).id)
            mt.start(db, ticket.id)
            mt.complete(
                db, ticket.id,
                resolution="اتصلّح واتجرّب قدام السوبرفايزر",
                cost=Decimal(RNG.choice(["0", "150", "320", "80"])),
            )
            closed += 1
        elif index % 3 == 1:
            mt.assign(db, ticket.id, RNG.choice(techs).id)
            if index % 2 == 1:
                mt.start(db, ticket.id)

    db.flush()
    return made, closed


def run() -> None:
    db = SessionLocal()
    try:
        prop = pick_property(db)
        waiter = pick_waiter(db, prop)

        orders, lines = open_live_orders(db, prop, waiter)
        unassigned = unassign_upcoming(db, prop)
        waiting = seed_waitlist(db, prop)
        limits = seed_overbooking(db, prop)
        pushed, from_channels, refused = seed_channels(db, prop)
        tickets, closed_tickets = seed_tickets(db, prop)
        db.commit()

        print("─" * 46)
        print(f"  أوردرات مفتوحة على الطاولات   {orders:>6,}")
        print(f"  أصناف عليها                   {lines:>6,}")
        print(f"  حجوزات بقت من غير تخصيص       {unassigned:>6,}")
        print(f"  طلبات في قائمة الانتظار        {waiting:>6,}")
        print(f"  أيام عليها حد تجاوز            {limits:>6,}")
        print(f"  رسايل مطابقة للقنوات           {pushed:>6,}")
        print(f"  حجوزات جت من القنوات           {from_channels:>6,}")
        print(f"  حجوزات القنوات المرفوضة        {refused:>6,}")
        print(f"  بلاغات صيانة                   {tickets:>6,}  (مقفول: {closed_tickets})")
        print("─" * 46)
        if orders == 0:
            print("  (فيه أوردرات مفتوحة بالفعل — مش هيتكرّر)")
    finally:
        db.close()


if __name__ == "__main__":
    run()
