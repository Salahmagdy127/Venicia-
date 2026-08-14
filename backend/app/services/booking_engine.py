"""محرك الحجز المباشر — Booking engine.

القيمة هنا رقم واحد: **العمولة صفر**. الحجز اللي بيجي من موقع القرية
بيدخل نفس الإتاحة ونفس التسعير ونفس الحساب زي أي حجز، بس من غير الـ
14–17% اللي القنوات بتاخدها.

الفرق الوحيد في المسار إن الزائر مش موظف: مبيقدرش يشوف حاجة غير المتاح
للبيع، ومبيقدرش يعدّل سعر، والوحدة بتتحجزله **مؤقتاً** وهو بيملا بياناته
بمهلة قصيرة. المهلة بتفك نفسها، فمفيش سلة متروكة بتقفل غرفة.

المهلة متخزنة في ``Reservation.hold_expires_at`` والحجز بيبقى ``TENTATIVE``
— يعني بيبان في شاشة الحجوزات على طول، والريسبشن يشوف إن فيه حد بيحجز
دلوقتي على الموقع.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token, decode_token
from app.models.enums import BookingSource, ReservationStatus
from app.models.guests import Guest
from app.models.organization import Property
from app.models.rates import RatePlan
from app.models.reservations import Reservation, ReservationUnit
from app.models.units import Unit, UnitCategory
from app.services import availability as av
from app.services import pricing
from app.services import reservations as res_svc

#: أطول إقامة يقدر الزائر يحجزها من الموقع من غير ما يكلّم الاستقبال
MAX_ONLINE_NIGHTS = 21
#: أبعد مدى للحجز المسبق
MAX_LEAD_DAYS = 365


class BookingEngineError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "booking_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Offer:
    """عرض واحد على الموقع — فئة بسعرها وإتاحتها."""

    category: UnitCategory
    plan: RatePlan
    quote: pricing.StayQuote
    available: int


# ═══════════════════════════════════════════════ تنضيف السلال المتروكة
def release_expired(db: Session, property_id: int, *, now: datetime | None = None) -> int:
    """أي سلة عدّت مهلتها: الحجز بيتلغي والوحدة بترجع للبيع.

    بيتنادى قبل أي بحث وفي التقفيل اليومي. من غيره أول زائر بيسيب الصفحة
    بيقفل غرفة للأبد.
    """
    moment = now or utcnow()
    rows = db.execute(
        select(Reservation).where(
            Reservation.property_id == property_id,
            Reservation.status == ReservationStatus.TENTATIVE,
            Reservation.hold_expires_at.is_not(None),
            Reservation.hold_expires_at <= moment,
        )
    ).scalars().all()

    for reservation in rows:
        res_svc.cancel(
            db,
            reservation.id,
            reason="انتهت مهلة السلة على الموقع",
            charge_penalty=False,
        )
    return len(rows)


# ═══════════════════════════════════════════════════════════ البحث
def _validate_stay(arrival: date, departure: date) -> int:
    today = date.today()
    if departure <= arrival:
        raise BookingEngineError(
            "تاريخ المغادرة لازم يكون بعد الوصول",
            "Departure must be after arrival",
            "invalid_dates",
        )
    if arrival < today:
        raise BookingEngineError(
            "مينفعش تحجز تواريخ عدّت", "Cannot book past dates", "past_dates"
        )
    nights = (departure - arrival).days
    if nights > MAX_ONLINE_NIGHTS:
        raise BookingEngineError(
            f"أطول إقامة على الموقع {MAX_ONLINE_NIGHTS} ليلة — كلّمنا للإقامات الأطول",
            f"Online stays are capped at {MAX_ONLINE_NIGHTS} nights — call us for longer",
            "too_long",
        )
    if (arrival - today).days > MAX_LEAD_DAYS:
        raise BookingEngineError(
            "الحجز متاح لسنة قدام", "Bookings open one year ahead", "too_far"
        )
    return nights


def search(
    db: Session,
    property_id: int,
    *,
    arrival: date,
    departure: date,
    adults: int = 2,
    children: int = 0,
) -> list[Offer]:
    """الفئات المتاحة فعلاً بأسعارها — بترتيب الأرخص الأول.

    الفئات اللي مفيهاش مكان أو مش داخلة السعة مبتظهرش خالص: الزائر
    مايشوفش حاجة يدوس عليها وتترفض.
    """
    _validate_stay(arrival, departure)
    if adults < 1:
        raise BookingEngineError("لازم فرد واحد على الأقل", "At least one adult", "no_adults")

    release_expired(db, property_id)

    plan = db.execute(
        select(RatePlan)
        .where(
            RatePlan.property_id == property_id,
            RatePlan.is_active.is_(True),
            RatePlan.is_public.is_(True),
        )
        .order_by(RatePlan.sort_order)
        .limit(1)
    ).scalar_one_or_none()
    if plan is None:
        raise BookingEngineError(
            "مفيش خطة أسعار متاحة على الموقع",
            "No public rate plan is configured",
            "no_public_plan",
        )

    categories = list(
        db.execute(
            select(UnitCategory)
            .where(UnitCategory.property_id == property_id, UnitCategory.is_active.is_(True))
            .order_by(UnitCategory.sort_order)
        ).scalars().all()
    )

    offers: list[Offer] = []
    for category in categories:
        if adults + children > category.max_occupancy:
            continue
        free = av.min_available(db, property_id, category.id, arrival, departure)
        if free < 1:
            continue
        try:
            quote = pricing.quote_stay(
                db,
                property_id=property_id,
                unit_category_id=category.id,
                rate_plan_id=plan.id,
                arrival=arrival,
                departure=departure,
                adults=adults,
                children=children,
            )
        except pricing.PricingError:
            continue  # يوم مقفول أو سعر ناقص — الفئة دي مش معروضة
        offers.append(Offer(category=category, plan=plan, quote=quote, available=free))

    offers.sort(key=lambda o: o.quote.grand_total)
    return offers


# ═══════════════════════════════════════════════════════════ السلة
def hold(
    db: Session,
    property_id: int,
    *,
    unit_category_id: int,
    arrival: date,
    departure: date,
    adults: int = 2,
    children: int = 0,
) -> tuple[Reservation, str, datetime]:
    """بيحجز الوحدة مؤقتاً وبيرجّع توكن السلة ووقت انتهائها.

    الحجز بيتعمل ``TENTATIVE`` بمهلة — يعني بيخصم من الإتاحة فعلاً. ده
    مقصود: لو خصمناش، اتنين على الموقع يقدروا يخلّصوا نفس الغرفة.
    """
    _validate_stay(arrival, departure)
    release_expired(db, property_id)

    plan = db.execute(
        select(RatePlan)
        .where(
            RatePlan.property_id == property_id,
            RatePlan.is_active.is_(True),
            RatePlan.is_public.is_(True),
        )
        .order_by(RatePlan.sort_order)
        .limit(1)
    ).scalar_one_or_none()
    if plan is None:
        raise BookingEngineError(
            "مفيش خطة أسعار متاحة على الموقع",
            "No public rate plan is configured",
            "no_public_plan",
        )

    category = db.get(UnitCategory, unit_category_id)
    if category is None or category.property_id != property_id or not category.is_active:
        raise BookingEngineError("الفئة دي مش متاحة", "Category is not available", "not_found")
    if adults + children > category.max_occupancy:
        raise BookingEngineError(
            f"الفئة دي بتستوعب {category.max_occupancy} أفراد كحد أقصى",
            f"This category holds up to {category.max_occupancy} guests",
            "over_capacity",
        )

    # نزيل مؤقت للسلة — بيتبدل ببيانات الزائر الحقيقية عند التأكيد
    placeholder = _placeholder_guest(db, property_id)

    reservation = res_svc.create_reservation(
        db,
        property_id=property_id,
        guest_id=placeholder.id,
        unit_category_id=unit_category_id,
        rate_plan_id=plan.id,
        arrival=arrival,
        departure=departure,
        adults=adults,
        children=children,
        source=BookingSource.WEBSITE,
        status=ReservationStatus.TENTATIVE,
    )
    expires = utcnow() + timedelta(minutes=settings.BOOKING_HOLD_MINUTES)
    reservation.hold_expires_at = expires
    reservation.internal_notes = "سلة حجز من الموقع — لسه ماتأكدتش"
    db.flush()

    token = create_token(reservation.id, "hold")
    return reservation, token, expires


def _placeholder_guest(db: Session, property_id: int) -> Guest:
    """ملف مؤقت واحد لكل المنشأة — بيتستخدم للسلال قبل ما الزائر يعرّف نفسه."""
    found = db.execute(
        select(Guest).where(
            Guest.property_id == property_id, Guest.id_number == "WEB-PLACEHOLDER"
        ).limit(1)
    ).scalar_one_or_none()
    if found is not None:
        return found

    row = Guest(
        property_id=property_id,
        first_name="زائر",
        last_name="الموقع",
        id_number="WEB-PLACEHOLDER",
        nationality="EG",
    )
    db.add(row)
    db.flush()
    return row


def read_hold(db: Session, property_id: int, token: str) -> Reservation:
    """بيتحقق من توكن السلة ويرجّع الحجز — أو يرمي خطأ مفهوم."""
    payload = decode_token(token, expected_type="hold")
    if payload is None:
        raise BookingEngineError(
            "مهلة الحجز خلصت — ابحث تاني من فضلك",
            "Your hold expired — please search again",
            "hold_expired",
        )
    try:
        reservation_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise BookingEngineError("رابط غير صالح", "Invalid hold", "bad_hold") from None

    reservation = db.get(Reservation, reservation_id)
    if reservation is None or reservation.property_id != property_id:
        raise BookingEngineError("الحجز مش موجود", "Hold not found", "not_found")
    if reservation.status == ReservationStatus.CANCELLED:
        raise BookingEngineError(
            "مهلة الحجز خلصت — ابحث تاني من فضلك",
            "Your hold expired — please search again",
            "hold_expired",
        )
    return reservation


# ═══════════════════════════════════════════════════════════ التأكيد
def confirm(
    db: Session,
    property_id: int,
    *,
    token: str,
    first_name: str,
    last_name: str,
    phone: str,
    email: str | None = None,
    notes: str | None = None,
    deposit_paid: Decimal | None = None,
) -> Reservation:
    """تحويل السلة لحجز مؤكد ببيانات الزائر."""
    reservation = read_hold(db, property_id, token)
    if reservation.status != ReservationStatus.TENTATIVE:
        raise BookingEngineError(
            "الحجز ده متأكد بالفعل", "This booking is already confirmed", "already_confirmed"
        )

    phone = (phone or "").strip()
    if len(phone) < 8:
        raise BookingEngineError(
            "رقم موبايل غير صحيح", "Please enter a valid phone number", "bad_phone"
        )
    if not first_name.strip() or not last_name.strip():
        raise BookingEngineError("الاسم مطلوب", "Your name is required", "no_name")

    guest = _resolve_guest(db, property_id, first_name, last_name, phone, email)
    if guest.is_blacklisted:
        raise BookingEngineError(
            "مش قادرين نكمّل الحجز — كلّمنا من فضلك",
            "We cannot complete this booking — please call us",
            "blocked",
        )

    reservation.guest_id = guest.id
    reservation.status = ReservationStatus.CONFIRMED
    reservation.hold_expires_at = None
    reservation.internal_notes = None
    reservation.special_requests = (notes or "").strip() or None

    deposit = pricing.money(deposit_paid or Decimal("0"))
    if deposit < 0 or deposit > reservation.grand_total:
        raise BookingEngineError(
            "قيمة العربون غير صحيحة", "Invalid deposit amount", "bad_deposit"
        )
    reservation.deposit_paid = deposit
    reservation.paid_total = deposit
    reservation.balance = pricing.money(reservation.grand_total - deposit)

    # سطور الحجز بتاخد نفس الحالة عشان الإتاحة والتقارير تفضل متسقة
    for line in db.execute(
        select(ReservationUnit).where(ReservationUnit.reservation_id == reservation.id)
    ).scalars():
        line.status = ReservationStatus.CONFIRMED

    db.flush()
    return reservation


def _resolve_guest(
    db: Session,
    property_id: int,
    first_name: str,
    last_name: str,
    phone: str,
    email: str | None,
) -> Guest:
    """نزيل قديم بنفس الموبايل ولا ملف جديد — عشان تاريخ الإقامات مايتفرقش."""
    found = db.execute(
        select(Guest).where(
            Guest.property_id == property_id,
            Guest.phone == phone,
            or_(Guest.id_number.is_(None), Guest.id_number != "WEB-PLACEHOLDER"),
        ).limit(1)
    ).scalar_one_or_none()
    if found is not None:
        if email and not found.email:
            found.email = email
        return found

    row = Guest(
        property_id=property_id,
        first_name=first_name.strip()[:100],
        last_name=last_name.strip()[:100],
        phone=phone,
        email=(email or "").strip() or None,
        nationality="EG",
        marketing_opt_in=False,
    )
    db.add(row)
    db.flush()
    return row


def release(db: Session, property_id: int, token: str) -> Reservation:
    """الزائر ساب السلة بإرادته — بنرجّع الوحدة للبيع فوراً."""
    reservation = read_hold(db, property_id, token)
    if reservation.status != ReservationStatus.TENTATIVE:
        raise BookingEngineError(
            "الحجز ده متأكد بالفعل", "This booking is already confirmed", "already_confirmed"
        )
    res_svc.cancel(db, reservation.id, reason="الزائر ساب السلة", charge_penalty=False)
    return reservation


# ═══════════════════════════════════════════════════════════ الاستعلام
def lookup(db: Session, property_id: int, code: str, phone: str) -> Reservation:
    """الزائر بيراجع حجزه — الكود والموبايل مع بعض، عشان محدش يشوف حجز غيره."""
    reservation = db.execute(
        select(Reservation).where(
            Reservation.property_id == property_id, Reservation.code == code.strip()
        ).limit(1)
    ).scalar_one_or_none()
    if reservation is None:
        raise BookingEngineError("مفيش حجز بالرقم ده", "No booking with this code", "not_found")

    guest = db.get(Guest, reservation.guest_id)
    if guest is None or (guest.phone or "") != phone.strip():
        raise BookingEngineError(
            "الرقم مش مطابق لبيانات الحجز",
            "The phone number does not match this booking",
            "mismatch",
        )
    return reservation


def property_info(db: Session, property_id: int) -> tuple[Property, list[UnitCategory], dict[int, int]]:
    """بيانات الصفحة العامة — المنشأة وفئاتها وعدد وحدات كل فئة."""
    prop = db.get(Property, property_id)
    if prop is None:
        raise BookingEngineError("المنشأة غير موجودة", "Property not found", "not_found")

    categories = list(
        db.execute(
            select(UnitCategory)
            .where(UnitCategory.property_id == property_id, UnitCategory.is_active.is_(True))
            .order_by(UnitCategory.sort_order)
        ).scalars().all()
    )
    counts = dict(
        db.execute(
            select(Unit.category_id, func.count(Unit.id))
            .where(Unit.property_id == property_id, Unit.is_active.is_(True))
            .group_by(Unit.category_id)
        ).all()
    )
    return prop, categories, counts
