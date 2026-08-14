"""محرك الإتاحة — Availability engine.

المبدأ: الإتاحة **عدّاد بيتحدّث لحظة الحجز**، مش بحث بيتعمل وقت السؤال.

الحجز والإلغاء بيتمّوا بجملة ``UPDATE`` شرطية واحدة، وده اللي بيمنع التعارض
لما موظفين اتنين يحجزوا آخر شاليه في نفس اللحظة: الجملة الشرطية بتنجح لواحد
بس، والتاني بياخد رفض نضيف بدل ما يحصل حجز زيادة.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.models.enums import UnitCondition
from app.models.reservations import AvailabilityCalendar
from app.models.units import Unit, UnitCategory
from app.services import channel_sync


class AvailabilityError(Exception):
    """الإتاحة مش كافية أو البيع مقفول."""

    def __init__(self, message_ar: str, message_en: str, blocking_dates: list[date] | None = None):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.blocking_dates = blocking_dates or []


@dataclass(slots=True)
class DayAvailability:
    stay_date: date
    unit_category_id: int
    total_units: int
    out_of_order: int
    sold_units: int
    held_units: int
    overbooking_limit: int
    is_closed: bool

    @property
    def available(self) -> int:
        if self.is_closed:
            return 0
        return max(
            0,
            self.total_units
            - self.out_of_order
            - self.sold_units
            - self.held_units
            + self.overbooking_limit,
        )

    @property
    def occupancy_percent(self) -> float:
        sellable = self.total_units - self.out_of_order
        if sellable <= 0:
            return 0.0
        return round(self.sold_units / sellable * 100, 2)

    @property
    def oversold_by(self) -> int:
        """كام وحدة اتباعت فوق السعة الحقيقية.

        ده الرقم اللي المدير لازم يشوفه كل يوم: أكبر من صفر يعني فيه نزلاء
        هيوصلوا ومفيش لهم مكان، ولازم يتنقلوا لفئة أعلى أو لمنشأة تانية.
        """
        sellable = self.total_units - self.out_of_order
        return max(0, self.sold_units + self.held_units - sellable)


def date_range(start: date, end: date) -> list[date]:
    """ليالي الإقامة: من الوصول (شامل) للمغادرة (غير شامل).

    نزيل واصل 10 ومغادر 12 بيشغل ليلتين: 10 و 11. ليلة المغادرة مش محسوبة.
    """
    if end <= start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days)]


# ------------------------------------------------------------------ التهيئة
def ensure_calendar(
    db: Session,
    property_id: int,
    start: date,
    end: date,
    category_ids: Sequence[int] | None = None,
) -> int:
    """بينشئ صفوف العدّاد الناقصة للمدى ده، وبيملا العدد الإجمالي من جدول الوحدات.

    آمن التكرار: بيضيف الناقص بس ومبيلمسش الأرقام الموجودة.
    """
    days = date_range(start, end)
    if not days:
        return 0

    cat_stmt = select(UnitCategory.id).where(
        UnitCategory.property_id == property_id, UnitCategory.is_active.is_(True)
    )
    if category_ids:
        cat_stmt = cat_stmt.where(UnitCategory.id.in_(category_ids))
    categories = list(db.execute(cat_stmt).scalars().all())
    if not categories:
        return 0

    # عدد الوحدات الصالحة للبيع في كل فئة
    counts = dict(
        db.execute(
            select(Unit.category_id, func.count(Unit.id))
            .where(
                Unit.property_id == property_id,
                Unit.is_active.is_(True),
                Unit.category_id.in_(categories),
            )
            .group_by(Unit.category_id)
        ).all()
    )
    ooo_counts = dict(
        db.execute(
            select(Unit.category_id, func.count(Unit.id))
            .where(
                Unit.property_id == property_id,
                Unit.is_active.is_(True),
                Unit.category_id.in_(categories),
                Unit.condition.in_([UnitCondition.OUT_OF_ORDER, UnitCondition.OUT_OF_SERVICE]),
            )
            .group_by(Unit.category_id)
        ).all()
    )

    existing = {
        (row.unit_category_id, row.stay_date)
        for row in db.execute(
            select(
                AvailabilityCalendar.unit_category_id, AvailabilityCalendar.stay_date
            ).where(
                AvailabilityCalendar.property_id == property_id,
                AvailabilityCalendar.unit_category_id.in_(categories),
                AvailabilityCalendar.stay_date >= days[0],
                AvailabilityCalendar.stay_date <= days[-1],
            )
        ).all()
    }

    now = datetime.now(timezone.utc)
    new_rows = [
        AvailabilityCalendar(
            property_id=property_id,
            unit_category_id=cat_id,
            stay_date=day,
            total_units=counts.get(cat_id, 0),
            out_of_order=ooo_counts.get(cat_id, 0),
            sold_units=0,
            held_units=0,
            overbooking_limit=0,
            is_closed=False,
            updated_at=now,
        )
        for cat_id in categories
        for day in days
        if (cat_id, day) not in existing
    ]

    if new_rows:
        db.add_all(new_rows)
        db.flush()
    return len(new_rows)


def sync_totals(db: Session, property_id: int, start: date, end: date) -> int:
    """بيعيد حساب ``total_units`` و ``out_of_order`` من واقع جدول الوحدات.

    بيتنادى بعد إضافة وحدة أو تعطيلها للصيانة.
    """
    counts = dict(
        db.execute(
            select(Unit.category_id, func.count(Unit.id))
            .where(Unit.property_id == property_id, Unit.is_active.is_(True))
            .group_by(Unit.category_id)
        ).all()
    )
    ooo_counts = dict(
        db.execute(
            select(Unit.category_id, func.count(Unit.id))
            .where(
                Unit.property_id == property_id,
                Unit.is_active.is_(True),
                Unit.condition.in_([UnitCondition.OUT_OF_ORDER, UnitCondition.OUT_OF_SERVICE]),
            )
            .group_by(Unit.category_id)
        ).all()
    )

    touched = 0
    for category_id, total in counts.items():
        result = db.execute(
            update(AvailabilityCalendar)
            .where(
                AvailabilityCalendar.property_id == property_id,
                AvailabilityCalendar.unit_category_id == category_id,
                AvailabilityCalendar.stay_date >= start,
                AvailabilityCalendar.stay_date < end,
            )
            .values(
                total_units=total,
                out_of_order=ooo_counts.get(category_id, 0),
                updated_at=datetime.now(timezone.utc),
            )
        )
        touched += result.rowcount or 0
    return touched


# ------------------------------------------------------------------ القراءة
def get_availability(
    db: Session,
    property_id: int,
    start: date,
    end: date,
    category_ids: Sequence[int] | None = None,
) -> list[DayAvailability]:
    """إتاحة مدى تواريخ — قراءة واحدة بالفهرس، مفيش مسح لجدول الحجوزات."""
    stmt = select(AvailabilityCalendar).where(
        AvailabilityCalendar.property_id == property_id,
        AvailabilityCalendar.stay_date >= start,
        AvailabilityCalendar.stay_date < end,
    )
    if category_ids:
        stmt = stmt.where(AvailabilityCalendar.unit_category_id.in_(category_ids))
    stmt = stmt.order_by(
        AvailabilityCalendar.unit_category_id, AvailabilityCalendar.stay_date
    )

    return [
        DayAvailability(
            stay_date=row.stay_date,
            unit_category_id=row.unit_category_id,
            total_units=row.total_units,
            out_of_order=row.out_of_order,
            sold_units=row.sold_units,
            held_units=row.held_units,
            overbooking_limit=row.overbooking_limit,
            is_closed=row.is_closed,
        )
        for row in db.execute(stmt).scalars().all()
    ]


def min_available(
    db: Session,
    property_id: int,
    category_id: int,
    arrival: date,
    departure: date,
) -> int:
    """أقل عدد متاح خلال الإقامة — ده اللي بيحدد هل الحجز ممكن ولا لأ."""
    days = date_range(arrival, departure)
    if not days:
        return 0

    rows = get_availability(db, property_id, arrival, departure, [category_id])
    if len(rows) < len(days):
        # فيه أيام لسه متعملهاش صفوف — يعني مفيش إتاحة معرّفة
        return 0
    return min(row.available for row in rows)


def is_available(
    db: Session,
    property_id: int,
    category_id: int,
    arrival: date,
    departure: date,
    quantity: int = 1,
) -> bool:
    return min_available(db, property_id, category_id, arrival, departure) >= quantity


# ------------------------------------------------------------------ الكتابة
def _apply(
    db: Session,
    property_id: int,
    category_id: int,
    arrival: date,
    departure: date,
    quantity: int,
    column: str,
    guard: bool,
    reason: str = "تغيير إتاحة",
) -> None:
    """يزوّد أو يقلل عدّاد على مدى تواريخ في جملة واحدة.

    ``guard`` بيمنع تجاوز السعة. إن فشل يوم واحد، بنرمي استثناء والمعاملة كلها
    بترجع — يعني مفيش حجز نص نص.

    وبعد النجاح، التغيير بيدخل طابور القنوات في **نفس المعاملة**. المكان ده
    مقصود: أي مسار بيحرّك الإتاحة بيعدّي من هنا، فمستحيل حد ينسى يبلّغ
    القنوات — وده بالظبط سبب الحجز المزدوج في الأنظمة التانية.
    """
    days = date_range(arrival, departure)
    if not days or quantity == 0:
        return

    col = getattr(AvailabilityCalendar, column)
    conditions = [
        AvailabilityCalendar.property_id == property_id,
        AvailabilityCalendar.unit_category_id == category_id,
        AvailabilityCalendar.stay_date >= arrival,
        AvailabilityCalendar.stay_date < departure,
    ]

    if guard:
        # الشرط الذرّي: السعة تكفي والبيع مفتوح
        conditions.extend(
            [
                AvailabilityCalendar.is_closed.is_(False),
                (
                    AvailabilityCalendar.sold_units
                    + AvailabilityCalendar.held_units
                    + AvailabilityCalendar.out_of_order
                    + quantity
                )
                <= (
                    AvailabilityCalendar.total_units
                    + AvailabilityCalendar.overbooking_limit
                ),
            ]
        )

    result = db.execute(
        update(AvailabilityCalendar)
        .where(and_(*conditions))
        .values({column: col + quantity, "updated_at": datetime.now(timezone.utc)})
    )

    if (result.rowcount or 0) != len(days):
        blocking = _find_blocking_dates(db, property_id, category_id, arrival, departure, quantity)
        raise AvailabilityError(
            message_ar="مفيش إتاحة كافية في التواريخ دي",
            message_en="Not enough availability for the selected dates",
            blocking_dates=blocking,
        )

    channel_sync.queue_availability(db, property_id, category_id, arrival, departure, reason)


def _find_blocking_dates(
    db: Session,
    property_id: int,
    category_id: int,
    arrival: date,
    departure: date,
    quantity: int,
) -> list[date]:
    """بيحدد الأيام اللي منعت الحجز بالظبط — عشان الرسالة تكون مفيدة للموظف."""
    rows = get_availability(db, property_id, arrival, departure, [category_id])
    found = {row.stay_date for row in rows}
    blocking = [row.stay_date for row in rows if row.available < quantity]
    # أيام مالهاش صف أصلاً = مفيش إتاحة معرّفة
    blocking.extend(day for day in date_range(arrival, departure) if day not in found)
    return sorted(set(blocking))


def reserve(
    db: Session,
    property_id: int,
    category_id: int,
    arrival: date,
    departure: date,
    quantity: int = 1,
) -> None:
    """بيخصم من الإتاحة. بيرمي ``AvailabilityError`` لو مفيش مكان."""
    _apply(
        db, property_id, category_id, arrival, departure, quantity, "sold_units",
        guard=True, reason="حجز جديد",
    )


def release(
    db: Session,
    property_id: int,
    category_id: int,
    arrival: date,
    departure: date,
    quantity: int = 1,
) -> None:
    """بيرجّع الإتاحة عند الإلغاء أو المغادرة المبكرة."""
    _apply(
        db, property_id, category_id, arrival, departure, -quantity, "sold_units",
        guard=False, reason="إلغاء أو تحرير",
    )


def hold(
    db: Session,
    property_id: int,
    category_id: int,
    arrival: date,
    departure: date,
    quantity: int = 1,
) -> None:
    """حجز مؤقت أثناء الدفع في محرك الحجز الإلكتروني."""
    _apply(
        db, property_id, category_id, arrival, departure, quantity, "held_units",
        guard=True, reason="حجز مؤقت",
    )


def release_hold(
    db: Session,
    property_id: int,
    category_id: int,
    arrival: date,
    departure: date,
    quantity: int = 1,
) -> None:
    _apply(
        db, property_id, category_id, arrival, departure, -quantity, "held_units",
        guard=False, reason="فك حجز مؤقت",
    )


def _runs(days: Iterable[date]) -> list[tuple[date, date]]:
    """بيحوّل مجموعة أيام لمديات متصلة — عشان كل مدى يتعمل بجملة واحدة."""
    ordered = sorted(days)
    if not ordered:
        return []
    runs: list[tuple[date, date]] = []
    start = previous = ordered[0]
    for day in ordered[1:]:
        if (day - previous).days == 1:
            previous = day
            continue
        runs.append((start, previous + timedelta(days=1)))
        start = previous = day
    runs.append((start, previous + timedelta(days=1)))
    return runs


def move(
    db: Session,
    property_id: int,
    *,
    from_category_id: int,
    from_arrival: date,
    from_departure: date,
    to_category_id: int,
    to_arrival: date,
    to_departure: date,
    quantity: int = 1,
) -> None:
    """نقل حجز — بنحرّك **الفرق** بس، مش المدى كله.

    ده مهم في حالة شائعة جداً: نزيل عايز يقعد ليلة زيادة. الليالي اللي هو
    قاعدها بالفعل مش المفروض تتحجز تاني — لو حجزناها وفضّيناها بعدها، الليلة
    المليانة هتفشل الحجز رغم إن النزيل نفسه ساكن فيها. فبنحسب الليالي
    الجديدة بس ونحجزها، والليالي اللي سابها بترجع للسوق.

    الترتيب مقصود: الجديد الأول. لو فشل، القديم يفضل زي ما هو.
    """
    old_days = set(date_range(from_arrival, from_departure))
    new_days = set(date_range(to_arrival, to_departure))

    if from_category_id != to_category_id:
        # فئة مختلفة — مفيش ليالي مشتركة، الحركة كاملة
        added, removed = new_days, old_days
    else:
        added, removed = new_days - old_days, old_days - new_days

    for start, end in _runs(added):
        _apply(
            db, property_id, to_category_id, start, end, quantity, "sold_units",
            guard=True, reason="تعديل حجز",
        )
    for start, end in _runs(removed):
        _apply(
            db, property_id, from_category_id, start, end, -quantity, "sold_units",
            guard=False, reason="تعديل حجز",
        )


def set_overbooking(
    db: Session,
    property_id: int,
    start: date,
    end: date,
    limit: int,
    category_ids: Iterable[int] | None = None,
) -> int:
    """تحديد حد التجاوز المسموح — Overbooking control.

    الحد ده بيتضاف للسعة في الحارس الذرّي، يعني بيسمح ببيع وحدات فوق
    الموجود فعلاً — وده مقصود: نسبة ثابتة من الحجوزات بتتلغي أو مبتحضرش،
    فالبيع بالسعة الحقيقية بالظبط معناه غرف فاضية كل ليلة.
    """
    conditions = [
        AvailabilityCalendar.property_id == property_id,
        AvailabilityCalendar.stay_date >= start,
        AvailabilityCalendar.stay_date < end,
    ]
    if category_ids:
        conditions.append(AvailabilityCalendar.unit_category_id.in_(list(category_ids)))

    result = db.execute(
        update(AvailabilityCalendar)
        .where(and_(*conditions))
        .values(overbooking_limit=limit, updated_at=datetime.now(timezone.utc))
    )

    # الحد بيغيّر الرقم اللي القنوات شايفاه، فلازم يوصلهم
    for category_id in _affected_categories(db, property_id, category_ids):
        channel_sync.queue_availability(
            db, property_id, category_id, start, end, f"حد تجاوز {limit}"
        )
    return result.rowcount or 0


def _affected_categories(
    db: Session, property_id: int, category_ids: Iterable[int] | None
) -> list[int]:
    if category_ids:
        return list(category_ids)
    return list(
        db.execute(
            select(UnitCategory.id).where(
                UnitCategory.property_id == property_id, UnitCategory.is_active.is_(True)
            )
        ).scalars().all()
    )


def set_closed(
    db: Session,
    property_id: int,
    start: date,
    end: date,
    closed: bool,
    category_ids: Iterable[int] | None = None,
) -> int:
    """إغلاق أو فتح البيع لمدى تواريخ."""
    conditions = [
        AvailabilityCalendar.property_id == property_id,
        AvailabilityCalendar.stay_date >= start,
        AvailabilityCalendar.stay_date < end,
    ]
    if category_ids:
        conditions.append(AvailabilityCalendar.unit_category_id.in_(list(category_ids)))

    result = db.execute(
        update(AvailabilityCalendar)
        .where(and_(*conditions))
        .values(is_closed=closed, updated_at=datetime.now(timezone.utc))
    )

    # قفل البيع لازم يوصل القنوات فوراً — ده أخطر تغيير ممكن يتأخر
    channel_sync.queue_stop_sell(
        db,
        property_id,
        _affected_categories(db, property_id, category_ids),
        start,
        end,
        "قفل البيع" if closed else "فتح البيع",
    )
    return result.rowcount or 0
