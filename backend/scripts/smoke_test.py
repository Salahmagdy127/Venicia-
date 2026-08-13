"""اختبار سريع لمحرّكي الإتاحة والتسعير — Smoke test for availability + pricing.

بيتشغّل على قاعدة بيانات في الذاكرة، فمبيلمسش أي بيانات حقيقية:

    python -m scripts.smoke_test
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.db.base import Base, SessionLocal, engine  # noqa: E402
from app.models.enums import AdjustmentMethod, MealPlan, RateRuleType, UnitKind  # noqa: E402
from app.models.organization import Property  # noqa: E402
from app.models.rates import RatePlan, RateRule  # noqa: E402
from app.models.units import Unit, UnitCategory  # noqa: E402
from app.services import availability as av  # noqa: E402
from app.services import pricing  # noqa: E402

PASS = "  [OK]  "
FAIL = "  [FAIL]"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"{PASS} {label}" + (f"  ->  {detail}" if detail else ""))
    else:
        print(f"{FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
        failures.append(label)


def main() -> int:
    Base.metadata.create_all(engine)
    db = SessionLocal()

    # ------------------------------------------------------------ التجهيز
    prop = Property(
        code="VNC",
        name_ar="قرية فينيسيا",
        name_en="Venicia Resort",
        vat_percent=Decimal("14"),
        service_charge_percent=Decimal("12"),
        service_charge_before_tax=True,
    )
    db.add(prop)
    db.flush()

    category = UnitCategory(
        property_id=prop.id,
        code="LAKE-CH",
        name_ar="شاليه على البحيرة",
        name_en="Lake Chalet",
        kind=UnitKind.CHALET,
        base_occupancy=2,
        max_occupancy=4,
        base_rate=Decimal("2000"),
        extra_adult_rate=Decimal("400"),
        extra_child_rate=Decimal("200"),
    )
    db.add(category)
    db.flush()

    # 3 وحدات بس — عشان نقدر نوصل لحد السعة بسرعة
    for i in range(1, 4):
        db.add(
            Unit(
                property_id=prop.id,
                category_id=category.id,
                code=f"LC-{i:03d}",
                label=f"A-{i}",
            )
        )

    plan = RatePlan(
        property_id=prop.id,
        code="BAR",
        name_ar="السعر المعلن",
        name_en="Best Available Rate",
        meal_plan=MealPlan.BB,
    )
    db.add(plan)
    db.flush()

    # قاعدة ويك إند: +25%
    db.add(
        RateRule(
            property_id=prop.id,
            code="WKND25",
            name_ar="زيادة الويك إند",
            name_en="Weekend uplift",
            rule_type=RateRuleType.WEEKEND,
            method=AdjustmentMethod.PERCENT,
            value=Decimal("25"),
            priority=10,
        )
    )
    db.flush()

    # الأربعاء 2026-09-02 عشان المدى يشمل جمعة وسبت
    start = date(2026, 9, 2)
    end = start + timedelta(days=14)

    created = av.ensure_calendar(db, prop.id, start, end)
    check("إنشاء صفوف العدّاد", created == 14, f"{created} صف")

    published = pricing.publish_rates(
        db,
        property_id=prop.id,
        unit_category_id=category.id,
        rate_plan_id=plan.id,
        start=start,
        end=end,
        rate=Decimal("2000"),
        extra_adult_rate=Decimal("400"),
        extra_child_rate=Decimal("200"),
    )
    check("نشر تقويم الأسعار", published == 14, f"{published} يوم")
    db.commit()

    # ------------------------------------------------------------ الإتاحة
    arrival = date(2026, 9, 3)     # خميس
    departure = date(2026, 9, 6)   # أحد -> 3 ليالي: خميس، جمعة، سبت

    check(
        "الإتاحة المبدئية = 3 وحدات",
        av.min_available(db, prop.id, category.id, arrival, departure) == 3,
    )

    av.reserve(db, prop.id, category.id, arrival, departure)
    av.reserve(db, prop.id, category.id, arrival, departure)
    db.commit()
    remaining = av.min_available(db, prop.id, category.id, arrival, departure)
    check("بعد حجز وحدتين يفضل وحدة", remaining == 1, f"المتاح {remaining}")

    av.reserve(db, prop.id, category.id, arrival, departure)
    db.commit()
    check(
        "بعد حجز التالتة المتاح صفر",
        av.min_available(db, prop.id, category.id, arrival, departure) == 0,
    )

    # الحجز الرابع لازم يترفض — ده اللي بيمنع الحجز الزائد
    blocked = False
    blocking_dates: list[date] = []
    try:
        av.reserve(db, prop.id, category.id, arrival, departure)
    except av.AvailabilityError as exc:
        blocked = True
        blocking_dates = exc.blocking_dates
    db.rollback()
    check(
        "الحجز الرابع اترفض",
        blocked and len(blocking_dates) == 3,
        f"أيام مانعة: {len(blocking_dates)}",
    )

    # الإلغاء بيرجّع الإتاحة
    av.release(db, prop.id, category.id, arrival, departure)
    db.commit()
    check(
        "الإلغاء رجّع وحدة",
        av.min_available(db, prop.id, category.id, arrival, departure) == 1,
    )

    # حجز جزئي مايتمش: لو يوم واحد مليان، المدى كله يترفض
    mid = date(2026, 9, 10)
    av.reserve(db, prop.id, category.id, mid, mid + timedelta(days=1), quantity=3)
    db.commit()
    partial_blocked = False
    try:
        av.reserve(db, prop.id, category.id, mid - timedelta(days=2), mid + timedelta(days=2))
    except av.AvailabilityError:
        partial_blocked = True
    db.rollback()
    check("مدى فيه يوم مليان بيترفض كله", partial_blocked)
    left = av.min_available(db, prop.id, category.id, mid - timedelta(days=2), mid - timedelta(days=1))
    check("ومفيش خصم جزئي حصل", left == 3, f"المتاح قبل اليوم المليان {left}")

    # ------------------------------------------------------------ التسعير
    quote = pricing.quote_stay(
        db,
        property_id=prop.id,
        unit_category_id=category.id,
        rate_plan_id=plan.id,
        arrival=arrival,
        departure=departure,
        adults=2,
        quoted_on=date(2026, 8, 12),
    )

    check("عدد الليالي", quote.nights == 3, f"{quote.nights} ليالي")

    by_day = {n.stay_date: n for n in quote.nights_detail}
    thursday = by_day[date(2026, 9, 3)]
    friday = by_day[date(2026, 9, 4)]
    saturday = by_day[date(2026, 9, 5)]

    check("الخميس بالسعر العادي", thursday.rate == Decimal("2000.00"), f"{thursday.rate}")
    check("الجمعة +25%", friday.rate == Decimal("2500.00"), f"{friday.rate}")
    check("السبت +25%", saturday.rate == Decimal("2500.00"), f"{saturday.rate}")
    check("القاعدة اتسجلت على الليلة", friday.applied_rules == ["WKND25"])

    # 2000 + 2500 + 2500 = 7000
    check("إجمالي الإقامة", quote.room_total == Decimal("7000.00"), f"{quote.room_total}")
    # خدمة 12% = 840
    check("الخدمة 12%", quote.service_charge_total == Decimal("840.00"), f"{quote.service_charge_total}")
    # ضريبة 14% على (7000 + 840) = 1097.60
    check("الضريبة 14% بعد الخدمة", quote.tax_total == Decimal("1097.60"), f"{quote.tax_total}")
    check("الإجمالي النهائي", quote.grand_total == Decimal("8937.60"), f"{quote.grand_total}")

    # فرد إضافي
    quote3 = pricing.quote_stay(
        db,
        property_id=prop.id,
        unit_category_id=category.id,
        rate_plan_id=plan.id,
        arrival=arrival,
        departure=departure,
        adults=3,
        quoted_on=date(2026, 8, 12),
    )
    check(
        "فرد إضافي = 400 × 3 ليالي",
        quote3.extras_total == Decimal("1200.00"),
        f"{quote3.extras_total}",
    )

    db.close()

    print()
    if failures:
        print(f"فشل {len(failures)} اختبار:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("كل الاختبارات نجحت.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
