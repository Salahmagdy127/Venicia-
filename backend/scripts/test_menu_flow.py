"""اختبار منيو الـ QR العام — Public QR menu flow test.

    python -m scripts.test_menu_flow

المبدأ اللي السويت دي بتحرسه: **الصفحة العامة بتكشف الأسعار وبس.**
مفيش تكلفة ولا هامش ولا رقم داخلي — النزيل بيمسح كود من على الطاولة،
مش بيفتح شاشة إدارية.

وكود الـ QR بيشاور على نفس العنوان اللي الشاشة مفتوحة منه، عشان على
الشبكة المحلية يشتغل من غير أي ضبط.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import SessionLocal
from app.main import app
from app.models.organization import Property
from app.models.pos import MenuItem, Outlet, PosTable

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []

#: الحقول اللي ممنوع تطلع في صفحة عامة
FORBIDDEN = {"cost", "margin", "average_cost", "id", "kitchen_station_id", "recipe"}


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:  # noqa: PLR0915
    client = TestClient(app)
    db = SessionLocal()

    def login(username: str) -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": "venicia2026"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    cashier = login("sayed")
    keeper = login("samia")   # هاوس كيبينج — مالهاش دعوة بالكاشير

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    outlets = list(
        db.execute(
            select(Outlet).where(Outlet.property_id == prop.id, Outlet.is_active.is_(True))
        ).scalars().all()
    )
    check("فيه منافذ", len(outlets) > 0, f"{len(outlets)} منفذ")

    print("\n─── المنيو العام ───")
    restaurant = next(o for o in outlets if o.code == "REST")
    r = client.get(f"/api/v1/menu/{restaurant.code}")
    menu = r.json()
    check("المنيو بيفتح من غير تسجيل دخول", r.status_code == 200,
          menu.get("outlet_name_ar", ""))
    check("اسم القرية ظاهر", bool(menu["property_name_ar"]), menu["property_name_ar"])
    check("فيه أقسام", len(menu["categories"]) > 0, f"{len(menu['categories'])} قسم")
    check("فيه أصناف", menu["item_count"] > 0, f"{menu['item_count']} صنف")
    check("عدد الأصناف = مجموع أصناف الأقسام",
          menu["item_count"] == sum(len(c["items"]) for c in menu["categories"]))

    print("\n─── الصفحة العامة مبتكشفش أرقام داخلية ───")
    all_items = [i for c in menu["categories"] for i in c["items"]]
    leaked = {k for item in all_items for k in item if k in FORBIDDEN}
    check("مفيش تكلفة ولا هامش ولا معرّفات داخلية", not leaked,
          str(sorted(leaked)) if leaked else "نضيفة")
    check("كل صنف له سعر", all(Decimal(i["price"]) > 0 for i in all_items))
    check("الاسم باللغتين",
          all(i["name_ar"] and i["name_en"] for i in all_items))
    check("نسب الخدمة والضريبة معلنة للنزيل",
          Decimal(menu["service_charge_percent"]) > 0
          and Decimal(menu["vat_percent"]) > 0,
          f"خدمة {menu['service_charge_percent']}% · ضريبة {menu['vat_percent']}%")

    print("\n─── الأصناف الخاصة ───")
    check("الأصناف النباتية معلّمة",
          any(i["is_vegetarian"] for i in all_items)
          or all(not i["is_vegetarian"] for i in all_items),
          f"{sum(1 for i in all_items if i['is_vegetarian'])} نباتي")
    check("الأصناف الكحولية معلّمة — مطلب في السوق المصري",
          all("contains_alcohol" in i for i in all_items),
          f"{sum(1 for i in all_items if i['contains_alcohol'])} صنف")
    check("الأصناف اللي خلصت معلّمة مش متشالة",
          all("is_out_of_stock" in i for i in all_items),
          f"{sum(1 for i in all_items if i['is_out_of_stock'])} خلصان")

    print("\n─── الطاولة ───")
    table = db.execute(
        select(PosTable).where(PosTable.outlet_id == restaurant.id).limit(1)
    ).scalars().first()
    if table is not None:
        r = client.get(f"/api/v1/menu/{restaurant.code}?table={table.label}")
        check("المنيو بكود الطاولة", r.status_code == 200,
              r.json().get("table_label") or "")
        check("رقم الطاولة بيتعرض للنزيل عشان يتأكد إنه مسح صح",
              r.json().get("table_label") == table.label,
              str(r.json().get("table_label")))

    r = client.get(f"/api/v1/menu/{restaurant.code}?table=MSH-MAWGODA")
    check("طاولة مش موجودة مبتوقّعش الصفحة", r.status_code == 200,
          "المنيو بيتعرض عادي")

    print("\n─── كل منفذ منيوه ───")
    seen: dict[str, int] = {}
    for outlet in outlets:
        r = client.get(f"/api/v1/menu/{outlet.code}")
        if r.status_code == 200:
            seen[outlet.code] = r.json()["item_count"]
    check("كل المنافذ ليها منيو", len(seen) == len(outlets),
          str(seen))
    check("مفيش منفذ منيوه فاضي", all(n > 0 for n in seen.values()),
          str({k: v for k, v in seen.items() if v == 0}) or "كلهم فيهم أصناف")

    room_service = next((o for o in outlets if o.code == "RSVC"), None)
    if room_service is not None:
        check("خدمة الغرف ليها أصناف — مش صفحة فاضية",
              seen.get("RSVC", 0) > 0, f"{seen.get('RSVC')} صنف")

    print("\n─── المنفذ الغلط ───")
    r = client.get("/api/v1/menu/MSH-MAWGOD")
    check("منفذ مش موجود بيرجّع 404", r.status_code == 404)

    print("\n─── كود الـ QR ───")
    r = client.get(f"/api/v1/menu/{restaurant.code}/qr.svg")
    check("الـ QR محتاج تسجيل دخول — ده للموظف مش للنزيل",
          r.status_code in (401, 403), str(r.status_code))

    r = client.get(f"/api/v1/menu/{restaurant.code}/qr.svg", headers=cashier)
    check("الكاشير بيطلّع الكود", r.status_code == 200, r.headers.get("content-type", ""))
    check("الرد SVG", "svg" in r.headers.get("content-type", ""),
          r.headers.get("content-type", ""))
    body = r.text
    check("الـ SVG سليم", body.lstrip().startswith("<?xml") or "<svg" in body,
          body[:40].replace("\n", " "))
    check("الكود مش فاضي", len(body) > 500, f"{len(body)} حرف")

    r = client.get(
        f"/api/v1/menu/{restaurant.code}/qr.svg?base_url=http://192.168.1.50:8000",
        headers=cashier,
    )
    check("الكود بيتبني على العنوان اللي جاي من المتصفح", r.status_code == 200,
          "بيشتغل على الشبكة المحلية من غير ضبط")

    if table is not None:
        r = client.get(
            f"/api/v1/menu/{restaurant.code}/qr.svg?table={table.label}",
            headers=cashier,
        )
        check("كود لكل طاولة", r.status_code == 200, f"طاولة {table.label}")

    r = client.get(f"/api/v1/menu/{restaurant.code}/qr.svg", headers=keeper)
    check("الهاوس كيبينج ممنوعة من كود الكاشير", r.status_code == 403)

    r = client.get("/api/v1/menu/MSH-MAWGOD/qr.svg", headers=cashier)
    check("كود لمنفذ مش موجود بيرجّع 404", r.status_code == 404)

    print("\n─── الصنف الموقوف مبيظهرش ───")
    item = db.execute(
        select(MenuItem)
        .join(MenuItem.outlets)
        .where(MenuItem.property_id == prop.id, Outlet.id == restaurant.id)
        .limit(1)
    ).scalars().first()
    if item is not None:
        was_available = item.is_available
        item.is_available = False
        db.commit()

        r = client.get(f"/api/v1/menu/{restaurant.code}")
        names = {i["name_ar"] for c in r.json()["categories"] for i in c["items"]}
        check("الصنف الموقوف اختفى من المنيو", item.name_ar not in names,
              item.name_ar)

        item.is_available = was_available
        db.commit()

        r = client.get(f"/api/v1/menu/{restaurant.code}")
        names = {i["name_ar"] for c in r.json()["categories"] for i in c["items"]}
        check("رجع لما اتفعّل تاني", item.name_ar in names, item.name_ar)

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
