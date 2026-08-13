"""محرك التسعير — Seasonal and dynamic rate engine.

بيحسب سعر كل ليلة على حدة: السعر المنشور من التقويم، وفوقه قواعد التسعير
الديناميكي (ويك إند / أعياد / إشغال / طول الإقامة)، وبعدين الأفراد الإضافيين،
وأخيراً الخدمة والضريبة.

الخدمة والضريبة بتتحسبوا **مرة واحدة على الإجمالي** مش على كل ليلة، عشان
التقريب ميعملش فروق قروش تظهر في المطابقة.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AdjustmentMethod, RateRuleType
from app.models.organization import Property
from app.models.rates import RateCalendarEntry, RateRule
from app.models.reservations import AvailabilityCalendar
from app.models.units import UnitCategory
from app.services.availability import date_range

TWO_DP = Decimal("0.01")
HUNDRED = Decimal("100")


def money(value: Decimal | int | float) -> Decimal:
    """تقريب نقدي موحّد — نصف لأعلى، خانتين عشريتين."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWO_DP, rounding=ROUND_HALF_UP)


class PricingError(Exception):
    def __init__(self, message_ar: str, message_en: str):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en


@dataclass(slots=True)
class NightQuote:
    stay_date: date
    published_rate: Decimal
    rate: Decimal
    extra_person_amount: Decimal
    discount_amount: Decimal
    #: القواعد اللي اتطبقت — للشفافية قدام الموظف والنزيل
    applied_rules: list[str] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return money(self.rate + self.extra_person_amount - self.discount_amount)


@dataclass(slots=True)
class StayQuote:
    unit_category_id: int
    rate_plan_id: int
    arrival: date
    departure: date
    nights_detail: list[NightQuote]

    room_total: Decimal
    extras_total: Decimal
    discount_total: Decimal
    service_charge_total: Decimal
    tax_total: Decimal
    grand_total: Decimal

    @property
    def nights(self) -> int:
        return len(self.nights_detail)

    @property
    def average_nightly_rate(self) -> Decimal:
        if not self.nights_detail:
            return Decimal("0")
        return money(self.room_total / self.nights)


# ------------------------------------------------------------------ القواعد
def _weekday_matches(rule: RateRule, day: date) -> bool:
    """أيام الأسبوع في القاعدة مخزّنة كنص أرقام، الاتنين = 0."""
    if not rule.weekdays:
        return True
    return str(day.weekday()) in rule.weekdays


def _rule_applies(
    rule: RateRule,
    day: date,
    *,
    nights: int,
    occupancy_percent: Decimal,
    lead_days: int,
) -> bool:
    if rule.valid_from and day < rule.valid_from:
        return False
    if rule.valid_to and day > rule.valid_to:
        return False
    if not _weekday_matches(rule, day):
        return False

    if rule.rule_type == RateRuleType.WEEKEND:
        # الويك إند في مصر: الجمعة (4) والسبت (5)
        return day.weekday() in (4, 5)
    if rule.rule_type == RateRuleType.MIDWEEK:
        return day.weekday() in (6, 0, 1, 2, 3)

    measured: Decimal | None = None
    if rule.rule_type == RateRuleType.OCCUPANCY:
        measured = occupancy_percent
    elif rule.rule_type == RateRuleType.LENGTH_OF_STAY:
        measured = Decimal(nights)
    elif rule.rule_type == RateRuleType.LEAD_TIME:
        measured = Decimal(lead_days)

    if measured is not None:
        if rule.threshold_min is not None and measured < rule.threshold_min:
            return False
        if rule.threshold_max is not None and measured > rule.threshold_max:
            return False
        return True

    # HOLIDAY وغيرها: بتعتمد على المدى الزمني وأيام الأسبوع اللي اتفحصوا فوق
    return True


