"""واجهات نقاط البيع — POS endpoints (cashier, floor plan, kitchen)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import (
    AuditAction,
    FolioStatus,
    KotStatus,
    PosOrderStatus,
    PosOrderType,
    SettlementType,
)
from app.models.folio import Folio
from app.models.pos import (
    KitchenStation,
    KotTicket,
    MenuCategory,
    MenuItem,
    Outlet,
    PosOrder,
    PosOrderLine,
    PosTable,
    Shift,
)
from app.schemas.common import ApiModel
from app.services import audit
from app.services import pos as svc

router = APIRouter(prefix="/pos", tags=["نقاط البيع — POS"])


# ═══════════════════════════════════════════════════════════ النماذج
class OutletOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    outlet_type: str
    has_floor_plan: bool
    allows_room_charge: bool
    service_charge_percent: Decimal
    vat_percent: Decimal
    order_prefix: str


class TableOut(ApiModel):
    id: int
    label: str
    zone_ar: str | None = None
    zone_en: str | None = None
    seats: int
    status: str
    pos_x: int
    pos_y: int
    width: int
    height: int
    shape: str
    open_order_id: int | None = None
    open_order_total: Decimal | None = None


class FloorPlanOut(ApiModel):
    outlet_id: int
    name_ar: str
    name_en: str
    tables: list[TableOut]
    occupied: int
    total: int


class MenuItemOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    category_id: int
    price: Decimal
    is_available: bool
    is_out_of_stock: bool
    is_vegetarian: bool
    contains_alcohol: bool
    preparation_minutes: int | None = None
    kitchen_station_id: int | None = None


class MenuCategoryOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    sort_order: int
    items: list[MenuItemOut]


class MenuOut(ApiModel):
    outlet_id: int
    categories: list[MenuCategoryOut]
    item_count: int


class OrderLineOut(ApiModel):
    id: int
    menu_item_id: int | None
    item_name_ar: str
    item_name_en: str | None = None
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    notes: str | None = None
    kot_status: KotStatus
    is_void: bool
    voided_after_send: bool


class OrderOut(ApiModel):
    id: int
    code: str
    outlet_id: int
    business_date: date
    order_type: PosOrderType
    status: PosOrderStatus
    table_id: int | None = None
    table_label: str | None = None
    covers: int
    folio_id: int | None = None
    unit_label: str | None = None
    subtotal: Decimal
    discount_percent: Decimal
    discount_total: Decimal
    discount_reason: str | None = None
    service_charge_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    settlement_type: SettlementType | None = None
    opened_at: datetime
    is_void: bool
    lines: list[OrderLineOut] = []


class InHouseOut(ApiModel):
    """النزلاء النازلين — لاختيار الغرفة عند الترحيل."""

    folio_id: int
    unit_label: str | None
    guest_name: str
    reservation_code: str | None = None
    balance: Decimal


class KotLineOut(ApiModel):
    id: int
    item_name_ar: str
    quantity: Decimal
    notes: str | None = None
    kot_status: KotStatus


class KotOut(ApiModel):
    id: int
    code: str
    order_id: int
    order_code: str
    table_label: str | None = None
    sequence: int
    status: KotStatus
    created_at: datetime
    waited_minutes: int
    lines: list[KotLineOut]


# ── مدخلات ──────────────────────────────────────────────────────────
class OpenOrderIn(ApiModel):
    outlet_id: int
    table_id: int | None = None
    covers: int = 1
    order_type: PosOrderType = PosOrderType.DINE_IN
    folio_id: int | None = None
    shift_id: int | None = None


class AddLineIn(ApiModel):
    menu_item_id: int
    quantity: Decimal = Decimal("1")
    notes: str | None = None


class VoidIn(ApiModel):
    reason: str


class DiscountIn(ApiModel):
    percent: Decimal
    reason: str


class SettleIn(ApiModel):
    settlement: SettlementType
    folio_id: int | None = None
    shift_id: int | None = None


class OpenShiftIn(ApiModel):
    outlet_id: int | None = None
    opening_float: Decimal = Decimal("0")


class CloseShiftIn(ApiModel):
    counted_cash: Decimal
    counted_card: Decimal
    notes: str | None = None


class ShiftOut(ApiModel):
    id: int
    code: str
    status: str
    business_date: date
    opening_float: Decimal
    expected_cash: Decimal
    expected_card: Decimal
    counted_cash: Decimal
    counted_card: Decimal
    variance: Decimal
    orders_count: int
    voids_count: int
    discounts_total: Decimal


# ═══════════════════════════════════════════════════════════ مساعدات
def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.PosError):
        code = status.HTTP_400_BAD_REQUEST
        if exc.code == "not_found":
            code = status.HTTP_404_NOT_FOUND
        elif exc.code in ("table_busy", "already_settled", "folio_closed"):
            code = status.HTTP_409_CONFLICT
        elif exc.code == "discount_limit":
            code = status.HTTP_403_FORBIDDEN
        return HTTPException(
            status_code=code,
            detail={"ar": exc.message_ar, "en": exc.message_en, "code": exc.code},
        )
    raise exc


def _order_out(db, order: PosOrder) -> OrderOut:
    table = db.get(PosTable, order.table_id) if order.table_id else None
    return OrderOut(
        id=order.id,
        code=order.code,
        outlet_id=order.outlet_id,
        business_date=order.business_date,
        order_type=order.order_type,
        status=order.status,
        table_id=order.table_id,
        table_label=table.label if table else None,
        covers=order.covers,
        folio_id=order.folio_id,
        unit_label=order.unit_label,
        subtotal=order.subtotal,
        discount_percent=order.discount_percent,
        discount_total=order.discount_total,
        discount_reason=order.discount_reason,
        service_charge_total=order.service_charge_total,
        tax_total=order.tax_total,
        grand_total=order.grand_total,
        settlement_type=order.settlement_type,
        opened_at=order.opened_at,
        is_void=order.is_void,
        lines=[OrderLineOut.model_validate(l) for l in order.lines],
    )


# ═══════════════════════════════════════════════════ الإعداد والقراءة
@router.get("/outlets", response_model=list[OutletOut], summary="منافذ البيع")
def list_outlets(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[OutletOut]:
    rows = db.execute(
        select(Outlet)
        .where(Outlet.property_id == prop.id, Outlet.is_active.is_(True))
        .order_by(Outlet.sort_order, Outlet.id)
    ).scalars().all()
    return [OutletOut.model_validate(o) for o in rows]


@router.get(
    "/outlets/{outlet_id}/floor-plan",
    response_model=FloorPlanOut,
    summary="تصميم الصالة",
)
def floor_plan(
    outlet_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> FloorPlanOut:
    outlet = db.get(Outlet, outlet_id)
    if outlet is None or outlet.property_id != prop.id:
        raise HTTPException(404, {"ar": "المنفذ غير موجود", "en": "Outlet not found"})

    tables = db.execute(
        select(PosTable)
        .where(PosTable.outlet_id == outlet_id, PosTable.is_active.is_(True))
        .order_by(PosTable.id)
    ).scalars().all()

    open_orders = {
        o.table_id: o
        for o in db.execute(
            select(PosOrder).where(
                PosOrder.outlet_id == outlet_id,
                PosOrder.status.in_(
                    [PosOrderStatus.OPEN, PosOrderStatus.SENT, PosOrderStatus.SERVED]
                ),
                PosOrder.table_id.isnot(None),
            )
        ).scalars().all()
    }

    out = []
    for t in tables:
        order = open_orders.get(t.id)
        out.append(
            TableOut(
                id=t.id, label=t.label, zone_ar=t.zone_ar, zone_en=t.zone_en,
                seats=t.seats, status=t.status, pos_x=t.pos_x, pos_y=t.pos_y,
                width=t.width, height=t.height, shape=t.shape,
                open_order_id=order.id if order else None,
                open_order_total=order.grand_total if order else None,
            )
        )

    return FloorPlanOut(
        outlet_id=outlet_id,
        name_ar=outlet.name_ar,
        name_en=outlet.name_en,
        tables=out,
        occupied=len(open_orders),
        total=len(tables),
    )


@router.get("/outlets/{outlet_id}/menu", response_model=MenuOut, summary="منيو المنفذ")
def menu(outlet_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty) -> MenuOut:
    outlet = db.get(Outlet, outlet_id)
    if outlet is None or outlet.property_id != prop.id:
        raise HTTPException(404, {"ar": "المنفذ غير موجود", "en": "Outlet not found"})

    items = (
        db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.outlets))
            .where(MenuItem.property_id == prop.id, MenuItem.is_active.is_(True))
            .order_by(MenuItem.sort_order, MenuItem.id)
        ).scalars().unique().all()
    )
    outlet_items = [i for i in items if any(o.id == outlet_id for o in i.outlets)]

    categories = db.execute(
        select(MenuCategory)
        .where(MenuCategory.property_id == prop.id, MenuCategory.is_active.is_(True))
        .order_by(MenuCategory.sort_order, MenuCategory.id)
    ).scalars().all()

    by_cat: dict[int, list[MenuItem]] = {}
    for item in outlet_items:
        by_cat.setdefault(item.category_id, []).append(item)

    return MenuOut(
        outlet_id=outlet_id,
        categories=[
            MenuCategoryOut(
                id=c.id, code=c.code, name_ar=c.name_ar, name_en=c.name_en,
                sort_order=c.sort_order,
                items=[MenuItemOut.model_validate(i) for i in by_cat[c.id]],
            )
            for c in categories
            if by_cat.get(c.id)
        ],
        item_count=len(outlet_items),
    )


@router.get("/in-house", response_model=list[InHouseOut], summary="النزلاء النازلين")
def in_house(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    search: str | None = Query(default=None, description="رقم الوحدة أو اسم النزيل"),
) -> list[InHouseOut]:
    from app.models.guests import Guest
    from app.models.reservations import Reservation

    stmt = (
        select(Folio, Guest, Reservation)
        .join(Guest, Guest.id == Folio.guest_id)
        .outerjoin(Reservation, Reservation.id == Folio.reservation_id)
        .where(Folio.property_id == prop.id, Folio.status == FolioStatus.OPEN)
        .order_by(Folio.unit_label)
    )
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            Folio.unit_label.ilike(term)
            | Guest.first_name.ilike(term)
            | Guest.last_name.ilike(term)
        )

    return [
        InHouseOut(
            folio_id=f.id,
            unit_label=f.unit_label,
            guest_name=g.full_name,
            reservation_code=r.code if r else None,
            balance=f.balance,
        )
        for f, g, r in db.execute(stmt.limit(200)).all()
    ]


@router.get("/orders", response_model=list[OrderOut], summary="الأوردرات المفتوحة")
def open_orders(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    outlet_id: int | None = None,
) -> list[OrderOut]:
    stmt = (
        select(PosOrder)
        .options(selectinload(PosOrder.lines))
        .where(
            PosOrder.property_id == prop.id,
            PosOrder.status.in_(
                [PosOrderStatus.OPEN, PosOrderStatus.SENT, PosOrderStatus.SERVED]
            ),
        )
        .order_by(PosOrder.opened_at.desc())
        .limit(100)
    )
    if outlet_id:
        stmt = stmt.where(PosOrder.outlet_id == outlet_id)
    return [_order_out(db, o) for o in db.execute(stmt).scalars().unique().all()]


@router.get("/orders/{order_id}", response_model=OrderOut, summary="تفاصيل أوردر")
def get_order(
    order_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> OrderOut:
    order = db.get(PosOrder, order_id)
    if order is None or order.property_id != prop.id:
        raise HTTPException(404, {"ar": "الأوردر غير موجود", "en": "Order not found"})
    return _order_out(db, order)


@router.get(
    "/kitchen/{station_id}",
    response_model=list[KotOut],
    summary="شاشة المطبخ",
)
def kitchen_display(
    station_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> list[KotOut]:
    """الطلبات المطلوب تحضيرها في المحطة دي، الأقدم الأول."""
    station = db.get(KitchenStation, station_id)
    if station is None or station.property_id != prop.id:
        raise HTTPException(404, {"ar": "المحطة غير موجودة", "en": "Station not found"})

    tickets = db.execute(
        select(KotTicket)
        .where(
            KotTicket.kitchen_station_id == station_id,
            KotTicket.status.in_([KotStatus.PRINTED, KotStatus.PREPARING]),
        )
        .order_by(KotTicket.created_at)
        .limit(50)
    ).scalars().all()

    if not tickets:
        return []

    order_ids = {t.order_id for t in tickets}
    orders = {
        o.id: o
        for o in db.execute(
            select(PosOrder).options(selectinload(PosOrder.lines))
            .where(PosOrder.id.in_(order_ids))
        ).scalars().unique().all()
    }

    now = datetime.now(tickets[0].created_at.tzinfo)
    out = []
    for t in tickets:
        order = orders.get(t.order_id)
        lines = [
            KotLineOut(
                id=l.id, item_name_ar=l.item_name_ar, quantity=l.quantity,
                notes=l.notes, kot_status=l.kot_status,
            )
            for l in (order.lines if order else [])
            if not l.is_void and l.kitchen_station_id == station_id
            and l.kot_status in (KotStatus.PREPARING, KotStatus.READY)
        ]
        if not lines:
            continue
        out.append(
            KotOut(
                id=t.id, code=t.code, order_id=t.order_id,
                order_code=order.code if order else "—",
                table_label=t.table_label, sequence=t.sequence, status=t.status,
                created_at=t.created_at,
                waited_minutes=int((now - t.created_at).total_seconds() // 60),
                lines=lines,
            )
        )
    return out


# ═══════════════════════════════════════════════════════════ الكتابة
@router.post(
    "/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="فتح أوردر",
    dependencies=[Depends(require("pos.order"))],
)
def create_order(
    payload: OpenOrderIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> OrderOut:
    try:
        order = svc.open_order(
            db,
            property_id=prop.id,
            outlet_id=payload.outlet_id,
            user_id=user.id,
            table_id=payload.table_id,
            covers=payload.covers,
            order_type=payload.order_type,
            folio_id=payload.folio_id,
            shift_id=payload.shift_id,
        )
    except Exception as exc:
        raise _fail(exc) from exc
    return _order_out(db, order)


@router.post(
    "/orders/{order_id}/lines",
    response_model=OrderOut,
    summary="إضافة صنف",
    dependencies=[Depends(require("pos.order"))],
)
def add_item(
    order_id: int, payload: AddLineIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> OrderOut:
    try:
        line = svc.add_line(
            db, order_id, menu_item_id=payload.menu_item_id,
            quantity=payload.quantity, notes=payload.notes,
        )
    except Exception as exc:
        raise _fail(exc) from exc
    return _order_out(db, db.get(PosOrder, line.order_id))


@router.post(
    "/orders/{order_id}/lines/{line_id}/void",
    response_model=OrderOut,
    summary="إلغاء صنف",
    dependencies=[Depends(require("pos.void"))],
)
def void_item(
    order_id: int,
    line_id: int,
    payload: VoidIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> OrderOut:
    try:
        line = svc.void_line(db, order_id, line_id, reason=payload.reason, user_id=user.id)
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.VOID,
        entity_type="PosOrderLine",
        entity_id=line.id,
        user=user,
        property_id=prop.id,
        summary_ar=(
            f"إلغاء {line.item_name_ar}"
            + (" — بعد الإرسال للمطبخ" if line.voided_after_send else "")
        ),
        summary_en=(
            f"Voided {line.item_name_en or line.item_name_ar}"
            + (" — after kitchen send" if line.voided_after_send else "")
        ),
        changes={"reason": {"from": None, "to": payload.reason},
                 "after_send": {"from": None, "to": line.voided_after_send}},
        request=request,
    )
    return _order_out(db, db.get(PosOrder, order_id))


@router.post(
    "/orders/{order_id}/send",
    response_model=OrderOut,
    summary="إرسال للمطبخ",
    dependencies=[Depends(require("pos.order"))],
)
def send(order_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty) -> OrderOut:
    try:
        svc.send_to_kitchen(db, order_id)
    except Exception as exc:
        raise _fail(exc) from exc
    return _order_out(db, db.get(PosOrder, order_id))


@router.post(
    "/orders/{order_id}/discount",
    response_model=OrderOut,
    summary="منح خصم",
    dependencies=[Depends(require("pos.discount"))],
)
def discount(
    order_id: int,
    payload: DiscountIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> OrderOut:
    try:
        order = svc.apply_discount(
            db, order_id, percent=payload.percent, reason=payload.reason, user=user
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.DISCOUNT,
        entity_type="PosOrder",
        entity_id=order.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"خصم {payload.percent}% على الأوردر {order.code} — {payload.reason}",
        summary_en=f"{payload.percent}% discount on {order.code} — {payload.reason}",
        changes={"amount": {"from": None, "to": str(order.discount_total)}},
        request=request,
    )
    return _order_out(db, order)


@router.post(
    "/orders/{order_id}/settle",
    response_model=OrderOut,
    summary="تحصيل الأوردر",
    dependencies=[Depends(require("pos.order"))],
)
def settle_order(
    order_id: int,
    payload: SettleIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> OrderOut:
    if payload.settlement == SettlementType.ROOM_CHARGE and not user.has_permission(
        "pos.room_charge"
    ):
        raise HTTPException(
            403,
            {"ar": "مالكش صلاحية الترحيل على الغرفة",
             "en": "You cannot post room charges"},
        )
    try:
        order = svc.settle(
            db,
            order_id,
            settlement=payload.settlement,
            user_id=user.id,
            folio_id=payload.folio_id,
            shift_id=payload.shift_id,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="PosOrder",
        entity_id=order.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تحصيل {order.code} — {order.grand_total} ج.م ({payload.settlement.value})",
        summary_en=f"Settled {order.code} — {order.grand_total} ({payload.settlement.value})",
        request=request,
    )
    return _order_out(db, order)


@router.post(
    "/orders/{order_id}/void",
    response_model=OrderOut,
    summary="إلغاء أوردر كامل",
    dependencies=[Depends(require("pos.void"))],
)
def void_whole_order(
    order_id: int,
    payload: VoidIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> OrderOut:
    try:
        order = svc.void_order(db, order_id, reason=payload.reason, user_id=user.id)
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.VOID,
        entity_type="PosOrder",
        entity_id=order.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إلغاء الأوردر {order.code} — {payload.reason}",
        summary_en=f"Voided order {order.code} — {payload.reason}",
        request=request,
    )
    return _order_out(db, order)


# ═══════════════════════════════════════════════════════════ الورديات
@router.post("/shifts/open", response_model=ShiftOut, summary="فتح وردية")
def shift_open(
    payload: OpenShiftIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> ShiftOut:
    shift = svc.open_shift(
        db,
        property_id=prop.id,
        user_id=user.id,
        outlet_id=payload.outlet_id,
        opening_float=payload.opening_float,
    )
    return ShiftOut.model_validate(shift)


@router.post(
    "/shifts/{shift_id}/close",
    response_model=ShiftOut,
    summary="تقفيل الوردية ومطابقة العهدة",
    dependencies=[Depends(require("pos.shift.close"))],
)
def shift_close(
    shift_id: int,
    payload: CloseShiftIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> ShiftOut:
    try:
        shift = svc.close_shift(
            db,
            shift_id,
            counted_cash=payload.counted_cash,
            counted_card=payload.counted_card,
            user_id=user.id,
            notes=payload.notes,
        )
    except Exception as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="Shift",
        entity_id=shift.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تقفيل وردية {shift.code} — فرق {shift.variance} ج.م",
        summary_en=f"Closed shift {shift.code} — variance {shift.variance}",
        changes={"variance": {"from": None, "to": str(shift.variance)}},
        request=request,
    )
    return ShiftOut.model_validate(shift)
