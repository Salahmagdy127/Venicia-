"""واجهات علاقات النزلاء — Guest 360, segments & feedback endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import FeedbackChannel, FeedbackKind, FeedbackStatus
from app.models.leisure import GuestFeedback
from app.schemas.common import ApiModel
from app.services import crm

router = APIRouter(tags=["علاقات النزلاء — CRM"])


# ═══════════════════════════════════════════════════════════ النماذج
class SpendOut(ApiModel):
    rooms: Decimal
    food: Decimal
    spa: Decimal
    activities: Decimal
    other: Decimal
    total: Decimal


class ProfileOut(ApiModel):
    guest_id: int
    name: str
    stays: int
    nights: int
    cancellations: int
    no_shows: int
    first_stay: date | None = None
    last_stay: date | None = None
    days_since_last: int | None = None
    spend: SpendOut
    average_per_stay: Decimal
    average_per_night: Decimal
    service_bookings: int
    open_feedback: int
    segments: list[str]
    preferences: dict = {}


class SegmentRowOut(ApiModel):
    guest_id: int
    name: str
    phone: str | None = None
    email: str | None = None
    stays: int
    nights: int
    last_stay: date | None = None
    total_spend: Decimal
    segments: list[str]


class SegmentSummaryOut(ApiModel):
    code: str
    name_ar: str
    name_en: str
    guests: int
    value: Decimal


class FeedbackOut(ApiModel):
    id: int
    number: str
    guest_id: int | None = None
    guest_name: str
    reservation_id: int | None = None
    unit_id: int | None = None
    kind: FeedbackKind
    channel: FeedbackChannel
    status: FeedbackStatus
    rating: int | None = None
    department: str | None = None
    subject: str
    body: str | None = None
    received_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None
    compensation: Decimal
    owner_name: str | None = None
    #: ساعات لحد ما حد ردّ. فاضي = لسه محدش ردّ
    hours_to_ack: Decimal | None = None
    is_overdue: bool = False


class FeedbackBoardOut(ApiModel):
    open: int
    acknowledged: int
    escalated: int
    resolved_30d: int
    complaints_30d: int
    compliments_30d: int
    overdue: int
    average_rating: Decimal | None = None
    average_ack_hours: Decimal | None = None
    average_resolve_hours: Decimal | None = None
    compensation_30d: Decimal
    ack_target_hours: int
    by_department: dict[str, int]
    items: list[FeedbackOut]


class LogFeedbackIn(ApiModel):
    subject: str
    kind: FeedbackKind
    channel: FeedbackChannel
    guest_id: int | None = None
    guest_name: str | None = None
    reservation_id: int | None = None
    unit_id: int | None = None
    rating: int | None = None
    department: str | None = None
    body: str | None = None


class ResolveIn(ApiModel):
    resolution: str
    compensation: Decimal | None = None


class NoteIn(ApiModel):
    note: str | None = None


def _fail(error: crm.CrmError) -> HTTPException:
    return HTTPException(
        404 if error.code == "not_found" else 400,
        {"ar": error.message_ar, "en": error.message_en, "code": error.code},
    )


def _feedback_out(entry: GuestFeedback, names: dict[int, str]) -> FeedbackOut:
    hours = None
    if entry.acknowledged_at:
        hours = Decimal(
            str((entry.acknowledged_at - entry.received_at).total_seconds() / 3600)
        ).quantize(Decimal("0.1"))
    overdue = (
        entry.acknowledged_at is None
        and entry.status not in (FeedbackStatus.RESOLVED, FeedbackStatus.CLOSED)
        and (crm.utcnow() - entry.received_at).total_seconds() / 3600
        > crm.ACK_TARGET_HOURS
    )
    return FeedbackOut(
        id=entry.id, number=entry.number, guest_id=entry.guest_id,
        guest_name=entry.guest_name, reservation_id=entry.reservation_id,
        unit_id=entry.unit_id, kind=entry.kind, channel=entry.channel,
        status=entry.status, rating=entry.rating, department=entry.department,
        subject=entry.subject, body=entry.body, received_at=entry.received_at,
        acknowledged_at=entry.acknowledged_at, resolved_at=entry.resolved_at,
        resolution=entry.resolution, compensation=entry.compensation,
        owner_name=names.get(entry.owner_user_id or 0),
        hours_to_ack=hours, is_overdue=overdue,
    )


# ═══════════════════════════════════════════════════════ ملف النزيل
@router.get(
    "/crm/guests/{guest_id}",
    response_model=ProfileOut,
    summary="ملف النزيل الكامل",
    dependencies=[Depends(require("guest.view"))],
)
def guest_profile(
    guest_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> ProfileOut:
    try:
        found = crm.profile(db, guest_id)
    except crm.CrmError as error:
        raise _fail(error)
    return ProfileOut(
        guest_id=found.guest_id, name=found.name, stays=found.stays,
        nights=found.nights, cancellations=found.cancellations,
        no_shows=found.no_shows, first_stay=found.first_stay,
        last_stay=found.last_stay, days_since_last=found.days_since_last,
        spend=SpendOut(
            rooms=found.spend.rooms, food=found.spend.food, spa=found.spend.spa,
            activities=found.spend.activities, other=found.spend.other,
            total=found.spend.total,
        ),
        average_per_stay=found.average_per_stay,
        average_per_night=found.average_per_night,
        service_bookings=found.service_bookings,
        open_feedback=found.open_feedback,
        segments=found.segments, preferences=found.preferences,
    )


# ═══════════════════════════════════════════════════════ الشرائح
@router.get(
    "/crm/segments",
    response_model=list[SegmentSummaryOut],
    summary="ملخّص الشرائح",
    dependencies=[Depends(require("guest.view"))],
)
def segments(
    db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> list[SegmentSummaryOut]:
    return [
        SegmentSummaryOut(
            code=s.code, name_ar=s.name_ar, name_en=s.name_en,
            guests=s.guests, value=s.value,
        )
        for s in crm.segment_summary(db, prop.id)
    ]


@router.get(
    "/crm/segments/{code}",
    response_model=list[SegmentRowOut],
    summary="نزلاء شريحة",
    dependencies=[Depends(require("guest.view"))],
)
def segment_rows(
    code: str,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[SegmentRowOut]:
    try:
        rows = crm.segment(db, prop.id, code, limit=limit)
    except crm.CrmError as error:
        raise _fail(error)
    return [
        SegmentRowOut(
            guest_id=r.guest_id, name=r.name, phone=r.phone, email=r.email,
            stays=r.stays, nights=r.nights, last_stay=r.last_stay,
            total_spend=r.total_spend, segments=r.segments,
        )
        for r in rows
    ]


@router.get(
    "/crm/top-guests",
    response_model=list[SegmentRowOut],
    summary="أعلى النزلاء إنفاقاً",
    dependencies=[Depends(require("guest.view"))],
)
def top(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SegmentRowOut]:
    return [
        SegmentRowOut(
            guest_id=r.guest_id, name=r.name, phone=r.phone, email=r.email,
            stays=r.stays, nights=r.nights, last_stay=r.last_stay,
            total_spend=r.total_spend, segments=r.segments,
        )
        for r in crm.top_guests(db, prop.id, limit)
    ]


# ═══════════════════════════════════════════════════════ الملاحظات
@router.get(
    "/crm/feedback",
    response_model=FeedbackBoardOut,
    summary="لوحة الشكاوى والتقييمات",
    dependencies=[Depends(require("guest.view"))],
)
def feedback_board(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    status: FeedbackStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> FeedbackBoardOut:
    from app.models.security import User

    summary = crm.feedback_board(db, prop.id)
    query = select(GuestFeedback).where(GuestFeedback.property_id == prop.id)
    if status:
        query = query.where(GuestFeedback.status == status)
    rows = db.execute(
        query.order_by(GuestFeedback.received_at.desc()).limit(limit)
    ).scalars().all()

    names = {
        u.id: u.full_name_ar
        for u in db.execute(select(User).where(User.property_id == prop.id)).scalars().all()
    }

    return FeedbackBoardOut(
        open=summary.open, acknowledged=summary.acknowledged,
        escalated=summary.escalated, resolved_30d=summary.resolved_30d,
        complaints_30d=summary.complaints_30d,
        compliments_30d=summary.compliments_30d, overdue=summary.overdue,
        average_rating=summary.average_rating,
        average_ack_hours=summary.average_ack_hours,
        average_resolve_hours=summary.average_resolve_hours,
        compensation_30d=summary.compensation_30d,
        ack_target_hours=crm.ACK_TARGET_HOURS,
        by_department=summary.by_department,
        items=[_feedback_out(r, names) for r in rows],
    )


@router.post(
    "/crm/feedback",
    response_model=FeedbackOut,
    summary="تسجيل ملاحظة",
    dependencies=[Depends(require("guest.edit"))],
)
def new_feedback(
    payload: LogFeedbackIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> FeedbackOut:
    try:
        entry = crm.log_feedback(
            db, prop.id,
            subject=payload.subject, kind=payload.kind, channel=payload.channel,
            guest_id=payload.guest_id, guest_name=payload.guest_name,
            reservation_id=payload.reservation_id, unit_id=payload.unit_id,
            rating=payload.rating, department=payload.department,
            body=payload.body, user=user,
        )
    except crm.CrmError as error:
        raise _fail(error)
    return _feedback_out(entry, {user.id: user.full_name_ar})


@router.post(
    "/crm/feedback/{feedback_id}/acknowledge",
    response_model=FeedbackOut,
    summary="تسجيل الرد",
    dependencies=[Depends(require("guest.edit"))],
)
def ack(
    feedback_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> FeedbackOut:
    try:
        entry = crm.acknowledge(db, feedback_id, user=user)
    except crm.CrmError as error:
        raise _fail(error)
    return _feedback_out(entry, {user.id: user.full_name_ar})


@router.post(
    "/crm/feedback/{feedback_id}/resolve",
    response_model=FeedbackOut,
    summary="إغلاق الملاحظة",
    dependencies=[Depends(require("guest.edit"))],
)
def close(
    feedback_id: int,
    payload: ResolveIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> FeedbackOut:
    try:
        entry = crm.resolve(
            db, feedback_id,
            resolution=payload.resolution,
            compensation=payload.compensation,
            user=user,
        )
    except crm.CrmError as error:
        raise _fail(error)
    return _feedback_out(entry, {user.id: user.full_name_ar})


@router.post(
    "/crm/feedback/{feedback_id}/escalate",
    response_model=FeedbackOut,
    summary="تصعيد للإدارة",
    dependencies=[Depends(require("guest.edit"))],
)
def raise_up(
    feedback_id: int,
    payload: NoteIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> FeedbackOut:
    try:
        entry = crm.escalate(db, feedback_id, payload.note)
    except crm.CrmError as error:
        raise _fail(error)
    return _feedback_out(entry, {user.id: user.full_name_ar})
