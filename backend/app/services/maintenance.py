"""الصيانة والميني بار — Maintenance tickets and minibar posting.

الفكرة المحورية: **التذكرة هي اللي بتحجب الوحدة وهي اللي بتفكّها.**

الوحدة مبتتحجبش بإيد حد في شاشة تانية، وبترجع للبيع **أوتوماتيك** أول ما
التذكرة تتقفل. ده اللي بيمنع الحالة الشائعة: وحدة قاعدة مقفولة أسبوعين
على عطل اتصلّح من زمان ومحدش فتحها تاني.

وبنحفظ الحالة اللي كانت عليها قبل الحجب، فبترجع لحالتها بالظبط — مش
لحالة افتراضية.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    OPEN_TICKET_STATUSES,
    ChargeKind,
    HousekeepingStatus,
    TicketCategory,
    TicketPriority,
    TicketSource,
    TicketStatus,
    UnitCondition,
)
from app.models.folio import Folio
from app.models.maintenance import MaintenanceTicket, MinibarItem
from app.models.security import User
from app.models.units import Unit
from app.services import folio as folio_svc
from app.services import sequences
from app.services.pricing import money

#: المهلة الافتراضية للإصلاح حسب الأولوية — بالساعات
DUE_HOURS: dict[TicketPriority, int] = {
    TicketPriority.URGENT: 2,
    TicketPriority.HIGH: 8,
    TicketPriority.NORMAL: 48,
    TicketPriority.LOW: 168,
}


class MaintenanceError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "maintenance_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════ فتح تذكرة
def open_ticket(
    db: Session,
    property_id: int,
    *,
    title: str,
    unit_id: int | None = None,
    location: str | None = None,
    category: TicketCategory = TicketCategory.OTHER,
    priority: TicketPriority = TicketPriority.NORMAL,
    source: TicketSource = TicketSource.STAFF,
    description: str | None = None,
    blocks_unit: bool = False,
    folio_id: int | None = None,
    user: User | None = None,
) -> MaintenanceTicket:
    """فتح بلاغ. لو ``blocks_unit`` الوحدة بتتشال من البيع فوراً."""
    if not title.strip():
        raise MaintenanceError("عنوان البلاغ مطلوب", "A title is required", "no_title")
    if unit_id is None and not (location or "").strip():
        raise MaintenanceError(
            "لازم تحدد وحدة أو مكان",
            "Specify a unit or a location",
            "no_place",
        )

    unit = None
    if unit_id is not None:
        unit = db.get(Unit, unit_id)
        if unit is None or unit.property_id != property_id:
            raise MaintenanceError("الوحدة غير موجودة", "Unit not found", "not_found")

    now = utcnow()
    ticket = MaintenanceTicket(
        number=sequences.next_number(db, property_id, "TICKET"),
        property_id=property_id,
        unit_id=unit_id,
        location=(location or "").strip() or None,
        category=category,
        priority=priority,
        status=TicketStatus.OPEN,
        source=source,
        title=title.strip()[:200],
        description=(description or "").strip() or None,
        blocks_unit=blocks_unit and unit is not None,
        folio_id=folio_id,
        reported_by_user_id=user.id if user else None,
        opened_at=now,
        due_at=now + timedelta(hours=DUE_HOURS.get(priority, 48)),
    )

    if ticket.blocks_unit and unit is not None:
        # بنحفظ الحالة القديمة عشان ترجعلها بالظبط لما التذكرة تتقفل.
        #
        # بس مش بنحفظ «صيانة» أبداً: لو الوحدة محجوبة أصلاً ببلاغ تاني،
        # يبقى دي مش حالتها الطبيعية — دي أثر بلاغ. لو حفظناها، آخر بلاغ
        # يتقفل هيرجّع الوحدة لحالة «صيانة» وتفضل مقفولة للأبد.
        if unit.condition != UnitCondition.MAINTENANCE:
            ticket.previous_condition = unit.condition
        unit.condition = UnitCondition.MAINTENANCE
        unit.block_reason = ticket.title

    db.add(ticket)
    db.flush()
    return ticket


# ═══════════════════════════════════════════════════ دورة حياة التذكرة
def assign(db: Session, ticket_id: int, user_id: int) -> MaintenanceTicket:
    ticket = _live_ticket(db, ticket_id)
    technician = db.get(User, user_id)
    if technician is None:
        raise MaintenanceError("الفني غير موجود", "User not found", "not_found")

    ticket.assigned_to_user_id = user_id
    ticket.assigned_at = utcnow()
    if ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.ASSIGNED
    db.flush()
    return ticket


def start(db: Session, ticket_id: int) -> MaintenanceTicket:
    ticket = _live_ticket(db, ticket_id)
    if ticket.assigned_to_user_id is None:
        raise MaintenanceError(
            "التذكرة لسه مسندتش لحد", "Assign the ticket first", "not_assigned"
        )
    ticket.status = TicketStatus.IN_PROGRESS
    ticket.started_at = ticket.started_at or utcnow()
    db.flush()
    return ticket


def complete(
    db: Session,
    ticket_id: int,
    *,
    resolution: str,
    cost: Decimal | None = None,
) -> MaintenanceTicket:
    """قفل التذكرة — والوحدة بترجع للبيع لوحدها.

    بترجع **متسخة** مش نضيفة عن قصد: الفني كان شغّال جواها، فمحتاجة
    مرور هاوس كيبينج قبل ما نزيل يدخلها.
    """
    ticket = _live_ticket(db, ticket_id)
    if not resolution.strip():
        raise MaintenanceError(
            "اكتب اتعمل إيه", "Describe what was done", "no_resolution"
        )

    ticket.status = TicketStatus.DONE
    ticket.completed_at = utcnow()
    ticket.resolution = resolution.strip()[:1000]
    ticket.cost = money(cost or Decimal("0"))
    _unblock(db, ticket)
    db.flush()
    return ticket


def cancel(db: Session, ticket_id: int, reason: str) -> MaintenanceTicket:
    ticket = _live_ticket(db, ticket_id)
    if not reason.strip():
        raise MaintenanceError("سبب الإلغاء مطلوب", "A reason is required", "no_reason")
    ticket.status = TicketStatus.CANCELLED
    ticket.completed_at = utcnow()
    ticket.cancelled_reason = reason.strip()[:300]
    _unblock(db, ticket)
    db.flush()
    return ticket


def _live_ticket(db: Session, ticket_id: int) -> MaintenanceTicket:
    ticket = db.get(MaintenanceTicket, ticket_id)
    if ticket is None:
        raise MaintenanceError("التذكرة غير موجودة", "Ticket not found", "not_found")
    if ticket.status in (TicketStatus.DONE, TicketStatus.CANCELLED):
        raise MaintenanceError(
            "التذكرة مقفولة بالفعل", "Ticket is already closed", "closed"
        )
    return ticket


def _unblock(db: Session, ticket: MaintenanceTicket) -> None:
    """فك حجب الوحدة — بشرط مفيش تذكرة تانية لسه حاجباها."""
    if not ticket.blocks_unit or ticket.unit_id is None:
        return

    still_blocked = db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.unit_id == ticket.unit_id,
            MaintenanceTicket.id != ticket.id,
            MaintenanceTicket.blocks_unit.is_(True),
            MaintenanceTicket.status.in_(list(OPEN_TICKET_STATUSES)),
        )
    ).scalar_one()
    if still_blocked:
        return  # فيه عطل تاني لسه مفتوح — الوحدة تفضل مقفولة

    unit = db.get(Unit, ticket.unit_id)
    if unit is None:
        return
    unit.condition = ticket.previous_condition or UnitCondition.OPERATIONAL
    unit.block_reason = None
    # الفني كان جوّه — الوحدة محتاجة تنضيف قبل ما تتباع
    unit.housekeeping_status = HousekeepingStatus.DIRTY


# ═══════════════════════════════════════════════════════════ اللوحة
@dataclass(slots=True)
class TicketBoard:
    open: int
    assigned: int
    in_progress: int
    done_today: int
    overdue: int
    urgent: int
    blocked_units: int
    cost_this_month: Decimal


def board(db: Session, property_id: int) -> TicketBoard:
    now = utcnow()
    today = date.today()

    def count(*where) -> int:
        return db.execute(
            select(func.count(MaintenanceTicket.id)).where(
                MaintenanceTicket.property_id == property_id, *where
            )
        ).scalar_one()

    month_cost = db.execute(
        select(func.coalesce(func.sum(MaintenanceTicket.cost), 0)).where(
            MaintenanceTicket.property_id == property_id,
            MaintenanceTicket.completed_at.is_not(None),
            MaintenanceTicket.completed_at >= datetime(today.year, today.month, 1, tzinfo=timezone.utc),
        )
    ).scalar_one()

    return TicketBoard(
        open=count(MaintenanceTicket.status == TicketStatus.OPEN),
        assigned=count(MaintenanceTicket.status == TicketStatus.ASSIGNED),
        in_progress=count(MaintenanceTicket.status == TicketStatus.IN_PROGRESS),
        done_today=count(
            MaintenanceTicket.status == TicketStatus.DONE,
            MaintenanceTicket.completed_at
            >= datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
        ),
        overdue=count(
            MaintenanceTicket.status.in_(list(OPEN_TICKET_STATUSES)),
            MaintenanceTicket.due_at.is_not(None),
            MaintenanceTicket.due_at < now,
        ),
        urgent=count(
            MaintenanceTicket.status.in_(list(OPEN_TICKET_STATUSES)),
            MaintenanceTicket.priority == TicketPriority.URGENT,
        ),
        blocked_units=count(
            MaintenanceTicket.status.in_(list(OPEN_TICKET_STATUSES)),
            MaintenanceTicket.blocks_unit.is_(True),
        ),
        cost_this_month=money(Decimal(str(month_cost))),
    )


# ═══════════════════════════════════════════════════════════ الميني بار
def catalog(db: Session, property_id: int) -> list[MinibarItem]:
    return list(
        db.execute(
            select(MinibarItem)
            .where(MinibarItem.property_id == property_id, MinibarItem.is_active.is_(True))
            .order_by(MinibarItem.sort_order, MinibarItem.id)
        ).scalars().all()
    )


def post_consumption(
    db: Session,
    property_id: int,
    folio_id: int,
    lines: Sequence[tuple[int, Decimal]],
    *,
    user: User | None = None,
    business_date: date | None = None,
) -> Decimal:
    """ترحيل استهلاك الميني بار على حساب النزيل.

    بيمشي على نفس مسار ترحيل البنود العادي — يعني بيدخل الفاتورة
    والتقارير والضريبة من غير أي استثناء.
    """
    folio = db.get(Folio, folio_id)
    if folio is None or folio.property_id != property_id:
        raise MaintenanceError("الحساب غير موجود", "Folio not found", "not_found")

    items = {i.id: i for i in catalog(db, property_id)}
    total = Decimal("0")
    posted = 0

    for item_id, quantity in lines:
        if quantity <= 0:
            continue
        item = items.get(item_id)
        if item is None:
            raise MaintenanceError(
                "صنف مش موجود في الميني بار", "Unknown minibar item", "unknown_item"
            )
        amount = money(item.price * quantity)
        folio_svc.post_charge(
            db,
            folio_id,
            charge_kind=ChargeKind.MINIBAR,
            description_ar=f"ميني بار — {item.name_ar}",
            description_en=f"Minibar — {item.name_en}",
            quantity=quantity,
            amount=amount,
            business_date=business_date or date.today(),
            user_id=user.id if user else None,
        )
        total += amount
        posted += 1

    if not posted:
        raise MaintenanceError("مفيش أصناف متحددة", "No items selected", "empty")

    db.flush()
    return money(total)
