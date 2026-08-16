"""مهام الهاوس كيبينج ومحرّك المزامنة الأوفلاين — Housekeeping tasks & offline sync.

الموديول ده بيحل تلات مشاكل مترتبين على بعض:

**١. مين ينضّف إيه؟** المهام بتتولّد من الحجوزات مش من دماغ حد:
مغادرة النهاردة = مهمة، نزيل مقيم = مهمة، وحدة الفني خلص فيها = مهمة.
والتوليد **آمن التكرار** — تشغيله عشر مرات بيدّي نفس القايمة، لأن
القيد ``(unit_id, task_date, kind)`` في الداتابيز هو اللي بيحرسها مش
شرط في الكود.

**٢. الشغل اتعمل فعلاً؟** صورة قبل وصورة بعد. من غيرهم المهمة مبتتقفلش
لو نوعها بيطلبهم. ودي مش بيروقراطية: المغادرة هي اللحظة اللي بينبني
عليها «الوحدة جاهزة للبيع»، ولو الحكم ده غلط النزيل الجاي هو اللي
بيكتشفه.

**٣. الشبكة مش موجودة.** ودي أصعبهم. الهاوس كيبر جوّه شاليه خرسانة على
بحيرة، ومفيش شبكة. التليفون بيسجّل كل حاجة محلياً وبيبعتها لما يطلع
بره. يعني السيرفر بيستقبل أحداث **عمرها ساعتين**، وممكن يستقبلها
مرتين لو الرد ضاع في السكة.

عشان كده كل عملية جاية من التليفون معاها ``client_uuid`` اتولّد على
التليفون **قبل** أول محاولة إرسال. السيرفر بيدوّر عليه الأول: لو
موجود يبقى العملية دي اتنفّذت خلاص، فبيرد ``DUPLICATE`` من غير ما
يلمس حاجة. ده اللي بيخلّي التليفون يعيد الإرسال براحته من غير خوف.

والوقت: بنفرّق بين ``happened_at`` (اللي التليفون سجّله) و``received_at``
(وصولها). التقارير بتقرا من الأول، عشان «الغرفة اتنضفت الساعة ٩» تفضل
تسعة حتى لو الحدث وصل الساعة ١١.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import (
    BLOCKING_RESERVATION_STATUSES,
    CLOSED_TASK_STATUSES,
    LIVE_TASK_STATUSES,
    OPEN_TICKET_STATUSES,
    HousekeepingStatus,
    PhotoPhase,
    ReservationStatus,
    SyncOutcome,
    TaskEventKind,
    TaskKind,
    TaskStatus,
    TicketCategory,
    TicketPriority,
    TicketSource,
    TicketStatus,
    UnitCondition,
)
from app.models.maintenance import MaintenanceTicket
from app.models.reservations import ReservationUnit
from app.models.security import User
from app.models.tasks import FieldPhoto, HousekeepingTask, TaskEvent
from app.models.units import Unit, UnitCategory, UnitStatusLog

#: الوقت المتوقّع لكل نوع — بالدقايق. الأرقام دي من الواقع مش من الكتب:
#: تنضيف مغادرة شاليه بياخد ٤٥ دقيقة، وترتيب نزيل مقيم ١٥.
EXPECTED_MINUTES: dict[TaskKind, int] = {
    TaskKind.DEPARTURE: 45,
    TaskKind.ARRIVAL_PREP: 20,
    TaskKind.STAYOVER: 15,
    TaskKind.TURNDOWN: 10,
    TaskKind.DEEP: 90,
    TaskKind.POST_MAINTENANCE: 35,
    TaskKind.INSPECTION: 8,
}

#: ترتيب الجولة. أقل رقم = الأول. المغادرة الأول لأن فيه نزيل جاي عليها
#: النهاردة، والتنضيف العميق آخر حاجة لأن الوحدة مش هتتباع دلوقتي.
PRIORITY: dict[TaskKind, int] = {
    TaskKind.DEPARTURE: 10,
    TaskKind.ARRIVAL_PREP: 20,
    TaskKind.POST_MAINTENANCE: 30,
    TaskKind.STAYOVER: 50,
    TaskKind.TURNDOWN: 60,
    TaskKind.INSPECTION: 70,
    TaskKind.DEEP: 90,
}

#: الأنواع اللي بتطلب صور قبل وبعد. الترتيب اليومي لنزيل مقيم مش محتاج
#: — النزيل جوّه وحاجاته مبعترة، والصورة هنا اقتحام مش إثبات.
PHOTOS_REQUIRED: frozenset[TaskKind] = frozenset(
    {TaskKind.DEPARTURE, TaskKind.DEEP, TaskKind.POST_MAINTENANCE}
)

#: «عدم إزعاج» بترجع بعد الفترة دي. ساعة كفاية إن النزيل يكون خرج.
DND_SNOOZE_MINUTES = 60

#: بعد كام محاولة «عدم إزعاج» نبلّغ الاستقبال. تلاتة يعني اليوم قرب
#: يخلص والوحدة لسه مش متنضفة — ده قرار إدارة مش قرار الهاوس كيبر.
DND_ESCALATE_AFTER = 3

#: أقصى فرق مقبول بين ساعة التليفون وساعة السيرفر. فوقه بنعتبر ساعة
#: التليفون غلط وبناخد وقت السيرفر — تليفون رخيص بساعة متقدّمة يوم
#: كامل ميعملش مهمة «اتقفلت بكرة».
MAX_CLOCK_SKEW = timedelta(hours=6)


class HousekeepingError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "housekeeping_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════ توليد مهام اليوم
@dataclass(slots=True)
class GenerationResult:
    business_date: date
    created: int = 0
    existing: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)


def generate_day(
    db: Session, property_id: int, business_date: date | None = None
) -> GenerationResult:
    """يبني قايمة مهام اليوم من الحجوزات وحالة الوحدات.

    آمن التكرار: المهمة الموجودة مبتتعملش تاني ومبتتعدّلش. ده مقصود —
    لو الهاوس كيبر بدأ في مهمة والنايت أوديت اتشغّل تاني، مينفعش شغله
    يترجّع لـ ``PENDING``.
    """
    business_date = business_date or date.today()
    result = GenerationResult(business_date=business_date)

    units = {
        u.id: u
        for u in db.execute(
            select(Unit).where(Unit.property_id == property_id, Unit.is_active.is_(True))
        ).scalars().all()
    }
    if not units:
        return result

    existing = {
        (row.unit_id, row.kind): row
        for row in db.execute(
            select(HousekeepingTask).where(
                HousekeepingTask.property_id == property_id,
                HousekeepingTask.task_date == business_date,
            )
        ).scalars().all()
    }

    stays = db.execute(
        select(ReservationUnit).where(
            ReservationUnit.property_id == property_id,
            ReservationUnit.unit_id.isnot(None),
            ReservationUnit.arrival_date <= business_date,
            ReservationUnit.departure_date >= business_date,
            ReservationUnit.status.in_(
                list(BLOCKING_RESERVATION_STATUSES) + [ReservationStatus.CHECKED_OUT]
            ),
        )
    ).scalars().all()

    departures = {s.unit_id for s in stays if s.departure_date == business_date}
    stayovers = {
        s.unit_id
        for s in stays
        if s.arrival_date < business_date < s.departure_date
    }
    arrivals = {
        row[0]
        for row in db.execute(
            select(ReservationUnit.unit_id).where(
                ReservationUnit.property_id == property_id,
                ReservationUnit.unit_id.isnot(None),
                ReservationUnit.arrival_date == business_date,
                ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
            )
        ).all()
    }

    # الوحدات اللي الفني خلص فيها النهاردة — بترجع متسخة عن قصد
    freed = {
        row[0]
        for row in db.execute(
            select(MaintenanceTicket.unit_id).where(
                MaintenanceTicket.property_id == property_id,
                MaintenanceTicket.unit_id.isnot(None),
                MaintenanceTicket.status == TicketStatus.DONE,
                MaintenanceTicket.blocks_unit.is_(True),
                MaintenanceTicket.completed_at.isnot(None),
                MaintenanceTicket.completed_at
                >= datetime.combine(business_date, datetime.min.time(), tzinfo=timezone.utc),
            )
        ).all()
    }

    plan: list[tuple[int, TaskKind]] = []
    for unit_id in sorted(departures):
        plan.append((unit_id, TaskKind.DEPARTURE))
    for unit_id in sorted(arrivals - departures):
        # الوصول اللي عليه مغادرة نفس اليوم متغطّي بمهمة المغادرة — مهمتين
        # على نفس الغرفة في نفس اليوم بتخلّي الهاوس كيبر يدخلها مرتين
        unit = units.get(unit_id)
        if unit and unit.housekeeping_status != HousekeepingStatus.INSPECTED:
            plan.append((unit_id, TaskKind.ARRIVAL_PREP))
    for unit_id in sorted(stayovers - departures):
        plan.append((unit_id, TaskKind.STAYOVER))
    for unit_id in sorted(freed - departures - arrivals):
        plan.append((unit_id, TaskKind.POST_MAINTENANCE))

    # وحدات فاضية ومتسخة ومحدش حاجزها — دي بتتنسى عادةً لحد ما نزيل
    # يقف على بابها. بندّيها مهمة تنضيف عميق بأقل أولوية.
    busy = departures | stayovers | arrivals | freed
    for unit_id, unit in sorted(units.items()):
        if unit_id in busy:
            continue
        if (
            unit.housekeeping_status == HousekeepingStatus.DIRTY
            and unit.condition == UnitCondition.OPERATIONAL
        ):
            plan.append((unit_id, TaskKind.DEEP))

    for unit_id, kind in plan:
        if (unit_id, kind) in existing:
            result.existing += 1
            continue
        task = HousekeepingTask(
            property_id=property_id,
            unit_id=unit_id,
            task_date=business_date,
            kind=kind,
            status=TaskStatus.PENDING,
            priority=PRIORITY.get(kind, 50),
            expected_minutes=EXPECTED_MINUTES.get(kind, 30),
            photos_required=kind in PHOTOS_REQUIRED,
        )
        # savepoint مش transaction: لو القيد اتكسر، اللي بيترجع هو الصف ده
        # بس — مش كل المهام اللي اتعملت قبله في نفس التشغيلة.
        savepoint = db.begin_nested()
        db.add(task)
        try:
            db.flush()
            savepoint.commit()
        except IntegrityError:
            # سباق: النايت أوديت والسوبرفايزر ضغطوا في نفس اللحظة. القيد
            # في الداتابيز مسك الموضوع — بنكمل عادي.
            savepoint.rollback()
            result.existing += 1
            continue
        result.created += 1
        result.by_kind[kind] = result.by_kind.get(kind, 0) + 1
        db.add(
            TaskEvent(
                property_id=property_id,
                task_id=task.id,
                unit_id=unit_id,
                kind=TaskEventKind.CREATED,
                client_uuid=f"gen:{property_id}:{unit_id}:{business_date}:{kind}",
                happened_at=utcnow(),
                received_at=utcnow(),
            )
        )

    db.flush()
    return result


# ═══════════════════════════════════════════════════════ توزيع الجولات
def auto_assign(
    db: Session,
    property_id: int,
    business_date: date | None = None,
    *,
    housekeepers: Sequence[User] | None = None,
) -> dict[int, int]:
    """يوزّع المهام غير المسندة على الهاوس كيبرز — بالمنطقة مش بالعدد.

    التوزيع بالعدد بيدّي أرقام متساوية وجولات وحشة: واحد بياخد شاليه
    على البحيرة وواحد جنبه وواحد في آخر القرية. بنجمّع مهام المنطقة
    الواحدة مع بعض الأول، وبعدين بنوازن بالوقت المتوقّع مش بعدد المهام
    — لأن مغادرة واحدة بتساوي تلات ترتيبات.
    """
    business_date = business_date or date.today()
    people = list(housekeepers or _active_housekeepers(db, property_id))
    if not people:
        return {}

    rows = db.execute(
        select(HousekeepingTask, Unit)
        .join(Unit, Unit.id == HousekeepingTask.unit_id)
        .where(
            HousekeepingTask.property_id == property_id,
            HousekeepingTask.task_date == business_date,
            HousekeepingTask.assigned_to_user_id.is_(None),
            HousekeepingTask.status.in_(list(LIVE_TASK_STATUSES)),
        )
        .order_by(HousekeepingTask.priority, Unit.zone_ar, Unit.sort_order)
    ).all()
    if not rows:
        return {}

    # الحمل الحالي لكل واحد — التوزيع بيكمّل على اللي موجود مش بيبدأ من صفر
    load: dict[int, int] = {u.id: 0 for u in people}
    for user_id, minutes in db.execute(
        select(
            HousekeepingTask.assigned_to_user_id,
            func.coalesce(func.sum(HousekeepingTask.expected_minutes), 0),
        )
        .where(
            HousekeepingTask.property_id == property_id,
            HousekeepingTask.task_date == business_date,
            HousekeepingTask.assigned_to_user_id.isnot(None),
            HousekeepingTask.status.in_(list(LIVE_TASK_STATUSES)),
        )
        .group_by(HousekeepingTask.assigned_to_user_id)
    ).all():
        if user_id in load:
            load[user_id] = int(minutes or 0)

    zones: dict[str, list[tuple[HousekeepingTask, Unit]]] = {}
    for task, unit in rows:
        zones.setdefault(unit.zone_ar or unit.building or "—", []).append((task, unit))

    assigned: dict[int, int] = {}
    now = utcnow()
    # المنطقة الأتقل الأول، وبتروح لأخف واحد — كده الجولات بتفضل مجمّعة
    for _zone, items in sorted(
        zones.items(), key=lambda kv: -sum(t.expected_minutes for t, _ in kv[1])
    ):
        for task, _unit in items:
            target = min(load, key=lambda uid: (load[uid], uid))
            task.assigned_to_user_id = target
            task.assigned_at = now
            load[target] += task.expected_minutes
            assigned[task.id] = target
            db.add(
                TaskEvent(
                    property_id=property_id,
                    task_id=task.id,
                    unit_id=task.unit_id,
                    kind=TaskEventKind.ASSIGNED,
                    client_uuid=f"assign:{task.id}:{target}",
                    happened_at=now,
                    received_at=now,
                    user_id=target,
                    payload={"minutes": task.expected_minutes},
                )
            )

    db.flush()
    return assigned


def _active_housekeepers(db: Session, property_id: int) -> list[User]:
    """المستخدمون اللي بيتوزّع عليهم الشغل فعلاً.

    الصلاحية لوحدها مش كفاية: المالك والمدير عندهم كل الصلاحيات بحكم
    الدور، ولو وزّعنا بالصلاحية بس هيلاقوا غرف في تليفوناتهم. القاعدة
    هنا: **اللي بينضّف هو اللي مش بيراجع** — يعني عنده ``field.clean``
    ومعندوش ``housekeeping.update``. ولو مفيش حد كده (قرية صغيرة
    والسوبرفايزر بينضّف بنفسه)، بنرجع لأي حد عنده صلاحية التنضيف.
    """
    users = [
        u
        for u in db.execute(
            select(User).where(User.property_id == property_id, User.is_active.is_(True))
        ).scalars().all()
        if u.has_permission("field.clean")
    ]
    line_staff = [
        u for u in users if not u.has_permission("housekeeping.update") and not u.is_superuser
    ]
    return line_staff or users


# ═══════════════════════════════════════════════════════ دورة المهمة
def _log(
    db: Session,
    task: HousekeepingTask,
    kind: TaskEventKind,
    *,
    client_uuid: str,
    happened_at: datetime,
    user: User | None,
    payload: dict[str, Any] | None = None,
    device_id: str | None = None,
    note: str | None = None,
) -> TaskEvent:
    received = utcnow()
    event = TaskEvent(
        property_id=task.property_id,
        task_id=task.id,
        unit_id=task.unit_id,
        kind=kind,
        client_uuid=client_uuid,
        device_id=device_id,
        happened_at=happened_at,
        received_at=received,
        offline_seconds=max(0, int((received - happened_at).total_seconds())),
        user_id=user.id if user else None,
        payload=payload,
        note=note,
    )
    db.add(event)
    return event


def normalize_time(client_time: datetime | None) -> datetime:
    """وقت التليفون بعد ما نتأكد إنه معقول.

    التليفون الرخيص ساعته بتضيع. لو الفرق أكبر من الحد المسموح بناخد
    وقت السيرفر — أحسن من مهمة مسجّلة إنها اتقفلت بكرة.
    """
    now = utcnow()
    if client_time is None:
        return now
    if client_time.tzinfo is None:
        client_time = client_time.replace(tzinfo=timezone.utc)
    if abs(client_time - now) > MAX_CLOCK_SKEW:
        return now
    # وقت في المستقبل غلط دايماً — مفيش حدث اتسجّل قبل ما يحصل
    return min(client_time, now)


def start(
    db: Session,
    task: HousekeepingTask,
    user: User,
    *,
    at: datetime | None = None,
    client_uuid: str,
    device_id: str | None = None,
) -> HousekeepingTask:
    if task.status in CLOSED_TASK_STATUSES:
        raise HousekeepingError(
            "المهمة اتقفلت خلاص", "Task is already closed", "closed"
        )
    moment = normalize_time(at)
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = task.started_at or moment
    task.snoozed_until = None
    if task.assigned_to_user_id is None:
        # اللي بدأ هو اللي عليها — بيحصل لما حد يلقط مهمة مش متوزّعة
        task.assigned_to_user_id = user.id
        task.assigned_at = moment

    unit = db.get(Unit, task.unit_id)
    if unit is not None and unit.housekeeping_status != HousekeepingStatus.CLEANING:
        _set_unit_status(db, unit, HousekeepingStatus.CLEANING, user, "بدأ التنضيف")

    _log(
        db, task, TaskEventKind.STARTED,
        client_uuid=client_uuid, happened_at=moment, user=user, device_id=device_id,
    )
    db.flush()
    return task


def complete(
    db: Session,
    task: HousekeepingTask,
    user: User,
    *,
    at: datetime | None = None,
    client_uuid: str,
    device_id: str | None = None,
    linen_changed: bool = False,
    amenities_restocked: bool = False,
    minibar_checked: bool = False,
    note: str | None = None,
) -> HousekeepingTask:
    """قفل المهمة — والوحدة بتبقى نضيفة.

    الصور شرط لو نوع المهمة بيطلبها. الرفض هنا مقصود إنه يحصل على
    السيرفر كمان مش على التليفون بس: التليفون ممكن يتعدّل، والسيرفر لأ.
    """
    if task.status in CLOSED_TASK_STATUSES:
        raise HousekeepingError("المهمة اتقفلت خلاص", "Task is already closed", "closed")
    if task.photos_required:
        if task.photo_before_count < 1:
            raise HousekeepingError(
                "لازم صورة قبل ما تبدأ", "A 'before' photo is required", "no_before_photo"
            )
        if task.photo_after_count < 1:
            raise HousekeepingError(
                "لازم صورة بعد ما تخلص", "An 'after' photo is required", "no_after_photo"
            )

    moment = normalize_time(at)
    task.started_at = task.started_at or moment
    task.completed_at = moment
    task.status = TaskStatus.DONE
    task.linen_changed = linen_changed
    task.amenities_restocked = amenities_restocked
    task.minibar_checked = minibar_checked
    if note:
        task.note = note.strip()[:500]
    task.working_seconds = _working_seconds(db, task)

    unit = db.get(Unit, task.unit_id)
    if unit is not None:
        _set_unit_status(db, unit, HousekeepingStatus.CLEAN, user, "خلص التنضيف")

    _log(
        db, task, TaskEventKind.COMPLETED,
        client_uuid=client_uuid, happened_at=moment, user=user, device_id=device_id,
        payload={
            "linen": linen_changed,
            "amenities": amenities_restocked,
            "minibar": minibar_checked,
            "seconds": task.working_seconds,
        },
        note=note,
    )
    db.flush()
    return task


def report_dnd(
    db: Session,
    task: HousekeepingTask,
    user: User,
    *,
    at: datetime | None = None,
    client_uuid: str,
    device_id: str | None = None,
    snooze_minutes: int = DND_SNOOZE_MINUTES,
    note: str | None = None,
) -> HousekeepingTask:
    """«عدم إزعاج» — المهمة بتتأجّل مش بتتلغي.

    الفرق ده مهم: الوحدة لسه محتاجة تنضيف، والقرية لسه عندها التزام
    ناحية النزيل الجاي. بنعدّ المحاولات، وبعد تلاتة الموضوع بيطلع من
    إيد الهاوس كيبر ويبقى قرار استقبال.
    """
    if task.status in CLOSED_TASK_STATUSES:
        raise HousekeepingError("المهمة اتقفلت خلاص", "Task is already closed", "closed")

    moment = normalize_time(at)
    task.status = TaskStatus.DND
    task.dnd_attempts += 1
    task.last_dnd_at = moment
    task.snoozed_until = moment + timedelta(minutes=max(5, snooze_minutes))

    _log(
        db, task, TaskEventKind.DND,
        client_uuid=client_uuid, happened_at=moment, user=user, device_id=device_id,
        payload={"attempt": task.dnd_attempts, "until": task.snoozed_until.isoformat()},
        note=note,
    )
    db.flush()
    return task


def block(
    db: Session,
    task: HousekeepingTask,
    user: User,
    *,
    reason: str,
    at: datetime | None = None,
    client_uuid: str,
    device_id: str | None = None,
) -> HousekeepingTask:
    """مش قادر يدخل لسبب غير «عدم إزعاج» — الباب مقفول، مفيش مية، إلخ."""
    if not reason.strip():
        raise HousekeepingError("اكتب السبب", "A reason is required", "no_reason")
    if task.status in CLOSED_TASK_STATUSES:
        raise HousekeepingError("المهمة اتقفلت خلاص", "Task is already closed", "closed")

    moment = normalize_time(at)
    task.status = TaskStatus.BLOCKED
    task.blocked_reason = reason.strip()[:300]
    _log(
        db, task, TaskEventKind.BLOCKED,
        client_uuid=client_uuid, happened_at=moment, user=user, device_id=device_id,
        note=reason,
    )
    db.flush()
    return task


def inspect(
    db: Session,
    task: HousekeepingTask,
    user: User,
    *,
    score: int,
    at: datetime | None = None,
    client_uuid: str,
    device_id: str | None = None,
    note: str | None = None,
) -> HousekeepingTask:
    """فحص السوبرفايزر. أقل من ٣ = المهمة بترجع للطابور."""
    if task.status not in (TaskStatus.DONE, TaskStatus.INSPECTED, TaskStatus.REJECTED):
        raise HousekeepingError(
            "المهمة لسه ماخلصتش", "Task is not finished yet", "not_done"
        )
    score = max(1, min(5, int(score)))
    moment = normalize_time(at)
    task.inspected_by_user_id = user.id
    task.inspected_at = moment
    task.inspection_score = score
    task.inspection_note = (note or "").strip()[:500] or None

    unit = db.get(Unit, task.unit_id)
    if score >= 3:
        task.status = TaskStatus.INSPECTED
        if unit is not None:
            _set_unit_status(db, unit, HousekeepingStatus.INSPECTED, user, "اتفحصت")
        kind = TaskEventKind.INSPECTED
    else:
        # الرفض بيرجّع الوحدة متسخة — لأن الحكم «نضيفة» اتلغى
        task.status = TaskStatus.REJECTED
        task.completed_at = None
        if unit is not None:
            _set_unit_status(db, unit, HousekeepingStatus.DIRTY, user, "الفحص رفضها")
        kind = TaskEventKind.REJECTED

    _log(
        db, task, kind,
        client_uuid=client_uuid, happened_at=moment, user=user, device_id=device_id,
        payload={"score": score}, note=note,
    )
    db.flush()
    return task


def skip(
    db: Session,
    task: HousekeepingTask,
    user: User,
    *,
    reason: str,
    at: datetime | None = None,
    client_uuid: str,
    device_id: str | None = None,
) -> HousekeepingTask:
    if not reason.strip():
        raise HousekeepingError("اكتب السبب", "A reason is required", "no_reason")
    moment = normalize_time(at)
    task.status = TaskStatus.SKIPPED
    task.blocked_reason = reason.strip()[:300]
    _log(
        db, task, TaskEventKind.SKIPPED,
        client_uuid=client_uuid, happened_at=moment, user=user, device_id=device_id,
        note=reason,
    )
    db.flush()
    return task


def _working_seconds(db: Session, task: HousekeepingTask) -> int:
    """الزمن الصافي — الوقفات (عدم إزعاج) متشالة.

    بنحسبه من سجل الأحداث مش من الفرق بين البداية والنهاية، عشان
    مهمة اتأجّلت ساعتين لعدم إزعاج متطلعش وكأنها خدت ساعتين شغل.
    """
    if task.started_at is None or task.completed_at is None:
        return 0
    events = db.execute(
        select(TaskEvent)
        .where(TaskEvent.task_id == task.id)
        .order_by(TaskEvent.happened_at, TaskEvent.id)
    ).scalars().all()

    total = 0
    running_from: datetime | None = None
    for event in events:
        if event.kind in (TaskEventKind.STARTED, TaskEventKind.RESUMED):
            running_from = running_from or event.happened_at
        elif event.kind in (TaskEventKind.DND, TaskEventKind.PAUSED, TaskEventKind.BLOCKED):
            if running_from is not None:
                total += int((event.happened_at - running_from).total_seconds())
                running_from = None
    if running_from is not None:
        total += int((task.completed_at - running_from).total_seconds())
    elif total == 0:
        total = int((task.completed_at - task.started_at).total_seconds())
    return max(0, total)


def _set_unit_status(
    db: Session,
    unit: Unit,
    status: HousekeepingStatus,
    user: User | None,
    note: str,
) -> None:
    before = unit.housekeeping_status
    if before == status:
        return
    unit.housekeeping_status = status
    db.add(
        UnitStatusLog(
            created_at=utcnow(),
            unit_id=unit.id,
            property_id=unit.property_id,
            from_housekeeping=before,
            to_housekeeping=status,
            from_condition=unit.condition,
            to_condition=unit.condition,
            changed_by_user_id=user.id if user else None,
            source="FIELD_APP",
            note=note,
        )
    )


# ═══════════════════════════════════════════════════════════ القوايم
@dataclass(slots=True)
class TaskView:
    task: HousekeepingTask
    unit: Unit
    category: UnitCategory


def day_tasks(
    db: Session,
    property_id: int,
    business_date: date | None = None,
    *,
    user_id: int | None = None,
    include_closed: bool = True,
) -> list[TaskView]:
    business_date = business_date or date.today()
    query = (
        select(HousekeepingTask, Unit, UnitCategory)
        .join(Unit, Unit.id == HousekeepingTask.unit_id)
        .join(UnitCategory, UnitCategory.id == Unit.category_id)
        .where(
            HousekeepingTask.property_id == property_id,
            HousekeepingTask.task_date == business_date,
        )
        .order_by(HousekeepingTask.priority, Unit.zone_ar, Unit.sort_order)
    )
    if user_id is not None:
        query = query.where(HousekeepingTask.assigned_to_user_id == user_id)
    if not include_closed:
        query = query.where(HousekeepingTask.status.in_(list(LIVE_TASK_STATUSES)))

    return [TaskView(task=t, unit=u, category=c) for t, u, c in db.execute(query).all()]


@dataclass(slots=True)
class DayBoard:
    business_date: date
    total: int = 0
    pending: int = 0
    in_progress: int = 0
    dnd: int = 0
    blocked: int = 0
    done: int = 0
    inspected: int = 0
    skipped: int = 0
    unassigned: int = 0
    escalated: int = 0
    minutes_planned: int = 0
    minutes_worked: int = 0
    photos: int = 0


def board(db: Session, property_id: int, business_date: date | None = None) -> DayBoard:
    business_date = business_date or date.today()
    tasks = db.execute(
        select(HousekeepingTask).where(
            HousekeepingTask.property_id == property_id,
            HousekeepingTask.task_date == business_date,
        )
    ).scalars().all()

    result = DayBoard(business_date=business_date, total=len(tasks))
    for task in tasks:
        result.minutes_planned += task.expected_minutes
        result.minutes_worked += task.working_seconds // 60
        if task.assigned_to_user_id is None and task.status in LIVE_TASK_STATUSES:
            result.unassigned += 1
        if task.dnd_attempts >= DND_ESCALATE_AFTER and task.status not in CLOSED_TASK_STATUSES:
            result.escalated += 1
        match task.status:
            case TaskStatus.PENDING | TaskStatus.REJECTED:
                result.pending += 1
            case TaskStatus.IN_PROGRESS:
                result.in_progress += 1
            case TaskStatus.DND:
                result.dnd += 1
            case TaskStatus.BLOCKED:
                result.blocked += 1
            case TaskStatus.DONE:
                result.done += 1
            case TaskStatus.INSPECTED:
                result.inspected += 1
            case TaskStatus.SKIPPED:
                result.skipped += 1

    result.photos = db.execute(
        select(func.count(FieldPhoto.id))
        .join(HousekeepingTask, HousekeepingTask.id == FieldPhoto.task_id)
        .where(
            HousekeepingTask.property_id == property_id,
            HousekeepingTask.task_date == business_date,
        )
    ).scalar_one()
    return result


# ═══════════════════════════════════════════════ محرّك المزامنة الأوفلاين
@dataclass(slots=True)
class ActionResult:
    uuid: str
    type: str
    outcome: SyncOutcome
    task_id: int | None = None
    ticket_id: int | None = None
    status: str | None = None
    message_ar: str | None = None
    message_en: str | None = None
    code: str | None = None


def _seen(db: Session, client_uuid: str) -> TaskEvent | None:
    return db.execute(
        select(TaskEvent).where(TaskEvent.client_uuid == client_uuid)
    ).scalar_one_or_none()


def apply_batch(
    db: Session,
    user: User,
    property_id: int,
    actions: Iterable[dict[str, Any]],
    *,
    device_id: str | None = None,
) -> list[ActionResult]:
    """ينفّذ دفعة عمليات جاية من الطابور المحلي للتليفون.

    كل عملية جوّه ``savepoint`` لوحدها. يعني عملية وحشة في نص الدفعة
    بتترفض لوحدها والباقي بيعدّي — من غير كده، خطأ واحد كان هيرجّع شغل
    يوم كامل ويخلّي التليفون يفضل يعيد إرسال دفعة مش هتعدي أبداً.
    """
    results: list[ActionResult] = []

    for raw in actions:
        uuid = str(raw.get("uuid") or "").strip()
        kind = str(raw.get("type") or "").strip()
        if not uuid or not kind:
            results.append(
                ActionResult(
                    uuid=uuid or "?", type=kind or "?", outcome=SyncOutcome.REJECTED,
                    message_ar="العملية ناقصة معرّف", message_en="Missing action id",
                    code="malformed",
                )
            )
            continue

        previous = _seen(db, uuid)
        if previous is not None:
            task = db.get(HousekeepingTask, previous.task_id) if previous.task_id else None
            results.append(
                ActionResult(
                    uuid=uuid, type=kind, outcome=SyncOutcome.DUPLICATE,
                    task_id=previous.task_id, ticket_id=previous.ticket_id,
                    status=task.status if task else None,
                )
            )
            continue

        savepoint = db.begin_nested()
        try:
            result = _apply_one(
                db, user, property_id, uuid, kind, raw, device_id=device_id
            )
            savepoint.commit()
        except HousekeepingError as error:
            savepoint.rollback()
            result = ActionResult(
                uuid=uuid, type=kind,
                outcome=SyncOutcome.CONFLICT if error.code in ("closed", "not_done")
                else SyncOutcome.REJECTED,
                task_id=_int(raw.get("task_id")),
                message_ar=error.message_ar, message_en=error.message_en,
                code=error.code,
            )
            task = db.get(HousekeepingTask, _int(raw.get("task_id")) or 0)
            if task is not None:
                result.status = task.status
        except Exception as error:  # pragma: no cover - خطأ فني
            savepoint.rollback()
            result = ActionResult(
                uuid=uuid, type=kind, outcome=SyncOutcome.FAILED,
                task_id=_int(raw.get("task_id")),
                message_ar="خطأ في السيرفر", message_en=str(error)[:200],
                code="server_error",
            )
        results.append(result)

    db.flush()
    return results


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _task_for(db: Session, task_id: int | None, property_id: int, user: User) -> HousekeepingTask:
    task = db.get(HousekeepingTask, task_id) if task_id else None
    if task is None or task.property_id != property_id:
        raise HousekeepingError("المهمة غير موجودة", "Task not found", "not_found")
    # الهاوس كيبر بيشتغل على مهامه بس. السوبرفايزر بيقدر على الكل.
    if (
        task.assigned_to_user_id is not None
        and task.assigned_to_user_id != user.id
        and not user.has_permission("housekeeping.update")
    ):
        raise HousekeepingError(
            "المهمة دي مش عليك", "This task is assigned to someone else", "not_yours"
        )
    return task


def _apply_one(
    db: Session,
    user: User,
    property_id: int,
    uuid: str,
    kind: str,
    raw: dict[str, Any],
    *,
    device_id: str | None,
) -> ActionResult:
    payload: dict[str, Any] = raw.get("payload") or {}
    at = _parse_time(raw.get("at"))
    task_id = _int(raw.get("task_id"))

    match kind:
        case "task.start":
            task = _task_for(db, task_id, property_id, user)
            start(db, task, user, at=at, client_uuid=uuid, device_id=device_id)

        case "task.complete":
            task = _task_for(db, task_id, property_id, user)
            complete(
                db, task, user, at=at, client_uuid=uuid, device_id=device_id,
                linen_changed=bool(payload.get("linen_changed")),
                amenities_restocked=bool(payload.get("amenities_restocked")),
                minibar_checked=bool(payload.get("minibar_checked")),
                note=payload.get("note"),
            )

        case "task.dnd":
            task = _task_for(db, task_id, property_id, user)
            report_dnd(
                db, task, user, at=at, client_uuid=uuid, device_id=device_id,
                snooze_minutes=_int(payload.get("snooze_minutes")) or DND_SNOOZE_MINUTES,
                note=payload.get("note"),
            )

        case "task.block":
            task = _task_for(db, task_id, property_id, user)
            block(
                db, task, user, reason=str(payload.get("reason") or ""),
                at=at, client_uuid=uuid, device_id=device_id,
            )

        case "task.skip":
            task = _task_for(db, task_id, property_id, user)
            if not user.has_permission("housekeeping.update"):
                raise HousekeepingError(
                    "إلغاء المهمة قرار سوبرفايزر",
                    "Skipping a task needs a supervisor",
                    "forbidden",
                )
            skip(
                db, task, user, reason=str(payload.get("reason") or ""),
                at=at, client_uuid=uuid, device_id=device_id,
            )

        case "task.inspect":
            task = _task_for(db, task_id, property_id, user)
            if not user.has_permission("housekeeping.update"):
                raise HousekeepingError(
                    "الفحص للسوبرفايزر", "Inspection needs a supervisor", "forbidden"
                )
            inspect(
                db, task, user, score=_int(payload.get("score")) or 5,
                at=at, client_uuid=uuid, device_id=device_id,
                note=payload.get("note"),
            )

        case "task.note":
            task = _task_for(db, task_id, property_id, user)
            text = str(payload.get("note") or "").strip()
            if not text:
                raise HousekeepingError("الملاحظة فاضية", "Empty note", "empty")
            task.note = text[:500]
            _log(
                db, task, TaskEventKind.NOTE, client_uuid=uuid,
                happened_at=normalize_time(at), user=user, device_id=device_id, note=text,
            )

        case "issue.open":
            return _open_issue(
                db, user, property_id, uuid, payload, at=at, task_id=task_id,
                device_id=device_id,
            )

        case "ticket.start" | "ticket.complete":
            return _ticket_action(
                db, user, property_id, uuid, kind, raw, payload, at=at,
                device_id=device_id,
            )

        case "task.minibar":
            return _minibar(
                db, user, property_id, uuid, task_id, payload, at=at, device_id=device_id
            )

        case _:
            raise HousekeepingError(
                f"عملية مش معروفة: {kind}", f"Unknown action: {kind}", "unknown_action"
            )

    db.flush()
    return ActionResult(
        uuid=uuid, type=kind, outcome=SyncOutcome.APPLIED,
        task_id=task.id, status=task.status,
    )


def _open_issue(
    db: Session,
    user: User,
    property_id: int,
    uuid: str,
    payload: dict[str, Any],
    *,
    at: datetime | None,
    task_id: int | None,
    device_id: str | None,
) -> ActionResult:
    """الهاوس كيبر لقى عطل وهو بينضّف — بيفتح تذكرة من التليفون.

    ودي أهم نقطة تكامل في التطبيق كله: البلاغ بيدخل نفس طابور الصيانة
    اللي الاستقبال بيشتغل عليه، مش دفتر جانبي. ولو العطل بيمنع البيع،
    الوحدة بتتشال من الإتاحة **من غير ما حد يفتح شاشة**.
    """
    from app.services import maintenance as mt

    title = str(payload.get("title") or "").strip()
    if not title:
        raise HousekeepingError("اكتب العطل", "Describe the issue", "no_title")

    task = db.get(HousekeepingTask, task_id) if task_id else None
    unit_id = _int(payload.get("unit_id")) or (task.unit_id if task else None)

    try:
        category = TicketCategory(str(payload.get("category") or "OTHER").upper())
    except ValueError:
        category = TicketCategory.OTHER
    try:
        priority = TicketPriority(str(payload.get("priority") or "NORMAL").upper())
    except ValueError:
        priority = TicketPriority.NORMAL

    ticket = mt.open_ticket(
        db, property_id,
        title=title,
        unit_id=unit_id,
        location=payload.get("location"),
        category=category,
        priority=priority,
        source=TicketSource.HOUSEKEEPING,
        description=payload.get("description"),
        blocks_unit=bool(payload.get("blocks_unit")),
        user=user,
    )

    moment = normalize_time(at)
    received = utcnow()
    db.add(
        TaskEvent(
            property_id=property_id,
            task_id=task.id if task else None,
            ticket_id=ticket.id,
            unit_id=unit_id,
            kind=TaskEventKind.ISSUE_REPORTED,
            client_uuid=uuid,
            device_id=device_id,
            happened_at=moment,
            received_at=received,
            offline_seconds=max(0, int((received - moment).total_seconds())),
            user_id=user.id,
            payload={"ticket": ticket.number, "blocks_unit": ticket.blocks_unit},
            note=title,
        )
    )
    if task is not None and task.ticket_id is None:
        task.ticket_id = ticket.id
    db.flush()
    return ActionResult(
        uuid=uuid, type="issue.open", outcome=SyncOutcome.APPLIED,
        task_id=task.id if task else None, ticket_id=ticket.id, status=ticket.status,
    )


def _ticket_action(
    db: Session,
    user: User,
    property_id: int,
    uuid: str,
    kind: str,
    raw: dict[str, Any],
    payload: dict[str, Any],
    *,
    at: datetime | None,
    device_id: str | None,
) -> ActionResult:
    """الفني بيبدأ ويقفل تذكرته من التليفون — نفس مسار شاشة الصيانة."""
    from app.services import maintenance as mt

    ticket_id = _int(raw.get("ticket_id"))
    ticket = db.get(MaintenanceTicket, ticket_id) if ticket_id else None
    if ticket is None or ticket.property_id != property_id:
        raise HousekeepingError("التذكرة غير موجودة", "Ticket not found", "not_found")
    if ticket.status in (TicketStatus.DONE, TicketStatus.CANCELLED):
        raise HousekeepingError("التذكرة اتقفلت خلاص", "Ticket already closed", "closed")
    if (
        ticket.assigned_to_user_id is not None
        and ticket.assigned_to_user_id != user.id
        and not user.has_permission("maintenance.manage")
    ):
        raise HousekeepingError(
            "التذكرة دي مش عليك", "This ticket is assigned to someone else", "not_yours"
        )

    moment = normalize_time(at)
    if kind == "ticket.start":
        if ticket.assigned_to_user_id is None:
            mt.assign(db, ticket.id, user.id)
        mt.start(db, ticket.id)
        event_kind = TaskEventKind.STARTED
    else:
        resolution = str(payload.get("resolution") or "").strip()
        if not resolution:
            raise HousekeepingError(
                "اكتب اتعمل إيه", "Describe what was done", "no_resolution"
            )
        cost_raw = payload.get("cost")
        cost = Decimal(str(cost_raw)) if cost_raw not in (None, "") else Decimal("0")
        mt.complete(db, ticket.id, resolution=resolution, cost=cost)
        event_kind = TaskEventKind.COMPLETED

    received = utcnow()
    db.add(
        TaskEvent(
            property_id=property_id,
            ticket_id=ticket.id,
            unit_id=ticket.unit_id,
            kind=event_kind,
            client_uuid=uuid,
            device_id=device_id,
            happened_at=moment,
            received_at=received,
            offline_seconds=max(0, int((received - moment).total_seconds())),
            user_id=user.id,
            payload={"ticket": ticket.number},
        )
    )
    db.flush()
    return ActionResult(
        uuid=uuid, type=kind, outcome=SyncOutcome.APPLIED,
        ticket_id=ticket.id, status=ticket.status,
    )


def _minibar(
    db: Session,
    user: User,
    property_id: int,
    uuid: str,
    task_id: int | None,
    payload: dict[str, Any],
    *,
    at: datetime | None,
    device_id: str | None,
) -> ActionResult:
    """جرد الميني بار من التليفون — بيترحّل على حساب النزيل فوراً.

    ده الفرق بين ورقة في جيب الهاوس كيبر بتوصل الاستقبال بعد ما النزيل
    مشي، وبين بند على الحساب قبل ما يوصل الريسبشن.
    """
    from app.models.enums import FolioStatus
    from app.models.folio import Folio
    from app.services import maintenance as mt

    task = _task_for(db, task_id, property_id, user)
    lines_raw = payload.get("lines") or []
    lines: list[tuple[int, Decimal]] = []
    for line in lines_raw:
        item_id = _int(line.get("item_id"))
        quantity = Decimal(str(line.get("quantity") or 0))
        if item_id and quantity > 0:
            lines.append((item_id, quantity))

    task.minibar_checked = True
    moment = normalize_time(at)

    if not lines:
        # جرد فاضي = «الميني بار متلمسش». ده معلومة برضه ولازم تتسجّل.
        _log(
            db, task, TaskEventKind.MINIBAR, client_uuid=uuid, happened_at=moment,
            user=user, device_id=device_id, payload={"lines": 0},
        )
        db.flush()
        return ActionResult(
            uuid=uuid, type="task.minibar", outcome=SyncOutcome.APPLIED,
            task_id=task.id, status=task.status,
        )

    folio_id = _int(payload.get("folio_id"))
    if folio_id is None:
        folio = db.execute(
            select(Folio)
            .where(
                Folio.property_id == property_id,
                Folio.unit_id == task.unit_id,
                Folio.status == FolioStatus.OPEN,
            )
            .order_by(Folio.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if folio is None:
            raise HousekeepingError(
                "مفيش حساب مفتوح على الوحدة دي",
                "No open folio for this unit",
                "no_folio",
            )
        folio_id = folio.id

    total = mt.post_consumption(
        db, property_id, folio_id, lines, user=user, business_date=moment.date()
    )
    _log(
        db, task, TaskEventKind.MINIBAR, client_uuid=uuid, happened_at=moment,
        user=user, device_id=device_id,
        payload={"lines": len(lines), "total": str(total), "folio_id": folio_id},
    )
    db.flush()
    return ActionResult(
        uuid=uuid, type="task.minibar", outcome=SyncOutcome.APPLIED,
        task_id=task.id, status=task.status,
    )


# ═══════════════════════════════════════════════════════════ الصور
def attach_photo(
    db: Session,
    user: User,
    property_id: int,
    *,
    client_uuid: str,
    phase: PhotoPhase,
    stored_path: str,
    thumb_path: str | None,
    sha256: str,
    byte_size: int,
    content_type: str,
    width: int | None = None,
    height: int | None = None,
    task_id: int | None = None,
    ticket_id: int | None = None,
    taken_at: datetime | None = None,
    device_id: str | None = None,
    note: str | None = None,
) -> tuple[FieldPhoto, bool]:
    """يربط صورة مرفوعة بمهمة أو تذكرة. بيرجّع ``(الصورة, جديدة؟)``.

    لو نفس ``client_uuid`` وصل قبل كده بنرجّع الصورة القديمة — التليفون
    بيعيد الرفع لما الشبكة تقطع في نص الرفع، والصورة الواحدة عمرها ما
    تتعدّ مرتين في «صور قبل».
    """
    existing = db.execute(
        select(FieldPhoto).where(FieldPhoto.client_uuid == client_uuid)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    task = db.get(HousekeepingTask, task_id) if task_id else None
    if task_id and (task is None or task.property_id != property_id):
        raise HousekeepingError("المهمة غير موجودة", "Task not found", "not_found")

    ticket = db.get(MaintenanceTicket, ticket_id) if ticket_id else None
    if ticket_id and (ticket is None or ticket.property_id != property_id):
        raise HousekeepingError("التذكرة غير موجودة", "Ticket not found", "not_found")

    moment = normalize_time(taken_at)
    now = utcnow()
    photo = FieldPhoto(
        property_id=property_id,
        task_id=task.id if task else None,
        ticket_id=ticket.id if ticket else None,
        unit_id=task.unit_id if task else (ticket.unit_id if ticket else None),
        phase=phase,
        client_uuid=client_uuid,
        sha256=sha256,
        storage_path=stored_path,
        thumb_path=thumb_path,
        content_type=content_type,
        byte_size=byte_size,
        width=width,
        height=height,
        taken_at=moment,
        uploaded_at=now,
        taken_by_user_id=user.id,
        device_id=device_id,
        note=(note or "").strip()[:300] or None,
    )
    db.add(photo)

    if task is not None:
        if phase == PhotoPhase.BEFORE:
            task.photo_before_count += 1
        elif phase == PhotoPhase.AFTER:
            task.photo_after_count += 1
        db.add(
            TaskEvent(
                property_id=property_id,
                task_id=task.id,
                unit_id=task.unit_id,
                kind=TaskEventKind.PHOTO,
                client_uuid=f"photo:{client_uuid}",
                device_id=device_id,
                happened_at=moment,
                received_at=now,
                offline_seconds=max(0, int((now - moment).total_seconds())),
                user_id=user.id,
                payload={"phase": phase, "sha256": sha256[:12]},
            )
        )

    db.flush()
    return photo, True


def photos_for(db: Session, task_id: int) -> list[FieldPhoto]:
    return list(
        db.execute(
            select(FieldPhoto)
            .where(FieldPhoto.task_id == task_id)
            .order_by(FieldPhoto.phase, FieldPhoto.taken_at)
        ).scalars().all()
    )


def open_tickets_for(db: Session, property_id: int, user: User) -> list[MaintenanceTicket]:
    """تذاكر الفني المفتوحة — بتاعته أو المفتوحة اللي لسه محدش خدها."""
    return list(
        db.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.property_id == property_id,
                MaintenanceTicket.status.in_(list(OPEN_TICKET_STATUSES)),
                (MaintenanceTicket.assigned_to_user_id == user.id)
                | (MaintenanceTicket.assigned_to_user_id.is_(None)),
            )
            # الأولوية محفوظة نص، فترتيبها الأبجدي غلط: URGENT قبل NORMAL
            # صدفةً، لكن HIGH بتيجي بعد LOW. بنرتّب بمعناها مش بحروفها.
            .order_by(
                case(
                    {
                        TicketPriority.URGENT: 0,
                        TicketPriority.HIGH: 1,
                        TicketPriority.NORMAL: 2,
                        TicketPriority.LOW: 3,
                    },
                    value=MaintenanceTicket.priority,
                    else_=4,
                ),
                MaintenanceTicket.due_at,
                MaintenanceTicket.id,
            )
            .limit(60)
        ).scalars().all()
    )
