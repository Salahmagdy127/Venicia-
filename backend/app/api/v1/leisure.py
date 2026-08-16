"""واجهات السبا والأنشطة والمناسبات — Spa, activities & events endpoints."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import (
    EventItemKind,
    EventKind,
    EventStatus,
    ResourceKind,
    ServiceBookingStatus,
    ServiceCategory,
    VenueKind,
)
from app.models.leisure import (
    EventBooking,
    EventItem,
    Service,
    ServiceBooking,
    ServiceResourceItem,
    Venue,
)
from app.schemas.common import ApiModel
from app.services import leisure as lz

router = APIRouter(tags=["السبا والمناسبات — Leisure & Events"])


# ═══════════════════════════════════════════════════════════ النماذج
class ResourceOut(ApiModel):
    id: int
    code: str
    kind: ResourceKind
    name_ar: str
    name_en: str
    capacity: int
    shift_start: time | None = None
    shift_end: time | None = None
    is_active: bool


class ServiceOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    category: ServiceCategory
    duration_minutes: int
    buffer_minutes: int
    price: Decimal
    price_child: Decimal
    unit_cost: Decimal
    capacity: int
    requires_resource: bool
    opens_at: time | None = None
    closes_at: time | None = None
    description_ar: str | None = None
    description_en: str | None = None
    is_active: bool
    resources: list[ResourceOut] = []
    #: هامش الربح — بيبان للإدارة عشان تعرف تسعّر
    margin_percent: Decimal = Decimal("0")


class SlotOut(ApiModel):
    start_at: datetime
    end_at: datetime
    resource_id: int
    resource_name: str
    seats_left: int


class BookingOut(ApiModel):
    id: int
    number: str
    service_id: int
    service_name_ar: str
    category: ServiceCategory
    resource_id: int | None = None
    resource_name: str | None = None
    guest_id: int | None = None
    guest_name: str
    folio_id: int | None = None
    start_at: datetime
    end_at: datetime
    business_date: date
    status: ServiceBookingStatus
    adults: int
    children: int
    unit_price: Decimal
    total: Decimal
    is_posted: bool = False
    notes: str | None = None
    cancelled_reason: str | None = None


class LeisureBoardOut(ApiModel):
    business_date: date
    bookings: int
    confirmed: int
    checked_in: int
    completed: int
    cancelled: int
    no_shows: int
    guests: int
    revenue: Decimal
    posted: Decimal
    rows: list[BookingOut]


class BookIn(ApiModel):
    service_id: int
    start_at: datetime
    guest_name: str
    resource_id: int | None = None
    guest_id: int | None = None
    folio_id: int | None = None
    reservation_id: int | None = None
    adults: int = 1
    children: int = 0
    notes: str | None = None
    price_override: Decimal | None = None


class RescheduleIn(ApiModel):
    start_at: datetime
    resource_id: int | None = None


class ReasonIn(ApiModel):
    reason: str


def _service_out(service: Service) -> ServiceOut:
    margin = Decimal("0")
    if service.price > 0:
        margin = ((service.price - service.unit_cost) / service.price * 100).quantize(
            Decimal("0.01")
        )
    return ServiceOut(
        id=service.id, code=service.code, name_ar=service.name_ar,
        name_en=service.name_en, category=service.category,
        duration_minutes=service.duration_minutes,
        buffer_minutes=service.buffer_minutes,
        price=service.price, price_child=service.price_child,
        unit_cost=service.unit_cost, capacity=service.capacity,
        requires_resource=service.requires_resource,
        opens_at=service.opens_at, closes_at=service.closes_at,
        description_ar=service.description_ar, description_en=service.description_en,
        is_active=service.is_active,
        resources=[
            ResourceOut(
                id=r.id, code=r.code, kind=r.kind, name_ar=r.name_ar,
                name_en=r.name_en, capacity=r.capacity,
                shift_start=r.shift_start, shift_end=r.shift_end, is_active=r.is_active,
            )
            for r in service.resources
        ],
        margin_percent=margin,
    )


def _booking_out(
    booking: ServiceBooking, service: Service, resource: ServiceResourceItem | None
) -> BookingOut:
    return BookingOut(
        id=booking.id, number=booking.number, service_id=booking.service_id,
        service_name_ar=service.name_ar, category=service.category,
        resource_id=booking.resource_id,
        resource_name=resource.name_ar if resource else None,
        guest_id=booking.guest_id, guest_name=booking.guest_name,
        folio_id=booking.folio_id, start_at=booking.start_at, end_at=booking.end_at,
        business_date=booking.business_date, status=booking.status,
        adults=booking.adults, children=booking.children,
        unit_price=booking.unit_price, total=booking.total,
        is_posted=booking.folio_line_id is not None,
        notes=booking.notes, cancelled_reason=booking.cancelled_reason,
    )


def _fail(error: lz.LeisureError) -> HTTPException:
    status = 404 if error.code == "not_found" else 409 if error.code == "conflict" else 400
    return HTTPException(
        status, {"ar": error.message_ar, "en": error.message_en, "code": error.code}
    )


# ═══════════════════════════════════════════════════════ الكتالوج
@router.get(
    "/services",
    response_model=list[ServiceOut],
    summary="الخدمات",
    dependencies=[Depends(require("leisure.view"))],
)
def services(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    category: ServiceCategory | None = None,
    active_only: bool = True,
) -> list[ServiceOut]:
    query = select(Service).where(Service.property_id == prop.id)
    if category:
        query = query.where(Service.category == category)
    if active_only:
        query = query.where(Service.is_active.is_(True))
    rows = db.execute(query.order_by(Service.category, Service.sort_order)).scalars().all()
    return [_service_out(s) for s in rows]


@router.get(
    "/services/resources",
    response_model=list[ResourceOut],
    summary="الموارد (معالجين وقوارب وكابائن)",
    dependencies=[Depends(require("leisure.view"))],
)
def resources(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[ResourceOut]:
    rows = db.execute(
        select(ServiceResourceItem)
        .where(ServiceResourceItem.property_id == prop.id)
        .order_by(ServiceResourceItem.kind, ServiceResourceItem.name_ar)
    ).scalars().all()
    return [
        ResourceOut(
            id=r.id, code=r.code, kind=r.kind, name_ar=r.name_ar, name_en=r.name_en,
            capacity=r.capacity, shift_start=r.shift_start, shift_end=r.shift_end,
            is_active=r.is_active,
        )
        for r in rows
    ]


@router.get(
    "/services/{service_id}/slots",
    response_model=list[SlotOut],
    summary="المواعيد الفاضية",
    dependencies=[Depends(require("leisure.view"))],
)
def slots(
    service_id: int,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    day: date = Query(default_factory=date.today, alias="date"),
) -> list[SlotOut]:
    try:
        found = lz.open_slots(db, prop.id, service_id, day)
    except lz.LeisureError as error:
        raise _fail(error)
    return [
        SlotOut(
            start_at=s.start_at, end_at=s.end_at, resource_id=s.resource_id,
            resource_name=s.resource_name, seats_left=s.seats_left,
        )
        for s in found
    ]


# ═══════════════════════════════════════════════════════ الحجوزات
@router.get(
    "/leisure/board",
    response_model=LeisureBoardOut,
    summary="لوحة السبا والأنشطة",
    dependencies=[Depends(require("leisure.view"))],
)
def leisure_board(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    business_date: date = Query(default_factory=date.today, alias="date"),
) -> LeisureBoardOut:
    summary = lz.board(db, prop.id, business_date)
    rows = lz.day_bookings(db, prop.id, business_date)
    return LeisureBoardOut(
        business_date=summary.business_date,
        bookings=summary.bookings, confirmed=summary.confirmed,
        checked_in=summary.checked_in, completed=summary.completed,
        cancelled=summary.cancelled, no_shows=summary.no_shows,
        guests=summary.guests, revenue=summary.revenue, posted=summary.posted,
        rows=[_booking_out(b, s, r) for b, s, r in rows],
    )


@router.post(
    "/leisure/bookings",
    response_model=BookingOut,
    summary="حجز موعد",
    dependencies=[Depends(require("leisure.book"))],
)
def create_booking(
    payload: BookIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> BookingOut:
    try:
        booking = lz.book_service(
            db, prop.id,
            service_id=payload.service_id,
            start_at=payload.start_at,
            guest_name=payload.guest_name,
            resource_id=payload.resource_id,
            guest_id=payload.guest_id,
            folio_id=payload.folio_id,
            reservation_id=payload.reservation_id,
            adults=payload.adults,
            children=payload.children,
            notes=payload.notes,
            user=user,
            price_override=payload.price_override,
        )
    except lz.LeisureError as error:
        raise _fail(error)

    service = db.get(Service, booking.service_id)
    resource = db.get(ServiceResourceItem, booking.resource_id) if booking.resource_id else None
    return _booking_out(booking, service, resource)


def _reload(db, booking: ServiceBooking) -> BookingOut:
    service = db.get(Service, booking.service_id)
    resource = db.get(ServiceResourceItem, booking.resource_id) if booking.resource_id else None
    return _booking_out(booking, service, resource)


@router.patch(
    "/leisure/bookings/{booking_id}/reschedule",
    response_model=BookingOut,
    summary="نقل الموعد",
    dependencies=[Depends(require("leisure.book"))],
)
def move_booking(
    booking_id: int,
    payload: RescheduleIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> BookingOut:
    try:
        booking = lz.reschedule(
            db, booking_id, payload.start_at, resource_id=payload.resource_id
        )
    except lz.LeisureError as error:
        raise _fail(error)
    return _reload(db, booking)


@router.post(
    "/leisure/bookings/{booking_id}/check-in",
    response_model=BookingOut,
    summary="حضور النزيل",
    dependencies=[Depends(require("leisure.book"))],
)
def booking_check_in(
    booking_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> BookingOut:
    try:
        booking = lz.check_in(db, booking_id)
    except lz.LeisureError as error:
        raise _fail(error)
    return _reload(db, booking)


@router.post(
    "/leisure/bookings/{booking_id}/complete",
    response_model=BookingOut,
    summary="إنهاء الموعد وترحيله",
    dependencies=[Depends(require("leisure.book"))],
)
def booking_complete(
    booking_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> BookingOut:
    try:
        booking = lz.complete(db, booking_id, user=user)
    except lz.LeisureError as error:
        raise _fail(error)
    return _reload(db, booking)


@router.post(
    "/leisure/bookings/{booking_id}/no-show",
    response_model=BookingOut,
    summary="لم يحضر",
    dependencies=[Depends(require("leisure.book"))],
)
def booking_no_show(
    booking_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> BookingOut:
    try:
        booking = lz.no_show(db, booking_id)
    except lz.LeisureError as error:
        raise _fail(error)
    return _reload(db, booking)


@router.post(
    "/leisure/bookings/{booking_id}/cancel",
    response_model=BookingOut,
    summary="إلغاء الموعد",
    dependencies=[Depends(require("leisure.book"))],
)
def booking_cancel(
    booking_id: int,
    payload: ReasonIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> BookingOut:
    try:
        booking = lz.cancel(db, booking_id, payload.reason)
    except lz.LeisureError as error:
        raise _fail(error)
    return _reload(db, booking)


# ═══════════════════════════════════════════════════════ المناسبات
class VenueOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    kind: VenueKind
    capacity_seated: int
    capacity_standing: int
    area_sqm: int | None = None
    day_rate: Decimal
    hourly_rate: Decimal
    minimum_spend: Decimal
    description_ar: str | None = None
    is_active: bool


class EventItemOut(ApiModel):
    id: int
    kind: EventItemKind
    description_ar: str
    description_en: str | None = None
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    is_complimentary: bool
    note: str | None = None


class EventOut(ApiModel):
    id: int
    number: str
    venue_id: int
    venue_name_ar: str
    title: str
    kind: EventKind
    status: EventStatus
    client_name: str
    client_phone: str | None = None
    client_email: str | None = None
    guest_id: int | None = None
    company_id: int | None = None
    start_at: datetime
    end_at: datetime
    event_date: date
    pax: int
    package_per_person: Decimal
    venue_charge: Decimal
    items_total: Decimal
    subtotal: Decimal
    service_charge: Decimal
    tax: Decimal
    grand_total: Decimal
    deposit_required: Decimal
    deposit_paid: Decimal
    deposit_outstanding: Decimal
    option_until: date | None = None
    notes: str | None = None
    setup_notes: str | None = None
    lost_reason: str | None = None
    cancelled_reason: str | None = None
    items: list[EventItemOut] = []


class EventsBoardOut(ApiModel):
    inquiries: int
    tentative: int
    confirmed: int
    completed: int
    lost: int
    cancelled: int
    pax_confirmed: int
    pipeline_value: Decimal
    confirmed_value: Decimal
    deposits_due: Decimal
    options_expiring: int
    #: نسبة التحويل من استعلام لمناسبة مؤكدة — أهم رقم في قسم المبيعات
    win_rate_percent: Decimal
    events: list[EventOut]


class CreateEventIn(ApiModel):
    venue_id: int
    title: str
    client_name: str
    start_at: datetime
    end_at: datetime
    kind: EventKind = EventKind.OTHER
    status: EventStatus = EventStatus.INQUIRY
    pax: int = 0
    package_per_person: Decimal = Decimal("0")
    guest_id: int | None = None
    company_id: int | None = None
    client_phone: str | None = None
    client_email: str | None = None
    notes: str | None = None


class AddItemIn(ApiModel):
    kind: EventItemKind
    description_ar: str
    description_en: str | None = None
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    is_complimentary: bool = False
    note: str | None = None


class StatusIn(ApiModel):
    status: EventStatus
    reason: str | None = None


class DepositIn(ApiModel):
    amount: Decimal


def _event_out(event: EventBooking, venue: Venue) -> EventOut:
    return EventOut(
        id=event.id, number=event.number, venue_id=event.venue_id,
        venue_name_ar=venue.name_ar, title=event.title, kind=event.kind,
        status=event.status, client_name=event.client_name,
        client_phone=event.client_phone, client_email=event.client_email,
        guest_id=event.guest_id, company_id=event.company_id,
        start_at=event.start_at, end_at=event.end_at, event_date=event.event_date,
        pax=event.pax, package_per_person=event.package_per_person,
        venue_charge=event.venue_charge, items_total=event.items_total,
        subtotal=event.subtotal, service_charge=event.service_charge, tax=event.tax,
        grand_total=event.grand_total, deposit_required=event.deposit_required,
        deposit_paid=event.deposit_paid,
        deposit_outstanding=max(
            Decimal("0"), event.deposit_required - event.deposit_paid
        ),
        option_until=event.option_until, notes=event.notes,
        setup_notes=event.setup_notes, lost_reason=event.lost_reason,
        cancelled_reason=event.cancelled_reason,
        items=[
            EventItemOut(
                id=i.id, kind=i.kind, description_ar=i.description_ar,
                description_en=i.description_en, quantity=i.quantity,
                unit_price=i.unit_price, total=i.total,
                is_complimentary=i.is_complimentary, note=i.note,
            )
            for i in sorted(event.items, key=lambda x: (x.sort_order, x.id))
        ],
    )


@router.get(
    "/venues",
    response_model=list[VenueOut],
    summary="أماكن المناسبات",
    dependencies=[Depends(require("leisure.view"))],
)
def venues(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[VenueOut]:
    rows = db.execute(
        select(Venue).where(Venue.property_id == prop.id).order_by(Venue.sort_order)
    ).scalars().all()
    return [
        VenueOut(
            id=v.id, code=v.code, name_ar=v.name_ar, name_en=v.name_en, kind=v.kind,
            capacity_seated=v.capacity_seated, capacity_standing=v.capacity_standing,
            area_sqm=v.area_sqm, day_rate=v.day_rate, hourly_rate=v.hourly_rate,
            minimum_spend=v.minimum_spend, description_ar=v.description_ar,
            is_active=v.is_active,
        )
        for v in rows
    ]


@router.get(
    "/events",
    response_model=EventsBoardOut,
    summary="لوحة المناسبات",
    dependencies=[Depends(require("leisure.view"))],
)
def events(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    days: int = Query(default=90, ge=1, le=730),
) -> EventsBoardOut:
    summary = lz.events_board(db, prop.id)
    rows = lz.upcoming_events(db, prop.id, days=days)

    decided = summary.confirmed + summary.completed + summary.lost
    win_rate = (
        (Decimal(summary.confirmed + summary.completed) / Decimal(decided) * 100).quantize(
            Decimal("0.1")
        )
        if decided
        else Decimal("0")
    )

    return EventsBoardOut(
        inquiries=summary.inquiries, tentative=summary.tentative,
        confirmed=summary.confirmed, completed=summary.completed,
        lost=summary.lost, cancelled=summary.cancelled,
        pax_confirmed=summary.pax_confirmed, pipeline_value=summary.pipeline_value,
        confirmed_value=summary.confirmed_value, deposits_due=summary.deposits_due,
        options_expiring=summary.options_expiring, win_rate_percent=win_rate,
        events=[_event_out(e, v) for e, v in rows],
    )


@router.post(
    "/events",
    response_model=EventOut,
    summary="مناسبة جديدة",
    dependencies=[Depends(require("leisure.manage"))],
)
def new_event(
    payload: CreateEventIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> EventOut:
    try:
        event = lz.create_event(
            db, prop.id,
            venue_id=payload.venue_id, title=payload.title,
            client_name=payload.client_name, start_at=payload.start_at,
            end_at=payload.end_at, kind=payload.kind, status=payload.status,
            pax=payload.pax, package_per_person=payload.package_per_person,
            guest_id=payload.guest_id, company_id=payload.company_id,
            client_phone=payload.client_phone, client_email=payload.client_email,
            notes=payload.notes, user=user,
        )
    except lz.LeisureError as error:
        raise _fail(error)
    return _event_out(event, db.get(Venue, event.venue_id))


@router.get(
    "/events/{event_id}",
    response_model=EventOut,
    summary="ورقة تشغيل المناسبة",
    dependencies=[Depends(require("leisure.view"))],
)
def event_detail(
    event_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> EventOut:
    event = db.get(EventBooking, event_id)
    if event is None or event.property_id != prop.id:
        raise HTTPException(404, {"ar": "المناسبة غير موجودة", "en": "Event not found"})
    return _event_out(event, db.get(Venue, event.venue_id))


@router.post(
    "/events/{event_id}/items",
    response_model=EventOut,
    summary="إضافة بند",
    dependencies=[Depends(require("leisure.manage"))],
)
def add_event_item(
    event_id: int,
    payload: AddItemIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> EventOut:
    try:
        lz.add_item(
            db, event_id, kind=payload.kind,
            description_ar=payload.description_ar,
            description_en=payload.description_en,
            quantity=payload.quantity, unit_price=payload.unit_price,
            is_complimentary=payload.is_complimentary, note=payload.note,
        )
    except lz.LeisureError as error:
        raise _fail(error)
    event = db.get(EventBooking, event_id)
    db.refresh(event)
    return _event_out(event, db.get(Venue, event.venue_id))


@router.delete(
    "/events/{event_id}/items/{item_id}",
    response_model=EventOut,
    summary="حذف بند",
    dependencies=[Depends(require("leisure.manage"))],
)
def delete_event_item(
    event_id: int,
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> EventOut:
    item = db.get(EventItem, item_id)
    if item is None or item.event_id != event_id:
        raise HTTPException(404, {"ar": "البند غير موجود", "en": "Item not found"})
    try:
        lz.remove_item(db, item_id)
    except lz.LeisureError as error:
        raise _fail(error)
    event = db.get(EventBooking, event_id)
    db.refresh(event)
    return _event_out(event, db.get(Venue, event.venue_id))


@router.patch(
    "/events/{event_id}/status",
    response_model=EventOut,
    summary="تغيير حالة المناسبة",
    dependencies=[Depends(require("leisure.manage"))],
)
def change_event_status(
    event_id: int,
    payload: StatusIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> EventOut:
    try:
        event = lz.set_event_status(db, event_id, payload.status, reason=payload.reason)
    except lz.LeisureError as error:
        raise _fail(error)
    return _event_out(event, db.get(Venue, event.venue_id))


@router.post(
    "/events/{event_id}/deposit",
    response_model=EventOut,
    summary="تسجيل عربون",
    dependencies=[Depends(require("leisure.manage"))],
)
def event_deposit(
    event_id: int,
    payload: DepositIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> EventOut:
    try:
        event = lz.record_deposit(db, event_id, payload.amount)
    except lz.LeisureError as error:
        raise _fail(error)
    return _event_out(event, db.get(Venue, event.venue_id))
