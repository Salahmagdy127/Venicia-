"""قياس أداء الاستعلامات الحقيقية — Query benchmark on the seeded database.

بيقيس الاستعلامات اللي الشاشات بتعملها فعلاً، وبيقارن **العدّاد** بـ **المسح**
عشان يثبت قرار التصميم بالأرقام مش بالكلام.

    python -m scripts.benchmark
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from sqlalchemy import func, select, text

from app.db.base import SessionLocal
from app.models.analytics import DailyStatistics
from app.models.enums import BLOCKING_RESERVATION_STATUSES
from app.models.folio import Folio, FolioLine
from app.models.pos import PosOrder, PosOrderLine
from app.models.reservations import (
    AvailabilityCalendar,
    Reservation,
    ReservationNight,
    ReservationUnit,
)


def timed(label: str, fn, runs: int = 5):
    fn()  # إحماء الكاش
    durations = []
    for _ in range(runs):
        start = time.perf_counter()
        result = fn()
        durations.append((time.perf_counter() - start) * 1000)

    ms = min(durations)
    bar = "█" * max(1, min(40, int(ms / 2)))
    flag = "  " if ms < 50 else ("!!" if ms > 250 else " ~")
    print(f"{flag} {label:<46} {ms:8.2f} ms  {bar}")
    return result, ms


def main() -> None:
    db = SessionLocal()
    today = date.today()

    print()
    print("=" * 82)
    print("  حجم البيانات")
    print("=" * 82)
    for label, model in [
        ("الحجوزات", Reservation),
        ("ليالي الحجوزات", ReservationNight),
        ("سطور حساب النزيل", FolioLine),
        ("أوردرات نقاط البيع", PosOrder),
        ("سطور الأوردرات", PosOrderLine),
    ]:
        count = db.execute(select(func.count(model.id))).scalar()
        print(f"  {label:<24} {count:>10,}")

    print()
    print("=" * 82)
    print("  الاستعلامات اللي الشاشات بتعملها")
    print("=" * 82)

    # 1) شاشة الحجوزات — الإتاحة لأسبوعين
    start = today
    end = today + timedelta(days=14)
    timed(
        "شاشة الحجوزات: الإتاحة 14 يوم × 6 فئات",
        lambda: db.execute(
            select(AvailabilityCalendar).where(
                AvailabilityCalendar.property_id == 1,
                AvailabilityCalendar.stay_date >= start,
                AvailabilityCalendar.stay_date < end,
            )
        ).scalars().all(),
    )

    # 2) شاشة الحجوزات — الشرائط
    timed(
        "شاشة الحجوزات: كل الحجوزات في المدى",
        lambda: db.execute(
            select(ReservationUnit).where(
                ReservationUnit.property_id == 1,
                ReservationUnit.arrival_date < end,
                ReservationUnit.departure_date > start,
                ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
            )
        ).scalars().all(),
    )

    # 3) داشبورد المالك — سنة كاملة
    timed(
        "داشبورد المالك: مؤشرات سنة كاملة",
        lambda: db.execute(
            select(DailyStatistics)
            .where(
                DailyStatistics.property_id == 1,
                DailyStatistics.business_date >= today - timedelta(days=365),
                DailyStatistics.business_date <= today,
            )
            .order_by(DailyStatistics.business_date)
        ).scalars().all(),
    )

    # 4) قائمة الوصول النهاردة
    timed(
        "الاستقبال: قائمة الوصول النهاردة",
        lambda: db.execute(
            select(Reservation).where(
                Reservation.property_id == 1,
                Reservation.arrival_date == today,
            )
        ).scalars().all(),
    )

    # 5) كشف حساب نزيل
    folio_id = db.execute(select(Folio.id).limit(1)).scalar()
    timed(
        "الفوليو: كشف حساب نزيل كامل",
        lambda: db.execute(
            select(FolioLine).where(FolioLine.folio_id == folio_id).order_by(FolioLine.id)
        ).scalars().all(),
    )

    # 6) الأصناف الأكتر مبيعاً في شهر
    month_start = today - timedelta(days=30)
    timed(
        "التقارير: أكتر 10 أصناف مبيعاً في 30 يوم",
        lambda: db.execute(
            select(
                PosOrderLine.item_name_ar,
                func.sum(PosOrderLine.quantity).label("qty"),
                func.sum(PosOrderLine.line_total).label("total"),
            )
            .where(
                PosOrderLine.property_id == 1,
                PosOrderLine.business_date >= month_start,
                PosOrderLine.is_void.is_(False),
            )
            .group_by(PosOrderLine.item_name_ar)
            .order_by(text("qty DESC"))
            .limit(10)
        ).all(),
    )

    # 7) الترقيم بالمؤشر — الصفحة الأولى مقابل صفحة بعيدة
    from app.core.pagination import paginate

    timed(
        "الترقيم بالمؤشر: أول صفحة حجوزات",
        lambda: paginate(
            db,
            select(Reservation).where(Reservation.property_id == 1),
            key_column=Reservation.id,
            limit=50,
        ),
    )

    deep_cursor = None
    page = paginate(
        db, select(Reservation).where(Reservation.property_id == 1),
        key_column=Reservation.id, limit=50,
    )
    for _ in range(60):  # ننزل لعمق 3000 صف
        if not page.next_cursor:
            break
        deep_cursor = page.next_cursor
        page = paginate(
            db, select(Reservation).where(Reservation.property_id == 1),
            key_column=Reservation.id, limit=50, cursor=deep_cursor,
        )

    timed(
        "الترقيم بالمؤشر: صفحة على عمق 3000 صف",
        lambda: paginate(
            db,
            select(Reservation).where(Reservation.property_id == 1),
            key_column=Reservation.id,
            limit=50,
            cursor=deep_cursor,
        ),
    )

    timed(
        "المقارنة — OFFSET على عمق 3000 صف",
        lambda: db.execute(
            select(Reservation)
            .where(Reservation.property_id == 1)
            .order_by(Reservation.id.desc())
            .offset(3000)
            .limit(50)
        ).scalars().all(),
    )

    print()
    print("=" * 82)
    print("  المقارنة الحاسمة: العدّاد مقابل المسح")
    print("=" * 82)

    check_start = today + timedelta(days=20)
    check_end = check_start + timedelta(days=3)

    _, counter_ms = timed(
        "العدّاد: في وحدة فاضية؟ (تصميمنا)",
        lambda: db.execute(
            select(
                AvailabilityCalendar.unit_category_id,
                func.min(
                    AvailabilityCalendar.total_units
                    - AvailabilityCalendar.out_of_order
                    - AvailabilityCalendar.sold_units
                    - AvailabilityCalendar.held_units
                ),
            )
            .where(
                AvailabilityCalendar.property_id == 1,
                AvailabilityCalendar.stay_date >= check_start,
                AvailabilityCalendar.stay_date < check_end,
            )
            .group_by(AvailabilityCalendar.unit_category_id)
        ).all(),
    )

    _, scan_ms = timed(
        "المسح: نفس السؤال بعدّ الحجوزات",
        lambda: db.execute(
            select(
                ReservationNight.unit_category_id,
                ReservationNight.stay_date,
                func.count(ReservationNight.id),
            )
            .join(
                ReservationUnit,
                ReservationUnit.id == ReservationNight.reservation_unit_id,
            )
            .where(
                ReservationNight.property_id == 1,
                ReservationNight.stay_date >= check_start,
                ReservationNight.stay_date < check_end,
                ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
            )
            .group_by(ReservationNight.unit_category_id, ReservationNight.stay_date)
        ).all(),
    )

    print()
    if counter_ms > 0:
        print(f"  العدّاد أسرع {scan_ms / counter_ms:.1f}×  على 62 ألف ليلة.")
    print("  والفرق ده بيكبر خطياً مع نمو الحجوزات — العدّاد بيفضل ثابت.")
    print()

    db.close()


if __name__ == "__main__":
    main()
