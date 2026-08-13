"""اختبار حساب النزيل والتشغيل — Folio & operations flow test.

    python -m scripts.test_folio_flow
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def D(value) -> Decimal:
    return Decimal(str(value))


def main() -> int:
    client = TestClient(app)

    def login(username: str) -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": "venicia2026"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    desk = login("nourhan")
    owner = login("owner")

    # ── اتساق الأرصدة ───────────────────────────────────────────────
    folios = client.get("/api/v1/folios", headers=desk).json()
    check("قائمة الحسابات المفتوحة", len(folios) > 0, f"{len(folios)} حساب")
    fid = folios[0]["id"]
    listed = D(folios[0]["balance"])

    f = client.get(f"/api/v1/folios/{fid}", headers=desk).json()
    detail = D(f["balance"])
    summed = sum((D(d["day_total"]) for d in f["days"]), Decimal("0"))

    check("رصيد القائمة = رصيد الكشف", listed == detail, f"{listed} / {detail}")
    check(
        "الرصيد يطابق مجموع السطور",
        abs(detail - summed) < Decimal("0.02"),
        f"{detail} مقابل {summed}",
    )
    check("الكشف مجمّع بالأيام", len(f["days"]) > 0,
          f"{f['guest_name']} · وحدة {f['unit_label']} · {len(f['days'])} يوم")

    # ── الترحيل والإلغاء ────────────────────────────────────────────
    before = detail
    r = client.post(
        f"/api/v1/folios/{fid}/charges",
        json={"charge_kind": "MINIBAR", "description_ar": "ميني بار", "amount": "250"},
        headers=owner,
    )
    check("ترحيل حركة ميني بار", r.status_code == 200, f"HTTP {r.status_code}")
    after = D(r.json()["folio"]["balance"])
    # 250 + خدمة 12% (30) + ضريبة 14% على 280 (39.20) = 319.20
    check("الزيادة = المبلغ + خدمة + ضريبة", after - before == Decimal("319.20"),
          f"+{after - before}")

    line_id = [
        l for d in r.json()["folio"]["days"] for l in d["lines"]
        if l["charge_kind"] == "MINIBAR" and not l["is_void"]
    ][-1]["id"]

    r = client.post(
        f"/api/v1/folios/{fid}/charges/{line_id}/void",
        json={"reason": "اتسجلت بالغلط"}, headers=owner,
    )
    check("إلغاء الحركة", r.status_code == 200, f"HTTP {r.status_code}")
    check("الرصيد رجع بالظبط", D(r.json()["folio"]["balance"]) == before,
          f"{r.json()['folio']['balance']}")

    voided = [
        l for d in r.json()["folio"]["days"] for l in d["lines"]
        if l["id"] == line_id
    ][0]
    check("الحركة الأصلية فضلت مكتوبة ومعلّمة ملغاة", voided["is_void"] is True,
          "مفيش حذف — دليل تدقيق كامل")

    # ── الصلاحيات ───────────────────────────────────────────────────
    r = client.post(
        f"/api/v1/folios/{fid}/charges",
        json={"charge_kind": "MINIBAR", "description_ar": "تجربة", "amount": "100"},
        headers=login("karim"),
    )
    check("الويتر ممنوع يرحّل على حساب نزيل", r.status_code == 403, f"HTTP {r.status_code}")

    # ── التحصيل ─────────────────────────────────────────────────────
    r = client.post(f"/api/v1/folios/{fid}/settle",
                    json={"method": "CASH", "amount": "1000"}, headers=desk)
    check("تحصيل دفعة نقدي", r.status_code == 200, r.json().get("message_ar", ""))
    check("الرصيد نقص بالدفعة",
          D(r.json()["folio"]["balance"]) == before - 1000,
          f"{r.json()['folio']['balance']}")

    r = client.post(f"/api/v1/folios/{fid}/settle",
                    json={"method": "CASH", "amount": "9999999"}, headers=desk)
    check("رفض دفعة أكبر من الرصيد", r.status_code == 400, f"HTTP {r.status_code}")

    # ── التحويل بين الغرف ───────────────────────────────────────────
    target = folios[1]["id"]
    src = client.get(f"/api/v1/folios/{fid}", headers=desk).json()
    room_line = [
        l for d in src["days"] for l in d["lines"]
        if l["charge_kind"] == "ROOM" and not l["is_void"] and not l["is_transferred"]
    ][0]
    src_balance = D(src["balance"])
    tgt_balance = D(client.get(f"/api/v1/folios/{target}", headers=desk).json()["balance"])

    r = client.post(
        f"/api/v1/folios/{fid}/charges/{room_line['id']}/transfer",
        json={"target_folio_id": target}, headers=owner,
    )
    check("تحويل حركة لغرفة تانية", r.status_code == 200, f"HTTP {r.status_code}")

    moved = D(room_line["total_amount"])
    new_src = D(client.get(f"/api/v1/folios/{fid}", headers=desk).json()["balance"])
    new_tgt = D(client.get(f"/api/v1/folios/{target}", headers=desk).json()["balance"])
    check("رصيد المصدر نقص", new_src == src_balance - moved, f"{src_balance} -> {new_src}")
    check("رصيد الهدف زاد بنفس المبلغ", new_tgt == tgt_balance + moved,
          f"{tgt_balance} -> {new_tgt}")

    # ── تقسيم الفاتورة ──────────────────────────────────────────────
    src = client.get(f"/api/v1/folios/{fid}", headers=desk).json()
    to_split = [
        l["id"] for d in src["days"] for l in d["lines"]
        if l["charge_kind"] in ("FNB", "SPA") and not l["is_void"] and not l["is_transferred"]
    ][:2]
    if to_split:
        r = client.post(f"/api/v1/folios/{fid}/split",
                        json={"line_ids": to_split, "label": "حساب منفصل"}, headers=owner)
        check("تقسيم الفاتورة", r.status_code == 200,
              f"حساب جديد #{r.json().get('new_folio_id')}")
    else:
        check("تقسيم الفاتورة (مفيش حركات مطعم على الحساب ده)", True, "تخطّي")

    # ── الهاوس كيبينج ───────────────────────────────────────────────
    hk = client.get("/api/v1/housekeeping", headers=desk).json()
    check("لوحة الهاوس كيبينج", len(hk["units"]) == 78,
          f"نظيفة {hk['clean']} · متسخة {hk['dirty']} · صيانة {hk['out_of_order']}")

    unit = hk["units"][0]
    r = client.patch(f"/api/v1/units/{unit['id']}/status",
                     json={"housekeeping_status": "CLEAN", "note": "اتنضفت"}, headers=owner)
    check("تغيير حالة النظافة", r.status_code == 200
          and r.json()["housekeeping_status"] == "CLEAN")

    r = client.patch(f"/api/v1/units/{unit['id']}/status",
                     json={"condition": "OUT_OF_ORDER", "note": "تكييف باظ"}, headers=owner)
    check("تعطيل وحدة للصيانة", r.status_code == 200
          and r.json()["condition"] == "OUT_OF_ORDER", "والسعة اتحدّثت")

    client.patch(f"/api/v1/units/{unit['id']}/status",
                 json={"condition": "OPERATIONAL"}, headers=owner)

    # ── الإعداد والتسعير ────────────────────────────────────────────
    cats = client.get("/api/v1/unit-categories", headers=desk).json()
    check("فئات الوحدات", len(cats) == 6,
          " · ".join(f"{x['name_ar']} ({x['unit_count']})" for x in cats[:3]))
    plans = client.get("/api/v1/rate-plans", headers=desk).json()
    check("خطط الأسعار", len(plans) == 5)

    r = client.get("/api/v1/guests?search=منصور&limit=5", headers=desk)
    check("بحث النزلاء بالاسم", r.status_code == 200, f"{len(r.json()['items'])} نتيجة")

    r = client.get("/api/v1/availability?days=14", headers=desk)
    check("الإتاحة 14 يوم × 6 فئات", len(r.json()) == 84, f"{len(r.json())} صف")

    arrival = (date.today() + timedelta(days=160)).isoformat()
    departure = (date.today() + timedelta(days=164)).isoformat()
    r = client.get(
        f"/api/v1/quote?unit_category_id={cats[0]['id']}&rate_plan_id={plans[0]['id']}"
        f"&arrival_date={arrival}&departure_date={departure}&adults=2",
        headers=desk,
    )
    q = r.json()
    check("تسعيرة إقامة", r.status_code == 200,
          f"{q['nights']} ليالي · {q['grand_total']} ج.م · متاح {q['available']}")
    check("تفصيل سعر كل ليلة", len(q["nights_detail"]) == 4,
          " | ".join(str(n["rate"]) for n in q["nights_detail"]))
    check("القواعد المطبّقة ظاهرة",
          any(n["applied_rules"] for n in q["nights_detail"]),
          " · ".join(sorted({r for n in q["nights_detail"] for r in n["applied_rules"]})))

    print()
    if failures:
        print(f"فشل {len(failures)} اختبار:")
        for f_ in failures:
            print(f"  - {f_}")
        return 1
    print("كل اختبارات الفوليو والتشغيل نجحت.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
