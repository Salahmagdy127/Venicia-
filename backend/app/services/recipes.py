"""الوصفات وخصم المخزون والفرق — Recipes, depletion and variance.

الموديول ده هو اللي بيربط الكاشير بالمخزن، وبيدّي الرقم اللي المالك
بيشتري النظام عشانه:

    اللي **المفروض** يتصرف   ←   من الوصفات × المبيعات
    اللي **اتصرف فعلاً**      ←   من حركات المخزن
    ─────────────────────────────────────────────
    الفـــرق = هالك أو سرقة أو وصفة غلط

من غير وصفات، «تكلفة المبيعات» بتبقى رقم بيتكتب بالإيد ومحدش بيصدّقه.
مع الوصفات بيبقى محسوب من الحركة الفعلية.

**الخصم بيحصل عند التقفيل مش عند الطلب** عن قصد: الأوردر ممكن يتلغي أو
يتعدّل وهو مفتوح، والمخزن مالوش دعوة بده. أول ما الأوردر يتقفل ويتحاسب،
الأكل خرج فعلاً.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import MovementKind
from app.models.pos import MenuItem, PosOrder, PosOrderLine
from app.models.security import User
from app.models.stock import Recipe, RecipeLine, StockItem, StockMovement, Warehouse
from app.services import stock as stock_svc
from app.services.pricing import money

ZERO = Decimal("0")


class RecipeError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "recipe_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


# ═══════════════════════════════════════════════════════ تحرير الوصفة
def save_recipe(
    db: Session,
    property_id: int,
    menu_item_id: int,
    lines: Sequence[tuple[int, Decimal, Decimal]],
    *,
    warehouse_id: int | None = None,
    yield_portions: Decimal = Decimal("1"),
    notes: str | None = None,
) -> Recipe:
    """حفظ وصفة — ``lines`` = (رقم الصنف، الكمية، نسبة الفاقد)."""
    item = db.get(MenuItem, menu_item_id)
    if item is None or item.property_id != property_id:
        raise RecipeError("صنف المنيو غير موجود", "Menu item not found", "not_found")
    if yield_portions <= 0:
        raise RecipeError(
            "عدد الأطباق لازم يكون أكبر من صفر", "Yield must be positive", "bad_yield"
        )
    if not lines:
        raise RecipeError("الوصفة لازم يكون فيها مكوّن واحد على الأقل", "Recipe is empty", "empty")

    if warehouse_id is not None:
        warehouse = db.get(Warehouse, warehouse_id)
        if warehouse is None or warehouse.property_id != property_id:
            raise RecipeError("المخزن غير موجود", "Warehouse not found", "not_found")

    catalog = {
        s.id: s
        for s in db.execute(
            select(StockItem).where(StockItem.property_id == property_id)
        ).scalars().all()
    }

    seen: set[int] = set()
    for stock_item_id, quantity, waste in lines:
        if stock_item_id not in catalog:
            raise RecipeError("صنف مخزني غير موجود", "Unknown stock item", "unknown_item")
        if quantity <= 0:
            raise RecipeError(
                "كمية المكوّن لازم تكون أكبر من صفر", "Ingredient quantity must be positive",
                "bad_qty",
            )
        if not 0 <= waste <= 90:
            raise RecipeError(
                "نسبة الفاقد لازم تكون بين صفر و90%", "Waste must be between 0 and 90%",
                "bad_waste",
            )
        if stock_item_id in seen:
            raise RecipeError(
                "المكوّن ده متكرر في الوصفة", "Duplicate ingredient", "duplicate"
            )
        seen.add(stock_item_id)

    recipe = db.execute(
        select(Recipe).where(Recipe.menu_item_id == menu_item_id)
    ).scalar_one_or_none()
    if recipe is None:
        recipe = Recipe(property_id=property_id, menu_item_id=menu_item_id)
        db.add(recipe)
        db.flush()

    recipe.warehouse_id = warehouse_id
    recipe.yield_portions = yield_portions
    recipe.notes = (notes or "").strip() or None
    recipe.is_active = True

    for old in list(recipe.lines):
        db.delete(old)
    db.flush()

    for stock_item_id, quantity, waste in lines:
        recipe.lines.append(
            RecipeLine(
                recipe_id=recipe.id,
                stock_item_id=stock_item_id,
                quantity=quantity,
                waste_percent=waste,
                # لقطة من التكلفة الحالية — بتتحدّث مع كل حفظ
                unit_cost=catalog[stock_item_id].average_cost,
            )
        )
    db.flush()

    # تكلفة صنف المنيو بقت **محسوبة** مش مكتوبة بالإيد
    item.cost = money(recipe.cost)
    db.flush()
    return recipe


def refresh_costs(db: Session, property_id: int) -> int:
    """إعادة حساب تكلفة كل الوصفات من متوسط التكلفة الحالي.

    بيتنادى بعد استلام كبير: أسعار الموردين اتغيّرت، يبقى تكلفة الطبق
    اتغيّرت، يبقى هامش الربح في التقارير كان بيكدب لحد ما نحدّثه.
    """
    costs = dict(
        db.execute(
            select(StockItem.id, StockItem.average_cost).where(
                StockItem.property_id == property_id
            )
        ).all()
    )
    recipes = list(
        db.execute(
            select(Recipe)
            .options(selectinload(Recipe.lines))
            .where(Recipe.property_id == property_id, Recipe.is_active.is_(True))
        ).scalars().all()
    )

    touched = 0
    for recipe in recipes:
        for line in recipe.lines:
            line.unit_cost = money(Decimal(str(costs.get(line.stock_item_id, 0))))
        item = db.get(MenuItem, recipe.menu_item_id)
        if item is not None:
            item.cost = money(recipe.cost)
        touched += 1
    db.flush()
    return touched


# ═══════════════════════════════════════════════════════ الخصم
@dataclass(slots=True)
class DepletionResult:
    order_id: int
    movements: int = 0
    total_cost: Decimal = ZERO
    #: أصناف اتباعت ومالهاش وصفة — دي أهم مخرجات العملية
    missing_recipes: list[str] = field(default_factory=list)


def deplete_for_order(
    db: Session,
    property_id: int,
    order_id: int,
    *,
    user: User | None = None,
    business_date: date | None = None,
) -> DepletionResult:
    """خصم مكوّنات أوردر اتقفل من المخزن.

    آمن التكرار: لو الأوردر ده اتخصم قبل كده، مبيتخصمش تاني.
    """
    order = db.get(PosOrder, order_id)
    if order is None or order.property_id != property_id:
        raise RecipeError("الأوردر غير موجود", "Order not found", "not_found")

    already = db.execute(
        select(func.count(StockMovement.id)).where(StockMovement.pos_order_id == order_id)
    ).scalar_one()
    if already:
        return DepletionResult(order_id=order_id)

    lines = list(
        db.execute(
            select(PosOrderLine).where(
                PosOrderLine.order_id == order_id, PosOrderLine.is_void.is_(False)
            )
        ).scalars().all()
    )
    if not lines:
        return DepletionResult(order_id=order_id)

    recipes = {
        r.menu_item_id: r
        for r in db.execute(
            select(Recipe)
            .options(selectinload(Recipe.lines))
            .where(Recipe.property_id == property_id, Recipe.is_active.is_(True))
        ).scalars().all()
    }
    default_warehouse = _outlet_warehouse(db, property_id, order.outlet_id)

    result = DepletionResult(order_id=order_id)
    #: بنجمّع المكوّنات الأول عشان صنفين فيهم نفس المكوّن يطلعوا حركة واحدة
    needed: dict[tuple[int, int], Decimal] = {}

    for line in lines:
        if line.menu_item_id is None:
            continue
        recipe = recipes.get(line.menu_item_id)
        if recipe is None:
            result.missing_recipes.append(line.item_name_ar)
            continue

        warehouse_id = recipe.warehouse_id or default_warehouse
        if warehouse_id is None:
            result.missing_recipes.append(line.item_name_ar)
            continue

        portions = line.quantity / (recipe.yield_portions or Decimal("1"))
        for ingredient in recipe.lines:
            key = (warehouse_id, ingredient.stock_item_id)
            needed[key] = needed.get(key, ZERO) + ingredient.gross_quantity * portions

    for (warehouse_id, stock_item_id), amount in needed.items():
        if amount <= 0:
            continue
        movement = stock_svc.record(
            db,
            property_id,
            warehouse_id=warehouse_id,
            stock_item_id=stock_item_id,
            kind=MovementKind.ISSUE,
            quantity=amount,
            business_date=business_date or order.business_date,
            reason=f"صرف على أوردر {order.code}",
            pos_order_id=order_id,
            user=user,
            # المطبخ طبخ فعلاً — الرصيد السالب إشارة استلام ناقص مش سبب منع
            allow_negative=True,
        )
        result.movements += 1
        result.total_cost += movement.total_cost

    result.total_cost = money(result.total_cost)
    db.flush()
    return result


def _outlet_warehouse(db: Session, property_id: int, outlet_id: int | None) -> int | None:
    """مخزن المنفذ، وإلا المخزن الرئيسي."""
    if outlet_id is not None:
        found = db.execute(
            select(Warehouse.id).where(
                Warehouse.property_id == property_id,
                Warehouse.outlet_id == outlet_id,
                Warehouse.is_active.is_(True),
            ).limit(1)
        ).scalar_one_or_none()
        if found is not None:
            return found
    return db.execute(
        select(Warehouse.id)
        .where(Warehouse.property_id == property_id, Warehouse.is_active.is_(True))
        .order_by(Warehouse.sort_order, Warehouse.id)
        .limit(1)
    ).scalar_one_or_none()


# ═══════════════════════════════════════════════════════ الفرق
@dataclass(slots=True)
class VarianceRow:
    item: StockItem
    theoretical: Decimal      # المفروض يتصرف حسب الوصفات
    actual: Decimal           # اتصرف فعلاً من الحركات
    waste: Decimal            # المسجّل كهالك صراحةً
    variance: Decimal         # الفرق غير المفسّر
    variance_percent: Decimal
    cost_impact: Decimal


def variance(
    db: Session, property_id: int, start: date, end: date
) -> list[VarianceRow]:
    """المفروض مقابل الفعلي — الرقم اللي بيمسك الهالك والسرقة.

    الفرق الموجب يعني اتصرف أكتر من اللازم: هالك مش متسجّل، أو حصص
    أكبر من الوصفة، أو حاجة ماشية من غير ما تتباع.
    """
    sold = db.execute(
        select(PosOrderLine.menu_item_id, func.sum(PosOrderLine.quantity))
        .join(PosOrder, PosOrder.id == PosOrderLine.order_id)
        .where(
            PosOrder.property_id == property_id,
            PosOrder.business_date.between(start, end),
            PosOrder.is_void.is_(False),
            PosOrderLine.is_void.is_(False),
            PosOrderLine.menu_item_id.is_not(None),
        )
        .group_by(PosOrderLine.menu_item_id)
    ).all()

    recipes = {
        r.menu_item_id: r
        for r in db.execute(
            select(Recipe)
            .options(selectinload(Recipe.lines))
            .where(Recipe.property_id == property_id)
        ).scalars().all()
    }

    theoretical: dict[int, Decimal] = {}
    for menu_item_id, quantity in sold:
        recipe = recipes.get(menu_item_id)
        if recipe is None:
            continue
        portions = Decimal(str(quantity)) / (recipe.yield_portions or Decimal("1"))
        for ingredient in recipe.lines:
            theoretical[ingredient.stock_item_id] = theoretical.get(
                ingredient.stock_item_id, ZERO
            ) + ingredient.gross_quantity * portions

    def totals(kinds: Sequence[MovementKind]) -> dict[int, Decimal]:
        rows = db.execute(
            select(StockMovement.stock_item_id, func.sum(StockMovement.quantity))
            .where(
                StockMovement.property_id == property_id,
                StockMovement.business_date.between(start, end),
                StockMovement.kind.in_(list(kinds)),
            )
            .group_by(StockMovement.stock_item_id)
        ).all()
        return {item_id: stock_svc.qty(total) for item_id, total in rows}

    issued = totals([MovementKind.ISSUE])
    wasted = totals([MovementKind.WASTE])

    catalog = {
        s.id: s
        for s in db.execute(
            select(StockItem).where(StockItem.property_id == property_id)
        ).scalars().all()
    }

    rows: list[VarianceRow] = []
    for item_id in set(theoretical) | set(issued) | set(wasted):
        item = catalog.get(item_id)
        if item is None:
            continue
        expected = stock_svc.qty(theoretical.get(item_id, ZERO))
        real = stock_svc.qty(issued.get(item_id, ZERO))
        lost = stock_svc.qty(wasted.get(item_id, ZERO))
        gap = stock_svc.qty(real + lost - expected)
        if expected == 0 and gap == 0:
            continue
        rows.append(
            VarianceRow(
                item=item,
                theoretical=expected,
                actual=real,
                waste=lost,
                variance=gap,
                variance_percent=(
                    stock_svc.qty(gap / expected * 100) if expected else Decimal("100")
                ),
                cost_impact=money(gap * item.average_cost),
            )
        )

    # الأغلى أولاً — ده اللي المالك عايز يشوفه
    rows.sort(key=lambda r: r.cost_impact, reverse=True)
    return rows


def menu_items_without_recipe(db: Session, property_id: int) -> list[MenuItem]:
    """أصناف بتتباع ومفيش وصفة ليها — كل واحد منهم ثقب في حساب التكلفة."""
    linked = select(Recipe.menu_item_id).where(Recipe.property_id == property_id)
    return list(
        db.execute(
            select(MenuItem)
            .where(
                MenuItem.property_id == property_id,
                MenuItem.is_active.is_(True),
                MenuItem.id.not_in(linked),
            )
            .order_by(MenuItem.sort_order)
        ).scalars().all()
    )
