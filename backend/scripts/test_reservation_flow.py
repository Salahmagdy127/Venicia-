"""اختبار دورة الحجز كاملة عبر الـ API — End-to-end reservation flow test.

بيشتغل على نسخة الديمو الحقيقية بيانات: إنشاء، تخصيص، نقل بالسحب، نزول،
مغادرة، إلغاء، ومنع التعارض والصلاحيات.

    python -m scripts.test_reservation_flow
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import SessionLocal
from app.main import app
from app.models.guests import Guest
from app.models.rates import RatePlan
from app.models.reservations import AvailabilityCalendar
from app.models.units import Unit, UnitCategory

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    client = TestClient(app)
    db = SessionLocal()

    # ── تسجيل الدخول بأدوار مختلفة ──────────────────────────────────
    def login(username: str, password: str = "venicia2026") -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": password}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    manager = login("nourhan")     # مدير استقبال
    waiter = login("karim")        # ويتر — مالوش صلاحية حجز

    check("دخول مدير الاستقبال", True)

    r = client.post("/api/v1/auth/login", data={"username": "ahmed", "password": "غلط"})
    check("رفض كلمة مرور خاطئة", r.status_code == 401, f"HTTP {r.status_code}")

    # ── بيانات الاختبار ─────────────────────────────────────────────
    category = db.execute(
        select(UnitCategory).where(UnitCategory.code == "LAKE-CH")
    ).scalar_one()
    plan = db.execute(select(RatePlan).where(RatePlan.code == "BAR")).scalar_one()
    guest = db.execute(select(Guest).order_by(Guest.id).limit(1)).scalar_one()
    units = list(
        db.execute(
            select(Unit).where(Unit.category_id == category.id).order_by(Unit.id)
        ).scalars().all()
    )

    # تواريخ في المستقبل جوه المدى المنشور، وبعد آخر حجز مولّد — إتاحة فاضية مضمونة
    arrival = date.today() + timedelta(days=150)
    departure = arrival + timedelta(days=3)

    def availability_on(day: date) -> int:
        db.expire_all()
        row = db.execute(
            select(AvailabilityCalendar).where(
                AvailabilityCalendar.unit_category_id == category.id,
                AvailabilityCalendar.stay_date == day,
            )
        ).scalar_one_or_none()
        return row.available_units if row else -1

    before_avail = availability_on(arrival)

    # ── 1. صلاحيات ──────────────────────────────────────────────────
    payload = {
        "guest_id": guest.id,
        "unit_category_id": category.id,
        "rate_plan_id": plan.id,
        "arrival_date": arrival.isoformat(),
        "departure_date": departure.isoformat(),
        "adults": 2,
        "source": "WEBSITE",
    }
    r = client.post("/api/v1/reservations", json=payload, headers=waiter)
    check("الويتر ممنوع يعمل حجز", r.status_code == 403, f"HTTP {r.status_code}")

    # ── 2. إنشاء حجز ────────────────────────────────────────────────
    r = client.post("/api/v1/reservations", json=payload, headers=manager)
    check("إنشاء حجز", r.status_code == 201, f"HTTP {r.status_code} {r.text[:120]}")
    if r.status_code != 201:
        return 1

    reservation = r.json()
    res_id = reservation["id"]
    line_id = reservation["units"][0]["id"]
    check("رقم الحجز اتولد", bool(reservation["code"]), reservation["code"])
    check("3 ليالي", reservation["nights"] == 3)
    check("الإجمالي أكبر من صفر", float(reservation["grand_total"]) > 0,
          f"{reservation['grand_total']} ج.م")
    check("الرصيد = الإجمالي (مفيش دفع)",
          reservation["balance"] == reservation["grand_total"])
    check("الوحدة لسه متخصصتش", reservation["units"][0]["unit_id"] is None)

    after_avail = availability_on(arrival)
    check("الإتاحة نقصت واحد", after_avail == before_avail - 1,
          f"{before_avail} -> {after_avail}")

    # ── 3. تخصيص وحدة ───────────────────────────────────────────────
    target = units[0]
    r = client.post(
        f"/api/v1/reservations/lines/{line_id}/assign",
        json={"unit_id": target.id}, headers=manager,
    )
    check("تخصيص وحدة", r.status_code == 200, f"HTTP {r.status_code}")
    check("الوحدة اتسجّلت",
          r.json()["reservation"]["units"][0]["unit_label"] == target.label,
          target.label)

    # ── 4. منع التعارض ──────────────────────────────────────────────
    r2 = client.post("/api/v1/reservations", json={**payload, "unit_id": target.id},
                     headers=manager)
    check("رفض حجز تاني على نفس الوحدة", r2.status_code == 409,
          f"HTTP {r2.status_code}")

    # ── 5. النقل بالسحب والإفلات ────────────────────────────────────
    other = units[1]
    r = client.post(
        f"/api/v1/reservations/lines/{line_id}/move",
        json={"unit_id": other.id}, headers=manager,
    )
    check("نقل الحجز لوحدة تانية", r.status_code == 200, f"HTTP {r.status_code}")
    check("الوحدة الجديدة اتسجّلت",
          r.json()["reservation"]["units"][0]["unit_label"] == other.label, other.label)

    # نقل مع تغيير التواريخ — لازم يعيد التسعير
    old_total = float(r.json()["reservation"]["grand_total"])
    new_departure = departure + timedelta(days=2)
    r = client.post(
        f"/api/v1/reservations/lines/{line_id}/move",
        json={"departure_date": new_departure.isoformat()}, headers=manager,
    )
    check("مد الإقامة بالسحب", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        moved = r.json()["reservation"]
        check("عدد الليالي بقى 5", moved["nights"] == 5, f"{moved['nights']} ليالي")
        check("الإجمالي اتعاد حسابه", float(moved["grand_total"]) > old_total,
              f"{old_total:.0f} -> {float(moved['grand_total']):.0f}")
        check("الإتاحة اتخصمت لليالي الجديدة",
              availability_on(departure + timedelta(days=1)) == before_avail - 1)

    # ── 6. النزول ───────────────────────────────────────────────────
    r = client.post(f"/api/v1/reservations/{res_id}/check-in", headers=manager)
    check("تسجيل النزول", r.status_code == 200, f"HTTP {r.status_code} {r.text[:150]}")
    folio_ids = r.json().get("folio_ids", []) if r.status_code == 200 else []
    check("اتفتح حساب للنزيل", len(folio_ids) == 1, f"{len(folio_ids)} حساب")

    r = client.post(f"/api/v1/reservations/{res_id}/check-in", headers=manager)
    check("رفض نزول مكرر", r.status_code == 400, f"HTTP {r.status_code}")

    # ── 7. المغادرة برصيد مستحق ─────────────────────────────────────
    r = client.post(f"/api/v1/reservations/{res_id}/check-out",
                    json={"force": False}, headers=manager)
    check("رفض المغادرة والرصيد مستحق", r.status_code == 400, f"HTTP {r.status_code}")

    r = client.post(f"/api/v1/reservations/{res_id}/check-out",
                    json={"force": True}, headers=manager)
    check("المغادرة بتجاهل الرصيد (بصلاحية مدير)", r.status_code == 200,
          f"HTTP {r.status_code}")
    if r.status_code == 200:
        check("الحالة بقت غادر",
              r.json()["reservation"]["status"] == "CHECKED_OUT")

    # ── 8. الإلغاء ──────────────────────────────────────────────────
    r = client.post("/api/v1/reservations", json=payload, headers=manager)
    cancel_id = r.json()["id"]
    avail_before_cancel = availability_on(arrival)

    r = client.post(f"/api/v1/reservations/{cancel_id}/cancel",
                    json={"reason": "النزيل غيّر رأيه"}, headers=manager)
    check("إلغاء حجز", r.status_code == 200, f"HTTP {r.status_code}")
    check("الإتاحة رجعت بعد الإلغاء",
          availability_on(arrival) == avail_before_cancel + 1,
          f"{avail_before_cancel} -> {availability_on(arrival)}")

    r = client.post(f"/api/v1/reservations/{cancel_id}/cancel", json={}, headers=manager)
    check("رفض إلغاء مكرر", r.status_code == 400, f"HTTP {r.status_code}")

    # ── 9. القوائم والترقيم ─────────────────────────────────────────
    r = client.get("/api/v1/reservations?limit=25", headers=manager)
    check("قائمة الحجوزات", r.status_code == 200 and len(r.json()["items"]) == 25,
          f"{len(r.json().get('items', []))} صف")
    cursor = r.json().get("next_cursor")
    r = client.get(f"/api/v1/reservations?limit=25&cursor={cursor}", headers=manager)
    check("الصفحة التانية بالمؤشر", r.status_code == 200 and r.json()["items"],
          f"{len(r.json().get('items', []))} صف")

    r = client.get("/api/v1/reservations/arrivals", headers=manager)
    check("قائمة وصول النهاردة", r.status_code == 200, f"{len(r.json())} حجز")

    r = client.get("/api/v1/reservations?search=فينيسيا-مش-موجود", headers=manager)
    check("بحث بدون نتايج بيرجع فاضي", r.status_code == 200 and not r.json()["items"])

    # ── 10. سجل التدقيق ─────────────────────────────────────────────
    from app.models.security import AuditLog

    db.expire_all()
    entries = db.execute(
        select(AuditLog).where(AuditLog.entity_id == res_id,
                               AuditLog.entity_type == "Reservation")
    ).scalars().all()
    actions = {e.action for e in entries}
    check("سجل التدقيق سجّل العمليات", len(entries) >= 3,
          f"{len(entries)} حركة: {sorted(actions)}")

    db.close()

    print()
    if failures:
        print(f"فشل {len(failures)} اختبار:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("كل اختبارات دورة الحجز نجحت.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
