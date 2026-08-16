"""واجهة تطبيق الميدان — Field app API (housekeeper & technician phones).

الواجهة دي مصمّمة لتليفون **مش** لمتصفح على مكتب، والفرق مش في الشكل:

* ``/field/bootstrap`` بيرجّع **كل** اللي التليفون محتاجه يشتغل بيه يوم
  كامل من غير شبكة: الوحدات، الأقسام، أنواع الأعطال، الميني بار،
  والنصوص. بيتنده مرة الصبح وخلاص.
* ``/field/board`` بيرجّع جولة اليوم في طلب واحد — مش عشر طلبات.
* ``/field/sync`` بياخد **دفعة** عمليات مسجّلة على التليفون ويرد على كل
  واحدة لوحدها. ده المسار اللي بيشتغل عليه التطبيق كله؛ مفيش عملية
  بتتنفّذ لحظياً ومفيش شاشة بتستنّى رد.
* ``/field/photos`` بياخد الصورة بمعرّفها اللي اتولّد على التليفون،
  فإعادة الرفع بترجّع نفس الصورة مش نسخة تانية.

المبدأ: **التليفون هو مصدر الحقيقة لحظياً، والسيرفر هو مصدر الحقيقة
في الآخر.** التطبيق بيشتغل من قاعدة بياناته المحلية وبيتصالح مع
السيرفر لما يلاقي شبكة.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import (
    PhotoPhase,
    SyncOutcome,
    TaskKind,
    TaskStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)
from app.models.maintenance import MinibarItem
from app.models.security import User
from app.models.tasks import FieldPhoto, HousekeepingTask
from app.models.units import Unit, UnitCategory
from app.schemas.common import ApiModel
from app.services import housekeeping as hk
from app.services import media

router = APIRouter(prefix="/field", tags=["تطبيق الميدان — Field app"])


# ═══════════════════════════════════════════════════════════ النماذج
class PhotoOut(ApiModel):
    id: int
    phase: PhotoPhase
    url: str
    thumb_url: str | None = None
    taken_at: datetime
    taken_by_name: str | None = None
    note: str | None = None


class TaskOut(ApiModel):
    id: int
    unit_id: int
    unit_label: str
    zone_ar: str | None = None
    zone_en: str | None = None
    category_name_ar: str
    category_name_en: str
    task_date: date
    kind: TaskKind
    status: TaskStatus
    priority: int
    expected_minutes: int
    working_seconds: int
    photos_required: bool
    photo_before_count: int
    photo_after_count: int
    dnd_attempts: int
    snoozed_until: datetime | None = None
    blocked_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    linen_changed: bool = False
    amenities_restocked: bool = False
    minibar_checked: bool = False
    inspection_score: int | None = None
    inspection_note: str | None = None
    note: str | None = None
    assigned_to_user_id: int | None = None
    assigned_to_name: str | None = None
    ticket_id: int | None = None
    has_minibar: bool = False
    is_occupied: bool = False
    photos: list[PhotoOut] = []


class FieldTicketOut(ApiModel):
    id: int
    number: str
    unit_id: int | None = None
    unit_label: str | None = None
    location: str | None = None
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    title: str
    description: str | None = None
    blocks_unit: bool
    opened_at: datetime
    due_at: datetime | None = None
    is_overdue: bool = False
    is_mine: bool = False


class BoardOut(ApiModel):
    """جولة اليوم — كل اللي التليفون بيرسمه في شاشة واحدة."""

    business_date: date
    server_time: datetime
    user_id: int
    user_name_ar: str
    user_name_en: str
    role_ar: str
    role_en: str
    can_clean: bool
    can_fix: bool
    can_inspect: bool
    tasks: list[TaskOut]
    tickets: list[FieldTicketOut]
    done: int = 0
    remaining: int = 0
    minutes_planned: int = 0
    minutes_worked: int = 0


class MinibarItemOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    price: Decimal
    contains_alcohol: bool


class UnitOut(ApiModel):
    id: int
    label: str
    zone_ar: str | None = None
    zone_en: str | None = None
    building: str | None = None
    category_name_ar: str
    category_name_en: str
    has_minibar: bool


class LabelOut(ApiModel):
    code: str
    name_ar: str
    name_en: str


class BootstrapOut(ApiModel):
    """الحزمة اللي التليفون بيحفظها عشان يشتغل يوم كامل من غير شبكة."""

    version: str
    server_time: datetime
    property_id: int
    property_name_ar: str
    property_name_en: str
    units: list[UnitOut]
    minibar: list[MinibarItemOut]
    ticket_categories: list[LabelOut]
    ticket_priorities: list[LabelOut]
    task_kinds: list[LabelOut]
    block_reasons: list[LabelOut]
    dnd_snooze_minutes: int
    dnd_escalate_after: int


class SyncActionIn(ApiModel):
    uuid: str
    type: str
    task_id: int | None = None
    ticket_id: int | None = None
    at: datetime | None = None
    payload: dict[str, Any] = {}


class SyncIn(ApiModel):
    device_id: str | None = None
    actions: list[SyncActionIn] = []
    #: التليفون بيقول آخر مرة زامن فيها — بيرجع له اللي اتغيّر بعدها
    since: datetime | None = None


class SyncResultOut(ApiModel):
    uuid: str
    type: str
    outcome: SyncOutcome
    task_id: int | None = None
    ticket_id: int | None = None
    status: str | None = None
    message_ar: str | None = None
    message_en: str | None = None
    code: str | None = None


class SyncOut(ApiModel):
    server_time: datetime
    applied: int
    duplicates: int
    rejected: int
    results: list[SyncResultOut]
    #: الحالة الجديدة بعد التنفيذ — التليفون بيستبدل بيها نسخته المحلية
    board: BoardOut


class PhotoUploadOut(ApiModel):
    photo: PhotoOut
    created: bool
    task_id: int | None = None
    photo_before_count: int = 0
    photo_after_count: int = 0


# ═══════════════════════════════════════════════════════════ مساعدات
BLOCK_REASONS: list[tuple[str, str, str]] = [
    ("LOCKED", "الباب مقفول", "Door locked"),
    ("GUEST_INSIDE", "النزيل جوّه ومش عايز", "Guest inside and declined"),
    ("NO_WATER", "مفيش مية", "No water supply"),
    ("NO_POWER", "مفيش كهربا", "No power"),
    ("NO_SUPPLIES", "المهمات خلصت", "Out of supplies"),
    ("MAINTENANCE", "الوحدة تحت الصيانة", "Unit under maintenance"),
    ("OTHER", "سبب تاني", "Other"),
]

TASK_KIND_LABELS: dict[TaskKind, tuple[str, str]] = {
    TaskKind.DEPARTURE: ("تنضيف مغادرة", "Departure clean"),
    TaskKind.ARRIVAL_PREP: ("تجهيز وصول", "Arrival prep"),
    TaskKind.STAYOVER: ("ترتيب يومي", "Stayover service"),
    TaskKind.TURNDOWN: ("ترتيب مسائي", "Turndown"),
    TaskKind.DEEP: ("تنضيف عميق", "Deep clean"),
    TaskKind.POST_MAINTENANCE: ("بعد الصيانة", "Post-maintenance"),
    TaskKind.INSPECTION: ("فحص", "Inspection"),
}

CATEGORY_LABELS: dict[TicketCategory, tuple[str, str]] = {
    TicketCategory.AC: ("تكييف", "Air conditioning"),
    TicketCategory.PLUMBING: ("سباكة", "Plumbing"),
    TicketCategory.ELECTRICAL: ("كهربا", "Electrical"),
    TicketCategory.FURNITURE: ("أثاث", "Furniture"),
    TicketCategory.APPLIANCE: ("أجهزة", "Appliances"),
    TicketCategory.NETWORK: ("نت وتليفزيون", "Network & TV"),
    TicketCategory.POOL: ("حمام السباحة", "Pool"),
    TicketCategory.GROUNDS: ("المساحات الخارجية", "Grounds"),
    TicketCategory.OTHER: ("حاجة تانية", "Other"),
}

PRIORITY_LABELS: dict[TicketPriority, tuple[str, str]] = {
    TicketPriority.URGENT: ("عاجل", "Urgent"),
    TicketPriority.HIGH: ("مهم", "High"),
    TicketPriority.NORMAL: ("عادي", "Normal"),
    TicketPriority.LOW: ("مش مستعجل", "Low"),
}


def _photo_out(photo: FieldPhoto, names: dict[int, str]) -> PhotoOut:
    return PhotoOut(
        id=photo.id,
        phase=photo.phase,
        url=f"/api/v1/field/photos/{photo.id}",
        thumb_url=f"/api/v1/field/photos/{photo.id}?thumb=1" if photo.thumb_path else None,
        taken_at=photo.taken_at,
        taken_by_name=names.get(photo.taken_by_user_id or 0),
        note=photo.note,
    )


def _build_board(
    db, user: User, property_id: int, business_date: date, *, mine_only: bool = True
) -> BoardOut:
    from app.models.enums import (
        BLOCKING_RESERVATION_STATUSES,
        CLOSED_TASK_STATUSES,
        OPEN_TICKET_STATUSES,
    )
    from app.models.reservations import ReservationUnit
    from app.models.maintenance import MaintenanceTicket

    can_inspect = user.has_permission("housekeeping.update")
    views = hk.day_tasks(
        db,
        property_id,
        business_date,
        user_id=None if (can_inspect and not mine_only) else user.id,
    )
    # السوبرفايزر بيشوف الكل؛ الهاوس كيبر بيشوف مهامه. ولو الهاوس كيبر
    # ملوش مهام لسه (التوزيع ماتعملش)، بيشوف المهام غير الموزّعة عشان
    # ميقفش مستني حد يوزّع عليه.
    if not can_inspect and not views:
        views = [
            v
            for v in hk.day_tasks(db, property_id, business_date)
            if v.task.assigned_to_user_id is None
        ]

    task_ids = [v.task.id for v in views]
    photos: dict[int, list[FieldPhoto]] = {}
    if task_ids:
        for photo in db.execute(
            select(FieldPhoto)
            .where(FieldPhoto.task_id.in_(task_ids))
            .order_by(FieldPhoto.phase, FieldPhoto.taken_at)
        ).scalars().all():
            photos.setdefault(photo.task_id or 0, []).append(photo)

    names = {
        u.id: u.full_name_ar
        for u in db.execute(
            select(User).where(User.property_id == property_id)
        ).scalars().all()
    }

    occupied = {
        row[0]
        for row in db.execute(
            select(ReservationUnit.unit_id).where(
                ReservationUnit.property_id == property_id,
                ReservationUnit.unit_id.isnot(None),
                ReservationUnit.arrival_date <= business_date,
                ReservationUnit.departure_date > business_date,
                ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
            )
        ).all()
    }

    tasks = [
        TaskOut(
            id=v.task.id,
            unit_id=v.unit.id,
            unit_label=v.unit.label,
            zone_ar=v.unit.zone_ar,
            zone_en=v.unit.zone_en,
            category_name_ar=v.category.name_ar,
            category_name_en=v.category.name_en,
            task_date=v.task.task_date,
            kind=v.task.kind,
            status=v.task.status,
            priority=v.task.priority,
            expected_minutes=v.task.expected_minutes,
            working_seconds=v.task.working_seconds,
            photos_required=v.task.photos_required,
            photo_before_count=v.task.photo_before_count,
            photo_after_count=v.task.photo_after_count,
            dnd_attempts=v.task.dnd_attempts,
            snoozed_until=v.task.snoozed_until,
            blocked_reason=v.task.blocked_reason,
            started_at=v.task.started_at,
            completed_at=v.task.completed_at,
            linen_changed=v.task.linen_changed,
            amenities_restocked=v.task.amenities_restocked,
            minibar_checked=v.task.minibar_checked,
            inspection_score=v.task.inspection_score,
            inspection_note=v.task.inspection_note,
            note=v.task.note,
            assigned_to_user_id=v.task.assigned_to_user_id,
            assigned_to_name=names.get(v.task.assigned_to_user_id or 0),
            ticket_id=v.task.ticket_id,
            has_minibar=v.unit.has_minibar,
            is_occupied=v.unit.id in occupied,
            photos=[_photo_out(p, names) for p in photos.get(v.task.id, [])],
        )
        for v in views
    ]

    can_fix = user.has_permission("field.fix") or user.has_permission("maintenance.manage")
    tickets: list[FieldTicketOut] = []
    if can_fix:
        now = hk.utcnow()
        labels = {
            u.id: u.label
            for u in db.execute(
                select(Unit).where(Unit.property_id == property_id)
            ).scalars().all()
        }
        for ticket in hk.open_tickets_for(db, property_id, user):
            tickets.append(
                FieldTicketOut(
                    id=ticket.id,
                    number=ticket.number,
                    unit_id=ticket.unit_id,
                    unit_label=labels.get(ticket.unit_id or 0),
                    location=ticket.location,
                    category=ticket.category,
                    priority=ticket.priority,
                    status=ticket.status,
                    title=ticket.title,
                    description=ticket.description,
                    blocks_unit=ticket.blocks_unit,
                    opened_at=ticket.opened_at,
                    due_at=ticket.due_at,
                    is_overdue=bool(ticket.due_at and ticket.due_at < now),
                    is_mine=ticket.assigned_to_user_id == user.id,
                )
            )

    role_ar = "هاوس كيبر"
    role_en = "Housekeeper"
    if can_inspect:
        role_ar, role_en = "سوبرفايزر", "Supervisor"
    elif can_fix and not user.has_permission("field.clean"):
        role_ar, role_en = "فني صيانة", "Technician"

    done = sum(1 for t in tasks if t.status in CLOSED_TASK_STATUSES)
    return BoardOut(
        business_date=business_date,
        server_time=hk.utcnow(),
        user_id=user.id,
        user_name_ar=user.full_name_ar,
        user_name_en=user.full_name_en,
        role_ar=role_ar,
        role_en=role_en,
        can_clean=user.has_permission("field.clean"),
        can_fix=can_fix,
        can_inspect=can_inspect,
        tasks=tasks,
        tickets=tickets,
        done=done,
        remaining=len(tasks) - done,
        minutes_planned=sum(t.expected_minutes for t in tasks),
        minutes_worked=sum(t.working_seconds for t in tasks) // 60,
    )


# ═══════════════════════════════════════════════════════════ المسارات
@router.get(
    "/bootstrap",
    response_model=BootstrapOut,
    summary="حزمة العمل الأوفلاين",
    dependencies=[Depends(require("field.clean", "field.fix", "housekeeping.view"))],
)
def bootstrap(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> BootstrapOut:
    """كل اللي التليفون محتاجه يشتغل يوم كامل من غير شبكة — في طلب واحد."""
    units = db.execute(
        select(Unit, UnitCategory)
        .join(UnitCategory, UnitCategory.id == Unit.category_id)
        .where(Unit.property_id == prop.id, Unit.is_active.is_(True))
        .order_by(UnitCategory.sort_order, Unit.sort_order)
    ).all()

    minibar = db.execute(
        select(MinibarItem)
        .where(MinibarItem.property_id == prop.id, MinibarItem.is_active.is_(True))
        .order_by(MinibarItem.sort_order, MinibarItem.id)
    ).scalars().all()

    return BootstrapOut(
        # النسخة بتتغيّر لما البيانات دي تتغيّر — التليفون بيقارنها
        # وبيحمّل من جديد بس لما تفرق
        version=f"{prop.id}-{len(units)}-{len(minibar)}-3",
        server_time=hk.utcnow(),
        property_id=prop.id,
        property_name_ar=prop.name_ar,
        property_name_en=prop.name_en,
        units=[
            UnitOut(
                id=u.id, label=u.label, zone_ar=u.zone_ar, zone_en=u.zone_en,
                building=u.building, category_name_ar=c.name_ar,
                category_name_en=c.name_en, has_minibar=u.has_minibar,
            )
            for u, c in units
        ],
        minibar=[
            MinibarItemOut(
                id=i.id, code=i.code, name_ar=i.name_ar, name_en=i.name_en,
                price=i.price, contains_alcohol=i.contains_alcohol,
            )
            for i in minibar
        ],
        ticket_categories=[
            LabelOut(code=c, name_ar=ar, name_en=en) for c, (ar, en) in CATEGORY_LABELS.items()
        ],
        ticket_priorities=[
            LabelOut(code=p, name_ar=ar, name_en=en) for p, (ar, en) in PRIORITY_LABELS.items()
        ],
        task_kinds=[
            LabelOut(code=k, name_ar=ar, name_en=en) for k, (ar, en) in TASK_KIND_LABELS.items()
        ],
        block_reasons=[
            LabelOut(code=c, name_ar=ar, name_en=en) for c, ar, en in BLOCK_REASONS
        ],
        dnd_snooze_minutes=hk.DND_SNOOZE_MINUTES,
        dnd_escalate_after=hk.DND_ESCALATE_AFTER,
    )


@router.get(
    "/board",
    response_model=BoardOut,
    summary="جولة اليوم",
    dependencies=[Depends(require("field.clean", "field.fix", "housekeeping.view"))],
)
def board(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    business_date: date | None = Query(default=None, alias="date"),
    all_staff: bool = Query(default=False, description="السوبرفايزر بيشوف الكل"),
) -> BoardOut:
    return _build_board(
        db, user, prop.id, business_date or date.today(), mine_only=not all_staff
    )


@router.post(
    "/sync",
    response_model=SyncOut,
    summary="مزامنة الطابور الأوفلاين",
    dependencies=[Depends(require("field.clean", "field.fix"))],
)
def sync(
    payload: SyncIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> SyncOut:
    """بياخد دفعة عمليات اتسجّلت على التليفون ويرد على كل واحدة لوحدها.

    مفيش «كله أو لا شيء» هنا عن قصد: عملية مرفوضة مالهاش لازمة توقف
    باقي شغل اليوم. التليفون بيمسح من طابوره اللي رجع ``APPLIED`` أو
    ``DUPLICATE``، وبيسيب اللي رجع ``FAILED`` للمحاولة الجاية، وبيوري
    الموظف اللي رجع ``REJECTED`` أو ``CONFLICT``.
    """
    actions = [a.model_dump() for a in payload.actions]
    results = hk.apply_batch(
        db, user, prop.id, actions, device_id=payload.device_id
    )

    counts = {"applied": 0, "duplicates": 0, "rejected": 0}
    for result in results:
        if result.outcome == SyncOutcome.APPLIED:
            counts["applied"] += 1
        elif result.outcome == SyncOutcome.DUPLICATE:
            counts["duplicates"] += 1
        else:
            counts["rejected"] += 1

    return SyncOut(
        server_time=hk.utcnow(),
        applied=counts["applied"],
        duplicates=counts["duplicates"],
        rejected=counts["rejected"],
        results=[SyncResultOut(**asdict(r)) for r in results],
        board=_build_board(db, user, prop.id, date.today()),
    )


@router.post(
    "/photos",
    response_model=PhotoUploadOut,
    summary="رفع صورة قبل/بعد",
    dependencies=[Depends(require("field.clean", "field.fix"))],
)
async def upload_photo(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    file: UploadFile = File(..., description="الصورة"),
    client_uuid: str = Form(..., description="معرّف الصورة من التليفون"),
    phase: PhotoPhase = Form(...),
    task_id: int | None = Form(default=None),
    ticket_id: int | None = Form(default=None),
    taken_at: datetime | None = Form(default=None),
    device_id: str | None = Form(default=None),
    note: str | None = Form(default=None),
) -> PhotoUploadOut:
    """رفع صورة واحدة. إعادة الرفع بنفس المعرّف بترجّع نفس الصورة."""
    existing = db.execute(
        select(FieldPhoto).where(FieldPhoto.client_uuid == client_uuid)
    ).scalar_one_or_none()
    if existing is not None:
        task = db.get(HousekeepingTask, existing.task_id) if existing.task_id else None
        return PhotoUploadOut(
            photo=_photo_out(existing, {user.id: user.full_name_ar}),
            created=False,
            task_id=existing.task_id,
            photo_before_count=task.photo_before_count if task else 0,
            photo_after_count=task.photo_after_count if task else 0,
        )

    data = await file.read()
    now = hk.utcnow()
    try:
        stored = media.store(
            data,
            property_id=prop.id,
            year=now.year,
            month=now.month,
            content_type=file.content_type or "image/jpeg",
        )
    except media.MediaError as error:
        raise HTTPException(
            400, {"ar": error.message_ar, "en": error.message_en, "code": error.code}
        )

    try:
        photo, created = hk.attach_photo(
            db, user, prop.id,
            client_uuid=client_uuid,
            phase=phase,
            stored_path=stored.path,
            thumb_path=stored.thumb_path,
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            content_type=file.content_type or "image/jpeg",
            width=stored.width,
            height=stored.height,
            task_id=task_id,
            ticket_id=ticket_id,
            taken_at=taken_at,
            device_id=device_id,
            note=note,
        )
    except hk.HousekeepingError as error:
        raise HTTPException(
            404, {"ar": error.message_ar, "en": error.message_en, "code": error.code}
        )

    task = db.get(HousekeepingTask, photo.task_id) if photo.task_id else None
    return PhotoUploadOut(
        photo=_photo_out(photo, {user.id: user.full_name_ar}),
        created=created,
        task_id=photo.task_id,
        photo_before_count=task.photo_before_count if task else 0,
        photo_after_count=task.photo_after_count if task else 0,
    )


@router.get(
    "/photos/{photo_id}",
    summary="عرض صورة",
    dependencies=[Depends(require("field.clean", "field.fix", "housekeeping.view"))],
)
def get_photo(
    photo_id: int,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    thumb: bool = Query(default=False),
) -> FileResponse:
    photo = db.get(FieldPhoto, photo_id)
    if photo is None or photo.property_id != prop.id:
        raise HTTPException(404, {"ar": "الصورة غير موجودة", "en": "Photo not found"})

    relative = photo.thumb_path if (thumb and photo.thumb_path) else photo.storage_path
    try:
        path = media.resolve(relative)
    except media.MediaError as error:
        raise HTTPException(404, {"ar": error.message_ar, "en": error.message_en})

    return FileResponse(
        path,
        media_type="image/jpeg" if thumb else photo.content_type,
        # الصور محتواها ثابت (الاسم بصمتها) فالكاش الطويل آمن
        headers={"Cache-Control": "private, max-age=604800"},
    )


# ═════════════════════════════════════════════ إدارة الجولة (سوبرفايزر)
class GenerateIn(ApiModel):
    business_date: date | None = None
    assign: bool = True


class GenerateOut(ApiModel):
    business_date: date
    created: int
    existing: int
    by_kind: dict[str, int]
    assigned: int
    housekeepers: int


@router.post(
    "/generate",
    response_model=GenerateOut,
    summary="توليد مهام اليوم وتوزيعها",
    dependencies=[Depends(require("housekeeping.update"))],
)
def generate(
    payload: GenerateIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> GenerateOut:
    business_date = payload.business_date or date.today()
    result = hk.generate_day(db, prop.id, business_date)
    assigned: dict[int, int] = {}
    if payload.assign:
        assigned = hk.auto_assign(db, prop.id, business_date)
    return GenerateOut(
        business_date=business_date,
        created=result.created,
        existing=result.existing,
        by_kind={str(k): v for k, v in result.by_kind.items()},
        assigned=len(assigned),
        housekeepers=len(set(assigned.values())),
    )


class SupervisorBoardOut(ApiModel):
    business_date: date
    total: int
    pending: int
    in_progress: int
    dnd: int
    blocked: int
    done: int
    inspected: int
    skipped: int
    unassigned: int
    escalated: int
    minutes_planned: int
    minutes_worked: int
    photos: int
    tasks: list[TaskOut]


@router.get(
    "/supervisor",
    response_model=SupervisorBoardOut,
    summary="لوحة السوبرفايزر",
    dependencies=[Depends(require("housekeeping.view"))],
)
def supervisor_board(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    business_date: date | None = Query(default=None, alias="date"),
) -> SupervisorBoardOut:
    business_date = business_date or date.today()
    summary = hk.board(db, prop.id, business_date)
    full = _build_board(db, user, prop.id, business_date, mine_only=False)
    return SupervisorBoardOut(
        business_date=business_date,
        total=summary.total,
        pending=summary.pending,
        in_progress=summary.in_progress,
        dnd=summary.dnd,
        blocked=summary.blocked,
        done=summary.done,
        inspected=summary.inspected,
        skipped=summary.skipped,
        unassigned=summary.unassigned,
        escalated=summary.escalated,
        minutes_planned=summary.minutes_planned,
        minutes_worked=summary.minutes_worked,
        photos=summary.photos,
        tasks=full.tasks,
    )


class AssignIn(ApiModel):
    user_id: int


@router.patch(
    "/tasks/{task_id}/assign",
    response_model=TaskOut,
    summary="إسناد مهمة لموظف",
    dependencies=[Depends(require("housekeeping.update"))],
)
def assign_task(
    task_id: int,
    payload: AssignIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> TaskOut:
    task = db.get(HousekeepingTask, task_id)
    if task is None or task.property_id != prop.id:
        raise HTTPException(404, {"ar": "المهمة غير موجودة", "en": "Task not found"})
    target = db.get(User, payload.user_id)
    if target is None or target.property_id != prop.id:
        raise HTTPException(404, {"ar": "الموظف غير موجود", "en": "User not found"})

    task.assigned_to_user_id = target.id
    task.assigned_at = hk.utcnow()
    db.flush()

    board = _build_board(db, user, prop.id, task.task_date, mine_only=False)
    for row in board.tasks:
        if row.id == task.id:
            return row
    raise HTTPException(404, {"ar": "المهمة غير موجودة", "en": "Task not found"})


class TimelineEntry(ApiModel):
    kind: str
    happened_at: datetime
    received_at: datetime
    offline_seconds: int
    user_name: str | None = None
    note: str | None = None
    payload: dict[str, Any] | None = None


@router.get(
    "/tasks/{task_id}/timeline",
    response_model=list[TimelineEntry],
    summary="سجل المهمة",
    dependencies=[Depends(require("housekeeping.view"))],
)
def timeline(
    task_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> list[TimelineEntry]:
    """اللي حصل في المهمة بالترتيب — بوقت الحدث مش بوقت وصوله."""
    from app.models.tasks import TaskEvent

    task = db.get(HousekeepingTask, task_id)
    if task is None or task.property_id != prop.id:
        raise HTTPException(404, {"ar": "المهمة غير موجودة", "en": "Task not found"})

    names = {
        u.id: u.full_name_ar
        for u in db.execute(
            select(User).where(User.property_id == prop.id)
        ).scalars().all()
    }
    events = db.execute(
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id)
        .order_by(TaskEvent.happened_at, TaskEvent.id)
    ).scalars().all()

    return [
        TimelineEntry(
            kind=e.kind,
            happened_at=e.happened_at,
            received_at=e.received_at,
            offline_seconds=e.offline_seconds,
            user_name=names.get(e.user_id or 0),
            note=e.note,
            payload=e.payload,
        )
        for e in events
    ]