def _apply_adjustment(base: Decimal, method: AdjustmentMethod, value: Decimal) -> Decimal:
    if method == AdjustmentMethod.PERCENT:
        return money(base + (base * value / HUNDRED))
    if method == AdjustmentMethod.AMOUNT:
        return money(base + value)
    return money(value)  # OVERRIDE


def _load_rules(db: Session, property_id: int) -> list[RateRule]:
    return list(
        db.execute(
            select(RateRule)
            .where(RateRule.property_id == property_id, RateRule.is_active.is_(True))
            .order_by(RateRule.priority)
        )
        .scalars()
        .all()
    )


def _occupancy_by_date(
    db: Session, property_id: int, arrival: date, departure: date
) -> dict[date, Decimal]:
    """نسبة الإشغال الحالية لكل يوم — مدخل قاعدة التسعير حسب الإشغال."""
    rows = db.execute(
        select(AvailabilityCalendar).where(
            AvailabilityCalendar.property_id == property_id,
            AvailabilityCalendar.stay_date >= arrival,
            AvailabilityCalendar.stay_date < departure,
        )
    ).scalars().all()

    totals: dict[date, list[int]] = {}
    for row in rows:
        sellable = row.total_units - row.out_of_order
        bucket = totals.setdefault(row.stay_date, [0, 0])
        bucket[0] += row.sold_units
        bucket[1] += max(0, sellable)

    return {
        day: (money(Decimal(sold) / Decimal(cap) * HUNDRED) if cap else Decimal("0"))
        for day, (sold, cap) in totals.items()
    }


# ------------------------------------------------------------------ التسعير
def quote_stay(
    db: Session,
    *,
    property_id: int,
    unit_category_id: int,
    rate_plan_id: int,
    arrival: date,
    departure: date,
    adults: int = 2,
    children: int = 0,
    quoted_on: date | None = None,
    discount_percent: Decimal | None = None,
) -> StayQuote:
    """تسعيرة إقامة كاملة، ليلة بليلة."""
    days = date_range(arrival, departure)
    if not days:
        raise PricingError(
            message_ar="تاريخ المغادرة لازم يكون بعد تاريخ الوصول",
            message_en="Departure must be after arrival",
        )

    prop = db.get(Property, property_id)
    if prop is None:
        raise PricingError(message_ar="المنشأة غير موجودة", message_en="Property not found")

    category = db.get(UnitCategory, unit_category_id)
    if category is None:
        raise PricingError(message_ar="فئة الوحدة غير موجودة", message_en="Unit category not found")

    # الأسعار المنشورة للمدى كله في استعلام واحد
    published = {
        row.stay_date: row
        for row in db.execute(
            select(RateCalendarEntry).where(
                RateCalendarEntry.property_id == property_id,
                RateCalendarEntry.unit_category_id == unit_category_id,
                RateCalendarEntry.rate_plan_id == rate_plan_id,
                RateCalendarEntry.stay_date >= arrival,
                RateCalendarEntry.stay_date < departure,
            )
        ).scalars().all()
    }

    rules = _load_rules(db, property_id)
    occupancy = _occupancy_by_date(db, property_id, arrival, departure)
    nights = len(days)
    reference_day = quoted_on or date.today()

    extra_adults = max(0, adults - category.base_occupancy)
    nights_detail: list[NightQuote] = []

    for day in days:
        entry = published.get(day)

        if entry is not None and entry.is_closed:
            raise PricingError(
                message_ar=f"البيع مقفول في يوم {day.isoformat()}",
                message_en=f"Sales are closed on {day.isoformat()}",
            )

        base = entry.rate if entry is not None else category.base_rate
        if base <= 0:
            raise PricingError(
                message_ar=f"مفيش سعر معرّف ليوم {day.isoformat()}",
                message_en=f"No rate defined for {day.isoformat()}",
            )

        published_rate = money(base)
        rate = published_rate
        applied: list[str] = []

        lead_days = (day - reference_day).days
        for rule in rules:
            if rule.unit_category_id and rule.unit_category_id != unit_category_id:
                continue
            if rule.rate_plan_id and rule.rate_plan_id != rate_plan_id:
                continue
            if not _rule_applies(
                rule,
                day,
                nights=nights,
                occupancy_percent=occupancy.get(day, Decimal("0")),
                lead_days=lead_days,
            ):
                continue
            rate = _apply_adjustment(rate, rule.method, rule.value)
            applied.append(rule.code)

        extra_adult_rate = (
            entry.extra_adult_rate if entry is not None else category.extra_adult_rate
        )
        extra_child_rate = (
            entry.extra_child_rate if entry is not None else category.extra_child_rate
        )
        extra_amount = money(
            extra_adults * extra_adult_rate + children * extra_child_rate
        )

        discount = Decimal("0")
        if discount_percent:
            discount = money((rate + extra_amount) * discount_percent / HUNDRED)

        nights_detail.append(
            NightQuote(
                stay_date=day,
                published_rate=published_rate,
                rate=rate,
                extra_person_amount=extra_amount,
                discount_amount=discount,
                applied_rules=applied,
            )
        )

    room_total = money(sum((n.rate for n in nights_detail), Decimal("0")))
    extras_total = money(sum((n.extra_person_amount for n in nights_detail), Decimal("0")))
    discount_total = money(sum((n.discount_amount for n in nights_detail), Decimal("0")))

    net = money(room_total + extras_total - discount_total)

    service_charge = money(net * prop.service_charge_percent / HUNDRED)
    taxable = net + service_charge if prop.service_charge_before_tax else net
    tax = money(taxable * prop.vat_percent / HUNDRED)

    return StayQuote(
        unit_category_id=unit_category_id,
        rate_plan_id=rate_plan_id,
        arrival=arrival,
        departure=departure,
        nights_detail=nights_detail,
        room_total=room_total,
        extras_total=extras_total,
        discount_total=discount_total,
        service_charge_total=service_charge,
        tax_total=tax,
        grand_total=money(net + service_charge + tax),
    )


