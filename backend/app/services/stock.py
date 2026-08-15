"""حركة المخزن والتقييم — Stock movements and valuation.

قاعدتين محكومتين في الملف ده:

**١. الحركة مبتتمسحش.** ``stock_movement`` جدول append-only. الغلط
بيتصحّح بحركة تسوية معاكسة ليها سبب مكتوب — يعني كشف الحركة بيفضل
يحكي اللي حصل فعلاً، بما فيه الغلط وتصحيحه.

**٢. الرصيد نسخة محسوبة.** ``stock_level`` بيتحدّث مع كل حركة عشان
السرعة، لكنه مش مصدر الحقيقة. ``rebuild_levels`` بيبنيه من الصفر من
الحركات، فلو حصل أي اختلاف فيه مرجع واحد صحيح نرجعله.

التقييم **متوسط مرجّح**: كل استلام بيحرّك متوسط التكلفة بنسبة الكمية.
اخترناه بدل FIFO لأنه بيدّي رقم واحد مفهوم للمالك، ولأن مخزون مطعم
بيدور بسرعة فالفرق بين الطريقتين بيبقى صغير.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.types import QUANTITY_SCALE
from app.models.enums import INBOUND_MOVEMENTS, MovementKind
from app.models.security import User
from app.models.stock import StockItem, StockLevel, StockMovement, Warehouse
from app.services.pricing import money

ZERO = Decimal("0")


class StockError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "stock_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def qty(value: Decimal | float | str | None) -> Decimal:
    if value is None:
        return ZERO
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(QUANTITY_SCALE)


# ═══════════════════════════════════════════════════════ الرصيد
def get_level(db: Session, warehouse_id: int, stock_item_id: int) -> StockLevel | None:
    return db.execute(
        select(StockLevel).where(
            StockLevel.warehouse_id == warehouse_id,
            StockLevel.stock_item_id == stock_item_id,
        )
    ).scalar_one_or_none()


def _ensure_level(
    db: Session, property_id: int, warehouse_id: int, stock_item_id: int
) -> StockLevel:
    level = get_level(db, warehouse_id, stock_item_id)
    if level is None:
        level = StockLevel(
            property_id=property_id,
            warehouse_id=warehouse_id,
            stock_item_id=stock_item_id,
            quantity=ZERO,
            value=ZERO,
        )
        db.add(level)
        db.flush()
    return level


def on_hand(db: Session, stock_item_id: int, warehouse_id: int | None = None) -> Decimal:
    """الرصيد في مخزن معيّن أو في كل المخازن."""
    stmt = select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(
        StockLevel.stock_item_id == stock_item_id
    )
    if warehouse_id is not None:
        stmt = stmt.where(StockLevel.warehouse_id == warehouse_id)
    return qty(db.execute(stmt).scalar_one())


# ═══════════════════════════════════════════════════════ الحركة
def record(
    db: Session,
    property_id: int,
    *,
    warehouse_id: int,
    stock_item_id: int,
    kind: MovementKind,
    quantity: Decimal,
    unit_cost: Decimal | None = None,
    business_date: date | None = None,
    reason: str | None = None,
    purchase_order_id: int | None = None,
    pos_order_id: int | None = None,
    user: User | None = None,
    allow_negative: bool = False,
) -> StockMovement:
    """بيسجّل حركة ويحدّث الرصيد والتكلفة في نفس المعاملة.

    ``allow_negative`` بيتسمح بيه في حالة واحدة: صرف الوصفات. المطبخ
    بيطبخ حتى لو المخزن مسجّل صفر بالغلط، والحقيقة إن الأكل اتصرف —
    فبنسجّلها ونسيب الرصيد بالسالب كإشارة إن فيه استلام ناقص، بدل ما
    نمنع البيع أو نبلع الحركة.
    """
    quantity = qty(quantity)
    if quantity <= 0:
        raise StockError("الكمية لازم تكون أكبر من صفر", "Quantity must be positive", "bad_qty")

    item = db.get(StockItem, stock_item_id)
    if item is None or item.property_id != property_id:
        raise StockError("الصنف غير موجود", "Stock item not found", "not_found")

    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None or warehouse.property_id != property_id:
        raise StockError("المخزن غير موجود", "Warehouse not found", "not_found")

    level = _ensure_level(db, property_id, warehouse_id, stock_item_id)
    inbound = kind in INBOUND_MOVEMENTS
    signed = quantity if inbound else -quantity

    if not inbound and not allow_negative and level.quantity < quantity:
        raise StockError(
            f"الرصيد مش كفاية — المتاح {level.quantity} {item.unit}",
            f"Not enough stock — {level.quantity} {item.unit} available",
            "insufficient",
        )

    cost = money(unit_cost if unit_cost is not None else item.average_cost)

    if inbound:
        # متوسط مرجّح: القيمة الجديدة على الكمية الجديدة
        new_quantity = level.quantity + quantity
        new_value = money(level.value + quantity * cost)
        level.quantity = qty(new_quantity)
        level.value = new_value
        if new_quantity > 0:
            item.average_cost = money(new_value / new_quantity)
        if kind == MovementKind.PURCHASE:
            item.last_purchase_cost = cost
    else:
        # الصرف بيخرج بمتوسط التكلفة الحالي، فالمتوسط مبيتغيّرش
        cost = money(item.average_cost)
        level.quantity = qty(level.quantity + signed)
        level.value = money(max(ZERO, level.value - quantity * cost))

    level.last_movement_at = utcnow()

    movement = StockMovement(
        property_id=property_id,
        warehouse_id=warehouse_id,
        stock_item_id=stock_item_id,
        kind=kind,
        quantity=quantity,
        unit_cost=cost,
        total_cost=money(quantity * cost),
        balance_after=level.quantity,
        business_date=business_date or date.today(),
        created_at=utcnow(),
        purchase_order_id=purchase_order_id,
        pos_order_id=pos_order_id,
        reason=(reason or "").strip()[:300] or None,
        created_by_user_id=user.id if user else None,
    )
    db.add(movement)
    db.flush()
    return movement


def transfer(
    db: Session,
    property_id: int,
    *,
    from_warehouse_id: int,
    to_warehouse_id: int,
    stock_item_id: int,
    quantity: Decimal,
    reason: str | None = None,
    user: User | None = None,
    business_date: date | None = None,
) -> tuple[StockMovement, StockMovement]:
    """تحويل بين مخزنين — حركتين مربوطتين ببعض.

    الخروج الأول: لو المخزن الأول مفيهوش الكمية، مفيش حاجة بتتحرك خالص.
    """
    if from_warehouse_id == to_warehouse_id:
        raise StockError(
            "مينفعش تحوّل لنفس المخزن", "Cannot transfer to the same warehouse", "same_warehouse"
        )

    out = record(
        db,
        property_id,
        warehouse_id=from_warehouse_id,
        stock_item_id=stock_item_id,
        kind=MovementKind.TRANSFER_OUT,
        quantity=quantity,
        reason=reason,
        user=user,
        business_date=business_date,
    )
    into = record(
        db,
        property_id,
        warehouse_id=to_warehouse_id,
        stock_item_id=stock_item_id,
        kind=MovementKind.TRANSFER_IN,
        quantity=quantity,
        unit_cost=out.unit_cost,
        reason=reason,
        user=user,
        business_date=business_date,
    )
    out.counterpart_id = into.id
    into.counterpart_id = out.id
    db.flush()
    return out, into


def adjust_to(
    db: Session,
    property_id: int,
    *,
    warehouse_id: int,
    stock_item_id: int,
    counted_quantity: Decimal,
    reason: str,
    user: User | None = None,
    business_date: date | None = None,
) -> StockMovement | None:
    """تسوية بعد الجرد — بنسجّل **الفرق** مش الرقم الجديد.

    كده كشف الحركة بيقول «الجرد لقى ناقص 2 كيلو» بدل ما يقول «الرصيد
    بقى 8»، والفرق ده هو اللي بيتحسب عليه الهالك.
    """
    if not reason.strip():
        raise StockError("سبب التسوية مطلوب", "A reason is required", "no_reason")

    counted = qty(counted_quantity)
    if counted < 0:
        raise StockError("الجرد مينفعش بالسالب", "Counted quantity cannot be negative", "bad_qty")

    level = _ensure_level(db, property_id, warehouse_id, stock_item_id)
    difference = counted - level.quantity
    if difference == 0:
        level.last_counted_at = utcnow()
        db.flush()
        return None

    movement = record(
        db,
        property_id,
        warehouse_id=warehouse_id,
        stock_item_id=stock_item_id,
        kind=MovementKind.ADJUSTMENT if difference > 0 else MovementKind.WASTE,
        quantity=abs(difference),
        business_date=business_date,
        reason=reason,
        user=user,
        allow_negative=True,
    )
    # التسوية بالزيادة بتدخل كوارد، فالرصيد بيوصل للمعدود بالظبط
    level.quantity = counted
    level.value = money(counted * (db.get(StockItem, stock_item_id).average_cost))
    level.last_counted_at = utcnow()
    movement.balance_after = counted
    db.flush()
    return movement


def rebuild_levels(db: Session, property_id: int) -> int:
    """بناء الأرصدة من الحركات — الحكم النهائي لو حصل أي اختلاف."""
    rows = db.execute(
        select(
            StockMovement.warehouse_id,
            StockMovement.stock_item_id,
            StockMovement.kind,
            func.sum(StockMovement.quantity),
        )
        .where(StockMovement.property_id == property_id)
        .group_by(
            StockMovement.warehouse_id, StockMovement.stock_item_id, StockMovement.kind
        )
    ).all()

    totals: dict[tuple[int, int], Decimal] = {}
    for warehouse_id, item_id, kind, total in rows:
        key = (warehouse_id, item_id)
        amount = qty(total)
        totals[key] = totals.get(key, ZERO) + (
            amount if kind in INBOUND_MOVEMENTS else -amount
        )

    costs = dict(
        db.execute(
            select(StockItem.id, StockItem.average_cost).where(
                StockItem.property_id == property_id
            )
        ).all()
    )

    touched = 0
    for (warehouse_id, item_id), total in totals.items():
        level = _ensure_level(db, property_id, warehouse_id, item_id)
        level.quantity = qty(total)
        level.value = money(max(ZERO, total) * Decimal(str(costs.get(item_id, 0))))
        touched += 1
    db.flush()
    return touched


# ═══════════════════════════════════════════════════════ التنبيهات
@dataclass(slots=True)
class LowStock:
    item: StockItem
    on_hand: Decimal
    reorder_level: Decimal
    shortfall: Decimal


def low_stock(db: Session, property_id: int) -> list[LowStock]:
    """الأصناف اللي تحت حد إعادة الطلب — مرتّبة بالأخطر."""
    items = list(
        db.execute(
            select(StockItem).where(
                StockItem.property_id == property_id,
                StockItem.is_active.is_(True),
                StockItem.reorder_level > 0,
            )
        ).scalars().all()
    )
    if not items:
        return []

    levels = dict(
        db.execute(
            select(StockLevel.stock_item_id, func.sum(StockLevel.quantity))
            .where(StockLevel.property_id == property_id)
            .group_by(StockLevel.stock_item_id)
        ).all()
    )

    rows = []
    for item in items:
        held = qty(levels.get(item.id, 0))
        if held < item.reorder_level:
            rows.append(
                LowStock(
                    item=item,
                    on_hand=held,
                    reorder_level=item.reorder_level,
                    shortfall=qty(item.reorder_level - held),
                )
            )
    rows.sort(key=lambda r: (r.on_hand / r.reorder_level) if r.reorder_level else 0)
    return rows


@dataclass(slots=True)
class StockValue:
    warehouse_id: int | None
    items: int
    quantity: Decimal
    value: Decimal


def valuation(db: Session, property_id: int) -> list[StockValue]:
    """قيمة المخزون لكل مخزن — الرقم اللي بيروح للميزانية."""
    rows = db.execute(
        select(
            StockLevel.warehouse_id,
            func.count(StockLevel.id),
            func.coalesce(func.sum(StockLevel.quantity), 0),
            func.coalesce(func.sum(StockLevel.value), 0),
        )
        .where(StockLevel.property_id == property_id, StockLevel.quantity != 0)
        .group_by(StockLevel.warehouse_id)
    ).all()

    out = [
        StockValue(
            warehouse_id=warehouse_id,
            items=int(count),
            quantity=qty(total_qty),
            value=money(Decimal(str(total_value))),
        )
        for warehouse_id, count, total_qty, total_value in rows
    ]
    out.append(
        StockValue(
            warehouse_id=None,
            items=sum(x.items for x in out),
            quantity=qty(sum((x.quantity for x in out), ZERO)),
            value=money(sum((x.value for x in out), ZERO)),
        )
    )
    return out


def ledger(
    db: Session,
    property_id: int,
    *,
    stock_item_id: int | None = None,
    warehouse_id: int | None = None,
    kinds: Sequence[MovementKind] | None = None,
    since: date | None = None,
    limit: int = 100,
) -> list[StockMovement]:
    stmt = select(StockMovement).where(StockMovement.property_id == property_id)
    if stock_item_id:
        stmt = stmt.where(StockMovement.stock_item_id == stock_item_id)
    if warehouse_id:
        stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
    if kinds:
        stmt = stmt.where(StockMovement.kind.in_(list(kinds)))
    if since:
        stmt = stmt.where(StockMovement.business_date >= since)
    return list(
        db.execute(stmt.order_by(StockMovement.id.desc()).limit(limit)).scalars().all()
    )
