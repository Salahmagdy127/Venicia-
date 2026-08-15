"""واجهات المخازن والوصفات والمشتريات — Inventory endpoints."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import (
    AuditAction,
    MovementKind,
    PurchaseStatus,
    StockUnit,
    WarehouseKind,
)
from app.models.pos import MenuItem
from app.models.stock import (
    PurchaseOrder,
    Recipe,
    StockItem,
    StockLevel,
    StockMovement,
    Supplier,
    Warehouse,
)
from app.schemas.common import ApiModel
from app.services import audit
from app.services import purchasing as po_svc
from app.services import recipes as recipe_svc
from app.services import stock as stock_svc

router = APIRouter(prefix="/stock", tags=["المخازن والمشتريات — Inventory"])


# ═══════════════════════════════════════════════════════════ النماذج
class WarehouseOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    kind: WarehouseKind
    outlet_id: int | None = None


class ItemOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    category_ar: str
    category_en: str
    unit: StockUnit
    average_cost: Decimal
    last_purchase_cost: Decimal
    reorder_level: Decimal
    reorder_quantity: Decimal
    is_critical: bool
    on_hand: Decimal
    value: Decimal
    is_low: bool


class LevelOut(ApiModel):
    warehouse_id: int
    warehouse_name_ar: str
    quantity: Decimal
    value: Decimal


class ItemDetail(ItemOut):
    levels: list[LevelOut] = []


class StockBoard(ApiModel):
    total_items: int
    total_value: Decimal
    low_stock: int
    negative: int
    warehouses: list[WarehouseOut]
    items: list[ItemOut]


class MovementOut(ApiModel):
    id: int
    stock_item_id: int
    item_name_ar: str
    warehouse_id: int
    warehouse_name_ar: str
    kind: MovementKind
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    balance_after: Decimal
    business_date: date
    created_at: datetime
    reason: str | None = None
    purchase_order_id: int | None = None
    pos_order_id: int | None = None


class AdjustIn(ApiModel):
    warehouse_id: int
    stock_item_id: int
    counted_quantity: Decimal
    reason: str


class WasteIn(ApiModel):
    warehouse_id: int
    stock_item_id: int
    quantity: Decimal
    reason: str


class TransferIn(ApiModel):
    from_warehouse_id: int
    to_warehouse_id: int
    stock_item_id: int
    quantity: Decimal
    reason: str | None = None


# --- الوصفات ---
class RecipeLineIn(ApiModel):
    stock_item_id: int
    quantity: Decimal
    waste_percent: Decimal = Decimal("0")


class RecipeLineOut(ApiModel):
    stock_item_id: int
    item_name_ar: str
    unit: StockUnit
    quantity: Decimal
    waste_percent: Decimal
    gross_quantity: Decimal
    unit_cost: Decimal
    line_cost: Decimal


class RecipeOut(ApiModel):
    menu_item_id: int
    menu_item_name_ar: str
    menu_item_price: Decimal
    warehouse_id: int | None = None
    yield_portions: Decimal
    cost: Decimal
    margin_percent: Decimal
    notes: str | None = None
    lines: list[RecipeLineOut] = []


class SaveRecipeIn(ApiModel):
    menu_item_id: int
    lines: list[RecipeLineIn]
    warehouse_id: int | None = None
    yield_portions: Decimal = Decimal("1")
    notes: str | None = None


class RecipeCoverage(ApiModel):
    with_recipe: int
    without_recipe: int
    missing: list[dict]


# --- المشتريات ---
class PoLineOut(ApiModel):
    id: int
    stock_item_id: int
    item_name_ar: str
    unit: StockUnit
    quantity_ordered: Decimal
    quantity_received: Decimal
    outstanding: Decimal
    unit_cost: Decimal
    line_total: Decimal


class PurchaseOut(ApiModel):
    id: int
    number: str
    supplier_id: int
    supplier_name_ar: str
    warehouse_id: int
    status: PurchaseStatus
    order_date: date
    expected_date: date | None = None
    received_date: date | None = None
    subtotal: Decimal
    grand_total: Decimal
    supplier_invoice_number: str | None = None
    notes: str | None = None
    lines: list[PoLineOut] = []


class PurchaseBoardOut(ApiModel):
    draft: int
    sent: int
    partial: int
    received_this_month: int
    outstanding_value: Decimal
    spend_this_month: Decimal
    orders: list[PurchaseOut]


class PoLineIn(ApiModel):
    stock_item_id: int
    quantity: Decimal
    unit_cost: Decimal


class CreatePoIn(ApiModel):
    supplier_id: int
    warehouse_id: int
    lines: list[PoLineIn]
    expected_date: date | None = None
    notes: str | None = None


class ReceiveLineIn(ApiModel):
    line_id: int
    quantity: Decimal
    actual_cost: Decimal | None = None


class ReceiveIn(ApiModel):
    lines: list[ReceiveLineIn]
    supplier_invoice_number: str | None = None


class ReasonIn(ApiModel):
    reason: str


class SupplierOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    phone: str | None = None
    payment_terms_days: int


class VarianceOut(ApiModel):
    stock_item_id: int
    item_name_ar: str
    unit: StockUnit
    theoretical: Decimal
    actual: Decimal
    waste: Decimal
    variance: Decimal
    variance_percent: Decimal
    cost_impact: Decimal


class VarianceReport(ApiModel):
    start_date: date
    end_date: date
    rows: list[VarianceOut]
    total_impact: Decimal
    uncovered_items: int
    #: أول يوم فيه حركة مخزنية — قبله المقارنة مالهاش معنى
    tracking_since: date | None = None
    #: المدى اتقصّ لأن المخزن أحدث من المطلوب
    was_clamped: bool = False


def _fail(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "error")
    http = {"not_found": 404, "insufficient": 409, "already_received": 409}.get(code, 400)
    return HTTPException(
        status_code=http,
        detail={
            "ar": getattr(exc, "message_ar", str(exc)),
            "en": getattr(exc, "message_en", str(exc)),
            "code": code,
        },
    )


# ═══════════════════════════════════════════════════════ لوحة المخزن
@router.get(
    "",
    response_model=StockBoard,
    summary="لوحة المخزن",
    dependencies=[Depends(require("stock.view"))],
)
def board(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    low_only: bool = False,
    search: str | None = None,
) -> StockBoard:
    warehouses = list(
        db.execute(
            select(Warehouse)
            .where(Warehouse.property_id == prop.id, Warehouse.is_active.is_(True))
            .order_by(Warehouse.sort_order, Warehouse.id)
        ).scalars().all()
    )

    stmt = select(StockItem).where(
        StockItem.property_id == prop.id, StockItem.is_active.is_(True)
    )
    if search and search.strip():
        needle = f"%{search.strip()}%"
        stmt = stmt.where(StockItem.name_ar.ilike(needle) | StockItem.code.ilike(needle))
    items = list(
        db.execute(stmt.order_by(StockItem.sort_order, StockItem.id)).scalars().all()
    )

    levels: dict[int, tuple[Decimal, Decimal]] = {}
    for row in db.execute(
        select(StockLevel.stock_item_id, StockLevel.quantity, StockLevel.value).where(
            StockLevel.property_id == prop.id
        )
    ).all():
        held, value = levels.get(row[0], (Decimal("0"), Decimal("0")))
        levels[row[0]] = (held + row[1], value + row[2])

    out: list[ItemOut] = []
    low = negative = 0
    total_value = Decimal("0")
    for item in items:
        held, value = levels.get(item.id, (Decimal("0"), Decimal("0")))
        is_low = item.reorder_level > 0 and held < item.reorder_level
        if is_low:
            low += 1
        if held < 0:
            negative += 1
        total_value += value
        if low_only and not is_low:
            continue
        out.append(
            ItemOut(
                id=item.id,
                code=item.code,
                name_ar=item.name_ar,
                name_en=item.name_en,
                category_ar=item.category_ar,
                category_en=item.category_en,
                unit=item.unit,
                average_cost=item.average_cost,
                last_purchase_cost=item.last_purchase_cost,
                reorder_level=item.reorder_level,
                reorder_quantity=item.reorder_quantity,
                is_critical=item.is_critical,
                on_hand=held,
                value=value,
                is_low=is_low,
            )
        )

    return StockBoard(
        total_items=len(items),
        total_value=total_value,
        low_stock=low,
        negative=negative,
        warehouses=[
            WarehouseOut(
                id=w.id,
                code=w.code,
                name_ar=w.name_ar,
                name_en=w.name_en,
                kind=w.kind,
                outlet_id=w.outlet_id,
            )
            for w in warehouses
        ],
        items=out,
    )


@router.get(
    "/items/{item_id}",
    response_model=ItemDetail,
    summary="صنف بأرصدته في كل مخزن",
    dependencies=[Depends(require("stock.view"))],
)
def item_detail(
    item_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> ItemDetail:
    item = db.get(StockItem, item_id)
    if item is None or item.property_id != prop.id:
        raise HTTPException(
            status_code=404, detail={"ar": "الصنف غير موجود", "en": "Item not found"}
        )

    names = dict(
        db.execute(
            select(Warehouse.id, Warehouse.name_ar).where(Warehouse.property_id == prop.id)
        ).all()
    )
    rows = list(
        db.execute(
            select(StockLevel).where(StockLevel.stock_item_id == item_id)
        ).scalars().all()
    )
    held = sum((r.quantity for r in rows), Decimal("0"))
    value = sum((r.value for r in rows), Decimal("0"))

    return ItemDetail(
        id=item.id,
        code=item.code,
        name_ar=item.name_ar,
        name_en=item.name_en,
        category_ar=item.category_ar,
        category_en=item.category_en,
        unit=item.unit,
        average_cost=item.average_cost,
        last_purchase_cost=item.last_purchase_cost,
        reorder_level=item.reorder_level,
        reorder_quantity=item.reorder_quantity,
        is_critical=item.is_critical,
        on_hand=held,
        value=value,
        is_low=item.reorder_level > 0 and held < item.reorder_level,
        levels=[
            LevelOut(
                warehouse_id=r.warehouse_id,
                warehouse_name_ar=names.get(r.warehouse_id, "—"),
                quantity=r.quantity,
                value=r.value,
            )
            for r in rows
        ],
    )


@router.get(
    "/movements",
    response_model=list[MovementOut],
    summary="كشف الحركة",
    dependencies=[Depends(require("stock.view"))],
)
def movements(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    stock_item_id: int | None = None,
    warehouse_id: int | None = None,
    kind: MovementKind | None = None,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=400),
) -> list[MovementOut]:
    rows = stock_svc.ledger(
        db,
        prop.id,
        stock_item_id=stock_item_id,
        warehouse_id=warehouse_id,
        kinds=[kind] if kind else None,
        since=date.today() - timedelta(days=days),
        limit=limit,
    )
    items = dict(
        db.execute(
            select(StockItem.id, StockItem.name_ar).where(StockItem.property_id == prop.id)
        ).all()
    )
    houses = dict(
        db.execute(
            select(Warehouse.id, Warehouse.name_ar).where(Warehouse.property_id == prop.id)
        ).all()
    )
    return [
        MovementOut(
            id=m.id,
            stock_item_id=m.stock_item_id,
            item_name_ar=items.get(m.stock_item_id, "—"),
            warehouse_id=m.warehouse_id,
            warehouse_name_ar=houses.get(m.warehouse_id, "—"),
            kind=m.kind,
            quantity=m.quantity,
            unit_cost=m.unit_cost,
            total_cost=m.total_cost,
            balance_after=m.balance_after,
            business_date=m.business_date,
            created_at=m.created_at,
            reason=m.reason,
            purchase_order_id=m.purchase_order_id,
            pos_order_id=m.pos_order_id,
        )
        for m in rows
    ]


# ═══════════════════════════════════════════════════════ حركات يدوية
@router.post(
    "/adjust",
    response_model=dict,
    summary="تسوية بعد الجرد",
    dependencies=[Depends(require("stock.manage"))],
)
def adjust(
    payload: AdjustIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> dict:
    try:
        movement = stock_svc.adjust_to(
            db,
            prop.id,
            warehouse_id=payload.warehouse_id,
            stock_item_id=payload.stock_item_id,
            counted_quantity=payload.counted_quantity,
            reason=payload.reason,
            user=user,
        )
    except stock_svc.StockError as exc:
        raise _fail(exc) from exc

    if movement is None:
        return {"ok": True, "message_ar": "الجرد مطابق — مفيش فرق", "difference": "0"}

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="StockItem",
        entity_id=payload.stock_item_id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تسوية جرد {movement.quantity} — {payload.reason}",
        summary_en=f"Stock adjustment {movement.quantity}",
        request=request,
    )
    return {
        "ok": True,
        "message_ar": f"اتسجّل فرق {movement.quantity} بقيمة {movement.total_cost}",
        "difference": str(movement.quantity),
        "kind": movement.kind,
    }


@router.post(
    "/waste",
    response_model=dict,
    summary="تسجيل هالك",
    dependencies=[Depends(require("stock.manage"))],
)
def waste(
    payload: WasteIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> dict:
    if not payload.reason.strip():
        raise HTTPException(
            status_code=400,
            detail={"ar": "سبب الهالك مطلوب", "en": "A reason is required"},
        )
    try:
        movement = stock_svc.record(
            db,
            prop.id,
            warehouse_id=payload.warehouse_id,
            stock_item_id=payload.stock_item_id,
            kind=MovementKind.WASTE,
            quantity=payload.quantity,
            reason=payload.reason,
            user=user,
        )
    except stock_svc.StockError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="StockItem",
        entity_id=payload.stock_item_id,
        user=user,
        property_id=prop.id,
        summary_ar=f"هالك {movement.quantity} بقيمة {movement.total_cost} — {payload.reason}",
        summary_en=f"Waste {movement.quantity}",
        request=request,
    )
    return {"ok": True, "message_ar": f"اتسجّل هالك بقيمة {movement.total_cost}"}


@router.post(
    "/transfer",
    response_model=dict,
    summary="تحويل بين مخزنين",
    dependencies=[Depends(require("stock.manage"))],
)
def transfer(
    payload: TransferIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> dict:
    try:
        out, _into = stock_svc.transfer(
            db,
            prop.id,
            from_warehouse_id=payload.from_warehouse_id,
            to_warehouse_id=payload.to_warehouse_id,
            stock_item_id=payload.stock_item_id,
            quantity=payload.quantity,
            reason=payload.reason,
            user=user,
        )
    except stock_svc.StockError as exc:
        raise _fail(exc) from exc
    return {"ok": True, "message_ar": f"اتحوّل {out.quantity}"}


# ═══════════════════════════════════════════════════════ الوصفات
def _recipe_out(db, recipe: Recipe, items: dict, menu: dict) -> RecipeOut:
    item = menu.get(recipe.menu_item_id)
    cost = recipe.cost
    price = item.price if item else Decimal("0")
    return RecipeOut(
        menu_item_id=recipe.menu_item_id,
        menu_item_name_ar=item.name_ar if item else "—",
        menu_item_price=price,
        warehouse_id=recipe.warehouse_id,
        yield_portions=recipe.yield_portions,
        cost=cost,
        margin_percent=(
            ((price - cost) / price * 100).quantize(Decimal("0.1")) if price else Decimal("0")
        ),
        notes=recipe.notes,
        lines=[
            RecipeLineOut(
                stock_item_id=line.stock_item_id,
                item_name_ar=items[line.stock_item_id].name_ar
                if line.stock_item_id in items
                else "—",
                unit=items[line.stock_item_id].unit
                if line.stock_item_id in items
                else StockUnit.PIECE,
                quantity=line.quantity,
                waste_percent=line.waste_percent,
                gross_quantity=line.gross_quantity,
                unit_cost=line.unit_cost,
                line_cost=line.line_cost,
            )
            for line in sorted(recipe.lines, key=lambda x: x.id)
        ],
    )


def _catalogs(db, prop) -> tuple[dict, dict]:
    items = {
        s.id: s
        for s in db.execute(
            select(StockItem).where(StockItem.property_id == prop.id)
        ).scalars().all()
    }
    menu = {
        m.id: m
        for m in db.execute(
            select(MenuItem).where(MenuItem.property_id == prop.id)
        ).scalars().all()
    }
    return items, menu


@router.get(
    "/recipes",
    response_model=list[RecipeOut],
    summary="الوصفات",
    dependencies=[Depends(require("stock.view"))],
)
def list_recipes(
    db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> list[RecipeOut]:
    items, menu = _catalogs(db, prop)
    rows = list(
        db.execute(
            select(Recipe).where(Recipe.property_id == prop.id).order_by(Recipe.id)
        ).scalars().all()
    )
    return [_recipe_out(db, r, items, menu) for r in rows]


@router.get(
    "/recipes/coverage",
    response_model=RecipeCoverage,
    summary="أصناف من غير وصفة",
    dependencies=[Depends(require("stock.view"))],
)
def coverage(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> RecipeCoverage:
    missing = recipe_svc.menu_items_without_recipe(db, prop.id)
    total = db.execute(
        select(MenuItem).where(
            MenuItem.property_id == prop.id, MenuItem.is_active.is_(True)
        )
    ).scalars().all()
    return RecipeCoverage(
        with_recipe=len(total) - len(missing),
        without_recipe=len(missing),
        missing=[
            {"id": m.id, "name_ar": m.name_ar, "price": str(m.price)} for m in missing[:60]
        ],
    )


@router.put(
    "/recipes",
    response_model=RecipeOut,
    summary="حفظ وصفة",
    dependencies=[Depends(require("stock.manage"))],
)
def save_recipe(
    payload: SaveRecipeIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> RecipeOut:
    try:
        recipe = recipe_svc.save_recipe(
            db,
            prop.id,
            payload.menu_item_id,
            [(l.stock_item_id, l.quantity, l.waste_percent) for l in payload.lines],
            warehouse_id=payload.warehouse_id,
            yield_portions=payload.yield_portions,
            notes=payload.notes,
        )
    except recipe_svc.RecipeError as exc:
        raise _fail(exc) from exc

    items, menu = _catalogs(db, prop)
    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="Recipe",
        entity_id=recipe.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"وصفة {menu[recipe.menu_item_id].name_ar} — تكلفة {recipe.cost}",
        summary_en="Recipe saved",
        request=request,
    )
    return _recipe_out(db, recipe, items, menu)


@router.post(
    "/recipes/refresh-costs",
    response_model=dict,
    summary="إعادة حساب التكاليف",
    dependencies=[Depends(require("stock.manage"))],
)
def refresh_costs(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> dict:
    touched = recipe_svc.refresh_costs(db, prop.id)
    return {"ok": True, "message_ar": f"اتحدّثت تكلفة {touched} وصفة", "count": touched}


# ═══════════════════════════════════════════════════════ الفرق
@router.get(
    "/variance",
    response_model=VarianceReport,
    summary="المفروض مقابل الفعلي",
    dependencies=[Depends(require("stock.view"))],
)
def variance(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    days: int = Query(default=30, ge=1, le=180),
) -> VarianceReport:
    end = date.today()
    requested = end - timedelta(days=days)

    # مقارنة المبيعات بالمخزن قبل ما المخزن يتشغّل مالهاش معنى: المبيعات
    # موجودة من سنين والحركة لسه بادئة، فالفرق بيطلع رقم مرعب وكاذب.
    # بنقصّ المدى على أول حركة فعلية ونقول للمستخدم إننا عملنا كده.
    first = db.execute(
        select(func.min(StockMovement.business_date)).where(
            StockMovement.property_id == prop.id
        )
    ).scalar_one()
    # sqlite بترجّع الدوال المجمّعة على التواريخ كنص — بنوحّد النوع
    if isinstance(first, str):
        first = date.fromisoformat(first[:10])

    start = max(requested, first) if first else requested
    rows = recipe_svc.variance(db, prop.id, start, end)
    return VarianceReport(
        start_date=start,
        end_date=end,
        tracking_since=first,
        was_clamped=bool(first and first > requested),
        rows=[
            VarianceOut(
                stock_item_id=r.item.id,
                item_name_ar=r.item.name_ar,
                unit=r.item.unit,
                theoretical=r.theoretical,
                actual=r.actual,
                waste=r.waste,
                variance=r.variance,
                variance_percent=r.variance_percent,
                cost_impact=r.cost_impact,
            )
            for r in rows
        ],
        total_impact=sum((r.cost_impact for r in rows), Decimal("0")),
        uncovered_items=len(recipe_svc.menu_items_without_recipe(db, prop.id)),
    )


# ═══════════════════════════════════════════════════════ المشتريات
def _po_out(order: PurchaseOrder, suppliers: dict, items: dict) -> PurchaseOut:
    supplier = suppliers.get(order.supplier_id)
    return PurchaseOut(
        id=order.id,
        number=order.number,
        supplier_id=order.supplier_id,
        supplier_name_ar=supplier.name_ar if supplier else "—",
        warehouse_id=order.warehouse_id,
        status=order.status,
        order_date=order.order_date,
        expected_date=order.expected_date,
        received_date=order.received_date,
        subtotal=order.subtotal,
        grand_total=order.grand_total,
        supplier_invoice_number=order.supplier_invoice_number,
        notes=order.notes,
        lines=[
            PoLineOut(
                id=line.id,
                stock_item_id=line.stock_item_id,
                item_name_ar=items[line.stock_item_id].name_ar
                if line.stock_item_id in items
                else "—",
                unit=items[line.stock_item_id].unit
                if line.stock_item_id in items
                else StockUnit.PIECE,
                quantity_ordered=line.quantity_ordered,
                quantity_received=line.quantity_received,
                outstanding=line.outstanding,
                unit_cost=line.unit_cost,
                line_total=line.line_total,
            )
            for line in sorted(order.lines, key=lambda x: x.id)
        ],
    )


def _po_catalogs(db, prop) -> tuple[dict, dict]:
    suppliers = {
        s.id: s
        for s in db.execute(
            select(Supplier).where(Supplier.property_id == prop.id)
        ).scalars().all()
    }
    items = {
        s.id: s
        for s in db.execute(
            select(StockItem).where(StockItem.property_id == prop.id)
        ).scalars().all()
    }
    return suppliers, items


@router.get(
    "/suppliers",
    response_model=list[SupplierOut],
    summary="الموردون",
    dependencies=[Depends(require("stock.view"))],
)
def suppliers(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[SupplierOut]:
    rows = db.execute(
        select(Supplier)
        .where(Supplier.property_id == prop.id, Supplier.is_active.is_(True))
        .order_by(Supplier.name_ar)
    ).scalars().all()
    return [
        SupplierOut(
            id=s.id,
            code=s.code,
            name_ar=s.name_ar,
            name_en=s.name_en,
            phone=s.phone,
            payment_terms_days=s.payment_terms_days,
        )
        for s in rows
    ]


@router.get(
    "/purchases",
    response_model=PurchaseBoardOut,
    summary="أوامر الشراء",
    dependencies=[Depends(require("stock.view"))],
)
def purchases(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    po_status: PurchaseStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> PurchaseBoardOut:
    counts = po_svc.board(db, prop.id)
    stmt = select(PurchaseOrder).where(PurchaseOrder.property_id == prop.id)
    if po_status:
        stmt = stmt.where(PurchaseOrder.status == po_status)
    rows = list(
        db.execute(stmt.order_by(PurchaseOrder.id.desc()).limit(limit)).scalars().all()
    )
    suppliers_, items = _po_catalogs(db, prop)
    return PurchaseBoardOut(
        draft=counts.draft,
        sent=counts.sent,
        partial=counts.partial,
        received_this_month=counts.received_this_month,
        outstanding_value=counts.outstanding_value,
        spend_this_month=counts.spend_this_month,
        orders=[_po_out(o, suppliers_, items) for o in rows],
    )


@router.post(
    "/purchases",
    response_model=PurchaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="أمر شراء جديد",
    dependencies=[Depends(require("stock.manage"))],
)
def create_purchase(
    payload: CreatePoIn, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> PurchaseOut:
    try:
        order = po_svc.create_order(
            db,
            prop.id,
            supplier_id=payload.supplier_id,
            warehouse_id=payload.warehouse_id,
            lines=[(l.stock_item_id, l.quantity, l.unit_cost) for l in payload.lines],
            expected_date=payload.expected_date,
            notes=payload.notes,
            user=user,
        )
    except po_svc.PurchaseError as exc:
        raise _fail(exc) from exc
    suppliers_, items = _po_catalogs(db, prop)
    return _po_out(order, suppliers_, items)


@router.post(
    "/purchases/{order_id}/send",
    response_model=PurchaseOut,
    summary="اعتماد وإرسال",
    dependencies=[Depends(require("stock.manage"))],
)
def send_purchase(
    order_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> PurchaseOut:
    _own_po(db, prop, order_id)
    try:
        order = po_svc.send(db, order_id)
    except po_svc.PurchaseError as exc:
        raise _fail(exc) from exc
    suppliers_, items = _po_catalogs(db, prop)
    return _po_out(order, suppliers_, items)


@router.post(
    "/purchases/{order_id}/receive",
    response_model=PurchaseOut,
    summary="استلام",
    dependencies=[Depends(require("stock.manage"))],
)
def receive_purchase(
    order_id: int,
    payload: ReceiveIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> PurchaseOut:
    _own_po(db, prop, order_id)
    try:
        result = po_svc.receive(
            db,
            prop.id,
            order_id,
            [(l.line_id, l.quantity, l.actual_cost) for l in payload.lines],
            supplier_invoice_number=payload.supplier_invoice_number,
            user=user,
        )
    except (po_svc.PurchaseError, stock_svc.StockError) as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="PurchaseOrder",
        entity_id=order_id,
        user=user,
        property_id=prop.id,
        summary_ar=f"استلام على أمر {result.order.number} بقيمة {result.total_value}"
        + (" — اكتمل" if result.fully_received else " — جزئي"),
        summary_en=f"Received {result.total_value} on {result.order.number}",
        request=request,
    )
    suppliers_, items = _po_catalogs(db, prop)
    return _po_out(result.order, suppliers_, items)


@router.post(
    "/purchases/{order_id}/cancel",
    response_model=PurchaseOut,
    summary="إلغاء أمر",
    dependencies=[Depends(require("stock.manage"))],
)
def cancel_purchase(
    order_id: int,
    payload: ReasonIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
) -> PurchaseOut:
    _own_po(db, prop, order_id)
    try:
        order = po_svc.cancel(db, order_id, payload.reason)
    except po_svc.PurchaseError as exc:
        raise _fail(exc) from exc
    suppliers_, items = _po_catalogs(db, prop)
    return _po_out(order, suppliers_, items)


@router.get(
    "/purchases/suggest",
    response_model=list[dict],
    summary="اقتراح طلبية من النواقص",
    dependencies=[Depends(require("stock.view"))],
)
def suggest(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    supplier_id: int | None = None,
) -> list[dict]:
    return [
        {
            "stock_item_id": item.id,
            "name_ar": item.name_ar,
            "unit": item.unit,
            "quantity": str(amount),
            "unit_cost": str(item.last_purchase_cost or item.average_cost),
            "preferred_supplier_id": item.preferred_supplier_id,
        }
        for item, amount in po_svc.suggest_reorder(db, prop.id, supplier_id)
    ]


def _own_po(db, prop, order_id: int) -> PurchaseOrder:
    order = db.get(PurchaseOrder, order_id)
    if order is None or order.property_id != prop.id:
        raise HTTPException(
            status_code=404,
            detail={"ar": "أمر الشراء غير موجود", "en": "Purchase order not found"},
        )
    return order
