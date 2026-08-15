"""وصفات المنيو — Menu item recipes seed.

    python -m scripts.seed_recipes

الوصفة هي اللي بتخلّي المخزن يعرف يخصم إيه. من غيرها «تكلفة المبيعات»
رقم بيتكتب بالإيد ومحدش بيصدّقه.

**الكميات مكتوبة بالجرام والمللي زي ما الشيف بيقيس فعلاً**، والفاقد
منفصل عن الكمية الصافية: 22% فاقد على السمك يعني التنضيف والتقفيص،
مش إن الطبق فيه سمك أكتر.

آمن التكرار: بيحدّث الوصفة الموجودة بدل ما يعملها تاني، فتشغيله بعد
تغيير سعر أو مكوّن بيصلّح البيانات مش بيكرّرها.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.organization import Property
from app.models.pos import MenuItem
from app.models.stock import Recipe, RecipeLine, StockItem, Warehouse
from app.services import recipes as recipe_svc

#: (كود صنف المنيو، [(كود الصنف المخزني، الكمية، نسبة الفاقد %)])
#: الكميات بوحدة الصنف المخزني — كيلو للحوم والخضار، لتر للزيت، وحدة للزجاجات
RECIPES: dict[str, list[tuple[str, str, str]]] = {
    # ── المقبلات ──
    "APP03": [("ST-CHEESE", "0.080", "3"), ("ST-FLOUR", "0.060", "5"),
              ("ST-OIL", "0.040", "0")],
    "APP04": [("ST-BEEF", "0.180", "12"), ("ST-ONION", "0.050", "18"),
              ("ST-SPICE", "0.006", "0"), ("ST-OIL", "0.020", "0")],
    # ── الشوربة ──
    "SOUP01": [("ST-ONION", "0.040", "18"), ("ST-SPICE", "0.004", "0"),
               ("ST-OIL", "0.015", "0")],
    # الجمبري في الشوربة حصة معقولة — 40 جرام مش 90
    "SOUP02": [("ST-SHRMP", "0.040", "16"), ("ST-BASS", "0.045", "22"),
               ("ST-BUTTER", "0.015", "0")],
    # ── السلطات ──
    "SLD01": [("ST-LETT", "0.140", "15"), ("ST-CHEESE", "0.030", "3"),
              ("ST-OIL", "0.020", "0"), ("ST-LEMON", "0.020", "10")],
    "SLD02": [("ST-TOM", "0.120", "8"), ("ST-LETT", "0.080", "15"),
              ("ST-CHEESE", "0.050", "3"), ("ST-OIL", "0.020", "0")],
    "SLD03": [("ST-TOM", "0.100", "8"), ("ST-ONION", "0.030", "18"),
              ("ST-LEMON", "0.015", "10")],
    # ── المشويات ──
    "GRL01": [("ST-BEEF", "0.280", "12"), ("ST-ONION", "0.040", "18"),
              ("ST-SPICE", "0.008", "0")],
    "GRL02": [("ST-LAMB", "0.320", "18"), ("ST-SPICE", "0.008", "0"),
              ("ST-OIL", "0.020", "0")],
    "GRL03": [("ST-CHICK", "0.400", "25"), ("ST-SPICE", "0.008", "0"),
              ("ST-LEMON", "0.030", "10")],
    "GRL04": [("ST-BEEF", "0.180", "12"), ("ST-LAMB", "0.180", "18"),
              ("ST-CHICK", "0.220", "25"), ("ST-SPICE", "0.012", "0")],
    # ── الأسماك ──
    # البلطي بيتعمل من بلطي مش من قاروص — الوصفة كانت غلط والفرق في
    # التكلفة كان بيخلّي الطبق يبان بيتباع بخسارة 45%
    "FSH01": [("ST-TILAP", "0.340", "35"), ("ST-LEMON", "0.040", "10"),
              ("ST-OIL", "0.030", "0")],
    "FSH02": [("ST-SHRMP", "0.220", "16"), ("ST-BUTTER", "0.030", "0"),
              ("ST-LEMON", "0.020", "10"), ("ST-SPICE", "0.004", "0")],
    "FSH04": [("ST-BASS", "0.200", "22"), ("ST-RICE", "0.120", "2"),
              ("ST-ONION", "0.050", "18"), ("ST-OIL", "0.025", "0")],
    # ── الباستا والأرز ──
    "PST01": [("ST-FLOUR", "0.110", "3"), ("ST-SHRMP", "0.090", "16"),
              ("ST-BASS", "0.060", "22"), ("ST-BUTTER", "0.025", "0")],
    "PST02": [("ST-FLOUR", "0.120", "3"), ("ST-CHEESE", "0.060", "3"),
              ("ST-BUTTER", "0.030", "0")],
    "PST03": [("ST-RICE", "0.140", "2"), ("ST-BUTTER", "0.015", "0"),
              ("ST-ONION", "0.020", "18")],
    # ── المشروبات الساخنة ──
    "HOT01": [("ST-COFFEE", "0.012", "0")],
    "HOT02": [("ST-COFFEE", "0.018", "0")],
    "HOT03": [("ST-COFFEE", "0.018", "0")],
    "HOT04": [("ST-TEA", "0.004", "0")],
    # ── المشروبات الباردة ──
    "CLD02": [("ST-LEMON", "0.080", "10")],
    "CLD03": [("ST-WATER", "1", "0")],
    "CLD04": [("ST-SODA", "1", "0")],
}

#: صنف مخزني ناقص كان بيخلّي وصفة البلطي تتعمل من قاروص
#: (كود، عربي، إنجليزي، تصنيف عربي، تصنيف إنجليزي، تكلفة، حد الطلب، كمية الطلب)
MISSING_ITEMS: list[tuple[str, str, str, str, str, str, str, str]] = [
    ("ST-TILAP", "بلطي", "Tilapia", "أسماك", "Fish", "95", "25", "40"),
]


def ensure_items(db: Session, prop: Property) -> int:
    """الأصناف المخزنية اللي الوصفات محتاجاها ومش موجودة."""
    have = {
        i.code
        for i in db.execute(
            select(StockItem).where(StockItem.property_id == prop.id)
        ).scalars()
    }
    reference = db.execute(
        select(StockItem).where(
            StockItem.property_id == prop.id, StockItem.code == "ST-BASS"
        )
    ).scalar_one_or_none()

    made = 0
    for code, ar, en, cat_ar, cat_en, cost, reorder, quantity in MISSING_ITEMS:
        if code in have:
            continue
        db.add(
            StockItem(
                property_id=prop.id,
                code=code,
                name_ar=ar,
                name_en=en,
                category_ar=cat_ar,
                category_en=cat_en,
                unit=reference.unit if reference else "KG",
                average_cost=Decimal(cost),
                last_purchase_cost=Decimal(cost),
                reorder_level=Decimal(reorder),
                reorder_quantity=Decimal(quantity),
                preferred_supplier_id=(
                    reference.preferred_supplier_id if reference else None
                ),
                is_critical=True,
                sort_order=99,
                is_active=True,
            )
        )
        made += 1
    db.flush()
    return made


def build(db: Session, prop: Property) -> tuple[int, int, list[str]]:
    """إنشاء أو تحديث الوصفات — بيرجّع (جديد، محدّث، أصناف ناقصة)."""
    menu = {
        m.code: m
        for m in db.execute(
            select(MenuItem).where(MenuItem.property_id == prop.id)
        ).scalars()
    }
    items = {
        i.code: i
        for i in db.execute(
            select(StockItem).where(StockItem.property_id == prop.id)
        ).scalars()
    }
    kitchen = db.execute(
        select(Warehouse).where(
            Warehouse.property_id == prop.id, Warehouse.code == "WH-KIT"
        )
    ).scalar_one_or_none()

    existing = {
        r.menu_item_id: r
        for r in db.execute(
            select(Recipe).where(Recipe.property_id == prop.id)
        ).scalars()
    }

    made = updated = 0
    missing: list[str] = []

    for menu_code, ingredients in RECIPES.items():
        menu_item = menu.get(menu_code)
        if menu_item is None:
            missing.append(f"صنف منيو {menu_code}")
            continue

        unknown = [c for c, _, _ in ingredients if c not in items]
        if unknown:
            missing.extend(f"صنف مخزني {c} (في {menu_code})" for c in unknown)
            continue

        recipe = existing.get(menu_item.id)
        if recipe is None:
            recipe = Recipe(
                property_id=prop.id,
                menu_item_id=menu_item.id,
                warehouse_id=kitchen.id if kitchen else None,
                yield_portions=Decimal("1"),
                is_active=True,
            )
            db.add(recipe)
            db.flush()
            made += 1
        else:
            # التحديث بيمسح المكوّنات القديمة ويكتبها من الأول — الوصفة
            # تعريف مش سجل حركة، فالكتابة فوقها مسموحة
            for line in list(recipe.lines):
                db.delete(line)
            db.flush()
            updated += 1

        for stock_code, quantity, waste in ingredients:
            stock_item = items[stock_code]
            db.add(
                RecipeLine(
                    recipe_id=recipe.id,
                    stock_item_id=stock_item.id,
                    quantity=Decimal(quantity),
                    waste_percent=Decimal(waste),
                    unit_cost=stock_item.average_cost,
                )
            )
    db.flush()
    return made, updated, missing


def run() -> None:
    db = SessionLocal()
    try:
        prop = db.execute(
            select(Property).where(Property.code == "VNC")
        ).scalar_one_or_none()
        if prop is None:
            print("المنشأة مش موجودة — شغّل seed_master الأول")
            return

        print("الأصناف المخزنية الناقصة...")
        added = ensure_items(db, prop)

        print("الوصفات...")
        made, updated, missing = build(db, prop)
        db.commit()

        recipe_svc.refresh_costs(db, prop.id)
        db.commit()

        rows = recipe_svc.menu_items_without_recipe(db, prop.id)
        all_recipes = list(
            db.execute(
                select(Recipe).where(Recipe.property_id == prop.id)
            ).scalars().all()
        )
        menu_prices = {
            m.id: m.price
            for m in db.execute(
                select(MenuItem).where(MenuItem.property_id == prop.id)
            ).scalars()
        }
        losing = [
            r
            for r in all_recipes
            if menu_prices.get(r.menu_item_id, Decimal("0")) > 0
            and r.cost >= menu_prices[r.menu_item_id]
        ]

        print()
        print("─" * 52)
        print(f"  أصناف مخزنية جديدة   {added}")
        print(f"  وصفات جديدة          {made}")
        print(f"  وصفات محدّثة         {updated}")
        print(f"  أصناف منيو بلا وصفة  {len(rows)}")
        print(f"  أصناف بتتباع بخسارة  {len(losing)}")
        if missing:
            print(f"  ✗ ناقص: {', '.join(missing[:6])}")
        for recipe in losing:
            item = next(
                (m for m in db.execute(
                    select(MenuItem).where(MenuItem.id == recipe.menu_item_id)
                ).scalars()), None
            )
            if item:
                print(f"    − {item.name_ar}: تكلفة {recipe.cost:,.0f} · سعر {item.price:,.0f}")
        print("─" * 52)
    finally:
        db.close()


if __name__ == "__main__":
    run()
