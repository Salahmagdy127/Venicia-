"""واجهات الربط بالقنوات — Channel manager endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.channels import Channel, ChannelBooking, ChannelMapping, ChannelMessage
from app.models.enums import (
    AuditAction,
    BookingSource,
    ChannelBookingAction,
    ChannelBookingStatus,
    ChannelMessageKind,
    ChannelMessageStatus,
)
from app.models.rates import RatePlan
from app.models.units import UnitCategory
from app.schemas.common import ApiModel
from app.services import audit
from app.services import channel_sync as cs

router = APIRouter(prefix="/channels", tags=["الربط بالقنوات — Channel Manager"])


# ═══════════════════════════════════════════════════════════ النماذج
class MappingOut(ApiModel):
    id: int
    unit_category_id: int
    category_name_ar: str
    category_name_en: str
    rate_plan_id: int | None = None
    rate_plan_name_ar: str | None = None
    external_room_id: str
    external_rate_id: str | None = None
    allocation: int
    is_active: bool


class ChannelOut(ApiModel):
    id: int
    source: BookingSource
    name_ar: str
    name_en: str
    is_active: bool
    is_connected: bool
    commission_percent: Decimal
    external_property_id: str | None = None
    last_push_at: datetime | None = None
    last_pull_at: datetime | None = None
    pushed_count: int
    pulled_count: int
    error_count: int
    last_error: str | None = None
    # حالة لحظية
    pending: int
    failed: int
    sent_today: int
    mapped_categories: int
    bookings_today: int
    rejected_today: int
    mappings: list[MappingOut] = []


class ChannelBoard(ApiModel):
    channels: list[ChannelOut]
    #: إجمالي اللي لسه في الطابور على مستوى المنشأة
    total_pending: int
    total_failed: int
    #: فئات مش مربوطة على ولا قناة — دي أخطر حاجة في الشاشة
    unmapped_categories: list[int]


class UpdateChannelIn(ApiModel):
    is_active: bool | None = None
    is_connected: bool | None = None
    commission_percent: Decimal | None = None
    external_property_id: str | None = None


class MappingIn(ApiModel):
    unit_category_id: int
    rate_plan_id: int | None = None
    external_room_id: str
    external_rate_id: str | None = None
    allocation: int = 0
    is_active: bool = True


class MessageOut(ApiModel):
    id: int
    channel_id: int
    channel_source: BookingSource
    unit_category_id: int | None = None
    category_name_ar: str | None = None
    kind: ChannelMessageKind
    status: ChannelMessageStatus
    start_date: date
    end_date: date
    reason: str | None = None
    attempts: int
    created_at: datetime
    sent_at: datetime | None = None
    error: str | None = None


class BookingOut(ApiModel):
    id: int
    channel_id: int
    channel_source: BookingSource
    external_reference: str
    action: ChannelBookingAction
    status: ChannelBookingStatus
    guest_name: str | None = None
    guest_phone: str | None = None
    arrival_date: date | None = None
    departure_date: date | None = None
    gross_amount: Decimal
    commission_amount: Decimal
    reservation_id: int | None = None
    reservation_code: str | None = None
    error: str | None = None
    received_at: datetime


class SyncResult(ApiModel):
    ok: bool = True
    message_ar: str
    message_en: str
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    queued: int = 0


class IncomingGuest(ApiModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    nationality: str | None = None


class IncomingBookingIn(ApiModel):
    """الشكل الموحّد اللي بنستقبل بيه من أي قناة."""

    external_reference: str
    action: ChannelBookingAction = ChannelBookingAction.NEW
    external_room_id: str | None = None
    arrival_date: date | None = None
    departure_date: date | None = None
    adults: int = 2
    children: int = 0
    guest: IncomingGuest = IncomingGuest()
    notes: str | None = None


# ═══════════════════════════════════════════════════════════ مساعدات
def _channel_or_404(db, prop, channel_id: int) -> Channel:
    channel = db.get(Channel, channel_id)
    if channel is None or channel.property_id != prop.id:
        raise HTTPException(
            status_code=404, detail={"ar": "القناة غير موجودة", "en": "Channel not found"}
        )
    return channel


def _mapping_out(m: ChannelMapping, cats: dict, plans: dict) -> MappingOut:
    cat = cats.get(m.unit_category_id)
    plan = plans.get(m.rate_plan_id) if m.rate_plan_id else None
    return MappingOut(
        id=m.id,
        unit_category_id=m.unit_category_id,
        category_name_ar=cat.name_ar if cat else "—",
        category_name_en=cat.name_en if cat else "—",
        rate_plan_id=m.rate_plan_id,
        rate_plan_name_ar=plan.name_ar if plan else None,
        external_room_id=m.external_room_id,
        external_rate_id=m.external_rate_id,
        allocation=m.allocation,
        is_active=m.is_active,
    )


def _references(db, prop) -> tuple[dict, dict]:
    cats = {
        c.id: c
        for c in db.execute(
            select(UnitCategory).where(UnitCategory.property_id == prop.id)
        ).scalars().all()
    }
    plans = {
        p.id: p
        for p in db.execute(
            select(RatePlan).where(RatePlan.property_id == prop.id)
        ).scalars().all()
    }
    return cats, plans


# ═══════════════════════════════════════════════════════════ القراءة
@router.get(
    "",
    response_model=ChannelBoard,
    summary="القنوات وحالتها",
    dependencies=[Depends(require("channel.view"))],
)
def list_channels(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> ChannelBoard:
    rows = cs.health(db, prop.id)
    cats, plans = _references(db, prop)

    mapped_ids = {
        m.unit_category_id
        for m in db.execute(
            select(ChannelMapping).where(
                ChannelMapping.property_id == prop.id, ChannelMapping.is_active.is_(True)
            )
        ).scalars().all()
    }
    active_cats = [c.id for c in cats.values() if c.is_active]

    return ChannelBoard(
        channels=[
            ChannelOut(
                id=h.channel.id,
                source=h.channel.source,
                name_ar=h.channel.name_ar,
                name_en=h.channel.name_en,
                is_active=h.channel.is_active,
                is_connected=h.channel.is_connected,
                commission_percent=h.channel.commission_percent,
                external_property_id=h.channel.external_property_id,
                last_push_at=h.channel.last_push_at,
                last_pull_at=h.channel.last_pull_at,
                pushed_count=h.channel.pushed_count,
                pulled_count=h.channel.pulled_count,
                error_count=h.channel.error_count,
                last_error=h.channel.last_error,
                pending=h.pending,
                failed=h.failed,
                sent_today=h.sent_today,
                mapped_categories=h.mapped_categories,
                bookings_today=h.bookings_today,
                rejected_today=h.rejected_today,
                mappings=[_mapping_out(m, cats, plans) for m in h.channel.mappings],
            )
            for h in rows
        ],
        total_pending=sum(h.pending for h in rows),
        total_failed=sum(h.failed for h in rows),
        unmapped_categories=[c for c in active_cats if c not in mapped_ids],
    )


@router.get(
    "/messages",
    response_model=list[MessageOut],
    summary="طابور الرسايل الطالعة",
    dependencies=[Depends(require("channel.view"))],
)
def list_messages(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    status_filter: ChannelMessageStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=60, ge=1, le=300),
) -> list[MessageOut]:
    stmt = select(ChannelMessage).where(ChannelMessage.property_id == prop.id)
    if status_filter:
        stmt = stmt.where(ChannelMessage.status == status_filter)
    rows = list(
        db.execute(stmt.order_by(ChannelMessage.id.desc()).limit(limit)).scalars().all()
    )

    channels = {
        c.id: c
        for c in db.execute(
            select(Channel).where(Channel.property_id == prop.id)
        ).scalars().all()
    }
    cats, _ = _references(db, prop)

    return [
        MessageOut(
            id=m.id,
            channel_id=m.channel_id,
            channel_source=channels[m.channel_id].source,
            unit_category_id=m.unit_category_id,
            category_name_ar=(
                cats[m.unit_category_id].name_ar if m.unit_category_id in cats else None
            ),
            kind=m.kind,
            status=m.status,
            start_date=m.start_date,
            end_date=m.end_date,
            reason=m.reason,
            attempts=m.attempts,
            created_at=m.created_at,
            sent_at=m.sent_at,
            error=m.error,
        )
        for m in rows
        if m.channel_id in channels
    ]


@router.get(
    "/bookings",
    response_model=list[BookingOut],
    summary="الحجوزات الواردة من القنوات",
    dependencies=[Depends(require("channel.view"))],
)
def list_bookings(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    status_filter: ChannelBookingStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[BookingOut]:
    from app.models.reservations import Reservation

    stmt = select(ChannelBooking).where(ChannelBooking.property_id == prop.id)
    if status_filter:
        stmt = stmt.where(ChannelBooking.status == status_filter)
    rows = list(
        db.execute(stmt.order_by(ChannelBooking.id.desc()).limit(limit)).scalars().all()
    )

    channels = {
        c.id: c
        for c in db.execute(
            select(Channel).where(Channel.property_id == prop.id)
        ).scalars().all()
    }
    codes = {}
    ids = {r.reservation_id for r in rows if r.reservation_id}
    if ids:
        codes = dict(
            db.execute(
                select(Reservation.id, Reservation.code).where(Reservation.id.in_(ids))
            ).all()
        )

    return [
        BookingOut(
            id=b.id,
            channel_id=b.channel_id,
            channel_source=channels[b.channel_id].source,
            external_reference=b.external_reference,
            action=b.action,
            status=b.status,
            guest_name=b.guest_name,
            guest_phone=b.guest_phone,
            arrival_date=b.arrival_date,
            departure_date=b.departure_date,
            gross_amount=b.gross_amount,
            commission_amount=b.commission_amount,
            reservation_id=b.reservation_id,
            reservation_code=codes.get(b.reservation_id),
            error=b.error,
            received_at=b.received_at,
        )
        for b in rows
        if b.channel_id in channels
    ]


# ═══════════════════════════════════════════════════════════ الكتابة
@router.patch(
    "/{channel_id}",
    response_model=ChannelOut,
    summary="تعديل إعدادات قناة",
    dependencies=[Depends(require("channel.manage"))],
)
def update_channel(
    channel_id: int,
    payload: UpdateChannelIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ChannelOut:
    channel = _channel_or_404(db, prop, channel_id)
    before = {
        "is_active": channel.is_active,
        "is_connected": channel.is_connected,
        "commission_percent": str(channel.commission_percent),
    }

    if payload.commission_percent is not None:
        if not 0 <= payload.commission_percent <= 50:
            raise HTTPException(
                status_code=400,
                detail={
                    "ar": "العمولة لازم تكون بين صفر و50%",
                    "en": "Commission must be between 0 and 50%",
                },
            )
        channel.commission_percent = payload.commission_percent
    if payload.is_active is not None:
        channel.is_active = payload.is_active
    just_connected = False
    if payload.is_connected is not None:
        if payload.is_connected and not channel.mappings:
            raise HTTPException(
                status_code=400,
                detail={
                    "ar": "مينفعش توصّل قناة من غير ربط ولا فئة واحدة",
                    "en": "Cannot connect a channel with no room mapping",
                },
            )
        just_connected = payload.is_connected and not channel.is_connected
        channel.is_connected = payload.is_connected
    if payload.external_property_id is not None:
        channel.external_property_id = payload.external_property_id.strip() or None

    db.flush()
    # قناة اتوصّلت لسه: الصورة اللي عندها قديمة، فبتاخد مطابقة كاملة فوراً
    if just_connected:
        cs.resync(db, prop.id)

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="Channel",
        entity_id=channel.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تعديل إعدادات قناة {channel.name_ar}",
        summary_en=f"Updated channel {channel.name_en}",
        changes=audit.diff(
            before,
            {
                "is_active": channel.is_active,
                "is_connected": channel.is_connected,
                "commission_percent": str(channel.commission_percent),
            },
        ),
        request=request,
    )

    db.flush()
    return _single(db, prop, channel)


@router.put(
    "/{channel_id}/mappings",
    response_model=ChannelOut,
    summary="ضبط ربط الغرف",
    dependencies=[Depends(require("channel.manage"))],
)
def set_mappings(
    channel_id: int,
    payload: list[MappingIn],
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ChannelOut:
    channel = _channel_or_404(db, prop, channel_id)
    cats, plans = _references(db, prop)

    seen: set[tuple[int, int | None]] = set()
    for row in payload:
        if row.unit_category_id not in cats:
            raise HTTPException(
                status_code=400,
                detail={"ar": "فئة غير موجودة", "en": "Unknown unit category"},
            )
        if row.rate_plan_id is not None and row.rate_plan_id not in plans:
            raise HTTPException(
                status_code=400,
                detail={"ar": "خطة أسعار غير موجودة", "en": "Unknown rate plan"},
            )
        if not row.external_room_id.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "ar": "رقم الغرفة على القناة مطلوب",
                    "en": "The channel room id is required",
                },
            )
        if row.allocation < 0:
            raise HTTPException(
                status_code=400,
                detail={"ar": "التخصيص مينفعش بالسالب", "en": "Allocation cannot be negative"},
            )
        key = (row.unit_category_id, row.rate_plan_id)
        if key in seen:
            raise HTTPException(
                status_code=409,
                detail={
                    "ar": "نفس الفئة وخطة السعر متكررة في الربط",
                    "en": "Duplicate category and rate plan in the mapping",
                },
            )
        seen.add(key)

    existing = list(
        db.execute(
            select(ChannelMapping).where(ChannelMapping.channel_id == channel.id)
        ).scalars().all()
    )
    for row in existing:
        db.delete(row)
    db.flush()

    for row in payload:
        db.add(
            ChannelMapping(
                channel_id=channel.id,
                property_id=prop.id,
                unit_category_id=row.unit_category_id,
                rate_plan_id=row.rate_plan_id,
                external_room_id=row.external_room_id.strip(),
                external_rate_id=(row.external_rate_id or "").strip() or None,
                allocation=row.allocation,
                is_active=row.is_active,
            )
        )
    db.flush()

    # ربط جديد معناه إن القناة شايفة صورة قديمة — بنبعتلها الصورة كاملة
    queued = cs.resync(db, prop.id)

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="Channel",
        entity_id=channel.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"ضبط ربط {len(payload)} فئة على {channel.name_ar} — {queued} رسالة مطابقة",
        summary_en=f"Mapped {len(payload)} categories on {channel.name_en}",
        request=request,
    )

    db.expire(channel, ["mappings"])
    return _single(db, prop, channel)


def _single(db, prop, channel: Channel) -> ChannelOut:
    rows = {h.channel.id: h for h in cs.health(db, prop.id)}
    h = rows[channel.id]
    cats, plans = _references(db, prop)
    return ChannelOut(
        id=channel.id,
        source=channel.source,
        name_ar=channel.name_ar,
        name_en=channel.name_en,
        is_active=channel.is_active,
        is_connected=channel.is_connected,
        commission_percent=channel.commission_percent,
        external_property_id=channel.external_property_id,
        last_push_at=channel.last_push_at,
        last_pull_at=channel.last_pull_at,
        pushed_count=channel.pushed_count,
        pulled_count=channel.pulled_count,
        error_count=channel.error_count,
        last_error=channel.last_error,
        pending=h.pending,
        failed=h.failed,
        sent_today=h.sent_today,
        mapped_categories=h.mapped_categories,
        bookings_today=h.bookings_today,
        rejected_today=h.rejected_today,
        mappings=[_mapping_out(m, cats, plans) for m in channel.mappings],
    )


@router.post(
    "/sync",
    response_model=SyncResult,
    summary="تمشية الطابور",
    dependencies=[Depends(require("channel.manage"))],
)
def sync_now(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> SyncResult:
    result = cs.flush(db, prop.id)
    return SyncResult(
        message_ar=f"اتبعت {result.sent} رسالة · فشل {result.failed} · متخطّي {result.skipped}",
        message_en=f"Sent {result.sent}, failed {result.failed}, skipped {result.skipped}",
        sent=result.sent,
        failed=result.failed,
        skipped=result.skipped,
    )


@router.post(
    "/resync",
    response_model=SyncResult,
    summary="مطابقة كاملة",
    dependencies=[Depends(require("channel.manage"))],
)
def resync(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
    days: int = Query(default=90, ge=1, le=365),
) -> SyncResult:
    queued = cs.resync(db, prop.id, days=days)
    result = cs.flush(db, prop.id)
    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="Channel",
        entity_id=prop.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"مطابقة كاملة للقنوات — {days} يوم",
        summary_en=f"Full channel resync — {days} days",
        request=request,
    )
    return SyncResult(
        message_ar=f"اتحطّت {queued} رسالة واتبعت {result.sent}",
        message_en=f"Queued {queued} messages, sent {result.sent}",
        queued=queued,
        sent=result.sent,
        failed=result.failed,
        skipped=result.skipped,
    )


@router.post(
    "/retry",
    response_model=SyncResult,
    summary="إعادة محاولة الفاشل",
    dependencies=[Depends(require("channel.manage"))],
)
def retry(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> SyncResult:
    back = cs.retry_failed(db, prop.id)
    result = cs.flush(db, prop.id)
    return SyncResult(
        message_ar=f"رجّعنا {back} رسالة للطابور واتبعت {result.sent}",
        message_en=f"Requeued {back} messages, sent {result.sent}",
        queued=back,
        sent=result.sent,
        failed=result.failed,
        skipped=result.skipped,
    )


@router.post(
    "/{source}/bookings",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="استقبال حجز من قناة",
    dependencies=[Depends(require("channel.manage"))],
)
def receive_booking(
    source: BookingSource,
    payload: IncomingBookingIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> BookingOut:
    """نقطة الاستقبال الموحّدة.

    في التنفيذ الحقيقي دي بتتنادى من webhook موقّع من القناة بدل مستخدم
    مسجّل دخول، لكن المنطق اللي وراها هو هو — دي بوابة واحدة بتسجّل كل
    حاجة وصلت، حتى اللي اترفض.
    """
    try:
        row = cs.ingest(db, prop.id, source, payload.model_dump(mode="json"))
    except cs.ChannelError as exc:
        raise HTTPException(
            status_code=400 if exc.code != "not_found" else 404,
            detail={"ar": exc.message_ar, "en": exc.message_en, "code": exc.code},
        ) from exc

    from app.models.reservations import Reservation

    channel = db.get(Channel, row.channel_id)
    code = None
    if row.reservation_id:
        reservation = db.get(Reservation, row.reservation_id)
        code = reservation.code if reservation else None

    return BookingOut(
        id=row.id,
        channel_id=row.channel_id,
        channel_source=channel.source,
        external_reference=row.external_reference,
        action=row.action,
        status=row.status,
        guest_name=row.guest_name,
        guest_phone=row.guest_phone,
        arrival_date=row.arrival_date,
        departure_date=row.departure_date,
        gross_amount=row.gross_amount,
        commission_amount=row.commission_amount,
        reservation_id=row.reservation_id,
        reservation_code=code,
        error=row.error,
        received_at=row.received_at,
    )
