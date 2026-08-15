"""أوامر الشراء والاستلام — Purchase orders and receiving.

الاستلام هو **الحركة الوحيدة اللي بتغيّر تكلفة الأصناف**، وعشان كده
مربوط بأمر شراء وبرقم فاتورة المورد: أي زيادة في التكلفة لها مستند.

الاستلام الجزئي مدعوم من الأول لأنه الواقع — المورد بيبعت 8 كراتين من
10 ويقولك الباقي بكرة. الأمر بيفضل مفتوح على الباقي بدل ما نقفله ونعمل
أمر جديد.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    OPEN_PURCHASE_STATUSES,
    MovementKind,
    PurchaseStatus,
)
from app.models.security import User
from app.models.stock import (
    PurchaseOrder,
    PurchaseOrderLine,
    StockItem,
    Supplier,
    Warehouse,
)
from app.services import sequences
from app.services import stock as stock_svc
from app.services.pricing import money

ZERO = Decimal("0")


class PurchaseError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "purchase_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


# ═══════════════════════════════════════════════════════ الإنشاء
def create_order(
    db: Session,
    property_id: int,
    *,
    supplier_id: int,
    warehouse_id: int,
    lines: Sequence[tuple[int, Decimal, Decimal]],
    expected_date: date | None = None,
    notes: str | None = None,
    user: User | None = None,
) -> PurchaseOrder:
    """أمر شراء جديد — ``lines`` = (رقم الصنف، الكمية، سعر الوحدة)."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.property_id != property_id:
        raise PurchaseError("المورد غير موجود", "Supplier not found", "not_found")

    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None or warehouse.property_id != property_id:
        raise PurchaseError("المخزن غير موجود", "Warehouse not found", "not_found")

    if not lines:
        raise PurchaseError("الأمر لازم يكون فيه صنف واحد على الأقل", "Order is empty", "empty")

    catalog = {
        s.id: s
        for s in db.execute(
            select(StockItem).where(StockItem.property_id == property_id)
        ).scalars().all()
    }

    seen: set[int] = set()
    for stock_item_id, quantity, unit_cost in lines:
        if stock_item_id not in catalog:
            raise PurchaseError("صنف مخزني غير موجود", "Unknown stock item", "unknown_item")
        if quantity <= 0:
            raise PurchaseError(
                "الكمية لازم تكون أكبر من صفر", "Quantity must be positive", "bad_qty"
            )
        if unit_cost < 0:
            raise PurchaseError("السعر مينفعش بالسالب", "Price cannot be negative", "bad_cost")
        if stock_item_id in seen:
            raise PurchaseError("الصنف ده متكرر في الأمر", "Duplicate item", "duplicate")
        seen.add(stock_item_id)

    order = PurchaseOrder(
        number=sequences.next_number(db, property_id, "PURCHASE"),
        property_id=property_id,
        supplier_id=supplier_id,
        warehouse_id=warehouse_id,
        status=PurchaseStatus.DRAFT,
        order_date=date.today(),
        expected_date=expected_date,
        notes=(notes or "").strip() or None,
        created_by_user_id=user.id if user else None,
    )
    db.add(order)
    db.flush()

    for stock_item_id, quantity, unit_cost in lines:
        order.lines.append(
            PurchaseOrderLine(
                purchase_order_id=order.id,
                stock_item_id=stock_item_id,
                quantity_ordered=quantity,
                unit_cost=money(unit_cost),
                line_total=money(quantity * unit_cost),
            )
        )
    _recalculate(order)
    db.flush()
    return order


def _recalculate(order: PurchaseOrder) -> None:
    order.subtotal = money(sum((line.line_total for line in order.lines), ZERO))
    order.grand_total = money(order.subtotal + order.tax_total)


def send(db: Session, order_id: int) -> PurchaseOrder:
    """اعتماد الأمر وإرساله للمورد — بعدها مبيتعدّلش."""
    order = _order(db, order_id)
    if order.status != PurchaseStatus.DRAFT:
        raise PurchaseError(
            "الأمر ده اتبعت بالفعل", "Order was already sent", "already_sent"
        )
    order.status = PurchaseStatus.SENT
    db.flush()
    return order


def cancel(db: Session, order_id: int, reason: str) -> PurchaseOrder:
    order = _order(db, order_id)
    if order.status == PurchaseStatus.RECEIVED:
        raise PurchaseError(
            "الأمر اتستلم بالكامل — مينفعش يتلغي",
            "A fully received order cannot be cancelled",
            "already_received",
        )
    if not reason.strip():
        raise PurchaseError("سبب الإلغاء مطلوب", "A reason is required", "no_reason")
    order.status = PurchaseStatus.CANCELLED
    order.cancelled_reason = reason.strip()[:300]
    db.flush()
    return order


def _order(db: Session, order_id: int) -> PurchaseOrder:
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise PurchaseError("أمر الشراء غير موجود", "Purchase order not found", "not_found")
    if order.status == PurchaseStatus.CANCELLED:
        raise PurchaseError("الأمر ملغي", "Order is cancelled", "cancelled")
    return order


# ═══════════════════════════════════════════════════════ الاستلام
@dataclass(slots=True)
class ReceiveResult:
    order: PurchaseOrder
    received_lines: int
    total_value: Decimal
    fully_received: bool


