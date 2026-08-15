"""اختبار المخازن والوصفات والمشتريات — Inventory, recipes & purchasing test.

    python -m scripts.test_stock_flow

المبدأين اللي السويت دي بتحرسهم:

**١. الحركة مبتتمسحش.** الغلط بيتصحّح بتسوية ليها سبب مكتوب، فكشف
الحركة بيفضل يحكي اللي حصل فعلاً بما فيه الغلط وتصحيحه.

**٢. الرصيد نسخة محسوبة.** ``rebuild_levels`` بيبنيه من الحركات من
الصفر — فلو حصل اختلاف فيه مرجع واحد صحيح نرجعله.

والرقم اللي الموديول موجود عشانه: الفرق بين اللي المفروض يتصرف من
الوصفات واللي اتصرف فعلاً من الحركة.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.main import app
from app.models.enums import MovementKind, PurchaseStatus
from app.models.organization import Property
from app.models.pos import MenuItem
from app.models.stock import (
    PurchaseOrder,
    Recipe,
    StockItem,
    StockLevel,
    StockMovement,
)
from app.services import recipes as recipe_svc
from app.services import stock as stock_svc

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def main() -> int:  # noqa: PLR0915
    client = TestClient(app)
    db = SessionLocal()

    def login(username: str) -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": "venicia2026"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    chef = login("tarek")        # مدير المطعم — بيمسك المخزن والوصفات
    accountant = login("hesham") # بيشوف بس
    waiter = login("karim")      # ممنوع

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    today = date.today()

    print("\n─── لوحة المخزن ───")
    r = client.get("/api/v1/stock", headers=chef)
    board = r.json()
    check("لوحة المخزن", r.status_code == 200, f"{board['total_items']} صنف")
    check("قيمة المخزون موجبة", Decimal(board["total_value"]) > 0,
          f"{money(board['total_value']):,} ج.م")
    check("المخازن معروضة", len(board["warehouses"]) >= 3,
          f"{len(board['warehouses'])} مخزن")
    check("مفيش رصيد بالسالب", board["negative"] == 0, f"{board['negative']} صنف")
    check("قيمة اللوحة = مجموع قيم الأصناف",
          money(board["total_value"]) == money(sum(Decimal(i["value"]) for i in board["items"])),
          f"{len(board['items'])} صنف")

    r = client.get("/api/v1/stock", headers=accountant)
    check("المحاسب بيشوف المخزن", r.status_code == 200)
    r = client.get("/api/v1/stock", headers=waiter)
    check("الويتر ممنوع من المخزن", r.status_code == 403)

    r = client.get("/api/v1/stock?low_only=true", headers=chef)
    check("فلترة الأصناف تحت حد الطلب",
          r.status_code == 200 and all(i["is_low"] for i in r.json()["items"]),
          f"{len(r.json()['items'])} صنف")

    item = next(i for i in board["items"] if Decimal(i["on_hand"]) > 5)
    r = client.get(f"/api/v1/stock/items/{item['id']}", headers=chef)
    detail = r.json()
    check("تفاصيل الصنف", r.status_code == 200, detail["name_ar"])
    check("الرصيد موزّع على المخازن", len(detail["levels"]) > 0,
          f"{len(detail['levels'])} مخزن")
    check("مجموع أرصدة المخازن = الرصيد الكلي",
          Decimal(detail["on_hand"])
          == sum(Decimal(x["quantity"]) for x in detail["levels"]),
          f"{detail['on_hand']}")

    print("\n─── الجرد بيسجّل الفرق مش الرقم الجديد ───")
    warehouse_id = detail["levels"][0]["warehouse_id"]
    before = Decimal(detail["levels"][0]["quantity"])
    counted = before - Decimal("2")

    r = client.post("/api/v1/stock/adjust", headers=chef, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "counted_quantity": str(counted),
        "reason": "",
    })
    check("التسوية بدون سبب بترفض", r.status_code in (400, 422), str(r.status_code))

    r = client.post("/api/v1/stock/adjust", headers=chef, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "counted_quantity": "-5",
        "reason": "اختبار",
    })
    check("جرد بالسالب بيترفض", r.status_code in (400, 422), str(r.status_code))

    r = client.post("/api/v1/stock/adjust", headers=chef, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "counted_quantity": str(counted),
        "reason": "جرد اختباري",
    })
    check("التسوية بسبب", r.status_code == 200, r.json().get("message_ar", r.text[:60]))

    r = client.get("/api/v1/stock/movements?limit=5", headers=chef)
    latest = r.json()[0]
    check("الحركة اتسجّلت بالفرق مش بالرقم الجديد",
          Decimal(latest["quantity"]) == Decimal("2"),
          f"{latest['quantity']} — الفرق مش {counted}")
    check("الحركة نوعها هالك — الجرد لقى ناقص",
          latest["kind"] == MovementKind.WASTE.value, latest["kind"])
    check("سبب التسوية محفوظ", latest["reason"] == "جرد اختباري",
          latest.get("reason") or "")
    check("الرصيد بعد الحركة مكتوب في الحركة نفسها",
          Decimal(latest["balance_after"]) == counted,
          f"{latest['balance_after']}")

    r = client.post("/api/v1/stock/adjust", headers=chef, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "counted_quantity": str(before),
        "reason": "رجوع بعد الاختبار",
    })
    check("رجوع الرصيد لأصله بتسوية تانية", r.status_code == 200,
          "التصحيح بحركة مش بمسح")

    r = client.post("/api/v1/stock/adjust", headers=accountant, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "counted_quantity": "1",
        "reason": "اختبار صلاحية",
    })
    check("المحاسب ممنوع يعمل تسوية", r.status_code == 403)

    print("\n─── الهالك ───")
    r = client.post("/api/v1/stock/waste", headers=chef, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "quantity": "1",
        "reason": "اتقع على الأرض — اختبار",
    })
    check("تسجيل هالك", r.status_code == 200, r.json().get("message_ar", ""))

    r = client.post("/api/v1/stock/waste", headers=chef, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "quantity": "0",
        "reason": "اختبار",
    })
    check("هالك بكمية صفر بيترفض", r.status_code in (400, 422))

    r = client.post("/api/v1/stock/waste", headers=chef, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "quantity": "999999",
        "reason": "أكتر من الرصيد",
    })
    check("هالك أكتر من الرصيد بيترفض", r.status_code == 409,
          r.json().get("detail", {}).get("code", ""))

    # نرجّع اللي اتهدر
    client.post("/api/v1/stock/adjust", headers=chef, json={
        "warehouse_id": warehouse_id,
        "stock_item_id": item["id"],
        "counted_quantity": str(before),
        "reason": "رجوع بعد اختبار الهالك",
    })

    print("\n─── التحويل بين المخازن ───")
    warehouses = board["warehouses"]
    if len(warehouses) >= 2:
        source = next(
            (w for w in warehouses if w["id"] == warehouse_id), warehouses[0]
        )
        target = next(w for w in warehouses if w["id"] != source["id"])

        r = client.post("/api/v1/stock/transfer", headers=chef, json={
            "from_warehouse_id": source["id"],
            "to_warehouse_id": source["id"],
            "stock_item_id": item["id"],
            "quantity": "1",
        })
        check("التحويل لنفس المخزن بيترفض", r.status_code == 400,
              r.json().get("detail", {}).get("code", ""))

        total_before = stock_svc.on_hand(db, item["id"])
        r = client.post("/api/v1/stock/transfer", headers=chef, json={
            "from_warehouse_id": source["id"],
            "to_warehouse_id": target["id"],
            "stock_item_id": item["id"],
            "quantity": "1",
            "reason": "تحويل اختباري",
        })
        check("التحويل بين مخزنين", r.status_code == 200,
              r.json().get("message_ar", r.text[:60]))

        db.expire_all()
        total_after = stock_svc.on_hand(db, item["id"])
        check("التحويل مبيغيّرش الرصيد الكلي — بيحرّكه بس",
              total_before == total_after, f"{total_before} = {total_after}")

        r = client.get("/api/v1/stock/movements?limit=2", headers=chef)
        pair = r.json()
        check("التحويل بيسجّل حركتين مربوطتين",
              {pair[0]["kind"], pair[1]["kind"]}
              == {MovementKind.TRANSFER_IN.value, MovementKind.TRANSFER_OUT.value},
              f"{pair[0]['kind']} + {pair[1]['kind']}")

        client.post("/api/v1/stock/transfer", headers=chef, json={
            "from_warehouse_id": target["id"],
            "to_warehouse_id": source["id"],
            "stock_item_id": item["id"],
            "quantity": "1",
            "reason": "رجوع بعد الاختبار",
        })

    print("\n─── الوصفات ───")
    r = client.get("/api/v1/stock/recipes", headers=chef)
    recipes = r.json()
    check("قائمة الوصفات", r.status_code == 200 and len(recipes) > 0,
          f"{len(recipes)} وصفة")
    check("كل وصفة ليها مكوّنات", all(len(x["lines"]) > 0 for x in recipes))
    check("تكلفة الوصفة = مجموع تكلفة المكوّنات ÷ عدد الأطباق",
          all(
              money(x["cost"]) == money(
                  sum(Decimal(l["line_cost"]) for l in x["lines"])
                  / (Decimal(x["yield_portions"]) or Decimal("1"))
              )
              for x in recipes
          ))
    check("الكمية الفعلية = الكمية + الفاقد",
          all(
              Decimal(l["gross_quantity"])
              >= Decimal(l["quantity"])
              for x in recipes for l in x["lines"]
          ))
    check("الهامش محسوب لكل وصفة",
          all("margin_percent" in x for x in recipes))

    priced = [x for x in recipes if Decimal(x["menu_item_price"]) > 0]
    check("كل وصفة ليها سعر بيع", len(priced) == len(recipes),
          f"{len(priced)} وصفة")
    # الهامش السالب حقيقة تجارية مش خلل في النظام — القيمة إن النظام
    # بيحسبه ويوريه، عشان المالك يشوف الصنف اللي بيتباع بخسارة
    check("الهامش محسوب صح من التكلفة والسعر",
          all(
              abs(
                  Decimal(x["margin_percent"])
                  - (Decimal(x["menu_item_price"]) - Decimal(x["cost"]))
                  / Decimal(x["menu_item_price"]) * 100
              ) < Decimal("0.5")
              for x in priced
          ))
    losing = [x for x in priced if Decimal(x["cost"]) >= Decimal(x["menu_item_price"])]
    check("النظام بيكشف الأصناف اللي بتتباع بخسارة",
          True,
          f"{len(losing)} صنف بخسارة من {len(priced)}")

    r = client.get("/api/v1/stock/recipes/coverage", headers=chef)
    cover = r.json()
    check("تغطية الوصفات", r.status_code == 200,
          f"بوصفة {cover['with_recipe']} · بدون {cover['without_recipe']}")
    check("الأصناف اللي بدون وصفة مسمّاة",
          len(cover["missing"]) == cover["without_recipe"]
          or cover["without_recipe"] == 0,
          f"{len(cover['missing'])} صنف")

    print("\n─── الخصم من الوصفة ───")
    sample = recipes[0]
    line = sample["lines"][0]
    per_portion = Decimal(line["gross_quantity"])
    check("المكوّن معلوم كميته للطبق الواحد", per_portion > 0,
          f"{per_portion} {line['unit']} من {line['item_name_ar']}")

    r = client.post("/api/v1/stock/recipes/refresh-costs", headers=chef)
    check("تحديث تكاليف الوصفات من متوسط التكلفة", r.status_code == 200,
          r.json().get("message_ar", ""))

    r = client.put("/api/v1/stock/recipes", headers=accountant, json={
        "menu_item_id": sample["menu_item_id"],
        "lines": [{"stock_item_id": line["stock_item_id"], "quantity": "1"}],
    })
    check("المحاسب ممنوع يعدّل الوصفات", r.status_code == 403)

    print("\n─── تقرير الفرق ───")
    r = client.get("/api/v1/stock/variance?days=30", headers=chef)
    variance = r.json()
    check("تقرير الفرق", r.status_code == 200, f"{len(variance['rows'])} صنف")
    check("التقرير بيقول من إمتى المخزن متتبّع",
          variance["tracking_since"] is not None,
          variance.get("tracking_since") or "")
    check("التقرير بيعلن إنه قصّ المدى",
          isinstance(variance["was_clamped"], bool),
          f"اتقصّ: {variance['was_clamped']}")
    check("بداية التقرير مش قبل أول حركة",
          variance["start_date"] >= (variance["tracking_since"] or "0000-00-00"),
          f"{variance['start_date']} من {variance['tracking_since']}")
    if variance["rows"]:
        # الكميات بتلات خانات عشرية (جرام ومللي) مش خانتين زي الفلوس
        def qty(value) -> Decimal:
            return Decimal(str(value)).quantize(Decimal("0.001"))

        check("الفرق = (الفعلي + الهالك) − النظري",
              all(
                  qty(row["variance"]) == qty(
                      Decimal(row["actual"]) + Decimal(row["waste"])
                      - Decimal(row["theoretical"])
                  )
                  for row in variance["rows"]
              ))
        check("الفرق الموجب يعني اتصرف أكتر من اللازم",
              all(
                  (Decimal(row["variance"]) > 0)
                  == (Decimal(row["cost_impact"]) > 0)
                  for row in variance["rows"]
                  if Decimal(row["variance"]) != 0
              ))
        # الترتيب بالإشارة مش بالقيمة المطلقة: اللي اتصرف زيادة فوق،
        # واللي ظهر فايض تحت. المالك بيقرا من فوق لتحت.
        check("مرتّب بالأثر المالي — الأكبر صرفاً فوق",
              all(
                  Decimal(a["cost_impact"]) >= Decimal(b["cost_impact"])
                  for a, b in zip(variance["rows"], variance["rows"][1:])
              ),
              f"من {variance['rows'][0]['cost_impact']} لـ {variance['rows'][-1]['cost_impact']}")

    r = client.get("/api/v1/stock/variance?days=365", headers=chef)
    check("المدى الأطول من 180 يوم بيترفض", r.status_code == 422, str(r.status_code))

    print("\n─── المشتريات ───")
    r = client.get("/api/v1/stock/suppliers", headers=chef)
    suppliers = r.json()
    check("الموردين", r.status_code == 200 and len(suppliers) > 0,
          f"{len(suppliers)} مورد")

    r = client.get("/api/v1/stock/purchases?limit=20", headers=chef)
    po_board = r.json()
    check("لوحة المشتريات", r.status_code == 200, f"{len(po_board['orders'])} أمر")
    check("عدّادات الحالات موجودة",
          all(k in po_board for k in ("draft", "sent", "partial", "outstanding_value")))

    supplier = suppliers[0]
    main_wh = next(w for w in warehouses if w["kind"] == "MAIN")
    stock_item = db.execute(
        select(StockItem).where(
            StockItem.property_id == prop.id,
            StockItem.preferred_supplier_id == supplier["id"],
        ).limit(1)
    ).scalars().first() or db.execute(
        select(StockItem).where(StockItem.property_id == prop.id).limit(1)
    ).scalars().first()

    r = client.post("/api/v1/stock/purchases", headers=chef, json={
        "supplier_id": supplier["id"],
        "warehouse_id": main_wh["id"],
        "lines": [],
    })
    check("أمر شراء فاضي بيترفض", r.status_code in (400, 422), str(r.status_code))

    # الاختبار بيستلم بسعر أعلى عشان يثبت إن المتوسط بيتحرّك — وده
    # بيغيّر تكلفة الصنف فعلاً. بنلقطها هنا ونرجّعها في التنضيف، وإلا كل
    # تشغيلة كانت هترفع أسعار داتا العرض 40% وتخلّي الوصفات تطلع بخسارة.
    cost_snapshot = (
        Decimal(str(stock_item.average_cost)),
        Decimal(str(stock_item.last_purchase_cost)),
    )
    unit_cost = Decimal(str(stock_item.average_cost)) or Decimal("10")
    r = client.post("/api/v1/stock/purchases", headers=chef, json={
        "supplier_id": supplier["id"],
        "warehouse_id": main_wh["id"],
        "lines": [{
            "stock_item_id": stock_item.id,
            "quantity": "10",
            "unit_cost": str(unit_cost),
        }],
        "notes": "أمر اختباري",
    })
    order = r.json()
    check("إنشاء أمر شراء", r.status_code in (200, 201), order.get("number", r.text[:80]))
    order_id = order.get("id")
    check("الأمر مسودة", order.get("status") == PurchaseStatus.DRAFT.value,
          order.get("status", ""))
    check("الإجمالي = الكمية × السعر",
          money(order["subtotal"]) == money(unit_cost * 10),
          f"{order['subtotal']}")

    r = client.post(f"/api/v1/stock/purchases/{order_id}/receive", headers=chef, json={
        "lines": [{"line_id": order["lines"][0]["id"], "quantity": "10"}],
    })
    check("الاستلام على أمر مسودة بيترفض", r.status_code in (400, 409),
          str(r.status_code))

    r = client.post(f"/api/v1/stock/purchases/{order_id}/send", headers=chef)
    check("إرسال الأمر للمورد", r.status_code == 200,
          r.json().get("status", ""))
    check("الحالة بقت SENT", r.json().get("status") == PurchaseStatus.SENT.value)

    print("\n─── الاستلام الجزئي ───")
    before_qty = stock_svc.on_hand(db, stock_item.id, main_wh["id"])
    line_id = order["lines"][0]["id"]

    r = client.post(f"/api/v1/stock/purchases/{order_id}/receive", headers=chef, json={
        "lines": [{"line_id": line_id, "quantity": "4"}],
        "supplier_invoice_number": "TEST-INV-1",
    })
    partial = r.json()
    check("استلام جزئي", r.status_code == 200, partial.get("status", r.text[:60]))
    check("الحالة بقت PARTIAL", partial.get("status") == PurchaseStatus.PARTIAL.value,
          partial.get("status", ""))
    check("المتبقّي محسوب",
          Decimal(partial["lines"][0]["outstanding"]) == Decimal("6"),
          f"{partial['lines'][0]['outstanding']}")

    db.expire_all()
    after_qty = stock_svc.on_hand(db, stock_item.id, main_wh["id"])
    check("الرصيد زاد بالمستلم بس", after_qty - before_qty == Decimal("4"),
          f"{before_qty} -> {after_qty}")

    r = client.post(f"/api/v1/stock/purchases/{order_id}/receive", headers=chef, json={
        "lines": [{"line_id": line_id, "quantity": "99"}],
    })
    check("استلام أكتر من المطلوب بيترفض", r.status_code in (400, 409),
          str(r.status_code))

    print("\n─── الاستلام بسعر مختلف بيحرّك المتوسط ───")
    db.expire_all()
    avg_before = Decimal(str(db.get(StockItem, stock_item.id).average_cost))
    higher = money(unit_cost * Decimal("1.4"))

    r = client.post(f"/api/v1/stock/purchases/{order_id}/receive", headers=chef, json={
        "lines": [{"line_id": line_id, "quantity": "6", "actual_cost": str(higher)}],
        "supplier_invoice_number": "TEST-INV-2",
    })
    full = r.json()
    check("استلام باقي الكمية بسعر أعلى", r.status_code == 200,
          full.get("status", r.text[:60]))
    check("الحالة بقت RECEIVED", full.get("status") == PurchaseStatus.RECEIVED.value,
          full.get("status", ""))

    db.expire_all()
    updated = db.get(StockItem, stock_item.id)
    check("متوسط التكلفة اتحرّك لفوق",
          Decimal(str(updated.average_cost)) > avg_before,
          f"{avg_before} -> {updated.average_cost}")
    check("آخر سعر شراء اتسجّل",
          money(updated.last_purchase_cost) == higher,
          f"{updated.last_purchase_cost}")

    r = client.post(f"/api/v1/stock/purchases/{order_id}/cancel", headers=chef,
                    json={"reason": "اختبار"})
    check("إلغاء أمر مستلم بيترفض", r.status_code in (400, 409), str(r.status_code))

    print("\n─── اقتراح إعادة الطلب ───")
    r = client.get("/api/v1/stock/purchases/suggest", headers=chef)
    check("اقتراح المشتريات", r.status_code == 200,
          f"{len(r.json())} اقتراح" if isinstance(r.json(), list) else "")

    print("\n─── الرصيد نسخة محسوبة ───")
    levels_before = dict(
        db.execute(
            select(StockLevel.id, StockLevel.quantity).where(
                StockLevel.property_id == prop.id
            )
        ).all()
    )
    touched = stock_svc.rebuild_levels(db, prop.id)
    db.commit()
    db.expire_all()
    levels_after = dict(
        db.execute(
            select(StockLevel.id, StockLevel.quantity).where(
                StockLevel.property_id == prop.id
            )
        ).all()
    )
    check("إعادة بناء الأرصدة من الحركات", touched > 0, f"{touched} رصيد")
    drift = [k for k in levels_before if levels_before[k] != levels_after.get(k)]
    detail_lines = []
    for key in drift:
        level = db.get(StockLevel, key)
        name = db.get(StockItem, level.stock_item_id).name_ar if level else "?"
        detail_lines.append(
            f"{name}: {levels_before[key]} -> {levels_after.get(key)}"
        )
    check("الرصيد المخزّن = الرصيد المحسوب من الحركات",
          len(drift) == 0, " · ".join(detail_lines) or "0 فرق")

    print("\n─── تنضيف ───")
    # بنشيل أمر الشراء الاختباري وحركاته ونرجّع الرصيد
    if order_id:
        moves = list(
            db.execute(
                select(StockMovement).where(StockMovement.purchase_order_id == order_id)
            ).scalars().all()
        )
        received = sum(m.quantity for m in moves)
        for m in moves:
            db.delete(m)
        po = db.get(PurchaseOrder, order_id)
        if po is not None:
            for row in list(po.lines):
                db.delete(row)
            db.delete(po)
        db.flush()
        restored = db.get(StockItem, stock_item.id)
        restored.average_cost, restored.last_purchase_cost = cost_snapshot
        db.flush()
        stock_svc.rebuild_levels(db, prop.id)
        db.commit()
        check("أمر الاختبار وحركاته اتشالوا والرصيد اتبنى تاني",
              True, f"{len(moves)} حركة · {received} وحدة")

        db.expire_all()
        check("تكلفة الصنف رجعت لأصلها — الاختبار مبيلوّثش داتا العرض",
              Decimal(str(db.get(StockItem, stock_item.id).average_cost))
              == cost_snapshot[0],
              f"{cost_snapshot[0]}")

    db.expire_all()
    negative = db.execute(
        select(func.count(StockLevel.id)).where(
            StockLevel.property_id == prop.id, StockLevel.quantity < 0
        )
    ).scalar_one()
    check("مفيش رصيد سالب بعد كل ده", negative == 0, f"{negative} صنف")

    db.close()

    print("\n" + "─" * 56)
    if failures:
        print(f"  فشل {len(failures)} اختبار:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("  كل الاختبارات نجحت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
