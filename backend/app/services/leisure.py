"""السبا والأنشطة والمناسبات — Spa/activity scheduling & event management.

**السبا والأنشطة**

القاعدة الوحيدة اللي بتمنع الفوضى: *المورد* مبيتحجزش مرتين في نفس
الوقت. الخدمة مجردة — «مساج سويدي ٦٠ دقيقة» مش حاجة تتحجز؛ اللي
بيتحجز هو **منى في الكابينة ٢ من ٣ لـ ٤**. عشان كده كل فحص إتاحة
بيتم على المورد، والحجز من غير مورد بيترفض للخدمات اللي بتحتاجه.

وبنحسب التعارض على المدة **زائد وقت التجهيز**. من غير كده الجدول
بيبان مظبوط والواقع بيتأخّر عشر دقايق كل حجز، وبعد خمس حجوزات المعالجة
بقت متأخرة ساعة.

**المناسبات**

المكان بيتقفل بالحالة مش بالنية: ``INQUIRY`` مبتقفلش، و``TENTATIVE``
بتقفل بميعاد انتهاء. الفرق ده بيمنع أشهر مشكلة في قاعات الأفراح —
قاعة اتباعت مرتين لأن حد قال «تمام هنأكدلك» على التليفون.

والحساب بيتبني من بنود ورقة التشغيل مش برقم بيتكتب بالإيد، فأي بند
بيتضاف بيوصل الإجمالي لوحده، والعربون المطلوب بيتحسب منه.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    BLOCKING_EVENT_STATUSES,
    BLOCKING_SERVICE_STATUSES,
    ChargeKind,
    EventItemKind,
    EventKind,
    EventStatus,
    ServiceBookingStatus,
    ServiceCategory,
)
from app.models.folio import Folio
from app.models.guests import Guest
from app.models.leisure import (
    EventBooking,
    EventItem,
    Service,
    ServiceBooking,
    ServiceResourceItem,
    Venue,
)
from app.models.organization import Property
from app.models.security import User
from app.services import folio as folio_svc
from app.services import sequences
from app.services.pricing import money

#: نسبة العربون الافتراضية على المناسبات. ٢٥٪ رقم السوق المصري:
#: كفاية إنه يثبت الجدية، ومش كفاية إن العميل يهرب من دفعه.
DEFAULT_DEPOSIT_PERCENT = Decimal("25")

#: الحجز المبدئي بيعيش أسبوعين. بعدهم المكان بيرجع للبيع تلقائياً.
DEFAULT_OPTION_DAYS = 14

#: نوع الحركة على حساب النزيل حسب نوع الخدمة
CHARGE_KIND: dict[ServiceCategory, ChargeKind] = {
    ServiceCategory.SPA: ChargeKind.SPA,
    ServiceCategory.FITNESS: ChargeKind.SPA,
    ServiceCategory.ACTIVITY: ChargeKind.ACTIVITY,
    ServiceCategory.EXCURSION: ChargeKind.ACTIVITY,
    ServiceCategory.KIDS: ChargeKind.ACTIVITY,
    ServiceCategory.RENTAL: ChargeKind.ACTIVITY,
}


class LeisureError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "leisure_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════ إتاحة المورد
def resource_conflicts(
    db: Session,
    resource_id: int,
    start_at: datetime,
    end_at: datetime,
    *,
    exclude_booking_id: int | None = None,
) -> list[ServiceBooking]:
    """الحجوزات اللي بتتقاطع مع الفترة دي على نفس المورد.

    التقاطع بيتحسب بالقاعدة الكلاسيكية: ``start < other_end AND
    end > other_start``. المساواة **مش** تقاطع — حجز بيخلص ٣:٠٠ وحجز
    بيبدأ ٣:٠٠ ماشيين، وده بالظبط اللي وقت التجهيز موجود عشانه.
    """
    query = select(ServiceBooking).where(
        ServiceBooking.resource_id == resource_id,
        ServiceBooking.status.in_(list(BLOCKING_SERVICE_STATUSES)),
        ServiceBooking.start_at < end_at,
        ServiceBooking.end_at > start_at,
    )
    if exclude_booking_id is not None:
        query = query.where(ServiceBooking.id != exclude_booking_id)
    return list(db.execute(query.order_by(ServiceBooking.start_at)).scalars().all())


@dataclass(slots=True)
class Slot:
    start_at: datetime
    end_at: datetime
    resource_id: int
    resource_name: str
    seats_left: int


def open_slots(
    db: Session,
    property_id: int,
    service_id: int,
    day: date,
    *,
    step_minutes: int = 30,
) -> list[Slot]:
    """المواعيد الفاضية للخدمة دي في اليوم ده.

    بنمشي على المواعيد كل نص ساعة عبر كل مورد ينفع للخدمة، وبنستبعد
    اللي بيتعارض. النتيجة هي اللي شاشة الحجز بتعرضها — يعني الموظف
    مبيقدرش يختار ميعاد مشغول أصلاً.
    """
    service = db.get(Service, service_id)
    if service is None or service.property_id != property_id:
        raise LeisureError("الخدمة غير موجودة", "Service not found", "not_found")

    resources = [r for r in service.resources if r.is_active]
    if not resources:
        if service.requires_resource:
            return []
        resources = []

    opens = service.opens_at or time(9, 0)
    closes = service.closes_at or time(21, 0)
    span = timedelta(minutes=service.duration_minutes + service.buffer_minutes)

    slots: list[Slot] = []
    for resource in resources:
        # وردية المورد بتضيّق ساعات الخدمة، مبتوسّعهاش
        begin = max(opens, resource.shift_start or opens)
        finish = min(closes, resource.shift_end or closes)
        cursor = datetime.combine(day, begin, tzinfo=timezone.utc)
        limit = datetime.combine(day, finish, tzinfo=timezone.utc)

        booked = resource_conflicts(
            db, resource.id, cursor, limit + span
        )

        while cursor + timedelta(minutes=service.duration_minutes) <= limit:
            end = cursor + timedelta(minutes=service.duration_minutes)
            taken = sum(
                b.adults + b.children
                for b in booked
                if b.start_at < end + timedelta(minutes=service.buffer_minutes)
                and b.end_at + timedelta(minutes=service.buffer_minutes) > cursor
            )
            seats = min(service.capacity, resource.capacity) - taken
            if seats > 0:
                slots.append(
                    Slot(
                        start_at=cursor,
                        end_at=end,
                        resource_id=resource.id,
                        resource_name=resource.name_ar,
                        seats_left=seats,
                    )
                )
            cursor += timedelta(minutes=step_minutes)

    slots.sort(key=lambda s: (s.start_at, s.resource_id))
    return slots


# ═══════════════════════════════════════════════════════ الحجز
def book_service(
    db: Session,
    property_id: int,
    *,
    service_id: int,
    start_at: datetime,
    guest_name: str,
    resource_id: int | None = None,
    guest_id: int | None = None,
    folio_id: int | None = None,
    reservation_id: int | None = None,
    adults: int = 1,
    children: int = 0,
    notes: str | None = None,
    user: User | None = None,
    price_override: Decimal | None = None,
) -> ServiceBooking:
    """يحجز موعد. بيرفض لو المورد مشغول أو الوقت بره ساعات الخدمة."""
    service = db.get(Service, service_id)
    if service is None or service.property_id != property_id or not service.is_active:
        raise LeisureError("الخدمة غير موجودة", "Service not found", "not_found")
    if adults + children < 1:
        raise LeisureError("لازم فرد واحد على الأقل", "At least one guest", "no_pax")
    if adults + children > service.capacity:
        raise LeisureError(
            f"الخدمة دي بتاخد {service.capacity} فرد كحد أقصى",
            f"Maximum {service.capacity} guests for this service",
            "over_capacity",
        )

    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    end_at = start_at + timedelta(minutes=service.duration_minutes)

    if service.opens_at and start_at.time() < service.opens_at:
        raise LeisureError(
            f"الخدمة بتفتح {service.opens_at.strftime('%H:%M')}",
            f"Service opens at {service.opens_at.strftime('%H:%M')}",
            "closed",
        )
    if service.closes_at and end_at.time() > service.closes_at:
        raise LeisureError(
            f"الخدمة بتقفل {service.closes_at.strftime('%H:%M')}",
            f"Service closes at {service.closes_at.strftime('%H:%M')}",
            "closed",
        )

    resource = None
    if service.requires_resource:
        if resource_id is None:
            # مفيش مورد متحدد — بندوّر على أول واحد فاضي بدل ما نرفض
            for candidate in service.resources:
                if not candidate.is_active:
                    continue
                if not _busy(db, candidate, start_at, end_at, service):
                    resource = candidate
                    break
            if resource is None:
                raise LeisureError(
                    "مفيش حد فاضي في الميعاد ده",
                    "No resource available at this time",
                    "no_resource",
                )
        else:
            resource = db.get(ServiceResourceItem, resource_id)
            if resource is None or resource.property_id != property_id:
                raise LeisureError("المورد غير موجود", "Resource not found", "not_found")
            if _busy(db, resource, start_at, end_at, service):
                clash = resource_conflicts(
                    db, resource.id,
                    start_at - timedelta(minutes=service.buffer_minutes),
                    end_at + timedelta(minutes=service.buffer_minutes),
                )
                raise LeisureError(
                    f"{resource.name_ar} محجوز في الميعاد ده"
                    + (f" ({clash[0].number})" if clash else ""),
                    f"{resource.name_en} is already booked at this time",
                    "conflict",
                )

    unit_price = price_override if price_override is not None else service.price
    total = money(unit_price * adults + service.price_child * children)

    booking = ServiceBooking(
        number=sequences.next_number(db, property_id, "SERVICE"),
        property_id=property_id,
        service_id=service.id,
        resource_id=resource.id if resource else None,
        guest_id=guest_id,
        guest_name=guest_name.strip()[:250] or "زائر",
        folio_id=folio_id,
        reservation_id=reservation_id,
        start_at=start_at,
        end_at=end_at,
        business_date=start_at.date(),
        status=ServiceBookingStatus.CONFIRMED,
        adults=adults,
        children=children,
        unit_price=money(unit_price),
        total=total,
        notes=(notes or "").strip()[:500] or None,
        created_by_user_id=user.id if user else None,
    )
    db.add(booking)
    db.flush()
    return booking


def _busy(
    db: Session,
    resource: ServiceResourceItem,
    start_at: datetime,
    end_at: datetime,
    service: Service,
) -> bool:
    """المورد مشغول؟ الفحص بيشمل وقت التجهيز على الجهتين."""
    buffer = timedelta(minutes=service.buffer_minutes)
    clashes = resource_conflicts(db, resource.id, start_at - buffer, end_at + buffer)
    if not clashes:
        return False
    if resource.capacity <= 1:
        return True
    seats = sum(b.adults + b.children for b in clashes)
    return seats >= resource.capacity


def reschedule(
    db: Session,
    booking_id: int,
    new_start: datetime,
    *,
    resource_id: int | None = None,
) -> ServiceBooking:
    booking = _live_booking(db, booking_id)
    service = db.get(Service, booking.service_id)
    if service is None:
        raise LeisureError("الخدمة غير موجودة", "Service not found", "not_found")

    if new_start.tzinfo is None:
        new_start = new_start.replace(tzinfo=timezone.utc)
    new_end = new_start + timedelta(minutes=service.duration_minutes)
    target_id = resource_id or booking.resource_id

    if target_id is not None:
        buffer = timedelta(minutes=service.buffer_minutes)
        clashes = resource_conflicts(
            db, target_id, new_start - buffer, new_end + buffer,
            exclude_booking_id=booking.id,
        )
        if clashes:
            raise LeisureError(
                f"الميعاد الجديد متعارض مع {clashes[0].number}",
                f"New time conflicts with {clashes[0].number}",
                "conflict",
            )

    booking.start_at = new_start
    booking.end_at = new_end
    booking.business_date = new_start.date()
    booking.resource_id = target_id
    db.flush()
    return booking


def check_in(db: Session, booking_id: int) -> ServiceBooking:
    booking = _live_booking(db, booking_id)
    booking.status = ServiceBookingStatus.CHECKED_IN
    db.flush()
    return booking


def complete(
    db: Session,
    booking_id: int,
    *,
    user: User | None = None,
    post_to_folio: bool = True,
) -> ServiceBooking:
    """إنهاء الموعد وترحيله على حساب النزيل.

    الترحيل بيتم مرة واحدة بس: ``folio_line_id`` هو الحارس. من غيره،
    ضغطتين على «تمّت» بيرحّلوا المساج مرتين على حساب النزيل — وده
    النوع من الأخطاء اللي بيوصل الريسبشن وقت الخروج.
    """
    booking = db.get(ServiceBooking, booking_id)
    if booking is None:
        raise LeisureError("الحجز غير موجود", "Booking not found", "not_found")
    if booking.status == ServiceBookingStatus.CANCELLED:
        raise LeisureError("الحجز ملغي", "Booking is cancelled", "cancelled")

    booking.status = ServiceBookingStatus.COMPLETED

    if post_to_folio and booking.folio_line_id is None and booking.folio_id and booking.total > 0:
        service = db.get(Service, booking.service_id)
        kind = CHARGE_KIND.get(
            service.category if service else ServiceCategory.ACTIVITY, ChargeKind.ACTIVITY
        )
        line = folio_svc.post_charge(
            db,
            booking.folio_id,
            charge_kind=kind,
            description_ar=f"{service.name_ar if service else 'خدمة'} — {booking.number}",
            description_en=service.name_en if service else "Service",
            amount=booking.total,
            business_date=booking.business_date,
            user_id=user.id if user else None,
        )
        booking.folio_line_id = line.id
        booking.posted_at = utcnow()

    db.flush()
    return booking


def cancel(db: Session, booking_id: int, reason: str) -> ServiceBooking:
    booking = db.get(ServiceBooking, booking_id)
    if booking is None:
        raise LeisureError("الحجز غير موجود", "Booking not found", "not_found")
    if booking.folio_line_id is not None:
        raise LeisureError(
            "الحجز اترحّل على الحساب — الغي الحركة من الفوليو",
            "Already posted — void the folio charge instead",
            "posted",
        )
    if not reason.strip():
        raise LeisureError("سبب الإلغاء مطلوب", "A reason is required", "no_reason")
    booking.status = ServiceBookingStatus.CANCELLED
    booking.cancelled_reason = reason.strip()[:300]
    db.flush()
    return booking


def no_show(db: Session, booking_id: int) -> ServiceBooking:
    booking = _live_booking(db, booking_id)
    booking.status = ServiceBookingStatus.NO_SHOW
    db.flush()
    return booking


def _live_booking(db: Session, booking_id: int) -> ServiceBooking:
    booking = db.get(ServiceBooking, booking_id)
    if booking is None:
        raise LeisureError("الحجز غير موجود", "Booking not found", "not_found")
    if booking.status in (
        ServiceBookingStatus.CANCELLED,
        ServiceBookingStatus.COMPLETED,
        ServiceBookingStatus.NO_SHOW,
    ):
        raise LeisureError("الحجز اتقفل خلاص", "Booking is closed", "closed")
    return booking


# ═══════════════════════════════════════════════════════ لوحة اليوم
@dataclass(slots=True)
class LeisureBoard:
    business_date: date
    bookings: int = 0
    confirmed: int = 0
    checked_in: int = 0
    completed: int = 0
    cancelled: int = 0
    no_shows: int = 0
    guests: int = 0
    revenue: Decimal = Decimal("0")
    posted: Decimal = Decimal("0")
    utilisation: dict[str, int] = field(default_factory=dict)


def board(db: Session, property_id: int, business_date: date | None = None) -> LeisureBoard:
    business_date = business_date or date.today()
    rows = db.execute(
        select(ServiceBooking).where(
            ServiceBooking.property_id == property_id,
            ServiceBooking.business_date == business_date,
        )
    ).scalars().all()

    result = LeisureBoard(business_date=business_date, bookings=len(rows))
    for booking in rows:
        match booking.status:
            case ServiceBookingStatus.CONFIRMED | ServiceBookingStatus.REQUESTED:
                result.confirmed += 1
            case ServiceBookingStatus.CHECKED_IN:
                result.checked_in += 1
            case ServiceBookingStatus.COMPLETED:
                result.completed += 1
            case ServiceBookingStatus.CANCELLED:
                result.cancelled += 1
            case ServiceBookingStatus.NO_SHOW:
                result.no_shows += 1
        if booking.status != ServiceBookingStatus.CANCELLED:
            result.guests += booking.adults + booking.children
            result.revenue += booking.total
        if booking.folio_line_id is not None:
            result.posted += booking.total
        if booking.resource_id:
            key = str(booking.resource_id)
            result.utilisation[key] = result.utilisation.get(key, 0) + int(
                (booking.end_at - booking.start_at).total_seconds() // 60
            )

    result.revenue = money(result.revenue)
    result.posted = money(result.posted)
    return result


# ═══════════════════════════════════════════════════════ المناسبات
def venue_conflicts(
    db: Session,
    venue_id: int,
    start_at: datetime,
    end_at: datetime,
    *,
    exclude_event_id: int | None = None,
) -> list[EventBooking]:
    """المناسبات اللي بتقفل المكان في الفترة دي.

    ``INQUIRY`` مش منها عن قصد: الاستعلام مبيقفلش قاعة. لو قفلها،
    القرية هتخسر شغل حقيقي عشان مكالمة مالهاش أي التزام وراها.
    """
    query = select(EventBooking).where(
        EventBooking.venue_id == venue_id,
        EventBooking.status.in_(list(BLOCKING_EVENT_STATUSES)),
        EventBooking.start_at < end_at,
        EventBooking.end_at > start_at,
    )
    if exclude_event_id is not None:
        query = query.where(EventBooking.id != exclude_event_id)
    return list(db.execute(query.order_by(EventBooking.start_at)).scalars().all())


def create_event(
    db: Session,
    property_id: int,
    *,
    venue_id: int,
    title: str,
    client_name: str,
    start_at: datetime,
    end_at: datetime,
    kind: EventKind = EventKind.OTHER,
    status: EventStatus = EventStatus.INQUIRY,
    pax: int = 0,
    package_per_person: Decimal | None = None,
    guest_id: int | None = None,
    company_id: int | None = None,
    client_phone: str | None = None,
    client_email: str | None = None,
    notes: str | None = None,
    user: User | None = None,
) -> EventBooking:
    venue = db.get(Venue, venue_id)
    if venue is None or venue.property_id != property_id or not venue.is_active:
        raise LeisureError("المكان غير موجود", "Venue not found", "not_found")
    if not title.strip():
        raise LeisureError("عنوان المناسبة مطلوب", "A title is required", "no_title")
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    if end_at <= start_at:
        raise LeisureError(
            "وقت النهاية لازم بعد البداية", "End must be after start", "bad_range"
        )

    capacity = max(venue.capacity_seated, venue.capacity_standing)
    if pax and capacity and pax > capacity:
        raise LeisureError(
            f"{venue.name_ar} بتاخد {capacity} فرد كحد أقصى",
            f"{venue.name_en} holds a maximum of {capacity}",
            "over_capacity",
        )

    if status in BLOCKING_EVENT_STATUSES:
        clashes = venue_conflicts(db, venue_id, start_at, end_at)
        if clashes:
            raise LeisureError(
                f"المكان محجوز — {clashes[0].number} «{clashes[0].title}»",
                f"Venue already booked — {clashes[0].number}",
                "conflict",
            )

    event = EventBooking(
        number=sequences.next_number(db, property_id, "EVENT"),
        property_id=property_id,
        venue_id=venue_id,
        title=title.strip()[:250],
        kind=kind,
        status=status,
        guest_id=guest_id,
        company_id=company_id,
        client_name=client_name.strip()[:250] or "—",
        client_phone=client_phone,
        client_email=client_email,
        start_at=start_at,
        end_at=end_at,
        event_date=start_at.date(),
        pax=pax,
        package_per_person=money(package_per_person or Decimal("0")),
        venue_charge=money(venue.day_rate),
        notes=(notes or "").strip()[:1500] or None,
        option_until=(
            date.today() + timedelta(days=DEFAULT_OPTION_DAYS)
            if status == EventStatus.TENTATIVE
            else None
        ),
        created_by_user_id=user.id if user else None,
    )
    db.add(event)
    db.flush()
    recalculate_event(db, event)
    return event


def add_item(
    db: Session,
    event_id: int,
    *,
    kind: EventItemKind,
    description_ar: str,
    quantity: Decimal,
    unit_price: Decimal,
    description_en: str | None = None,
    is_complimentary: bool = False,
    note: str | None = None,
) -> EventItem:
    event = db.get(EventBooking, event_id)
    if event is None:
        raise LeisureError("المناسبة غير موجودة", "Event not found", "not_found")
    if event.status in (EventStatus.CANCELLED, EventStatus.LOST, EventStatus.COMPLETED):
        raise LeisureError("المناسبة مقفولة", "Event is closed", "closed")
    if not description_ar.strip():
        raise LeisureError("وصف البند مطلوب", "A description is required", "no_description")

    item = EventItem(
        event_id=event.id,
        kind=kind,
        description_ar=description_ar.strip()[:300],
        description_en=(description_en or "").strip()[:300] or None,
        quantity=quantity,
        unit_price=money(unit_price),
        total=Decimal("0") if is_complimentary else money(quantity * unit_price),
        is_complimentary=is_complimentary,
        note=(note or "").strip()[:300] or None,
        sort_order=len(event.items),
    )
    db.add(item)
    db.flush()
    recalculate_event(db, event)
    return item


def remove_item(db: Session, item_id: int) -> EventBooking:
    item = db.get(EventItem, item_id)
    if item is None:
        raise LeisureError("البند غير موجود", "Item not found", "not_found")
    event = db.get(EventBooking, item.event_id)
    db.delete(item)
    db.flush()
    if event is not None:
        db.refresh(event)
        recalculate_event(db, event)
    return event


def recalculate_event(db: Session, event: EventBooking) -> EventBooking:
    """يبني إجمالي المناسبة من بنودها.

    الإجمالي **محسوب** مش مكتوب. أي بند بيتضاف أو يتشال بيغيّره لوحده،
    فمستحيل ورقة التشغيل تقول حاجة والفاتورة تقول حاجة تانية.
    """
    prop = db.get(Property, event.property_id)
    service_percent = prop.service_charge_percent if prop else Decimal("12")
    vat_percent = prop.vat_percent if prop else Decimal("14")

    items = db.execute(
        select(EventItem).where(EventItem.event_id == event.id)
    ).scalars().all()

    event.items_total = money(sum((i.total for i in items), Decimal("0")))
    package = money(event.package_per_person * event.pax)
    event.subtotal = money(event.venue_charge + event.items_total + package)

    # الحد الأدنى للإنفاق: لو الإجمالي أقل منه، الفرق بيتحسب على المكان.
    # ده مش عقاب — ده تسعير القاعة الحقيقي؛ اليوم في قاعة الأفراح ليه
    # تكلفة فرصة بديلة مش إيجار.
    venue = db.get(Venue, event.venue_id)
    if venue is not None and venue.minimum_spend > 0 and event.subtotal < venue.minimum_spend:
        event.venue_charge = money(
            event.venue_charge + (venue.minimum_spend - event.subtotal)
        )
        event.subtotal = money(venue.minimum_spend)

    event.service_charge = money(event.subtotal * service_percent / 100)
    event.tax = money((event.subtotal + event.service_charge) * vat_percent / 100)
    event.grand_total = money(event.subtotal + event.service_charge + event.tax)
    if event.deposit_required == 0:
        event.deposit_required = money(event.grand_total * DEFAULT_DEPOSIT_PERCENT / 100)

    db.flush()
    return event


def set_event_status(
    db: Session,
    event_id: int,
    status: EventStatus,
    *,
    reason: str | None = None,
) -> EventBooking:
    """نقل المناسبة لحالة تانية — مع فحص التعارض عند القفل."""
    event = db.get(EventBooking, event_id)
    if event is None:
        raise LeisureError("المناسبة غير موجودة", "Event not found", "not_found")

    if status in BLOCKING_EVENT_STATUSES and event.status not in BLOCKING_EVENT_STATUSES:
        clashes = venue_conflicts(
            db, event.venue_id, event.start_at, event.end_at, exclude_event_id=event.id
        )
        if clashes:
            raise LeisureError(
                f"المكان اتحجز في الوقت ده — {clashes[0].number}",
                f"Venue was taken — {clashes[0].number}",
                "conflict",
            )

    if status == EventStatus.CONFIRMED and event.deposit_paid < event.deposit_required:
        raise LeisureError(
            f"العربون المطلوب {event.deposit_required} ولسه اتدفع {event.deposit_paid}",
            f"Deposit of {event.deposit_required} required, {event.deposit_paid} paid",
            "deposit_due",
        )

    if status in (EventStatus.CANCELLED, EventStatus.LOST) and not (reason or "").strip():
        raise LeisureError("السبب مطلوب", "A reason is required", "no_reason")

    event.status = status
    if status == EventStatus.CANCELLED:
        event.cancelled_reason = (reason or "").strip()[:300]
    elif status == EventStatus.LOST:
        event.lost_reason = (reason or "").strip()[:300]
    elif status == EventStatus.TENTATIVE and event.option_until is None:
        event.option_until = date.today() + timedelta(days=DEFAULT_OPTION_DAYS)
    elif status == EventStatus.CONFIRMED:
        event.option_until = None

    db.flush()
    return event


def record_deposit(db: Session, event_id: int, amount: Decimal) -> EventBooking:
    event = db.get(EventBooking, event_id)
    if event is None:
        raise LeisureError("المناسبة غير موجودة", "Event not found", "not_found")
    if amount <= 0:
        raise LeisureError("المبلغ لازم أكبر من صفر", "Amount must be positive", "bad_amount")
    event.deposit_paid = money(event.deposit_paid + amount)
    db.flush()
    return event


def release_expired_options(db: Session, property_id: int, today: date | None = None) -> int:
    """يفك الحجوزات المبدئية اللي فات ميعاد عربونها.

    من غير الخطوة دي، القاعة بتفضل مقفولة على وعد قديم — والقرية
    بتقول «محجوزة» لعميل جاهز يدفع.
    """
    today = today or date.today()
    stale = db.execute(
        select(EventBooking).where(
            EventBooking.property_id == property_id,
            EventBooking.status == EventStatus.TENTATIVE,
            EventBooking.option_until.isnot(None),
            EventBooking.option_until < today,
        )
    ).scalars().all()
    for event in stale:
        event.status = EventStatus.LOST
        event.lost_reason = "فات ميعاد العربون والحجز المبدئي اتفك تلقائياً"
    db.flush()
    return len(stale)


@dataclass(slots=True)
class EventsBoard:
    inquiries: int = 0
    tentative: int = 0
    confirmed: int = 0
    completed: int = 0
    lost: int = 0
    cancelled: int = 0
    pax_confirmed: int = 0
    pipeline_value: Decimal = Decimal("0")
    confirmed_value: Decimal = Decimal("0")
    deposits_due: Decimal = Decimal("0")
    options_expiring: int = 0


def events_board(
    db: Session, property_id: int, *, since: date | None = None
) -> EventsBoard:
    since = since or date.today() - timedelta(days=90)
    rows = db.execute(
        select(EventBooking).where(
            EventBooking.property_id == property_id,
            EventBooking.event_date >= since,
        )
    ).scalars().all()

    result = EventsBoard()
    soon = date.today() + timedelta(days=7)
    for event in rows:
        match event.status:
            case EventStatus.INQUIRY:
                result.inquiries += 1
                result.pipeline_value += event.grand_total
            case EventStatus.TENTATIVE:
                result.tentative += 1
                result.pipeline_value += event.grand_total
                if event.option_until and event.option_until <= soon:
                    result.options_expiring += 1
            case EventStatus.CONFIRMED | EventStatus.RUNNING:
                result.confirmed += 1
                result.confirmed_value += event.grand_total
                result.pax_confirmed += event.pax
                result.deposits_due += max(
                    Decimal("0"), event.deposit_required - event.deposit_paid
                )
            case EventStatus.COMPLETED:
                result.completed += 1
                result.confirmed_value += event.grand_total
                result.pax_confirmed += event.pax
            case EventStatus.LOST:
                result.lost += 1
            case EventStatus.CANCELLED:
                result.cancelled += 1

    result.pipeline_value = money(result.pipeline_value)
    result.confirmed_value = money(result.confirmed_value)
    result.deposits_due = money(result.deposits_due)
    return result


def upcoming_events(
    db: Session, property_id: int, *, days: int = 60, limit: int = 100
) -> list[tuple[EventBooking, Venue]]:
    today = date.today()
    return list(
        db.execute(
            select(EventBooking, Venue)
            .join(Venue, Venue.id == EventBooking.venue_id)
            .where(
                EventBooking.property_id == property_id,
                EventBooking.event_date >= today - timedelta(days=7),
                EventBooking.event_date <= today + timedelta(days=days),
            )
            .order_by(EventBooking.start_at)
            .limit(limit)
        ).all()
    )


def day_bookings(
    db: Session, property_id: int, business_date: date
) -> list[tuple[ServiceBooking, Service, ServiceResourceItem | None]]:
    rows = db.execute(
        select(ServiceBooking, Service)
        .join(Service, Service.id == ServiceBooking.service_id)
        .where(
            ServiceBooking.property_id == property_id,
            ServiceBooking.business_date == business_date,
        )
        .order_by(ServiceBooking.start_at, ServiceBooking.id)
    ).all()

    resources = {
        r.id: r
        for r in db.execute(
            select(ServiceResourceItem).where(
                ServiceResourceItem.property_id == property_id
            )
        ).scalars().all()
    }
    return [(b, s, resources.get(b.resource_id or 0)) for b, s in rows]