def receive(
    db: Session,
    property_id: int,
    order_id: int,
    lines: Sequence[tuple[int, Decimal, Decimal | None]],
    *,
    supplier_invoice_number: str | None = None,
    user: User | None = None,
    business_date: date | None = None,
) -> ReceiveResult:
    """استلام كامل أو جزئي — ``lines`` = (رقم السطر، الكمية، السعر الفعلي).

    السعر الفعلي اختياري: المورد أحياناً بيسلّم بسعر غير المتفق عليه،
    والاستلام لازم يسجّل اللي حصل مش اللي كان متوقّع.
    """
    order = _order(db, order_id)
    if order.property_id != property_id:
        raise PurchaseError("أمر الشراء غير موجود", "Purchase order not found", "not_found")
    if order.status == PurchaseStatus.DRAFT:
        raise PurchaseError(
            "لازم تعتمد الأمر الأول", "Send the order before receiving", "not_sent"
        )
    if order.status == PurchaseStatus.RECEIVED:
        raise PurchaseError(
            "الأمر اتستلم بالكامل", "Order is fully received", "already_received"
        )

    by_id = {line.id: line for line in order.lines}
    total = ZERO
    touched = 0

    for line_id, quantity, actual_cost in lines:
        line = by_id.get(line_id)
        if line is None:
            raise PurchaseError("سطر مش من الأمر ده", "Line does not belong here", "bad_line")
        quantity = stock_svc.qty(quantity)
        if quantity <= 0:
            continue
        if quantity > line.outstanding:
            raise PurchaseError(
                f"الكمية أكبر من المتبقي ({line.outstanding})",
                f"Quantity exceeds the outstanding {line.outstanding}",
                "over_receive",
            )

        cost = money(actual_cost if actual_cost is not None else line.unit_cost)
        stock_svc.record(
            db,
            property_id,
            warehouse_id=order.warehouse_id,
            stock_item_id=line.stock_item_id,
            kind=MovementKind.PURCHASE,
            quantity=quantity,
            unit_cost=cost,
            business_date=business_date,
            reason=f"استلام على أمر {order.number}",
            purchase_order_id=order.id,
            user=user,
        )
        line.quantity_received = stock_svc.qty(line.quantity_received + quantity)
        if actual_cost is not None:
            line.unit_cost = cost
            line.line_total = money(line.quantity_ordered * cost)
        total += quantity * cost
        touched += 1

    if not touched:
        raise PurchaseError("ماستلمتش أي كمية", "Nothing was received", "empty")

    if supplier_invoice_number:
        order.supplier_invoice_number = supplier_invoice_number.strip()[:60]

    done = all(line.outstanding == 0 for line in order.lines)
    order.status = PurchaseStatus.RECEIVED if done else PurchaseStatus.PARTIAL
    if done:
        order.received_date = business_date or date.today()
    _recalculate(order)
    db.flush()

    return ReceiveResult(
        order=order,
        received_lines=touched,
        total_value=money(total),
        fully_received=done,
    )


# ═══════════════════════════════════════════════════════ اللوحة
@dataclass(slots=True)
class PurchaseBoard:
    draft: int
    sent: int
    partial: int
    received_this_month: int
    outstanding_value: Decimal
    spend_this_month: Decimal


def board(db: Session, property_id: int) -> PurchaseBoard:
    today = date.today()
    month_start = date(today.year, today.month, 1)

    def count(*where) -> int:
        return db.execute(
            select(func.count(PurchaseOrder.id)).where(
                PurchaseOrder.property_id == property_id, *where
            )
        ).scalar_one()

    outstanding = db.execute(
        select(func.coalesce(func.sum(PurchaseOrder.grand_total), 0)).where(
            PurchaseOrder.property_id == property_id,
            PurchaseOrder.status.in_(list(OPEN_PURCHASE_STATUSES)),
        )
    ).scalar_one()

    spend = db.execute(
        select(func.coalesce(func.sum(PurchaseOrder.grand_total), 0)).where(
            PurchaseOrder.property_id == property_id,
            PurchaseOrder.status == PurchaseStatus.RECEIVED,
            PurchaseOrder.received_date >= month_start,
        )
    ).scalar_one()

    return PurchaseBoard(
        draft=count(PurchaseOrder.status == PurchaseStatus.DRAFT),
        sent=count(PurchaseOrder.status == PurchaseStatus.SENT),
        partial=count(PurchaseOrder.status == PurchaseStatus.PARTIAL),
        received_this_month=count(
            PurchaseOrder.status == PurchaseStatus.RECEIVED,
            PurchaseOrder.received_date >= month_start,
        ),
        outstanding_value=money(Decimal(str(outstanding))),
        spend_this_month=money(Decimal(str(spend))),
    )


def suggest_reorder(
    db: Session, property_id: int, supplier_id: int | None = None
) -> list[tuple[StockItem, Decimal]]:
    """اقتراح أمر شراء من الأصناف اللي تحت حد الطلب.

    بيرجّع الكمية المعتادة أو اللي تكفّي توصل لحد الطلب — أيهما أكبر،
    عشان الأمر مايتعملش تاني بعد يومين.
    """
    rows = stock_svc.low_stock(db, property_id)
    out: list[tuple[StockItem, Decimal]] = []
    for row in rows:
        if supplier_id is not None and row.item.preferred_supplier_id != supplier_id:
            continue
        amount = max(row.item.reorder_quantity, row.shortfall)
        if amount > 0:
            out.append((row.item, stock_svc.qty(amount)))
    return out
