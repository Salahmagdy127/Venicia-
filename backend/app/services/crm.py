"""علاقات النزلاء — Guest 360, segments and feedback.

الموديول ده مش بيخزّن بيانات جديدة عن النزيل تقريباً — البيانات موجودة
أصلاً موزّعة على الحجوزات والحسابات والسبا. اللي بيعمله إنه **يجمّعها
في مكان واحد ويحوّلها لقرار**.

تلات أسئلة بيجاوب عليهم:

* **النزيل ده بيساوي كام؟** مش عدد الليالي — الإنفاق الكامل: إقامة
  وأكل وسبا. كتير من النزلاء اللي بيقعدوا قليل بينفقوا أكتر من اللي
  بيقعدوا كتير، والغرفة لوحدها بتخفي ده.
* **مين المفروض نكلّمه؟** الشرايح بتتحسب من السلوك مش من رأي حد:
  ناس بتيجي كل سنة ومجاتش، ناس أنفقوا فوق حد معيّن، ناس عندهم مناسبة
  قريبة.
* **الشكوى اتحلّت في قد إيه؟** زمن الرد هو الفرق بين شكوى بتتحل
  وشكوى بتتحوّل مراجعة بنجمة واحدة على جوجل.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    ChargeKind,
    FeedbackChannel,
    FeedbackKind,
    FeedbackStatus,
    ReservationStatus,
    ServiceBookingStatus,
)
from app.models.folio import Folio, FolioLine
from app.models.guests import Guest
from app.models.leisure import GuestFeedback, Service, ServiceBooking
from app.models.reservations import Reservation
from app.models.security import User
from app.services import sequences
from app.services.pricing import money

#: حد النزيل «الكبير» بالجنيه. الرقم ده مش مقدّس — بيتظبّط حسب القرية،
#: بس لازم يبقى **رقم واحد معلن** عشان الفريق كله يقصد نفس الناس.
VIP_SPEND_THRESHOLD = Decimal("150000")

#: نزيل بيتحسب «متكرر» من تالت إقامة. الاتنين ممكن تكون صدفة.
REPEAT_STAYS = 3

#: بعد كام يوم من غير ما ييجي نعتبره «غايب». موسم كامل + شهر.
LAPSED_DAYS = 400

#: الشكوى المفروض يترد عليها في الوقت ده. مش وقت الحل — وقت **الرد**،
#: لأن السكوت هو اللي بيحوّل الشكوى لمراجعة عامة.
ACK_TARGET_HOURS = 4


class CrmError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "crm_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════ ملف النزيل الكامل
@dataclass(slots=True)
class SpendBreakdown:
    rooms: Decimal = Decimal("0")
    food: Decimal = Decimal("0")
    spa: Decimal = Decimal("0")
    activities: Decimal = Decimal("0")
    other: Decimal = Decimal("0")
    total: Decimal = Decimal("0")


@dataclass(slots=True)
class GuestProfile:
    guest_id: int
    name: str
    stays: int = 0
    nights: int = 0
    cancellations: int = 0
    no_shows: int = 0
    first_stay: date | None = None
    last_stay: date | None = None
    days_since_last: int | None = None
    spend: SpendBreakdown = field(default_factory=SpendBreakdown)
    average_per_stay: Decimal = Decimal("0")
    average_per_night: Decimal = Decimal("0")
    service_bookings: int = 0
    open_feedback: int = 0
    segments: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)


#: تصنيف بنود الحساب لفئات إنفاق يفهمها المدير
SPEND_BUCKETS: dict[str, tuple[ChargeKind, ...]] = {
    "rooms": (ChargeKind.ROOM,),
    "food": (ChargeKind.FNB, ChargeKind.MINIBAR),
    "spa": (ChargeKind.SPA,),
    "activities": (ChargeKind.ACTIVITY,),
}


def profile(db: Session, guest_id: int) -> GuestProfile:
    """ملف النزيل الكامل — كل حاجة عنه في استعلام واحد لكل مصدر."""
    guest = db.get(Guest, guest_id)
    if guest is None:
        raise CrmError("النزيل غير موجود", "Guest not found", "not_found")

    result = GuestProfile(
        guest_id=guest.id,
        name=f"{guest.first_name} {guest.last_name}".strip(),
        stays=guest.total_stays,
        nights=guest.total_nights,
        cancellations=guest.total_cancellations,
        no_shows=guest.total_no_shows,
        first_stay=guest.first_stay_date,
        last_stay=guest.last_stay_date,
        preferences=guest.preferences or {},
    )
    if guest.last_stay_date:
        result.days_since_last = (date.today() - guest.last_stay_date).days

    # الإنفاق الحقيقي من سطور الحساب مش من عمود مخزّن. العمود المخزّن
    # بيتحدّث في النايت أوديت وبيتأخّر؛ السطور هي الحقيقة.
    rows = db.execute(
        select(FolioLine.charge_kind, func.sum(FolioLine.total_amount))
        .join(Folio, Folio.id == FolioLine.folio_id)
        .where(
            Folio.guest_id == guest_id,
            FolioLine.is_void.is_(False),
            FolioLine.is_transferred.is_(False),
        )
        .group_by(FolioLine.charge_kind)
    ).all()

    spend = SpendBreakdown()
    for kind, amount in rows:
        value = Decimal(str(amount or 0))
        if kind in (ChargeKind.PAYMENT, ChargeKind.REFUND, ChargeKind.DEPOSIT):
            continue          # دفعات مش إنفاق
        placed = False
        for bucket, kinds in SPEND_BUCKETS.items():
            if kind in kinds:
                setattr(spend, bucket, getattr(spend, bucket) + value)
                placed = True
                break
        if not placed:
            spend.other += value

    spend.rooms = money(spend.rooms)
    spend.food = money(spend.food)
    spend.spa = money(spend.spa)
    spend.activities = money(spend.activities)
    spend.other = money(spend.other)
    spend.total = money(
        spend.rooms + spend.food + spend.spa + spend.activities + spend.other
    )
    result.spend = spend

    if result.stays:
        result.average_per_stay = money(spend.total / result.stays)
    if result.nights:
        result.average_per_night = money(spend.total / result.nights)

    result.service_bookings = db.execute(
        select(func.count(ServiceBooking.id)).where(
            ServiceBooking.guest_id == guest_id,
            ServiceBooking.status != ServiceBookingStatus.CANCELLED,
        )
    ).scalar_one()

    result.open_feedback = db.execute(
        select(func.count(GuestFeedback.id)).where(
            GuestFeedback.guest_id == guest_id,
            GuestFeedback.status.in_(
                [FeedbackStatus.OPEN, FeedbackStatus.ACKNOWLEDGED, FeedbackStatus.ESCALATED]
            ),
        )
    ).scalar_one()

    result.segments = segments_for(guest, spend.total, result.days_since_last)
    return result


def segments_for(
    guest: Guest, total_spend: Decimal, days_since_last: int | None
) -> list[str]:
    """شرايح النزيل — محسوبة من سلوكه، مش مكتوبة بإيد حد.

    الشريحة اللي بتتكتب بالإيد بتتقادم في شهر ومحدش بيراجعها. اللي
    بتتحسب بتفضل صح لوحدها.
    """
    tags: list[str] = []
    if guest.is_vip or total_spend >= VIP_SPEND_THRESHOLD:
        tags.append("VIP")
    if guest.total_stays >= REPEAT_STAYS:
        tags.append("REPEAT")
    if guest.company_id:
        tags.append("CORPORATE")
    if days_since_last is not None and days_since_last > LAPSED_DAYS:
        tags.append("LAPSED")
    if guest.total_no_shows >= 2:
        tags.append("RISK")
    if guest.is_blacklisted:
        tags.append("BLACKLIST")
    if guest.marketing_opt_in:
        tags.append("REACHABLE")
    if not tags:
        tags.append("NEW")
    return tags


# ═══════════════════════════════════════════════════════ الشرائح
@dataclass(slots=True)
class SegmentRow:
    guest_id: int
    name: str
    phone: str | None
    email: str | None
    stays: int
    nights: int
    last_stay: date | None
    total_spend: Decimal
    segments: list[str]


def segment(
    db: Session,
    property_id: int,
    code: str,
    *,
    limit: int = 200,
) -> list[SegmentRow]:
    """قايمة نزلاء شريحة معيّنة — جاهزة للاتصال أو الحملة.

    بنقرا الإنفاق من العمود المخزّن هنا مش من السطور: القايمة دي بتطلع
    لمئات النزلاء، وحساب السطور لكل واحد معناه استعلام لكل صف.
    """
    query = select(Guest).where(Guest.is_active.is_(True))
    today = date.today()

    match code.upper():
        case "VIP":
            query = query.where(
                (Guest.is_vip.is_(True)) | (Guest.total_revenue >= VIP_SPEND_THRESHOLD)
            ).order_by(Guest.total_revenue.desc())
        case "REPEAT":
            query = query.where(Guest.total_stays >= REPEAT_STAYS).order_by(
                Guest.total_stays.desc()
            )
        case "LAPSED":
            query = query.where(
                Guest.total_stays >= 1,
                Guest.last_stay_date.isnot(None),
                Guest.last_stay_date < today - timedelta(days=LAPSED_DAYS),
            ).order_by(Guest.total_revenue.desc())
        case "CORPORATE":
            query = query.where(Guest.company_id.isnot(None)).order_by(
                Guest.total_revenue.desc()
            )
        case "RISK":
            query = query.where(
                (Guest.total_no_shows >= 2) | (Guest.is_blacklisted.is_(True))
            ).order_by(Guest.total_no_shows.desc())
        case "REACHABLE":
            # اللي وافقوا على التسويق **وبس**. القايمة دي بتتبعت لناس
            # حقيقية، ومحدش فيها موجود بالغلط.
            query = query.where(
                Guest.marketing_opt_in.is_(True),
                (Guest.email.isnot(None)) | (Guest.phone.isnot(None)),
            ).order_by(Guest.total_revenue.desc())
        case "NEW":
            query = query.where(Guest.total_stays <= 1).order_by(Guest.id.desc())
        case _:
            raise CrmError(
                f"شريحة مش معروفة: {code}", f"Unknown segment: {code}", "unknown_segment"
            )

    rows = db.execute(query.limit(limit)).scalars().all()
    return [
        SegmentRow(
            guest_id=g.id,
            name=f"{g.first_name} {g.last_name}".strip(),
            phone=g.phone,
            email=g.email,
            stays=g.total_stays,
            nights=g.total_nights,
            last_stay=g.last_stay_date,
            total_spend=money(g.total_revenue),
            segments=segments_for(
                g,
                g.total_revenue,
                (today - g.last_stay_date).days if g.last_stay_date else None,
            ),
        )
        for g in rows
    ]


@dataclass(slots=True)
class SegmentSummary:
    code: str
    name_ar: str
    name_en: str
    guests: int
    value: Decimal


SEGMENT_LABELS: list[tuple[str, str, str]] = [
    ("VIP", "نزلاء كبار", "Top spenders"),
    ("REPEAT", "متكررون", "Repeat guests"),
    ("CORPORATE", "شركات", "Corporate"),
    ("LAPSED", "غايبون", "Lapsed"),
    ("REACHABLE", "موافقون على التسويق", "Marketing opt-in"),
    ("RISK", "متابعة", "Watch list"),
    ("NEW", "جدد", "New"),
]


def segment_summary(db: Session, property_id: int) -> list[SegmentSummary]:
    result: list[SegmentSummary] = []
    for code, name_ar, name_en in SEGMENT_LABELS:
        rows = segment(db, property_id, code, limit=5000)
        result.append(
            SegmentSummary(
                code=code,
                name_ar=name_ar,
                name_en=name_en,
                guests=len(rows),
                value=money(sum((r.total_spend for r in rows), Decimal("0"))),
            )
        )
    return result


# ═══════════════════════════════════════════════════════ الملاحظات
def log_feedback(
    db: Session,
    property_id: int,
    *,
    subject: str,
    kind: FeedbackKind,
    channel: FeedbackChannel,
    guest_id: int | None = None,
    guest_name: str | None = None,
    reservation_id: int | None = None,
    unit_id: int | None = None,
    rating: int | None = None,
    department: str | None = None,
    body: str | None = None,
    received_at: datetime | None = None,
    user: User | None = None,
) -> GuestFeedback:
    if not subject.strip():
        raise CrmError("العنوان مطلوب", "A subject is required", "no_subject")

    name = (guest_name or "").strip()
    if not name and guest_id:
        guest = db.get(Guest, guest_id)
        if guest is not None:
            name = f"{guest.first_name} {guest.last_name}".strip()
    if not name:
        name = "نزيل"

    entry = GuestFeedback(
        number=sequences.next_number(db, property_id, "FEEDBACK"),
        property_id=property_id,
        guest_id=guest_id,
        guest_name=name[:250],
        reservation_id=reservation_id,
        unit_id=unit_id,
        kind=kind,
        channel=channel,
        status=FeedbackStatus.OPEN,
        rating=max(1, min(5, rating)) if rating is not None else None,
        department=(department or "").strip()[:60] or None,
        subject=subject.strip()[:250],
        body=(body or "").strip()[:2000] or None,
        received_at=received_at or utcnow(),
        owner_user_id=user.id if user else None,
    )
    db.add(entry)
    db.flush()
    return entry


def acknowledge(
    db: Session, feedback_id: int, *, user: User | None = None
) -> GuestFeedback:
    """تسجيل إن حد ردّ. ده أهم توقيت في السجل كله."""
    entry = db.get(GuestFeedback, feedback_id)
    if entry is None:
        raise CrmError("الملاحظة غير موجودة", "Feedback not found", "not_found")
    if entry.acknowledged_at is None:
        entry.acknowledged_at = utcnow()
    if entry.status == FeedbackStatus.OPEN:
        entry.status = FeedbackStatus.ACKNOWLEDGED
    if user is not None:
        entry.owner_user_id = entry.owner_user_id or user.id
    db.flush()
    return entry


def resolve(
    db: Session,
    feedback_id: int,
    *,
    resolution: str,
    compensation: Decimal | None = None,
    user: User | None = None,
) -> GuestFeedback:
    entry = db.get(GuestFeedback, feedback_id)
    if entry is None:
        raise CrmError("الملاحظة غير موجودة", "Feedback not found", "not_found")
    if not resolution.strip():
        raise CrmError("اكتب اتعمل إيه", "Describe the resolution", "no_resolution")

    now = utcnow()
    entry.acknowledged_at = entry.acknowledged_at or now
    entry.resolved_at = now
    entry.status = FeedbackStatus.RESOLVED
    entry.resolution = resolution.strip()[:1500]
    if compensation is not None:
        entry.compensation = money(compensation)
    if user is not None:
        entry.owner_user_id = entry.owner_user_id or user.id
    db.flush()
    return entry


def escalate(db: Session, feedback_id: int, note: str | None = None) -> GuestFeedback:
    entry = db.get(GuestFeedback, feedback_id)
    if entry is None:
        raise CrmError("الملاحظة غير موجودة", "Feedback not found", "not_found")
    if entry.status in (FeedbackStatus.RESOLVED, FeedbackStatus.CLOSED):
        raise CrmError("الملاحظة اتقفلت خلاص", "Already closed", "closed")
    entry.status = FeedbackStatus.ESCALATED
    if note:
        entry.body = f"{entry.body or ''}\n— تصعيد: {note.strip()}"[:2000]
    db.flush()
    return entry


@dataclass(slots=True)
class FeedbackBoard:
    open: int = 0
    acknowledged: int = 0
    escalated: int = 0
    resolved_30d: int = 0
    complaints_30d: int = 0
    compliments_30d: int = 0
    overdue: int = 0
    average_rating: Decimal | None = None
    average_ack_hours: Decimal | None = None
    average_resolve_hours: Decimal | None = None
    compensation_30d: Decimal = Decimal("0")
    by_department: dict[str, int] = field(default_factory=dict)


def feedback_board(db: Session, property_id: int) -> FeedbackBoard:
    now = utcnow()
    horizon = now - timedelta(days=30)
    rows = db.execute(
        select(GuestFeedback).where(GuestFeedback.property_id == property_id)
    ).scalars().all()

    result = FeedbackBoard()
    ratings: list[int] = []
    ack_hours: list[Decimal] = []
    resolve_hours: list[Decimal] = []

    for entry in rows:
        recent = entry.received_at >= horizon
        match entry.status:
            case FeedbackStatus.OPEN:
                result.open += 1
            case FeedbackStatus.ACKNOWLEDGED:
                result.acknowledged += 1
            case FeedbackStatus.ESCALATED:
                result.escalated += 1

        # «متأخرة» = محدش ردّ عليها في المهلة. مش «مش متحلّة» — الحل
        # ممكن ياخد يومين، لكن السكوت أربع ساعات هو المشكلة.
        if entry.acknowledged_at is None and entry.status not in (
            FeedbackStatus.RESOLVED,
            FeedbackStatus.CLOSED,
        ):
            if (now - entry.received_at) > timedelta(hours=ACK_TARGET_HOURS):
                result.overdue += 1

        if entry.acknowledged_at:
            ack_hours.append(
                Decimal(str((entry.acknowledged_at - entry.received_at).total_seconds() / 3600))
            )
        if entry.resolved_at:
            resolve_hours.append(
                Decimal(str((entry.resolved_at - entry.received_at).total_seconds() / 3600))
            )

        if recent:
            if entry.status == FeedbackStatus.RESOLVED:
                result.resolved_30d += 1
            if entry.kind == FeedbackKind.COMPLAINT:
                result.complaints_30d += 1
                if entry.department:
                    result.by_department[entry.department] = (
                        result.by_department.get(entry.department, 0) + 1
                    )
            elif entry.kind == FeedbackKind.COMPLIMENT:
                result.compliments_30d += 1
            result.compensation_30d += entry.compensation
            if entry.rating is not None:
                ratings.append(entry.rating)

    if ratings:
        result.average_rating = (
            Decimal(sum(ratings)) / Decimal(len(ratings))
        ).quantize(Decimal("0.01"))
    if ack_hours:
        result.average_ack_hours = (
            sum(ack_hours) / Decimal(len(ack_hours))
        ).quantize(Decimal("0.1"))
    if resolve_hours:
        result.average_resolve_hours = (
            sum(resolve_hours) / Decimal(len(resolve_hours))
        ).quantize(Decimal("0.1"))
    result.compensation_30d = money(result.compensation_30d)
    return result


def top_guests(db: Session, property_id: int, limit: int = 20) -> list[SegmentRow]:
    today = date.today()
    rows = db.execute(
        select(Guest)
        .where(Guest.is_active.is_(True), Guest.total_revenue > 0)
        .order_by(Guest.total_revenue.desc())
        .limit(limit)
    ).scalars().all()
    return [
        SegmentRow(
            guest_id=g.id,
            name=f"{g.first_name} {g.last_name}".strip(),
            phone=g.phone,
            email=g.email,
            stays=g.total_stays,
            nights=g.total_nights,
            last_stay=g.last_stay_date,
            total_spend=money(g.total_revenue),
            segments=segments_for(
                g,
                g.total_revenue,
                (today - g.last_stay_date).days if g.last_stay_date else None,
            ),
        )
        for g in rows
    ]
