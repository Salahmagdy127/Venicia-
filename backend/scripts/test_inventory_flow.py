"""اختبار الإتاحة والبيع الزايد وقائمة الانتظار — Inventory & waitlist test.

    python -m scripts.test_inventory_flow

المبدأ اللي السويت دي بتحرسه: **الإتاحة عدّاد ذرّي مش استعلام.** حجزين
في نفس اللحظة على آخر وحدة لازم واحد بس يعدّي، والتاني يترفض بصوت عالي.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.main import app
from app.models.enums import WaitlistStatus
from app.models.guests import Guest
from app.models.organization import Property
from app.models.reservations import AvailabilityCalendar, WaitlistEntry
from app.models.units import Unit, UnitCategory
from app.services import availability as av

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []


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

    manager = login("gm")        # مدير عام — بيضبط الإتاحة وحد التجاوز
    desk = login("nourhan")      # مدير استقبال — بيشوف مش بيعدّل
    cashier = login("sayed")     # كاشير — ممنوع خالص

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    today = date.today()

    print("\n─── لوحة الإتاحة ───")
    r = client.get("/api/v1/inventory?days=30", headers=manager)
    board = r.json()
    check("لوحة الإتاحة", r.status_code == 200, f"{len(board['cells'])} خانة")
    check("الفئات ظاهرة", len(board["categories"]) >= 5, f"{len(board['categories'])} فئة")
    check("كل فئة معاها عدد وحداتها",
          all(c["total_units"] > 0 for c in board["categories"]))

    cells = board["cells"]
    check("عدد الخانات = فئات × أيام",
          len(cells) == len(board["categories"]) * 30,
          f"{len(board['categories'])} × 30")

    check("المتاح مبيزيدش عن الإجمالي + حد التجاوز",
          all(c["available"] <= c["total"] - c["out_of_order"] + c["overbooking_limit"]
              for c in cells))
    check("الخارج عن الخدمة متخصوم",
          all(c["sold"] + c["available"] <= c["total"] + c["overbooking_limit"]
              for c in cells))

    r = client.get("/api/v1/inventory?days=200", headers=manager)
    check("المدى الأكبر من 90 يوم بيترفض", r.status_code == 422)

    r = client.get("/api/v1/inventory", headers=cashier)
    check("الكاشير ممنوع من لوحة الإتاحة", r.status_code == 403)

    print("\n─── حد التجاوز ───")
    category = min(board["categories"], key=lambda c: c["total_units"])
    start = today + timedelta(days=120)
    end = start + timedelta(days=3)

    r = client.patch("/api/v1/inventory", headers=manager, json={
        "start_date": str(start), "end_date": str(end),
        "category_ids": [category["id"]], "overbooking_limit": 99,
    })
    check("حد التجاوز فوق السقف بيترفض", r.status_code == 400)

    r = client.patch("/api/v1/inventory", headers=manager, json={
        "start_date": str(start), "end_date": str(end),
        "category_ids": [category["id"]],
        "overbooking_limit": category["total_units"] + 1,
    })
    check("حد أكبر من عدد وحدات الفئة بيترفض", r.status_code == 400,
          f"الفئة فيها {category['total_units']} وحدة")

    r = client.patch("/api/v1/inventory", headers=manager, json={
        "start_date": str(end), "end_date": str(start),
        "category_ids": [category["id"]], "overbooking_limit": 1,
    })
    check("المدى المقلوب بيترفض", r.status_code == 400)

    r = client.patch("/api/v1/inventory", headers=manager, json={
        "start_date": str(start), "end_date": str(end),
        "category_ids": [category["id"]],
    })
    check("التعديل الفاضي بيترفض", r.status_code == 400)

    r = client.patch("/api/v1/inventory", headers=desk, json={
        "start_date": str(start), "end_date": str(end), "overbooking_limit": 1,
    })
    check("مدير الاستقبال ممنوع يعدّل الإتاحة", r.status_code == 403)

    r = client.patch("/api/v1/inventory", headers=manager, json={
        "start_date": str(start), "end_date": str(end),
        "category_ids": [category["id"]], "overbooking_limit": 2,
    })
    check("ضبط حد التجاوز", r.status_code == 200, r.json().get("message_ar", ""))
    changed = r.json()["rows_changed"]
    check("عدد الصفوف المتغيّرة = عدد الأيام", changed == 3, f"{changed} صف")

    r = client.get(f"/api/v1/inventory?start={start}&days=3", headers=manager)
    after = [c for c in r.json()["cells"] if c["unit_category_id"] == category["id"]]
    check("الحد اتطبّق على كل الأيام",
          all(c["overbooking_limit"] == 2 for c in after[:3]),
          str([c["overbooking_limit"] for c in after[:3]]))
    check("المتاح زاد بمقدار الحد",
          after[0]["available"] == after[0]["total"] - after[0]["out_of_order"]
          - after[0]["sold"] + 2,
          f"متاح {after[0]['available']}")

    print("\n─── قفل البيع ───")
    r = client.patch("/api/v1/inventory", headers=manager, json={
        "start_date": str(start), "end_date": str(end),
        "category_ids": [category["id"]], "is_closed": True,
    })
    check("قفل البيع", r.status_code == 200)

    r = client.get(f"/api/v1/inventory?start={start}&days=3", headers=manager)
    closed = [c for c in r.json()["cells"] if c["unit_category_id"] == category["id"]][:3]
    check("الخانات اتقفلت", all(c["is_closed"] for c in closed))
    check("المقفول متاحه صفر", all(c["available"] == 0 for c in closed),
          str([c["available"] for c in closed]))

    quote = client.post("/api/v1/reservations/quote", headers=manager, json={
        "unit_category_id": category["id"],
        "arrival_date": str(start),
        "departure_date": str(start + timedelta(days=1)),
        "adults": 2, "children": 0,
    })
    if quote.status_code == 200:
        check("التسعيرة بتقول مش متاح على يوم مقفول",
              quote.json()["is_available"] is False,
              f"متاح {quote.json()['available']}")

    r = client.patch("/api/v1/inventory", headers=manager, json={
        "start_date": str(start), "end_date": str(end),
        "category_ids": [category["id"]], "is_closed": False, "overbooking_limit": 0,
    })
    check("فتح البيع ورجوع الحد لصفر", r.status_code == 200)

    print("\n─── الحجز الذرّي على آخر وحدة ───")
    # بنجيب فئة ونقفل إتاحتها على يوم واحد بحيث يفضل وحدة واحدة بالظبط
    probe_day = today + timedelta(days=200)
    cat = db.execute(
        select(UnitCategory)
        .where(UnitCategory.property_id == prop.id, UnitCategory.is_active.is_(True))
        .order_by(UnitCategory.sort_order)
    ).scalars().first()

    av.ensure_calendar(db, prop.id, probe_day, probe_day + timedelta(days=1), [cat.id])
    row = db.execute(
        select(AvailabilityCalendar).where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.unit_category_id == cat.id,
            AvailabilityCalendar.stay_date == probe_day,
        )
    ).scalar_one()
    original_sold = row.sold_units
    # نخلّي المتاح وحدة واحدة بالظبط
    row.sold_units = row.total_units - row.out_of_order - 1
    row.is_closed = False
    row.overbooking_limit = 0
    db.commit()

    available = av.get_availability(db, prop.id, probe_day, probe_day + timedelta(days=1), [cat.id])[0]
    check("جهّزنا يوم فيه وحدة واحدة متاحة", available.available == 1,
          f"متاح {available.available}")

    try:
        av.reserve(db, prop.id, cat.id, probe_day, probe_day + timedelta(days=1))
        db.commit()
        first_ok = True
    except av.AvailabilityError:
        db.rollback()
        first_ok = False
    check("أول حجز عدّى", first_ok)

    try:
        av.reserve(db, prop.id, cat.id, probe_day, probe_day + timedelta(days=1))
        db.commit()
        second_blocked = False
    except av.AvailabilityError as exc:
        db.rollback()
        second_blocked = True
        blocking = exc.blocking_dates
    check("التاني اترفض — العدّاد ذرّي", second_blocked,
          str(blocking[0]) if second_blocked else "عدّى غلط!")

    db.expire_all()
    after_row = db.execute(
        select(AvailabilityCalendar).where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.unit_category_id == cat.id,
            AvailabilityCalendar.stay_date == probe_day,
        )
    ).scalar_one()
    check("العدّاد زاد مرة واحدة بس",
          after_row.sold_units == after_row.total_units - after_row.out_of_order,
          f"مباع {after_row.sold_units} من {after_row.total_units}")

    av.release(db, prop.id, cat.id, probe_day, probe_day + timedelta(days=1))
    db.commit()
    db.expire_all()
    released = av.get_availability(db, prop.id, probe_day, probe_day + timedelta(days=1), [cat.id])[0]
    check("الإلغاء رجّع الوحدة للبيع", released.available == 1,
          f"متاح {released.available}")

    print("\n─── تمديد الإقامة على يوم مليان ───")
    # الباج القديم: التمديد كان بيحجز المدى الجديد كله قبل ما يسيب القديم،
    # فلو الليلة الأولى مليانة التمديد كان بيفشل غلط
    extend_day = today + timedelta(days=210)
    av.ensure_calendar(db, prop.id, extend_day, extend_day + timedelta(days=3), [cat.id])
    rows = db.execute(
        select(AvailabilityCalendar).where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.unit_category_id == cat.id,
            AvailabilityCalendar.stay_date >= extend_day,
            AvailabilityCalendar.stay_date < extend_day + timedelta(days=3),
        ).order_by(AvailabilityCalendar.stay_date)
    ).scalars().all()
    for r_ in rows:
        r_.is_closed = False
        r_.overbooking_limit = 0
        r_.sold_units = 0
    db.commit()

    av.reserve(db, prop.id, cat.id, extend_day, extend_day + timedelta(days=1))
    db.commit()
    # نملّي الليلة الأولى بالكامل
    db.expire_all()
    first_night = db.execute(
        select(AvailabilityCalendar).where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.unit_category_id == cat.id,
            AvailabilityCalendar.stay_date == extend_day,
        )
    ).scalar_one()
    first_night.sold_units = first_night.total_units - first_night.out_of_order
    db.commit()
    db.expire_all()
    check("الليلة الأولى بقت مليانة",
          av.get_availability(db, prop.id, extend_day, extend_day + timedelta(days=1), [cat.id])[0].available == 0)

    try:
        av.move(
            db, prop.id,
            from_category_id=cat.id, from_arrival=extend_day,
            from_departure=extend_day + timedelta(days=1),
            to_category_id=cat.id, to_arrival=extend_day,
            to_departure=extend_day + timedelta(days=2),
        )
        db.commit()
        extended = True
    except av.AvailabilityError:
        db.rollback()
        extended = False
    check("التمديد شغّال رغم إن الليلة الأولى مليانة", extended,
          "بيحرّك الفرق بس مش المدى كله")

    if extended:
        db.expire_all()
        second_night = av.get_availability(
            db, prop.id, extend_day + timedelta(days=1), extend_day + timedelta(days=2), [cat.id]
        )[0]
        check("الليلة الجديدة اتحجزت", second_night.sold_units >= 1,
              f"مباع {second_night.sold_units}")
        av.release(db, prop.id, cat.id, extend_day, extend_day + timedelta(days=2))
        db.commit()

    # تنضيف
    db.expire_all()
    reset = db.execute(
        select(AvailabilityCalendar).where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.unit_category_id == cat.id,
            AvailabilityCalendar.stay_date.in_([probe_day, extend_day]),
        )
    ).scalars().all()
    for r_ in reset:
        r_.sold_units = original_sold if r_.stay_date == probe_day else 0
    db.commit()

    print("\n─── قائمة الانتظار ───")
    r = client.get("/api/v1/waitlist", headers=manager)
    page = r.json()
    check("قائمة الانتظار", r.status_code == 200, f"{len(page['items'])} طلب")
    check("العدّادات موجودة",
          all(k in page for k in ("waiting_count", "offered_count", "ready_count")))

    guest = db.execute(
        select(Guest).where(Guest.property_id == prop.id).limit(1)
    ).scalar_one_or_none()
    check("فيه نزيل نجرّب عليه", guest is not None)

    busy_start = today + timedelta(days=3)
    payload = {
        "guest_id": guest.id,
        "unit_category_id": cat.id,
        "arrival_date": str(busy_start),
        "departure_date": str(busy_start + timedelta(days=2)),
        "adults": 2,
        "priority": "VIP",
        "contact_note": "اختبار",
    }

    r = client.post("/api/v1/waitlist", headers=manager, json=payload)
    check("إضافة طلب انتظار", r.status_code in (200, 201), r.json().get("id", r.text[:60]))
    entry_id = r.json().get("id") if r.status_code in (200, 201) else None

    if entry_id:
        r = client.post("/api/v1/waitlist", headers=manager, json=payload)
        check("نفس الطلب مرتين بيترفض", r.status_code == 409,
              r.json().get("detail", {}).get("code", ""))

        r = client.get("/api/v1/waitlist", headers=manager)
        mine = next((x for x in r.json()["items"] if x["id"] == entry_id), None)
        check("الطلب ظهر في القائمة", mine is not None)
        check("الأولوية اتسجّلت", mine and mine["priority"] == "VIP")
        check("عدد الليالي محسوب", mine and mine["nights"] == 2, f"{mine['nights']} ليلة")
        check("الطلب حالته WAITING", mine and mine["status"] == "WAITING")

        r = client.post(f"/api/v1/waitlist/{entry_id}/offer", headers=manager,
                        json={"hours": 24})
        offered_ok = r.status_code == 200
        check("عرض المكان على النزيل", offered_ok or r.status_code == 409,
              r.json().get("detail", {}).get("code", "اتعرض"))

        if offered_ok:
            r = client.get("/api/v1/waitlist", headers=manager)
            mine = next(x for x in r.json()["items"] if x["id"] == entry_id)
            check("الحالة بقت OFFERED", mine["status"] == "OFFERED")
            check("للعرض تاريخ انتهاء", mine["offer_expires_at"] is not None)

            r = client.post(f"/api/v1/waitlist/{entry_id}/offer", headers=manager,
                            json={"hours": 24})
            check("العرض مرتين بيترفض", r.status_code == 409,
                  r.json().get("detail", {}).get("code", ""))

            r = client.post(f"/api/v1/waitlist/{entry_id}/withdraw", headers=manager, json={})
            check("سحب العرض بيرجّع الوحدة للبيع", r.status_code == 200)

            db.expire_all()
            back = db.get(WaitlistEntry, entry_id)
            check("الحالة رجعت WAITING", back.status == WaitlistStatus.WAITING,
                  back.status)

        r = client.post(f"/api/v1/waitlist/{entry_id}/cancel", headers=manager,
                        json={"reason": "تنضيف بعد الاختبار"})
        check("إلغاء الطلب", r.status_code == 200)

        db.expire_all()
        cancelled = db.get(WaitlistEntry, entry_id)
        check("الحالة بقت CANCELLED", cancelled.status == WaitlistStatus.CANCELLED,
              cancelled.status)

        r = client.post(f"/api/v1/waitlist/{entry_id}/offer", headers=manager,
                        json={"hours": 24})
        check("العرض على طلب ملغي بيترفض", r.status_code == 409)

    r = client.post("/api/v1/waitlist", headers=manager, json={
        **payload, "departure_date": str(busy_start - timedelta(days=1)),
    })
    check("تواريخ مقلوبة بترفض", r.status_code in (400, 409, 422))

    r = client.get("/api/v1/waitlist", headers=cashier)
    check("الكاشير ممنوع من قائمة الانتظار", r.status_code == 403)

    r = client.post(f"/api/v1/waitlist/{10**9}/offer", headers=manager, json={"hours": 24})
    check("طلب مش موجود بيرجّع 404", r.status_code == 404)

    print("\n─── سلامة العدّادات ───")
    negative = db.execute(
        select(func.count(AvailabilityCalendar.id)).where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.sold_units < 0,
        )
    ).scalar_one()
    check("مفيش عدّاد بالسالب", negative == 0, f"{negative} صف")

    units_per_category = dict(
        db.execute(
            select(Unit.category_id, func.count(Unit.id))
            .where(Unit.property_id == prop.id, Unit.is_active.is_(True))
            .group_by(Unit.category_id)
        ).all()
    )
    mismatched = db.execute(
        select(func.count(AvailabilityCalendar.id)).where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.stay_date >= today,
            AvailabilityCalendar.stay_date < today + timedelta(days=30),
        )
    ).scalar_one()
    check("صفوف الإتاحة موجودة للشهر الجاي", mismatched > 0, f"{mismatched} صف")

    sample = db.execute(
        select(AvailabilityCalendar).where(
            AvailabilityCalendar.property_id == prop.id,
            AvailabilityCalendar.stay_date == today,
        )
    ).scalars().all()
    check("إجمالي الوحدات في الإتاحة = الوحدات الفعلية",
          all(s.total_units == units_per_category.get(s.unit_category_id, 0) for s in sample),
          f"{len(sample)} فئة")

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
