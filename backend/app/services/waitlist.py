"""قائمة الانتظار — Waitlist.

الفكرة التشغيلية: القرية بتترفض فيها طلبات كتير في الويك إند والمواسم، والطلب
المرفوض بيضيع. هنا بنحتفظ بالطلب بتواريخه، وأول ما حجز يتلغي أو يتقفل مبكر
بيبان فوراً مين الطلبات اللي التواريخ بقت مناسبة ليها.

ثلاث قواعد بتفرق:

1. **الطلب مش حجز.** مبياخدش كود ولا بيخصم إتاحة — عشان قايمة الانتظار
   متبوّظش أرقام الإشغال والإيراد المتوقّع.
2. **العرض بيحجز مؤقتاً.** لما الموظف يكلّم النزيل، بنشيل الوحدة من السوق
   في ``held_units`` لمدة محدودة. من غير كده الوحدة تتباع وهو بيرد.
3. **المهلة بتفك نفسها.** أي عرض عدّت مهلته بيرجع الطلب لـ WAITING
   والوحدة ترجع للبيع أوتوماتيك — مفيش وحدة بتفضل محجوزة منسية.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    BookingSource,
    ReservationStatus,
    WaitlistPriority,
    WaitlistStatus,
)
from app.models.guests import Guest
from app.models.rates import RatePlan
from app.models.reservations import Reservation, WaitlistEntry
from app.models.units import UnitCategory
from app.services import availability as av
from app.services import pricing
from app.services import reservations as res_svc

#: مهلة العرض الافتراضية — ساعات
DEFAULT_OFFER_HOURS = 24
#: أقصى مهلة مسموح بيها — بعد كده الوحدة بتبقى محبوسة أكتر من اللازم
MAX_OFFER_HOURS = 72
#: أقصى مرونة في التواريخ — أسبوع قدام أو ورا
MAX_FLEXIBLE_DAYS = 7

#: ترتيب الأولوية في العرض — الأعلى الأول
PRIORITY_RANK: dict[WaitlistPriority, int] = {
    WaitlistPriority.VIP: 0,
    WaitlistPriority.HIGH: 1,
    WaitlistPriority.NORMAL: 2,
}

#: الطلبات اللي لسه حيّة
OPEN_STATUSES: frozenset[WaitlistStatus] = frozenset(
    {WaitlistStatus.WAITING, WaitlistStatus.OFFERED}
)


class WaitlistError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "waitlist_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Match:
    """نافذة تواريخ لقيناها فاضية لطلب في الانتظار."""

    arrival: date
    departure: date
    #: بكام يوم زحلقنا التواريخ عن اللي النزيل طلبه — صفر يعني بالظبط
    shift_days: int

    @property
    def is_exact(self) -> bool:
        return self.shift_days == 0


# ═══════════════════════════════════════════════════════════ البحث عن مكان
def find_match(db: Session, entry: WaitlistEntry) -> Match | None:
    """أقرب نافذة فاضية للطلب ده — التواريخ الأصلية الأول، وبعدين الأقرب فالأقرب.

    المرونة بتتجرّب في الاتجاهين: نزيل قابل يقدّم أو يأخّر يومين بيتجرّبله
    ‎-1 و ‎+1 و ‎-2 و ‎+2 بالترتيب ده، فبنديله أقرب حاجة لطلبه الأصلي.
    """
    flex = max(0, min(entry.flexible_days, MAX_FLEXIBLE_DAYS))
    # صفر الأول، وبعدين ±1، ±2 … — الأقرب لطلبه الأصلي بيكسب
    shifts = [0]
    for step in range(1, flex + 1):
        shifts.extend([-step, step])

    today = date.today()
    for shift in shifts:
        arrival = entry.arrival_date + timedelta(days=shift)
        departure = entry.departure_date + timedelta(days=shift)
        if arrival < today:
            continue  # مش هنعرض عليه تواريخ عدّت
        if av.min_available(db, entry.property_id, entry.unit_category_id, arrival, departure) >= 1:
            return Match(arrival=arrival, departure=departure, shift_days=shift)
    return None


def match_all(db: Session, property_id: int, entries: list[WaitlistEntry]) -> dict[int, Match | None]:
    """نفس ``find_match`` لكن لقائمة كاملة بقراءة إتاحة واحدة.

    شاشة الانتظار بتعرض عشرين طلب، وكل طلب بمرونة 3 أيام بيحتاج 7 محاولات.
    القراءة الواحدة بتوفّر مية وأربعين استعلام على كل فتحة للشاشة.
    """
    if not entries:
        return {}

    flexes = {e.id: max(0, min(e.flexible_days, MAX_FLEXIBLE_DAYS)) for e in entries}
    span_start = min(e.arrival_date - timedelta(days=flexes[e.id]) for e in entries)
    span_end = max(e.departure_date + timedelta(days=flexes[e.id]) for e in entries)
    categories = {e.unit_category_id for e in entries}

    rows = av.get_availability(db, property_id, span_start, span_end, list(categories))
    free = {(row.unit_category_id, row.stay_date): row.available for row in rows}

    today = date.today()
    results: dict[int, Match | None] = {}

    for entry in entries:
        flex = flexes[entry.id]
        shifts = [0]
        for step in range(1, flex + 1):
            shifts.extend([-step, step])

        found: Match | None = None
        for shift in shifts:
            arrival = entry.arrival_date + timedelta(days=shift)
            departure = entry.departure_date + timedelta(days=shift)
            if arrival < today:
                continue
            nights = av.date_range(arrival, departure)
            # يوم ناقص من الجدول = مفيش إتاحة معرّفة، فالنافذة دي مرفوضة
            if all(free.get((entry.unit_category_id, day), 0) >= 1 for day in nights):
                found = Match(arrival=arrival, departure=departure, shift_days=shift)
                break
        results[entry.id] = found

    return results


def sort_key(entry: WaitlistEntry) -> tuple[int, date, int]:
    """ترتيب الدور: الأولوية الأعلى، وبعدين الأقرب وصولاً، وبعدين الأقدم تسجيلاً."""
    return (
        PRIORITY_RANK.get(entry.priority, 9),
        entry.arrival_date,
        entry.id or 0,
    )


# ═══════════════════════════════════════════════════════════ التسجيل
def add(
    db: Session,
    *,
    property_id: int,
    guest_id: int,
    unit_category_id: int,
    arrival: date,
    departure: date,
    adults: int = 2,
    children: int = 0,
    rate_plan_id: int | None = None,
    flexible_days: int = 0,
    priority: WaitlistPriority = WaitlistPriority.NORMAL,
    source: BookingSource = BookingSource.DIRECT,
    contact_note: str | None = None,
    created_by_user_id: int | None = None,
) -> WaitlistEntry:
    """تسجيل طلب في الانتظار — بيسعّره تقريبياً عشان الموظف يعرف يقول إيه."""
    if departure <= arrival:
        raise WaitlistError(
            "تاريخ المغادرة لازم يكون بعد الوصول",
            "Departure must be after arrival",
            "invalid_dates",
        )
    if arrival < date.today():
        raise WaitlistError(
            "مينفعش تسجّل انتظار على تواريخ عدّت",
            "Cannot waitlist dates in the past",
            "past_dates",
        )
    if not 0 <= flexible_days <= MAX_FLEXIBLE_DAYS:
        raise WaitlistError(
            f"المرونة لازم تكون بين صفر و{MAX_FLEXIBLE_DAYS} أيام",
            f"Flexibility must be between 0 and {MAX_FLEXIBLE_DAYS} days",
            "invalid_flexibility",
        )

    guest = db.get(Guest, guest_id)
    category = db.get(UnitCategory, unit_category_id)
    if guest is None or category is None:
        raise WaitlistError("بيانات ناقصة أو غير صحيحة", "Invalid references", "not_found")
    if guest.is_blacklisted:
        raise WaitlistError("النزيل ده على القايمة السودة", "Guest is blacklisted", "blacklisted")
    if adults + children > category.max_occupancy:
        raise WaitlistError(
            f"الفئة دي بتستوعب {category.max_occupancy} أفراد كحد أقصى",
            f"Category holds a maximum of {category.max_occupancy} guests",
            "over_capacity",
        )

    # نفس النزيل بنفس التواريخ ونفس الفئة — طلب واحد يكفي
    duplicate = db.execute(
        select(WaitlistEntry).where(
            WaitlistEntry.property_id == property_id,
            WaitlistEntry.guest_id == guest_id,
            WaitlistEntry.unit_category_id == unit_category_id,
            WaitlistEntry.arrival_date == arrival,
            WaitlistEntry.departure_date == departure,
            WaitlistEntry.status.in_(list(OPEN_STATUSES)),
        ).limit(1)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise WaitlistError(
            "النزيل ده مسجّل بالفعل في الانتظار على نفس التواريخ",
            "This guest is already waitlisted for the same dates",
            "duplicate",
        )

    plan_id = rate_plan_id
    if plan_id is None:
        plan_id = db.execute(
            select(RatePlan.id)
            .where(RatePlan.property_id == property_id, RatePlan.is_active.is_(True))
            .order_by(RatePlan.sort_order)
            .limit(1)
        ).scalar_one_or_none()

    # تسعيرة تقريبية — لو التسعير فشل (مفيش سعر معرّف) بنسجّل بصفر بدل ما نرفض الطلب
    quoted = Decimal("0")
    if plan_id is not None:
        try:
            quote = pricing.quote_stay(
                db,
                property_id=property_id,
                unit_category_id=unit_category_id,
                rate_plan_id=plan_id,
                arrival=arrival,
                departure=departure,
                adults=adults,
                children=children,
            )
            quoted = quote.grand_total
        except pricing.PricingError:
            quoted = Decimal("0")

    entry = WaitlistEntry(
        property_id=property_id,
        guest_id=guest_id,
        unit_category_id=unit_category_id,
        rate_plan_id=plan_id,
        arrival_date=arrival,
        departure_date=departure,
        nights=(departure - arrival).days,
        adults=adults,
        children=children,
        flexible_days=flexible_days,
        status=WaitlistStatus.WAITING,
        priority=priority,
        source=source,
        quoted_total=quoted,
        contact_note=contact_note,
        created_by_user_id=created_by_user_id,
    )
    db.add(entry)
    db.flush()
    return entry


# ═══════════════════════════════════════════════════════════ العرض
def offer(
    db: Session,
    entry_id: int,
    *,
    hours: int = DEFAULT_OFFER_HOURS,
    user_id: int | None = None,
) -> WaitlistEntry:
    """عرض المكان على صاحب الطلب وحجزه مؤقتاً لحد ما يرد.

    الحجز المؤقت بيمشي على ``held_units`` بنفس الحارس الذرّي بتاع الحجز
    العادي — يعني مينفعش نعرض مكان مش موجود.
    """
    entry = _get_open(db, entry_id)
    if entry.status == WaitlistStatus.OFFERED:
        raise WaitlistError(
            "الطلب معروض بالفعل ولسه في المهلة",
            "This entry already has an active offer",
            "already_offered",
        )
    if not 1 <= hours <= MAX_OFFER_HOURS:
        raise WaitlistError(
            f"المهلة لازم تكون بين ساعة و{MAX_OFFER_HOURS} ساعة",
            f"Offer window must be between 1 and {MAX_OFFER_HOURS} hours",
            "invalid_window",
        )

    match = find_match(db, entry)
    if match is None:
        raise WaitlistError(
            "لسه مفيش مكان فاضي في التواريخ دي",
            "No availability for these dates yet",
            "no_availability",
        )

    av.ensure_calendar(db, entry.property_id, match.arrival, match.departure, [entry.unit_category_id])
    av.hold(db, entry.property_id, entry.unit_category_id, match.arrival, match.departure)

    now = utcnow()
    entry.status = WaitlistStatus.OFFERED
    entry.offered_at = now
    entry.offer_expires_at = now + timedelta(hours=hours)
    entry.offered_by_user_id = user_id
    entry.offered_arrival = match.arrival
    entry.offered_departure = match.departure
    db.flush()
    return entry


def withdraw_offer(db: Session, entry_id: int, *, reason: str | None = None) -> WaitlistEntry:
    """سحب العرض ورجوع الوحدة للبيع — الطلب بيفضل في الانتظار."""
    entry = db.get(WaitlistEntry, entry_id)
    if entry is None:
        raise WaitlistError("الطلب غير موجود", "Waitlist entry not found", "not_found")
    if entry.status != WaitlistStatus.OFFERED:
        raise WaitlistError(
            "مفيش عرض قايم على الطلب ده",
            "This entry has no active offer",
            "not_offered",
        )
    _release_hold(db, entry)
    entry.status = WaitlistStatus.WAITING
    entry.offered_at = None
    entry.offer_expires_at = None
    entry.offered_by_user_id = None
    entry.offered_arrival = None
    entry.offered_departure = None
    if reason:
        entry.contact_note = reason
    db.flush()
    return entry


def _release_hold(db: Session, entry: WaitlistEntry) -> None:
    """بيفك الحجز المؤقت لو موجود. آمن التكرار."""
    if entry.offered_arrival and entry.offered_departure:
        av.release_hold(
            db,
            entry.property_id,
            entry.unit_category_id,
            entry.offered_arrival,
            entry.offered_departure,
        )


# ═══════════════════════════════════════════════════════════ التحويل لحجز
def convert(
    db: Session,
    entry_id: int,
    *,
    rate_plan_id: int | None = None,
    deposit_paid: Decimal | None = None,
    unit_id: int | None = None,
    user_id: int | None = None,
) -> tuple[WaitlistEntry, Reservation]:
    """تحويل طلب انتظار لحجز فعلي.

    بنفك الحجز المؤقت الأول وبعدين نحجز — لأن الحجز المؤقت بتاعنا نفسه
    بيتحسب على السعة، فلو مافكّيناهوش هيمنع الحجز اللي احنا عايزينه.
    كله في معاملة واحدة، فلو الحجز فشل الحجز المؤقت بيرجع زي ما كان.
    """
    entry = _get_open(db, entry_id)

    arrival = entry.offered_arrival or entry.arrival_date
    departure = entry.offered_departure or entry.departure_date

    if entry.status == WaitlistStatus.OFFERED:
        _release_hold(db, entry)
    else:
        # طلب مااتعرضش عليه — لازم نتأكد إن فيه مكان فعلاً
        match = find_match(db, entry)
        if match is None:
            raise WaitlistError(
                "لسه مفيش مكان فاضي في التواريخ دي",
                "No availability for these dates yet",
                "no_availability",
            )
        arrival, departure = match.arrival, match.departure

    plan_id = rate_plan_id or entry.rate_plan_id
    if plan_id is None:
        raise WaitlistError("مفيش خطة أسعار محددة", "No rate plan selected", "no_rate_plan")

    reservation = res_svc.create_reservation(
        db,
        property_id=entry.property_id,
        guest_id=entry.guest_id,
        unit_category_id=entry.unit_category_id,
        rate_plan_id=plan_id,
        arrival=arrival,
        departure=departure,
        adults=entry.adults,
        children=entry.children,
        source=entry.source,
        unit_id=unit_id,
        special_requests=entry.contact_note,
        created_by_user_id=user_id,
        status=ReservationStatus.CONFIRMED,
        deposit_paid=deposit_paid,
    )

    entry.status = WaitlistStatus.CONVERTED
    entry.converted_reservation_id = reservation.id
    entry.closed_at = utcnow()
    entry.closed_reason = f"اتحوّل للحجز {reservation.code}"
    db.flush()
    return entry, reservation


def cancel(
    db: Session, entry_id: int, *, reason: str | None = None, user_id: int | None = None
) -> WaitlistEntry:
    """شطب الطلب — بيفك أي حجز مؤقت قايم عليه."""
    entry = _get_open(db, entry_id)
    if entry.status == WaitlistStatus.OFFERED:
        _release_hold(db, entry)
    entry.status = WaitlistStatus.CANCELLED
    entry.closed_at = utcnow()
    entry.closed_reason = reason
    entry.offered_arrival = None
    entry.offered_departure = None
    entry.offer_expires_at = None
    db.flush()
    return entry


# ═══════════════════════════════════════════════════════════ الصيانة الدورية
def expire_offers(db: Session, property_id: int, *, now: datetime | None = None) -> int:
    """أي عرض عدّت مهلته: الوحدة ترجع للبيع والطلب يرجع للانتظار.

    بيتنادى قبل أي قراءة للقايمة وفي التقفيل اليومي — فمفيش وحدة بتفضل
    محبوسة على عرض حد نسيه.
    """
    moment = now or utcnow()
    rows = db.execute(
        select(WaitlistEntry).where(
            WaitlistEntry.property_id == property_id,
            WaitlistEntry.status == WaitlistStatus.OFFERED,
            WaitlistEntry.offer_expires_at.is_not(None),
            WaitlistEntry.offer_expires_at <= moment,
        )
    ).scalars().all()

    for entry in rows:
        _release_hold(db, entry)
        entry.status = WaitlistStatus.WAITING
        entry.offered_at = None
        entry.offer_expires_at = None
        entry.offered_arrival = None
        entry.offered_departure = None
    if rows:
        db.flush()
    return len(rows)


def expire_stale(db: Session, property_id: int, *, today: date | None = None) -> int:
    """طلبات فات ميعاد وصولها ولسه مستنية — بتتقفل كـ EXPIRED."""
    day = today or date.today()
    rows = db.execute(
        select(WaitlistEntry).where(
            WaitlistEntry.property_id == property_id,
            WaitlistEntry.status == WaitlistStatus.WAITING,
            WaitlistEntry.arrival_date < day,
        )
    ).scalars().all()

    for entry in rows:
        entry.status = WaitlistStatus.EXPIRED
        entry.closed_at = utcnow()
        entry.closed_reason = "التواريخ عدّت من غير ما نلاقي مكان"
    if rows:
        db.flush()
    return len(rows)


# ═══════════════════════════════════════════════════════════ القراءة
def list_entries(
    db: Session,
    property_id: int,
    *,
    statuses: list[WaitlistStatus] | None = None,
    unit_category_id: int | None = None,
    arrival_from: date | None = None,
    arrival_to: date | None = None,
    limit: int = 200,
) -> list[WaitlistEntry]:
    stmt = select(WaitlistEntry).where(WaitlistEntry.property_id == property_id)
    stmt = stmt.where(WaitlistEntry.status.in_(list(statuses or OPEN_STATUSES)))
    if unit_category_id:
        stmt = stmt.where(WaitlistEntry.unit_category_id == unit_category_id)
    if arrival_from:
        stmt = stmt.where(WaitlistEntry.arrival_date >= arrival_from)
    if arrival_to:
        stmt = stmt.where(WaitlistEntry.arrival_date <= arrival_to)

    rows = list(db.execute(stmt.limit(limit)).scalars().all())
    rows.sort(key=sort_key)
    return rows


def _get_open(db: Session, entry_id: int) -> WaitlistEntry:
    entry = db.get(WaitlistEntry, entry_id)
    if entry is None:
        raise WaitlistError("الطلب غير موجود", "Waitlist entry not found", "not_found")
    if entry.status not in OPEN_STATUSES:
        raise WaitlistError(
            "الطلب ده مقفول بالفعل",
            "This waitlist entry is already closed",
            "closed",
        )
    return entry
