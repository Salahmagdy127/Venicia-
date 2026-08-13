"""اختبار دورة الكاشير كاملة — End-to-end POS flow test.

    python -m scripts.test_pos_flow
"""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import SessionLocal
from app.main import app
from app.models.folio import Folio
from app.models.pos import KotTicket, PosOrderLine

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    client = TestClient(app)
    db = SessionLocal()

    def login(username: str) -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": "venicia2026"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    cashier = login("sayed")     # كاشير — مفيش خصم ولا إلغاء
    manager = login("tarek")     # مدير مطعم — خصم لحد 25%
    waiter = login("karim")      # ويتر

    # ── الإعداد ─────────────────────────────────────────────────────
    r = client.get("/api/v1/pos/outlets", headers=cashier)
    outlets = r.json()
    check("قائمة المنافذ", r.status_code == 200 and len(outlets) == 6, f"{len(outlets)} منفذ")
    restaurant = next(o for o in outlets if o["code"] == "REST")

    r = client.get(f"/api/v1/pos/outlets/{restaurant['id']}/floor-plan", headers=cashier)
    plan = r.json()
    check("تصميم الصالة", r.status_code == 200 and plan["total"] == 22,
          f"{plan['total']} طاولة · مشغول {plan['occupied']}")

    free_tables = [t for t in plan["tables"] if t["open_order_id"] is None]
    check("فيه طاولات فاضية", len(free_tables) > 0, f"{len(free_tables)} طاولة")
    table = free_tables[0]

    r = client.get(f"/api/v1/pos/outlets/{restaurant['id']}/menu", headers=cashier)
    menu = r.json()
    items = [i for c in menu["categories"] for i in c["items"]]
    check("منيو المطعم", r.status_code == 200 and len(items) > 10,
          f"{len(menu['categories'])} قسم · {len(items)} صنف")

    # ── الوردية ─────────────────────────────────────────────────────
    r = client.post("/api/v1/pos/shifts/open",
                    json={"outlet_id": restaurant["id"], "opening_float": "500"},
                    headers=cashier)
    check("فتح وردية", r.status_code == 200, r.json().get("code", ""))
    shift_id = r.json()["id"]

    # ── فتح أوردر ───────────────────────────────────────────────────
    r = client.post("/api/v1/pos/orders", json={
        "outlet_id": restaurant["id"], "table_id": table["id"],
        "covers": 4, "shift_id": shift_id,
    }, headers=cashier)
    check("فتح أوردر على طاولة", r.status_code == 201, f"HTTP {r.status_code} {r.text[:120]}")
    if r.status_code != 201:
        return 1
    order = r.json()
    order_id = order["id"]
    check("رقم الأوردر اتولد", order["code"].startswith("R-"), order["code"])

    r = client.post("/api/v1/pos/orders", json={
        "outlet_id": restaurant["id"], "table_id": table["id"], "covers": 2,
    }, headers=waiter)
    check("رفض أوردر تاني على نفس الطاولة", r.status_code == 409, f"HTTP {r.status_code}")

    # ── إضافة أصناف ─────────────────────────────────────────────────
    shrimp = next(i for i in items if i["code"] == "FSH02")   # جمبري بالثوم 420
    salad = next(i for i in items if i["code"] == "SLD01")    # سلطة سيزر 165
    juice = next(i for i in items if i["code"] == "CLD02")    # ليمون بالنعناع 70

    client.post(f"/api/v1/pos/orders/{order_id}/lines",
                json={"menu_item_id": shrimp["id"], "quantity": "2"}, headers=cashier)
    client.post(f"/api/v1/pos/orders/{order_id}/lines",
                json={"menu_item_id": salad["id"], "quantity": "1",
                      "notes": "بدون بصل"}, headers=cashier)
    r = client.post(f"/api/v1/pos/orders/{order_id}/lines",
                    json={"menu_item_id": juice["id"], "quantity": "2"}, headers=cashier)
    order = r.json()

    check("3 أصناف اتضافوا", len(order["lines"]) == 3)
    check("الملاحظة اتسجّلت",
          any(l["notes"] == "بدون بصل" for l in order["lines"]))

    # 420×2 + 165 + 70×2 = 840 + 165 + 140 = 1145
    expected_sub = Decimal("1145.00")
    check("الإجمالي قبل الخصم", Decimal(order["subtotal"]) == expected_sub,
          f"{order['subtotal']} ج.م")

    service = (expected_sub * Decimal("12") / 100).quantize(Decimal("0.01"))
    tax = ((expected_sub + service) * Decimal("14") / 100).quantize(Decimal("0.01"))
    check("خدمة 12%", Decimal(order["service_charge_total"]) == service, f"{service}")
    check("ضريبة 14% بعد الخدمة", Decimal(order["tax_total"]) == tax, f"{tax}")
    check("الإجمالي النهائي",
          Decimal(order["grand_total"]) == expected_sub + service + tax,
          f"{order['grand_total']} ج.م")

    # ── إرسال للمطبخ ────────────────────────────────────────────────
    r = client.post(f"/api/v1/pos/orders/{order_id}/send", headers=cashier)
    check("إرسال للمطبخ", r.status_code == 200 and r.json()["status"] == "SENT")

    db.expire_all()
    tickets = db.execute(
        select(KotTicket).where(KotTicket.order_id == order_id)
    ).scalars().all()
    check("تذاكر المطبخ اتولدت", len(tickets) >= 2,
          f"{len(tickets)} تذكرة على محطات مختلفة")

    r = client.post(f"/api/v1/pos/orders/{order_id}/send", headers=cashier)
    check("رفض إرسال مكرر بدون أصناف جديدة", r.status_code == 400, f"HTTP {r.status_code}")

    # ── الإلغاء والصلاحيات ──────────────────────────────────────────
    line_to_void = order["lines"][1]["id"]
    r = client.post(f"/api/v1/pos/orders/{order_id}/lines/{line_to_void}/void",
                    json={"reason": "النزيل غيّر رأيه"}, headers=cashier)
    check("الكاشير ممنوع يلغي صنف", r.status_code == 403, f"HTTP {r.status_code}")

    r = client.post(f"/api/v1/pos/orders/{order_id}/lines/{line_to_void}/void",
                    json={"reason": ""}, headers=manager)
    check("رفض الإلغاء بدون سبب", r.status_code == 400, f"HTTP {r.status_code}")

    r = client.post(f"/api/v1/pos/orders/{order_id}/lines/{line_to_void}/void",
                    json={"reason": "النزيل غيّر رأيه"}, headers=manager)
    check("المدير يقدر يلغي صنف", r.status_code == 200, f"HTTP {r.status_code}")

    db.expire_all()
    voided = db.get(PosOrderLine, line_to_void)
    check("اتسجّل إن الإلغاء بعد الإرسال للمطبخ", voided.voided_after_send is True,
          "مؤشر تلاعب مرصود")

    # 1145 - 165 = 980
    order = r.json()
    check("الإجمالي اتعاد حسابه بعد الإلغاء",
          Decimal(order["subtotal"]) == Decimal("980.00"), f"{order['subtotal']} ج.م")

    # ── الخصم ───────────────────────────────────────────────────────
    r = client.post(f"/api/v1/pos/orders/{order_id}/discount",
                    json={"percent": "10", "reason": "عميل متكرر"}, headers=cashier)
    check("الكاشير ممنوع يمنح خصم", r.status_code == 403, f"HTTP {r.status_code}")

    r = client.post(f"/api/v1/pos/orders/{order_id}/discount",
                    json={"percent": "40", "reason": "مجاملة"}, headers=manager)
    check("رفض خصم فوق حد الدور (25%)", r.status_code == 403, f"HTTP {r.status_code}")

    r = client.post(f"/api/v1/pos/orders/{order_id}/discount",
                    json={"percent": "15", "reason": "تأخير في الخدمة"}, headers=manager)
    check("المدير يقدر يخصم 15%", r.status_code == 200, f"HTTP {r.status_code}")
    order = r.json()
    check("قيمة الخصم", Decimal(order["discount_total"]) == Decimal("147.00"),
          f"{order['discount_total']} ج.م")

    # ── الترحيل على الغرفة ──────────────────────────────────────────
    r = client.get("/api/v1/pos/in-house", headers=cashier)
    residents = r.json()
    check("قائمة النزلاء النازلين", r.status_code == 200 and len(residents) > 0,
          f"{len(residents)} نزيل")
    target = residents[0]

    db.expire_all()
    folio_before = db.get(Folio, target["folio_id"]).balance

    r = client.post(f"/api/v1/pos/orders/{order_id}/settle",
                    json={"settlement": "ROOM_CHARGE", "folio_id": target["folio_id"],
                          "shift_id": shift_id}, headers=cashier)
    check("الترحيل على الغرفة", r.status_code == 200, f"HTTP {r.status_code} {r.text[:150]}")
    settled = r.json()
    check("حالة الأوردر بقت اتحاسب", settled["status"] == "SETTLED")

    db.expire_all()
    folio_after = db.get(Folio, target["folio_id"]).balance
    check("رصيد حساب النزيل زاد بقيمة الأوردر",
          folio_after - folio_before == Decimal(settled["grand_total"]),
          f"{folio_before} -> {folio_after}  (+{settled['grand_total']})")

    r = client.get(f"/api/v1/pos/outlets/{restaurant['id']}/floor-plan", headers=cashier)
    freed = next(t for t in r.json()["tables"] if t["id"] == table["id"])
    check("الطاولة رجعت فاضية بعد التحصيل", freed["open_order_id"] is None)

    r = client.post(f"/api/v1/pos/orders/{order_id}/lines",
                    json={"menu_item_id": juice["id"], "quantity": "1"}, headers=cashier)
    check("رفض إضافة صنف لأوردر متحاسب", r.status_code == 409, f"HTTP {r.status_code}")

    # ── شاشة المطبخ ─────────────────────────────────────────────────
    from app.models.pos import KitchenStation
    station = db.execute(select(KitchenStation).where(KitchenStation.code == "HOT")).scalar_one()
    r = client.get(f"/api/v1/pos/kitchen/{station.id}", headers=manager)
    check("شاشة المطبخ", r.status_code == 200, f"{len(r.json())} تذكرة في الانتظار")

    # ── تقفيل الوردية ───────────────────────────────────────────────
    r = client.post(f"/api/v1/pos/shifts/{shift_id}/close",
                    json={"counted_cash": "500", "counted_card": "0"}, headers=cashier)
    check("الكاشير ممنوع يقفّل الوردية", r.status_code == 403, f"HTTP {r.status_code}")

    r = client.post(f"/api/v1/pos/shifts/{shift_id}/close",
                    json={"counted_cash": "480", "counted_card": "0",
                          "notes": "فرق في الدرج"}, headers=manager)
    check("المدير يقفّل الوردية", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        shift = r.json()
        check("الفرق اتحسب", Decimal(shift["variance"]) == Decimal("-20.00"),
              f"{shift['variance']} ج.م — ناقص في الدرج")

    db.close()
    print()
    if failures:
        print(f"فشل {len(failures)} اختبار:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("كل اختبارات دورة الكاشير نجحت.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
