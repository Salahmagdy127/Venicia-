"""سبا ومناسبات وملاحظات نزلاء للعرض — Leisure, events & feedback demo data.

    python -m scripts.seed_leisure
    python -m scripts.seed_leisure --reset

بيملا الشهرين الجايين بشغل واقعي: مواعيد سبا موزّعة على المعالجين،
رحلات غروب في الأوقات اللي بتتباع فعلاً، فرحين مؤكدين وواحد مبدئي
وواحد ضاع، وشكاوى وتقييمات بأوقات رد مختلفة.

الأرقام كلها بتمشي على نفس مسار النظام — يعني مفيش صف بيتكتب في
الداتابيز مباشرة. الحجز بيمرّ على فحص التعارض، والمناسبة بيتحسب
إجماليها من بنودها، والشكوى بتاخد رقمها من عدّاد المستندات.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.db.base import Base, SessionLocal, engine
from app.models.enums import (
    EventItemKind,
    EventKind,
    EventStatus,
    FeedbackChannel,
    FeedbackKind,
    FolioStatus,
    ServiceBookingStatus,
)
from app.models.folio import Folio
from app.models.guests import Guest
from app.models.leisure import (
    EventBooking,
    EventItem,
    GuestFeedback,
    Service,
    ServiceBooking,
    Venue,
)
from app.models.organization import Property
from app.models.security import User
from app.services import crm
from app.services import leisure as lz

random.seed(20260817)

#: توزيع الطلب الحقيقي: المساج بالليل، الرحلات وقت الغروب، اليوجا الفجر
PEAK_HOURS: dict[str, list[int]] = {
    "SPA": [11, 12, 15, 16, 17, 18, 19, 20],
    "FITNESS": [6, 7],
    "ACTIVITY": [8, 9, 16, 17],
    "EXCURSION": [7, 8, 15],
    "KIDS": [10, 11, 14],
}

WEDDING_TITLES = [
    ("فرح سلمى وأحمد", "عائلة الشناوي"),
    ("فرح ندى وكريم", "عائلة عبد الرحمن"),
    ("كتب كتاب هبة ومحمد", "عائلة الجندي"),
    ("خطوبة ليلى", "عائلة فوزي"),
]

CORPORATE_TITLES = [
    ("يوم شركة النيل للتوزيع", "شركة النيل للتوزيع"),
    ("مؤتمر مبيعات الربع الرابع", "مجموعة الأهرام"),
    ("ورشة القيادة", "بنك القاهرة الأول"),
]

COMPLAINTS = [
    ("التكييف مش بيبرّد كفاية", "الصيانة", 2),
    ("الواي فاي بيقطع في الشاليه", "الصيانة", 3),
    ("طلب خدمة الغرف اتأخر ساعة", "المطعم", 2),
    ("الأوضة ماكانتش جاهزة وقت النزول", "الهاوس كيبينج", 2),
    ("صوت عالي من الشاليه اللي جنبنا", "الاستقبال", 3),
    ("حمام السباحة كان مقفول من غير إعلان", "التشغيل", 3),
]

COMPLIMENTS = [
    ("فريق المطعم كان ممتاز", "المطعم", 5),
    ("المكان نضيف جداً والخدمة راقية", "الهاوس كيبينج", 5),
    ("رحلة الغروب كانت أحلى حاجة في الرحلة", "الأنشطة", 5),
    ("الاستقبال ساعدونا في كل حاجة", "الاستقبال", 5),
    ("المعالجة في السبا شاطرة جداً", "السبا", 5),
]

SUGGESTIONS = [
    ("ياريت فيه مواصلات للقاهرة", "التشغيل", 4),
    ("محتاجين مطعم مفتوح بالليل", "المطعم", 4),
]

FNB_PACKAGES = [
    ("بوفيه عشاء فاخر", "850"),
    ("بوفيه غداء", "600"),
    ("كوكتيل استقبال", "220"),
    ("قهوة وحلويات", "180"),
]


def reset(db, property_id: int) -> tuple[int, int, int]:
    today = date.today()
    bookings = db.execute(
        select(ServiceBooking).where(
            ServiceBooking.property_id == property_id,
            ServiceBooking.business_date >= today - timedelta(days=30),
        )
    ).scalars().all()
    ids = [b.id for b in bookings]
    if ids:
        db.execute(delete(ServiceBooking).where(ServiceBooking.id.in_(ids)))

    events = db.execute(
        select(EventBooking).where(EventBooking.property_id == property_id)
    ).scalars().all()
    event_ids = [e.id for e in events]
    if event_ids:
        db.execute(delete(EventItem).where(EventItem.event_id.in_(event_ids)))
        db.execute(delete(EventBooking).where(EventBooking.id.in_(event_ids)))

    notes = db.execute(
        select(GuestFeedback).where(GuestFeedback.property_id == property_id)
    ).scalars().all()
    note_ids = [n.id for n in notes]
    if note_ids:
        db.execute(delete(GuestFeedback).where(GuestFeedback.id.in_(note_ids)))

    db.commit()
    return len(ids), len(event_ids), len(note_ids)


def seed_spa(db, prop: Property, days: int = 21) -> int:  # noqa: PLR0912
    """مواعيد سبا وأنشطة على الفترة الجاية — بتمرّ على فحص التعارض."""
    services = db.execute(
        select(Service).where(Service.property_id == prop.id, Service.is_active.is_(True))
    ).scalars().all()
    if not services:
        return 0

    folios = db.execute(
        select(Folio)
        .where(Folio.property_id == prop.id, Folio.status == FolioStatus.OPEN)
        .limit(120)
    ).scalars().all()
    guests = db.execute(
        select(Guest).where(Guest.is_active.is_(True)).limit(400)
    ).scalars().all()
    if not guests:
        return 0

    made = 0
    today = date.today()
    now = datetime.now(timezone.utc)

    for offset in range(-3, days):
        day = today + timedelta(days=offset)
        # الويك إند أعلى طلب — الجمعة والسبت
        load = 14 if day.weekday() in (4, 5) else 8
        for _ in range(load):
            service = random.choice(services)
            hours = PEAK_HOURS.get(service.category, [11, 15, 18])
            hour = random.choice(hours)
            minute = random.choice([0, 30])
            start = datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)

            guest = random.choice(guests)
            folio = random.choice(folios) if folios and random.random() < 0.65 else None

            adults = 1
            children = 0
            if service.capacity > 1:
                adults = random.randint(1, min(3, service.capacity))
                if service.price_child > 0 and random.random() < 0.4:
                    children = random.randint(1, 2)

            try:
                booking = lz.book_service(
                    db, prop.id,
                    service_id=service.id,
                    start_at=start,
                    guest_name=f"{guest.first_name} {guest.last_name}".strip(),
                    guest_id=guest.id,
                    folio_id=folio.id if folio else None,
                    adults=adults,
                    children=children,
                )
            except lz.LeisureError:
                continue      # المورد مشغول — عادي، ده بالظبط شغل الفحص

            # اللي عدّى خلاص بياخد حالته النهائية
            if booking.end_at < now:
                roll = random.random()
                if roll < 0.06:
                    booking.status = ServiceBookingStatus.NO_SHOW
                elif roll < 0.12:
                    booking.status = ServiceBookingStatus.CANCELLED
                    booking.cancelled_reason = "النزيل أجّل"
                else:
                    lz.complete(db, booking.id, post_to_folio=bool(folio))
            elif booking.start_at < now < booking.end_at:
                booking.status = ServiceBookingStatus.CHECKED_IN
            made += 1

        if offset % 5 == 0:
            db.commit()

    db.commit()
    return made


def seed_events(db, prop: Property) -> int:
    """مناسبات على مدى الشهرين الجايين + مناسبات خلصت."""
    venues = {
        v.code: v
        for v in db.execute(
            select(Venue).where(Venue.property_id == prop.id)
        ).scalars().all()
    }
    if not venues:
        return 0

    today = date.today()
    plan: list[tuple] = []

    # فرحين على حديقة البحيرة وقاعة الأفراح
    for index, (title, client) in enumerate(WEDDING_TITLES):
        venue = venues["V-LAWN"] if index % 2 == 0 else venues["V-HALL"]
        day = today + timedelta(days=12 + index * 17)
        status = [
            EventStatus.CONFIRMED, EventStatus.CONFIRMED,
            EventStatus.TENTATIVE, EventStatus.INQUIRY,
        ][index]
        plan.append(
            (venue, title, client, day, 17, 24, EventKind.WEDDING,
             status, random.randint(180, 340), "850")
        )

    for index, (title, client) in enumerate(CORPORATE_TITLES):
        venue = venues["V-MEET"] if index == 2 else venues["V-BEACH"]
        day = today + timedelta(days=6 + index * 11)
        plan.append(
            (venue, title, client, day, 9, 17, EventKind.CORPORATE,
             [EventStatus.CONFIRMED, EventStatus.TENTATIVE, EventStatus.INQUIRY][index],
             random.randint(30, 120), "420")
        )

    # مناسبات خلصت — عشان التقارير تلاقي تاريخ
    for index in range(3):
        venue = venues["V-TERR"]
        day = today - timedelta(days=15 + index * 12)
        plan.append(
            (venue, f"حفلة عيد ميلاد {index + 1}", "عميل مباشر", day, 19, 23,
             EventKind.BIRTHDAY, EventStatus.COMPLETED, random.randint(40, 90), "380")
        )

    # واحدة ضاعت — تقرير الخسائر لازم يلاقي حاجة
    plan.append(
        (venues["V-HALL"], "فرح راح لمكان تاني", "عائلة مجهولة",
         today + timedelta(days=40), 18, 24, EventKind.WEDDING,
         EventStatus.LOST, 260, "800")
    )

    made = 0
    for venue, title, client, day, start_h, end_h, kind, status, pax, package in plan:
        start = datetime.combine(day, time(start_h % 24), tzinfo=timezone.utc)
        end = datetime.combine(
            day + (timedelta(days=1) if end_h >= 24 else timedelta()),
            time(end_h % 24),
            tzinfo=timezone.utc,
        )
        # كل مناسبة بتتعمل استعلام الأول وبعدين بتتنقل — زي الواقع
        try:
            event = lz.create_event(
                db, prop.id,
                venue_id=venue.id, title=title, client_name=client,
                start_at=start, end_at=end, kind=kind,
                status=EventStatus.INQUIRY, pax=pax,
                package_per_person=Decimal(package),
                client_phone=f"01{random.randint(0, 2)}{random.randint(10**7, 10**8 - 1)}",
            )
        except lz.LeisureError:
            continue

        label, price = random.choice(FNB_PACKAGES)
        lz.add_item(
            db, event.id, kind=EventItemKind.FNB, description_ar=label,
            quantity=Decimal(pax), unit_price=Decimal(price),
        )
        lz.add_item(
            db, event.id, kind=EventItemKind.EQUIPMENT,
            description_ar="صوت وإضاءة", quantity=Decimal("1"),
            unit_price=Decimal(random.choice(["18000", "26000", "35000"])),
        )
        if kind == EventKind.WEDDING:
            lz.add_item(
                db, event.id, kind=EventItemKind.DECOR,
                description_ar="تنسيق زهور وممر", quantity=Decimal("1"),
                unit_price=Decimal(random.choice(["40000", "65000"])),
            )
            lz.add_item(
                db, event.id, kind=EventItemKind.ACCOMMODATION,
                description_ar="جناح العروسين — مجاملة", quantity=Decimal("1"),
                unit_price=Decimal("6500"), is_complimentary=True,
            )

        db.refresh(event)
        if status in (EventStatus.TENTATIVE, EventStatus.CONFIRMED, EventStatus.COMPLETED):
            lz.set_event_status(db, event.id, EventStatus.TENTATIVE)
        if status in (EventStatus.CONFIRMED, EventStatus.COMPLETED):
            lz.record_deposit(db, event.id, event.deposit_required)
            lz.set_event_status(db, event.id, EventStatus.CONFIRMED)
        if status == EventStatus.COMPLETED:
            lz.set_event_status(db, event.id, EventStatus.COMPLETED)
        if status == EventStatus.LOST:
            lz.set_event_status(
                db, event.id, EventStatus.LOST, reason="السعر أعلى من مكان منافس"
            )

        event.setup_notes = (
            "جلوس دائري ١٠ أفراد للطاولة · وصول الفرقة ٦ مساءً · "
            "المطبخ يبدأ التقديم بعد الزفة بنص ساعة"
        )
        made += 1

    db.commit()
    return made


def seed_feedback(db, prop: Property) -> int:
    """شكاوى وتقييمات بأوقات رد مختلفة — عشان المتوسطات تبقى واقعية."""
    guests = db.execute(
        select(Guest).where(Guest.is_active.is_(True), Guest.total_stays > 0).limit(200)
    ).scalars().all()
    users = db.execute(
        select(User).where(User.property_id == prop.id)
    ).scalars().all()
    if not guests:
        return 0

    manager = next((u for u in users if u.username == "nourhan"), None)
    now = datetime.now(timezone.utc)
    made = 0

    pool = (
        [(s, d, r, FeedbackKind.COMPLAINT, FeedbackChannel.IN_HOUSE) for s, d, r in COMPLAINTS]
        + [(s, d, r, FeedbackKind.COMPLAINT, FeedbackChannel.BOOKING_COM)
           for s, d, r in COMPLAINTS[:3]]
        + [(s, d, r, FeedbackKind.COMPLIMENT, FeedbackChannel.GOOGLE) for s, d, r in COMPLIMENTS]
        + [(s, d, r, FeedbackKind.COMPLIMENT, FeedbackChannel.SURVEY)
           for s, d, r in COMPLIMENTS[:3]]
        + [(s, d, r, FeedbackKind.SUGGESTION, FeedbackChannel.SURVEY) for s, d, r in SUGGESTIONS]
    )

    for index, (subject, department, rating, kind, channel) in enumerate(pool):
        guest = random.choice(guests)
        received = now - timedelta(
            days=random.randint(0, 28), hours=random.randint(0, 23)
        )
        entry = crm.log_feedback(
            db, prop.id,
            subject=subject, kind=kind, channel=channel,
            guest_id=guest.id, department=department, rating=rating,
            body=None, received_at=received, user=manager,
        )

        # ٧٠٪ اتردّ عليها، منهم ٧٥٪ اتحلّت. الباقي لسه مفتوح —
        # لوحة فيها صفر مفتوح بتبان مزوّرة.
        if random.random() < 0.7:
            entry.acknowledged_at = received + timedelta(
                hours=random.choice([0.5, 1, 2, 3, 6, 9])
            )
            entry.status = "ACKNOWLEDGED"
            if random.random() < 0.75:
                entry.resolved_at = entry.acknowledged_at + timedelta(
                    hours=random.randint(2, 60)
                )
                entry.status = "RESOLVED"
                entry.resolution = "اتواصلنا مع النزيل واتحلّت المشكلة"
                if kind == FeedbackKind.COMPLAINT and random.random() < 0.4:
                    entry.compensation = Decimal(random.choice(["500", "1000", "1500"]))
        elif index % 5 == 0:
            entry.status = "ESCALATED"
        made += 1

    db.commit()
    return made


def run(do_reset: bool = False) -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()

        if do_reset:
            removed = reset(db, prop.id)
            print(
                f"اتمسح: {removed[0]} حجز · {removed[1]} مناسبة · {removed[2]} ملاحظة"
            )

        print("مواعيد السبا والأنشطة...")
        bookings = seed_spa(db, prop)

        print("المناسبات وأوراق التشغيل...")
        events = seed_events(db, prop)

        print("ملاحظات النزلاء...")
        notes = seed_feedback(db, prop)

        today_board = lz.board(db, prop.id, date.today())
        events_board = lz.events_board(db, prop.id)
        feedback = crm.feedback_board(db, prop.id)

        print("\n" + "─" * 54)
        print(f"  حجوزات السبا والأنشطة   {bookings}")
        print(
            f"  النهاردة                {today_board.bookings} موعد"
            f"  ·  {today_board.guests} فرد  ·  {today_board.revenue} ج"
        )
        print(f"  المناسبات               {events}")
        print(
            f"    مؤكدة {events_board.confirmed}"
            f"  ·  مبدئية {events_board.tentative}"
            f"  ·  استعلامات {events_board.inquiries}"
            f"  ·  ضاعت {events_board.lost}"
        )
        print(f"    قيمة المؤكد           {events_board.confirmed_value} ج")
        print(f"    قيمة الاحتمالات       {events_board.pipeline_value} ج")
        print(f"    عرابين مستحقة         {events_board.deposits_due} ج")
        print(f"  الملاحظات               {notes}")
        print(
            f"    مفتوح {feedback.open}  ·  متصعّد {feedback.escalated}"
            f"  ·  متأخر رد {feedback.overdue}"
            f"  ·  متوسط الرد {feedback.average_ack_hours} ساعة"
        )
        print(f"    متوسط التقييم         ★ {feedback.average_rating}")
        print("─" * 54)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="بيانات السبا والمناسبات للعرض")
    parser.add_argument("--reset", action="store_true", help="امسح الموجود الأول")
    args = parser.parse_args()
    run(args.reset)
    sys.exit(0)