# ------------------------------------------------------- نشر تقويم الأسعار
def publish_rates(
    db: Session,
    *,
    property_id: int,
    unit_category_id: int,
    rate_plan_id: int,
    start: date,
    end: date,
    rate: Decimal,
    extra_adult_rate: Decimal | None = None,
    extra_child_rate: Decimal | None = None,
    min_stay: int = 1,
    weekdays: Sequence[int] | None = None,
) -> int:
    """نشر سعر على مدى تواريخ — بيحدّث الموجود وينشئ الناقص."""
    days = date_range(start, end)
    if not days:
        return 0
    if weekdays is not None:
        days = [d for d in days if d.weekday() in weekdays]

    existing = {
        row.stay_date: row
        for row in db.execute(
            select(RateCalendarEntry).where(
                RateCalendarEntry.unit_category_id == unit_category_id,
                RateCalendarEntry.rate_plan_id == rate_plan_id,
                RateCalendarEntry.stay_date >= start,
                RateCalendarEntry.stay_date < end,
            )
        ).scalars().all()
    }

    new_rows = []
    for day in days:
        row = existing.get(day)
        if row is not None:
            row.rate = rate
            if extra_adult_rate is not None:
                row.extra_adult_rate = extra_adult_rate
            if extra_child_rate is not None:
                row.extra_child_rate = extra_child_rate
            row.min_stay = min_stay
        else:
            new_rows.append(
                RateCalendarEntry(
                    property_id=property_id,
                    unit_category_id=unit_category_id,
                    rate_plan_id=rate_plan_id,
                    stay_date=day,
                    rate=rate,
                    extra_adult_rate=extra_adult_rate or Decimal("0"),
                    extra_child_rate=extra_child_rate or Decimal("0"),
                    min_stay=min_stay,
                )
            )

    if new_rows:
        db.add_all(new_rows)
    db.flush()
    return len(days)
