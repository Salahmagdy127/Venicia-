"""منطق نقاط البيع — POS business logic.

القواعد اللي بتحكم الشغل هنا:
- الخصم محكوم بصلاحية الدور، مش بنية الكاشير.
- إلغاء صنف **بعد** ما راح المطبخ بيتسجّل منفصل — ده أهم مؤشر تلاعب.
- الترحيل على الغرفة بيتحقق إن الحساب مفتوح فعلاً قبل ما يرحّل.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    ChargeKind,
    FolioStatus,
    KotStatus,
    OutletType,
    PosOrderStatus,
    PosOrderType,
    SettlementType,
    ShiftStatus,
    TableStatus,
)
from app.models.folio import Folio, FolioLine, Payment
from app.models.enums import PaymentMethod
from app.models.pos import (
    KotTicket,
    MenuItem,
    Outlet,
    PosOrder,
    PosOrderLine,
    PosTable,
    Shift,
)
from app.models.security import User
from app.services.pricing import money
from app.services.sequences import next_number

CAIRO_OFFSET = timedelta(hours=3)


class PosError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "pos_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def business_date_for(prop_start_hour: int = 6, at: datetime | None = None) -> date:
    """اليوم الفندقي — الشغل بعد نص الليل بيتحسب على اليوم اللي فات."""
    moment = (at or utcnow()) + CAIRO_OFFSET
    if moment.hour < prop_start_hour:
        return (moment - timedelta(days=1)).date()
    return moment.date()


# ────────────────────────────────────────────────────────── الورديات
def open_shift(
    db: Session, *, property_id: int, user_id: int, outlet_id: int | None,
    opening_float: Decimal = Decimal("0"),
) -> Shift:
    existing = db.execute(
        select(Shift).where(
            Shift.user_id == user_id,
            Shift.outlet_id == outlet_id,
            Shift.status == ShiftStatus.OPEN,
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    shift = Shift(
        code=next_number(db, property_id, "SHIFT"),
        property_id=property_id,
        outlet_id=outlet_id,
        user_id=user_id,
        business_date=business_date_for(),
        status=ShiftStatus.OPEN,
        opened_at=utcnow(),
        opening_float=opening_float,
    )
    db.add(shift)
    db.flush()
    return shift


def close_shift(
    db: Session, shift_id: int, *, counted_cash: Decimal, counted_card: Decimal,
    user_id: int | None = None, notes: str | None = None,
) -> Shift:
    """تقفيل الدرج ومطابقة العهدة — الفرق هو الرقم اللي بيكشف المشاكل."""
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise PosError("الوردية غير موجودة", "Shift not found", "not_found")
    if shift.status != ShiftStatus.OPEN:
        raise PosError("الوردية مقفولة بالفعل", "Shift is already closed", "already_closed")

    totals = db.execute(
        select(
            PosOrder.settlement_type,
            func.count(PosOrder.id),
            func.sum(PosOrder.grand_total),
        )
        .where(PosOrder.shift_id == shift_id, PosOrder.is_void.is_(False))
        .group_by(PosOrder.settlement_type)
    ).all()

    expected_cash = Decimal("0")
    expected_card = Decimal("0")
    orders_count = 0
    for settlement, count, total in totals:
        orders_count += count or 0
        amount = Decimal(str(total or 0))
        if settlement == SettlementType.CASH:
            expected_cash += amount
        elif settlement == SettlementType.CARD:
            expected_card += amount

    voids = db.execute(
        select(func.count(PosOrder.id)).where(
            PosOrder.shift_id == shift_id, PosOrder.is_void.is_(True)
        )
    ).scalar() or 0
    discounts = db.execute(
        select(func.sum(PosOrder.discount_total)).where(PosOrder.shift_id == shift_id)
    ).scalar() or 0

    shift.expected_cash = money(expected_cash + shift.opening_float)
    shift.expected_card = money(expected_card)
    shift.counted_cash = money(counted_cash)
    shift.counted_card = money(counted_card)
    shift.variance = money(
        (counted_cash + counted_card) - (shift.expected_cash + shift.expected_card)
    )
    shift.orders_count = orders_count
    shift.voids_count = voids
    shift.discounts_total = money(Decimal(str(discounts)))
    shift.status = ShiftStatus.CLOSED
    shift.closed_at = utcnow()
    shift.reconciled_by_user_id = user_id
    shift.notes = notes
    db.flush()
    return shift


# ────────────────────────────────────────────────────────── الأوردرات
def open_order(
    db: Session,
    *,
    property_id: int,
    outlet_id: int,
    user_id: int,
    table_id: int | None = None,
    covers: int = 1,
    order_type: PosOrderType = PosOrderType.DINE_IN,
    folio_id: int | None = None,
    shift_id: int | None = None,
) -> PosOrder:
    outlet = db.get(Outlet, outlet_id)
    if outlet is None or not outlet.is_active:
        raise PosError("المنفذ غير موجود أو موقوف", "Outlet not found or inactive", "not_found")

    table = None
    if table_id is not None:
        table = db.get(PosTable, table_id)
        if table is None or table.outlet_id != outlet_id:
            raise PosError("الطاولة مش في المنفذ ده", "Table is not in this outlet", "bad_table")
        open_on_table = db.execute(
            select(PosOrder).where(
                PosOrder.table_id == table_id,
                PosOrder.status.in_([PosOrderStatus.OPEN, PosOrderStatus.SENT,
                                     PosOrderStatus.SERVED]),
            )
        ).scalar_one_or_none()
        if open_on_table is not None:
            raise PosError(
                f"الطاولة {table.label} عليها أوردر مفتوح بالفعل",
                f"Table {table.label} already has an open order",
                "table_busy",
            )

    order = PosOrder(
        code=next_number(db, property_id, "POS_ORDER", prefix=outlet.order_prefix),
        property_id=property_id,
        outlet_id=outlet_id,
        business_date=business_date_for(),
        order_type=order_type,
        status=PosOrderStatus.OPEN,
        table_id=table_id,
        covers=max(1, covers),
        folio_id=folio_id,
        waiter_user_id=user_id,
        shift_id=shift_id,
        opened_at=utcnow(),
    )
    db.add(order)
    db.flush()

    if table is not None:
        table.status = TableStatus.OCCUPIED
    return order


def add_line(
    db: Session, order_id: int, *, menu_item_id: int, quantity: Decimal, notes: str | None = None
) -> PosOrderLine:
    order = _editable_order(db, order_id)
    item = db.get(MenuItem, menu_item_id)
    if item is None or not item.is_active:
        raise PosError("الصنف غير موجود", "Menu item not found", "not_found")
    if item.is_out_of_stock:
        raise PosError(
            f"{item.name_ar} خلص النهاردة", f"{item.name_en} is out of stock", "out_of_stock"
        )
    if quantity <= 0:
        raise PosError("الكمية لازم تكون أكبر من صفر", "Quantity must be positive", "bad_quantity")

    line = PosOrderLine(
        created_at=utcnow(),
        property_id=order.property_id,
        outlet_id=order.outlet_id,
        business_date=order.business_date,
        menu_item_id=item.id,
        # لقطة من الصنف وقت البيع — الفاتورة القديمة تفضل زي ما اتطبعت
        item_name_ar=item.name_ar,
        item_name_en=item.name_en,
        kitchen_station_id=item.kitchen_station_id,
        quantity=quantity,
        unit_price=item.price,
        unit_cost=item.cost,
        line_total=money(item.price * quantity),
        notes=notes,
        kot_status=KotStatus.PENDING,
    )
    # الإضافة عن طريق العلاقة مش ``db.add`` — عشان القايمة المحمّلة في الذاكرة
    # تشوف السطر الجديد فوراً، وإلا الإجمالي بيتحسب ناقص صنف.
    order.lines.append(line)
    db.flush()
    recalculate(db, order)
    return line


def void_line(
    db: Session, order_id: int, line_id: int, *, reason: str, user_id: int
) -> PosOrderLine:
    """إلغاء صنف. لو كان راح المطبخ بالفعل، بيتعلّم منفصل كمؤشر تلاعب."""
    order = _editable_order(db, order_id)
    line = db.get(PosOrderLine, line_id)
    if line is None or line.order_id != order.id:
        raise PosError("السطر غير موجود", "Line not found", "not_found")
    if line.is_void:
        raise PosError("السطر ملغي بالفعل", "Line is already void", "already_void")
    if not reason or not reason.strip():
        raise PosError("لازم تكتب سبب الإلغاء", "A void reason is required", "reason_required")

    line.is_void = True
    line.void_reason = reason.strip()
    line.voided_by_user_id = user_id
    line.voided_after_send = line.kot_status != KotStatus.PENDING
    line.kot_status = KotStatus.CANCELLED
    db.flush()
    recalculate(db, order)
    return line


def send_to_kitchen(db: Session, order_id: int) -> list[KotTicket]:
    """إرسال الأصناف الجديدة للمطبخ — تذكرة لكل محطة تحضير."""
    order = _editable_order(db, order_id)

    pending = [
        l for l in order.lines
        if not l.is_void and l.kot_status == KotStatus.PENDING
    ]
    if not pending:
        raise PosError(
            "مفيش أصناف جديدة تتبعت", "No new items to send", "nothing_to_send"
        )

    by_station: dict[int | None, list[PosOrderLine]] = {}
    for line in pending:
        by_station.setdefault(line.kitchen_station_id, []).append(line)

    sequence = (
        db.execute(
            select(func.count(KotTicket.id)).where(KotTicket.order_id == order.id)
        ).scalar() or 0
    )

    table = db.get(PosTable, order.table_id) if order.table_id else None
    now = utcnow()
    tickets: list[KotTicket] = []

    for station_id, lines in by_station.items():
        sequence += 1
        ticket = KotTicket(
            created_at=now,
            code=next_number(db, order.property_id, "KOT"),
            order_id=order.id,
            property_id=order.property_id,
            outlet_id=order.outlet_id,
            kitchen_station_id=station_id,
            business_date=order.business_date,
            status=KotStatus.PRINTED,
            sequence=sequence,
            table_label=table.label if table else None,
            printed_at=now,
        )
        db.add(ticket)
        tickets.append(ticket)
        for line in lines:
            line.kot_status = KotStatus.PREPARING
            line.sent_at = now

    order.status = PosOrderStatus.SENT
    db.flush()
    return tickets


def apply_discount(
    db: Session, order_id: int, *, percent: Decimal, reason: str, user: User
) -> PosOrder:
    """خصم محكوم بصلاحية الدور — مش بمزاج الكاشير."""
    order = _editable_order(db, order_id)

    if percent < 0 or percent > 100:
        raise PosError("نسبة الخصم لازم تكون بين 0 و 100", "Discount must be 0–100", "bad_percent")
    if not reason or not reason.strip():
        raise PosError("لازم تكتب سبب الخصم", "A discount reason is required", "reason_required")

    max_allowed = max(
        (r.max_discount_percent for r in user.roles if r.is_active), default=0
    )
    if user.is_superuser:
        max_allowed = 100
    if percent > max_allowed:
        raise PosError(
            f"أقصى خصم مسموح ليك {max_allowed}% — ده محتاج موافقة أعلى",
            f"Your maximum allowed discount is {max_allowed}%",
            "discount_limit",
        )

    order.discount_percent = percent
    order.discount_reason = reason.strip()
    order.discount_approved_by_user_id = user.id
    db.flush()
    recalculate(db, order)
    return order


def settle(
    db: Session,
    order_id: int,
    *,
    settlement: SettlementType,
    user_id: int,
    folio_id: int | None = None,
    shift_id: int | None = None,
) -> PosOrder:
    """تحصيل الأوردر — نقدي، كارت، أو ترحيل على الغرفة."""
    order = _editable_order(db, order_id)
    if not [l for l in order.lines if not l.is_void]:
        raise PosError("الأوردر فاضي", "Order has no items", "empty_order")

    recalculate(db, order)
    now = utcnow()

    if settlement == SettlementType.ROOM_CHARGE:
        target_folio_id = folio_id or order.folio_id
        if target_folio_id is None:
            raise PosError(
                "لازم تحدد الغرفة اللي هتترحّل عليها",
                "A folio is required for a room charge",
                "folio_required",
            )
        folio = db.get(Folio, target_folio_id)
        if folio is None:
            raise PosError("الحساب غير موجود", "Folio not found", "not_found")
        if folio.status != FolioStatus.OPEN:
            raise PosError(
                "حساب النزيل مقفول — مينفعش الترحيل عليه",
                "The folio is closed and cannot be charged",
                "folio_closed",
            )

        outlet = db.get(Outlet, order.outlet_id)
        if outlet and not outlet.allows_room_charge:
            raise PosError(
                "المنفذ ده مش بيسمح بالترحيل على الغرفة",
                "This outlet does not allow room charges",
                "not_allowed",
            )

        net = money(order.subtotal - order.discount_total)
        db.add(
            FolioLine(
                created_at=now,
                folio_id=folio.id,
                property_id=order.property_id,
                business_date=order.business_date,
                charge_kind=(
                    ChargeKind.SPA
                    if outlet and outlet.outlet_type == OutletType.SPA
                    else ChargeKind.FNB
                ),
                description_ar=f"{outlet.name_ar if outlet else 'نقطة بيع'} — أوردر {order.code}",
                description_en=f"{outlet.name_en if outlet else 'POS'} — order {order.code}",
                quantity=Decimal("1"),
                unit_price=net,
                amount=net,
                service_charge_amount=order.service_charge_total,
                tax_amount=order.tax_total,
                tax_percent=outlet.vat_percent if outlet else Decimal("14"),
                total_amount=order.grand_total,
                outlet_id=order.outlet_id,
                pos_order_id=order.id,
                posted_by_user_id=user_id,
            )
        )
        folio.charges_total = money(folio.charges_total + net)
        folio.service_charge_total = money(
            folio.service_charge_total + order.service_charge_total
        )
        folio.tax_total = money(folio.tax_total + order.tax_total)
        folio.balance = money(folio.balance + order.grand_total)

        order.folio_id = folio.id
        order.unit_label = folio.unit_label

    elif settlement in (SettlementType.CASH, SettlementType.CARD):
        db.add(
            Payment(
                code=next_number(db, order.property_id, "PAYMENT"),
                property_id=order.property_id,
                business_date=order.business_date,
                pos_order_id=order.id,
                method=(
                    PaymentMethod.CASH if settlement == SettlementType.CASH
                    else PaymentMethod.CARD
                ),
                amount=order.grand_total,
                currency="EGP",
                exchange_rate=Decimal("1"),
                amount_base=order.grand_total,
                shift_id=shift_id or order.shift_id,
                received_by_user_id=user_id,
            )
        )

    order.status = PosOrderStatus.SETTLED
    order.settlement_type = settlement
    order.paid_total = order.grand_total
    order.settled_at = now
    order.cashier_user_id = user_id
    if shift_id:
        order.shift_id = shift_id

    if order.table_id:
        table = db.get(PosTable, order.table_id)
        if table:
            table.status = TableStatus.FREE

    # خصم مكوّنات الوصفات من المخزن — هنا مش عند الطلب، لأن الأوردر
    # وهو مفتوح ممكن يتعدّل أو يتلغي والمخزن مالوش دعوة بده. أول ما
    # يتحاسب، الأكل خرج فعلاً.
    #
    # الاستيراد محلي عن قصد: خدمة الوصفات بتقرا الأوردرات، فاستيرادها
    # فوق كان هيعمل دورة.
    from app.services import recipes as recipe_svc

    recipe_svc.deplete_for_order(db, order.property_id, order.id, business_date=order.business_date)

    db.flush()
    return order


def void_order(db: Session, order_id: int, *, reason: str, user_id: int) -> PosOrder:
    order = db.get(PosOrder, order_id)
    if order is None:
        raise PosError("الأوردر غير موجود", "Order not found", "not_found")
    if order.status == PosOrderStatus.SETTLED:
        raise PosError(
            "الأوردر اتحاسب — لازم إشعار خصم مش إلغاء",
            "A settled order requires a credit note, not a void",
            "already_settled",
        )
    if not reason or not reason.strip():
        raise PosError("لازم تكتب سبب الإلغاء", "A void reason is required", "reason_required")

    order.is_void = True
    order.status = PosOrderStatus.VOID
    order.void_reason = reason.strip()
    order.voided_by_user_id = user_id
    for line in order.lines:
        line.is_void = True
        line.voided_after_send = line.kot_status not in (KotStatus.PENDING, KotStatus.CANCELLED)
        line.kot_status = KotStatus.CANCELLED

    if order.table_id:
        table = db.get(PosTable, order.table_id)
        if table:
            table.status = TableStatus.FREE
    db.flush()
    return order


# ────────────────────────────────────────────────────────── الحساب
def recalculate(db: Session, order: PosOrder) -> PosOrder:
    """إعادة حساب الأوردر: الإجمالي ثم الخصم ثم الخدمة ثم الضريبة.

    الترتيب ده مهم — الخدمة بتتحسب على الصافي بعد الخصم، والضريبة عليهم
    الاتنين، زي القانون المصري.
    """
    outlet = db.get(Outlet, order.outlet_id)
    service_pct = outlet.service_charge_percent if outlet else Decimal("12")
    vat_pct = outlet.vat_percent if outlet else Decimal("14")

    subtotal = money(
        sum((l.line_total for l in order.lines if not l.is_void), Decimal("0"))
    )
    discount = money(subtotal * order.discount_percent / 100)
    net = money(subtotal - discount)
    service = money(net * service_pct / 100)
    tax = money((net + service) * vat_pct / 100)

    order.subtotal = subtotal
    order.discount_total = discount
    order.service_charge_total = service
    order.tax_total = tax
    order.grand_total = money(net + service + tax)
    db.flush()
    return order


def _editable_order(db: Session, order_id: int) -> PosOrder:
    order = db.get(PosOrder, order_id)
    if order is None:
        raise PosError("الأوردر غير موجود", "Order not found", "not_found")
    if order.is_void:
        raise PosError("الأوردر ملغي", "Order is void", "void")
    if order.status == PosOrderStatus.SETTLED:
        raise PosError(
            "الأوردر اتحاسب بالفعل", "Order is already settled", "already_settled"
        )
    return order
