"""واجهات الحجز المباشر — Public booking engine.

المسارات دي **مفتوحة من غير تسجيل دخول** — دي صفحة الحجز على موقع القرية.
عشان كده كل رد هنا متقشّر: الزائر بيشوف المتاح للبيع وسعره وبس. مفيش
أرقام إشغال ولا بيانات نزلاء ولا أي حاجة داخلية.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.models.organization import Property
from app.models.units import UnitCategory
from app.schemas.common import ApiModel
from app.services import booking_engine as be

router = APIRouter(prefix="/book", tags=["الحجز المباشر — Booking Engine"])


def public_property(db: DbSession) -> Property:
    """المنشأة المعروضة على الموقع — أول منشأة، من غير تسجيل دخول."""
    prop = db.execute(select(Property).order_by(Property.id).limit(1)).scalar_one_or_none()
    if prop is None:
        raise HTTPException(
            status_code=404, detail={"ar": "مفيش منشأة", "en": "No property configured"}
        )
    return prop


PublicProperty = Depends(public_property)


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, be.BookingEngineError):
        code = 404 if exc.code == "not_found" else 409 if exc.code == "hold_expired" else 400
        return HTTPException(
            status_code=code,
            detail={"ar": exc.message_ar, "en": exc.message_en, "code": exc.code},
        )
    raise exc


# ═══════════════════════════════════════════════════════════ النماذج
class PublicCategory(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None
    kind: str
    base_occupancy: int
    max_occupancy: int
    area_sqm: int | None = None
    bed_configuration: str | None = None
    amenities_ar: str | None = None
    amenities_en: str | None = None
    from_rate: Decimal
    unit_count: int


class PublicProperty_(ApiModel):
    name_ar: str
    name_en: str
    city: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    currency: str
    check_in_time: str
    check_out_time: str
    vat_percent: Decimal
    service_charge_percent: Decimal
    categories: list[PublicCategory]


class NightPrice(ApiModel):
    stay_date: date
    rate: Decimal


class OfferOut(ApiModel):
    unit_category_id: int
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None
    kind: str
    max_occupancy: int
    area_sqm: int | None = None
    bed_configuration: str | None = None
    amenities_ar: str | None = None
    amenities_en: str | None = None
    nights: int
    room_total: Decimal
    service_charge_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    average_nightly_rate: Decimal
    #: عدد الوحدات الفاضلة — بيتقصّ عند 5 عشان مانكشفش المخزون الحقيقي
    left: int
    nights_detail: list[NightPrice]


class SearchOut(ApiModel):
    arrival_date: date
    departure_date: date
    nights: int
    adults: int
    children: int
    currency: str
    offers: list[OfferOut]


class HoldIn(ApiModel):
    unit_category_id: int
    arrival_date: date
    departure_date: date
    adults: int = 2
    children: int = 0


class HoldOut(ApiModel):
    token: str
    expires_at: datetime
    hold_minutes: int
    unit_category_id: int
    name_ar: str
    name_en: str
    arrival_date: date
    departure_date: date
    nights: int
    adults: int
    children: int
    room_total: Decimal
    service_charge_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    deposit_required: Decimal


class ConfirmIn(ApiModel):
    token: str
    first_name: str
    last_name: str
    phone: str
    email: str | None = None
    notes: str | None = None
    deposit_paid: Decimal = Decimal("0")


class BookingOut(ApiModel):
    code: str
    status: str
    guest_name: str
    arrival_date: date
    departure_date: date
    nights: int
    adults: int
    children: int
    category_name_ar: str
    category_name_en: str
    grand_total: Decimal
    paid_total: Decimal
    balance: Decimal
    check_in_time: str
    check_out_time: str
    special_requests: str | None = None


class LookupIn(ApiModel):
    code: str
    phone: str


class ReleaseIn(ApiModel):
    token: str


# ═══════════════════════════════════════════════════════════ القراءة
@router.get("/property", response_model=PublicProperty_, summary="بيانات القرية للعرض")
def get_property_info(db: DbSession, prop: Property = PublicProperty) -> PublicProperty_:
    try:
        prop, categories, counts = be.property_info(db, prop.id)
    except Exception as exc:
        raise _fail(exc) from exc

    return PublicProperty_(
        name_ar=prop.name_ar,
        name_en=prop.name_en,
        city=prop.city,
        address=prop.address,
        phone=prop.phone,
        email=prop.email,
        currency=prop.currency,
        check_in_time=prop.check_in_time,
        check_out_time=prop.check_out_time,
        vat_percent=prop.vat_percent,
        service_charge_percent=prop.service_charge_percent,
        categories=[
            PublicCategory(
                id=c.id,
                code=c.code,
                name_ar=c.name_ar,
                name_en=c.name_en,
                description_ar=c.description_ar,
                description_en=c.description_en,
                kind=c.kind,
                base_occupancy=c.base_occupancy,
                max_occupancy=c.max_occupancy,
                area_sqm=c.area_sqm,
                bed_configuration=c.bed_configuration,
                amenities_ar=c.amenities_ar,
                amenities_en=c.amenities_en,
                from_rate=c.base_rate,
                unit_count=counts.get(c.id, 0),
            )
            for c in categories
        ],
    )


@router.get("/search", response_model=SearchOut, summary="بحث عن إقامة")
def search(
    db: DbSession,
    arrival_date: date,
    departure_date: date,
    adults: int = Query(default=2, ge=1, le=12),
    children: int = Query(default=0, ge=0, le=8),
    prop: Property = PublicProperty,
) -> SearchOut:
    try:
        offers = be.search(
            db,
            prop.id,
            arrival=arrival_date,
            departure=departure_date,
            adults=adults,
            children=children,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    return SearchOut(
        arrival_date=arrival_date,
        departure_date=departure_date,
        nights=(departure_date - arrival_date).days,
        adults=adults,
        children=children,
        currency=prop.currency,
        offers=[
            OfferOut(
                unit_category_id=o.category.id,
                name_ar=o.category.name_ar,
                name_en=o.category.name_en,
                description_ar=o.category.description_ar,
                description_en=o.category.description_en,
                kind=o.category.kind,
                max_occupancy=o.category.max_occupancy,
                area_sqm=o.category.area_sqm,
                bed_configuration=o.category.bed_configuration,
                amenities_ar=o.category.amenities_ar,
                amenities_en=o.category.amenities_en,
                nights=o.quote.nights,
                room_total=o.quote.room_total,
                service_charge_total=o.quote.service_charge_total,
                tax_total=o.quote.tax_total,
                grand_total=o.quote.grand_total,
                average_nightly_rate=o.quote.average_nightly_rate,
                # المخزون الحقيقي مش من حق الزائر — بنعرض «فاضل قليل» وبس
                left=min(o.available, 5),
                nights_detail=[
                    NightPrice(stay_date=n.stay_date, rate=n.rate) for n in o.quote.nights_detail
                ],
            )
            for o in offers
        ],
    )


# ═══════════════════════════════════════════════════════════ السلة
@router.post("/hold", response_model=HoldOut, summary="احجز الوحدة مؤقتاً")
def create_hold(
    payload: HoldIn, db: DbSession, request: Request, prop: Property = PublicProperty
) -> HoldOut:
    try:
        reservation, token, expires = be.hold(
            db,
            prop.id,
            unit_category_id=payload.unit_category_id,
            arrival=payload.arrival_date,
            departure=payload.departure_date,
            adults=payload.adults,
            children=payload.children,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    category = db.get(UnitCategory, payload.unit_category_id)
    return HoldOut(
        token=token,
        expires_at=expires,
        hold_minutes=settings.BOOKING_HOLD_MINUTES,
        unit_category_id=payload.unit_category_id,
        name_ar=category.name_ar if category else "—",
        name_en=category.name_en if category else "—",
        arrival_date=reservation.arrival_date,
        departure_date=reservation.departure_date,
        nights=reservation.nights,
        adults=reservation.adults,
        children=reservation.children,
        room_total=reservation.room_total,
        service_charge_total=reservation.service_charge_total,
        tax_total=reservation.tax_total,
        grand_total=reservation.grand_total,
        deposit_required=reservation.deposit_required,
    )


@router.post("/release", summary="سيب السلة")
def release_hold(
    payload: ReleaseIn, db: DbSession, prop: Property = PublicProperty
) -> dict[str, bool]:
    try:
        be.release(db, prop.id, payload.token)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"ok": True}


@router.post("/confirm", response_model=BookingOut, summary="أكّد الحجز")
def confirm(
    payload: ConfirmIn, db: DbSession, prop: Property = PublicProperty
) -> BookingOut:
    try:
        reservation = be.confirm(
            db,
            prop.id,
            token=payload.token,
            first_name=payload.first_name,
            last_name=payload.last_name,
            phone=payload.phone,
            email=payload.email,
            notes=payload.notes,
            deposit_paid=payload.deposit_paid,
        )
    except Exception as exc:
        raise _fail(exc) from exc
    return _booking_out(db, prop, reservation)


@router.post("/lookup", response_model=BookingOut, summary="راجع حجزك")
def lookup(payload: LookupIn, db: DbSession, prop: Property = PublicProperty) -> BookingOut:
    try:
        reservation = be.lookup(db, prop.id, payload.code, payload.phone)
    except Exception as exc:
        raise _fail(exc) from exc
    return _booking_out(db, prop, reservation)


def _booking_out(db, prop: Property, reservation) -> BookingOut:
    from app.models.guests import Guest
    from app.models.reservations import ReservationUnit

    guest = db.get(Guest, reservation.guest_id)
    line = db.execute(
        select(ReservationUnit).where(ReservationUnit.reservation_id == reservation.id).limit(1)
    ).scalar_one_or_none()
    category = db.get(UnitCategory, line.unit_category_id) if line else None

    return BookingOut(
        code=reservation.code,
        status=reservation.status,
        guest_name=guest.full_name if guest else "—",
        arrival_date=reservation.arrival_date,
        departure_date=reservation.departure_date,
        nights=reservation.nights,
        adults=reservation.adults,
        children=reservation.children,
        category_name_ar=category.name_ar if category else "—",
        category_name_en=category.name_en if category else "—",
        grand_total=reservation.grand_total,
        paid_total=reservation.paid_total,
        balance=reservation.balance,
        check_in_time=prop.check_in_time,
        check_out_time=prop.check_out_time,
        special_requests=reservation.special_requests,
    )
