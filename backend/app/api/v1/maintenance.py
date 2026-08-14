"""واجهات الصيانة والميني بار — Maintenance & minibar endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import (
    OPEN_TICKET_STATUSES,
    AuditAction,
    TicketCategory,
    TicketPriority,
    TicketSource,
    TicketStatus,
)
from app.models.maintenance import MaintenanceTicket, MinibarItem
from app.models.security import User
from app.models.units import Unit
from app.schemas.common import ApiModel
from app.services import audit
from app.services import maintenance as mt

router = APIRouter(tags=["الصيانة والميني بار — Maintenance"])


# ═══════════════════════════════════════════════════════════ النماذج
class TicketOut(ApiModel):
    id: int
    number: str
    unit_id: int | None = None
    unit_label: str | None = None
    location: str | None = None
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    source: TicketSource
    title: str
    description: str | None = None
    blocks_unit: bool
    reported_by_name: str | None = None
    assigned_to_user_id: int | None = None
    assigned_to_name: str | None = None
    folio_id: int | None = None
    opened_at: datetime
    assigned_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    due_at: datetime | None = None
    is_overdue: bool = False
    resolution: str | None = None
    cost: Decimal
    cancelled_reason: str | None = None


class BoardOut(ApiModel):
    open: int
    assigned: int
    in_progress: int
    done_today: int
    overdue: int
    urgent: int
    blocked_units: int
    cost_this_month: Decimal
    tickets: list[TicketOut]


class OpenTicketIn(ApiModel):
    title: str
    unit_id: int | None = None
    location: str | None = None
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.NORMAL
    source: TicketSource = TicketSource.STAFF
    description: str | None = None
    blocks_unit: bool = False
    folio_id: int | None = None


class AssignIn(ApiModel):
    user_id: int


class CompleteIn(ApiModel):
    resolution: str
    cost: Decimal = Decimal("0")


class CancelIn(ApiModel):
    reason: str


class TechnicianOut(ApiModel):
    id: int
    name_ar: str
    name_en: str
    role_ar: str


class MinibarItemOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    price: Decimal
    contains_alcohol: bool


class MinibarLineIn(ApiModel):
    item_id: int
    quantity: Decimal


class PostMinibarIn(ApiModel):
    folio_id: int
    lines: list[MinibarLineIn]


class PostResult(ApiModel):
    ok: bool = True
    message_ar: str
    message_en: str
    total: Decimal


def _fail(exc: mt.MaintenanceError) -> HTTPException:
    code = {"not_found": 404, "closed": 409}.get(exc.code, 400)
    return HTTPException(
        status_code=code, detail={"ar": exc.message_ar, "en": exc.message_en, "code": exc.code}
    )


def _out(t: MaintenanceTicket, units: dict, users: dict, now: datetime) -> TicketOut:
    reporter = users.get(t.reported_by_user_id)
    tech = users.get(t.assigned_to_user_id)
    return TicketOut(
        id=t.id,
        number=t.number,
        unit_id=t.unit_id,
        unit_label=units.get(t.unit_id),
        location=t.location,
        category=t.category,
        priority=t.priority,
        status=t.status,
        source=t.source,
        title=t.title,
        description=t.description,
        blocks_unit=t.blocks_unit,
        reported_by_name=reporter.full_name_ar if reporter else None,
        assigned_to_user_id=t.assigned_to_user_id,
        assigned_to_name=tech.full_name_ar if tech else None,
        folio_id=t.folio_id,
        opened_at=t.opened_at,
        assigned_at=t.assigned_at,
        started_at=t.started_at,
        completed_at=t.completed_at,
        due_at=t.due_at,
        is_overdue=bool(
            t.due_at and t.due_at < now and t.status in OPEN_TICKET_STATUSES
        ),
        resolution=t.resolution,
        cost=t.cost,
        cancelled_reason=t.cancelled_reason,
    )


def _lookups(db, prop, tickets: list[MaintenanceTicket]) -> tuple[dict, dict]:
    unit_ids = {t.unit_id for t in tickets if t.unit_id}
    units = (
        dict(db.execute(select(Unit.id, Unit.label).where(Unit.id.in_(unit_ids))).all())
        if unit_ids
        else {}
    )
    user_ids = {t.reported_by_user_id for t in tickets if t.reported_by_user_id} | {
        t.assigned_to_user_id for t in tickets if t.assigned_to_user_id
    }
    users = (
        {u.id: u for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()}
        if user_ids
        else {}
    )
    return units, users


# ═══════════════════════════════════════════════════════════ القراءة
@router.get(
    "/maintenance",
    response_model=BoardOut,
    summary="لوحة الصيانة",
    dependencies=[Depends(require("maintenance.view"))],
)
def get_board(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    ticket_status: TicketStatus | None = Query(default=None, alias="status"),
    unit_id: int | None = None,
    limit: int = Query(default=80, ge=1, le=300),
) -> BoardOut:
    counts = mt.board(db, prop.id)

    stmt = select(MaintenanceTicket).where(MaintenanceTicket.property_id == prop.id)
    if ticket_status:
        stmt = stmt.where(MaintenanceTicket.status == ticket_status)
    else:
        # الافتراضي: الشغّال بس — التاريخ بيتطلب صراحةً
        stmt = stmt.where(MaintenanceTicket.status.in_(list(OPEN_TICKET_STATUSES)))
    if unit_id:
        stmt = stmt.where(MaintenanceTicket.unit_id == unit_id)

    tickets = list(
        db.execute(
            stmt.order_by(MaintenanceTicket.priority.desc(), MaintenanceTicket.id.desc()).limit(limit)
        ).scalars().all()
    )
    units, users = _lookups(db, prop, tickets)
    now = mt.utcnow()

    return BoardOut(
        open=counts.open,
        assigned=counts.assigned,
        in_progress=counts.in_progress,
        done_today=counts.done_today,
        overdue=counts.overdue,
        urgent=counts.urgent,
        blocked_units=counts.blocked_units,
        cost_this_month=counts.cost_this_month,
        tickets=[_out(t, units, users, now) for t in tickets],
    )


@router.get(
    "/maintenance/technicians",
    response_model=list[TechnicianOut],
    summary="مين ينفع يتسند له",
    dependencies=[Depends(require("maintenance.view"))],
)
def technicians(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[TechnicianOut]:
    rows = list(
        db.execute(
            select(User).where(User.property_id == prop.id, User.is_active.is_(True))
        ).scalars().all()
    )
    return [
        TechnicianOut(
            id=u.id,
            name_ar=u.full_name_ar,
            name_en=u.full_name_en,
            role_ar=" · ".join(r.name_ar for r in u.roles) or "—",
        )
        for u in rows
    ]


# ═══════════════════════════════════════════════════════════ الكتابة
@router.post(
    "/maintenance",
    response_model=TicketOut,
    status_code=status.HTTP_201_CREATED,
    summary="افتح بلاغ",
    dependencies=[Depends(require("maintenance.manage"))],
)
def open_ticket(
    payload: OpenTicketIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> TicketOut:
    try:
        ticket = mt.open_ticket(
            db,
            prop.id,
            title=payload.title,
            unit_id=payload.unit_id,
            location=payload.location,
            category=payload.category,
            priority=payload.priority,
            source=payload.source,
            description=payload.description,
            blocks_unit=payload.blocks_unit,
            folio_id=payload.folio_id,
            user=user,
        )
    except mt.MaintenanceError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="MaintenanceTicket",
        entity_id=ticket.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"بلاغ صيانة {ticket.number} — {ticket.title}"
        + (" (الوحدة اتشالت من البيع)" if ticket.blocks_unit else ""),
        summary_en=f"Opened ticket {ticket.number}",
        request=request,
    )
    return _single(db, prop, ticket)


@router.post(
    "/maintenance/{ticket_id}/assign",
    response_model=TicketOut,
    summary="اسند لفني",
    dependencies=[Depends(require("maintenance.manage"))],
)
def assign(
    ticket_id: int, payload: AssignIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> TicketOut:
    _own(db, prop, ticket_id)
    try:
        ticket = mt.assign(db, ticket_id, payload.user_id)
    except mt.MaintenanceError as exc:
        raise _fail(exc) from exc
    return _single(db, prop, ticket)


@router.post(
    "/maintenance/{ticket_id}/start",
    response_model=TicketOut,
    summary="ابدأ الشغل",
    dependencies=[Depends(require("maintenance.manage"))],
)
def start(ticket_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty) -> TicketOut:
    _own(db, prop, ticket_id)
    try:
        ticket = mt.start(db, ticket_id)
    except mt.MaintenanceError as exc:
        raise _fail(exc) from exc
    return _single(db, prop, ticket)


@router.post(
    "/maintenance/{ticket_id}/complete",
    response_model=TicketOut,
    summary="قفل البلاغ",
    dependencies=[Depends(require("maintenance.manage"))],
)
def complete(
    ticket_id: int,
    payload: CompleteIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> TicketOut:
    _own(db, prop, ticket_id)
    try:
        ticket = mt.complete(db, ticket_id, resolution=payload.resolution, cost=payload.cost)
    except mt.MaintenanceError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="MaintenanceTicket",
        entity_id=ticket.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"قفل بلاغ {ticket.number} بتكلفة {ticket.cost}"
        + (" — الوحدة رجعت للبيع" if ticket.blocks_unit else ""),
        summary_en=f"Completed ticket {ticket.number}",
        request=request,
    )
    return _single(db, prop, ticket)


@router.post(
    "/maintenance/{ticket_id}/cancel",
    response_model=TicketOut,
    summary="اشطب البلاغ",
    dependencies=[Depends(require("maintenance.manage"))],
)
def cancel(
    ticket_id: int, payload: CancelIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> TicketOut:
    _own(db, prop, ticket_id)
    try:
        ticket = mt.cancel(db, ticket_id, payload.reason)
    except mt.MaintenanceError as exc:
        raise _fail(exc) from exc
    return _single(db, prop, ticket)


def _own(db, prop, ticket_id: int) -> MaintenanceTicket:
    ticket = db.get(MaintenanceTicket, ticket_id)
    if ticket is None or ticket.property_id != prop.id:
        raise HTTPException(
            status_code=404, detail={"ar": "التذكرة غير موجودة", "en": "Ticket not found"}
        )
    return ticket


def _single(db, prop, ticket: MaintenanceTicket) -> TicketOut:
    units, users = _lookups(db, prop, [ticket])
    return _out(ticket, units, users, mt.utcnow())


# ═══════════════════════════════════════════════════════════ الميني بار
@router.get(
    "/minibar",
    response_model=list[MinibarItemOut],
    summary="أصناف الميني بار",
    dependencies=[Depends(require("folio.post"))],
)
def minibar_catalog(
    db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> list[MinibarItemOut]:
    return [
        MinibarItemOut(
            id=i.id,
            code=i.code,
            name_ar=i.name_ar,
            name_en=i.name_en,
            price=i.price,
            contains_alcohol=i.contains_alcohol,
        )
        for i in mt.catalog(db, prop.id)
    ]


@router.post(
    "/minibar/post",
    response_model=PostResult,
    summary="رحّل استهلاك ميني بار",
    dependencies=[Depends(require("folio.post"))],
)
def post_minibar(
    payload: PostMinibarIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> PostResult:
    try:
        total = mt.post_consumption(
            db,
            prop.id,
            payload.folio_id,
            [(l.item_id, l.quantity) for l in payload.lines],
            user=user,
        )
    except mt.MaintenanceError as exc:
        raise _fail(exc) from exc
    except Exception as exc:  # أخطاء الحساب بترجع برسالتها المفهومة
        message = getattr(exc, "message_ar", None)
        if message is None:
            raise
        raise HTTPException(
            status_code=400,
            detail={"ar": message, "en": getattr(exc, "message_en", str(exc))},
        ) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="Folio",
        entity_id=payload.folio_id,
        user=user,
        property_id=prop.id,
        summary_ar=f"ترحيل ميني بار بمبلغ {total}",
        summary_en=f"Posted minibar consumption {total}",
        request=request,
    )
    return PostResult(
        message_ar=f"اترحّل {total} ج.م على الحساب",
        message_en=f"Posted {total} EGP to the folio",
        total=total,
    )
