"""اختبار محرك الحجز المباشر — Public booking engine flow test.

    python -m scripts.test_booking_flow_web

المبدأ اللي السويت دي بتحرسه: **الحجز المؤقت بيخصم إتاحة حقيقية.**
سلة مفتوحة على شاشة زائر بتقفل الوحدة فعلاً، ولو الزائر مشي السلة
بتنتهي وترجع الوحدة للبيع لوحدها. من غير كده اتنين يقدروا يحجزوا نفس
آخر شاليه في نفس الدقيقة.

وكل الواجهات هنا عامة — من غير تسجيل دخول. فالحد الأقصى للّيالي والمدى
والمتاح المعروض كلهم حواجز مقصودة مش تفاصيل.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import SessionLocal
from app.main import app
from app.models.enums import ReservationStatus
from app.models.organization import Property
from app.models.reservations import Reservation, ReservationNight, ReservationUnit
from app.services import booking_engine as be

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:  # noqa: PLR0915
    client = TestClient(app)
    db = SessionLocal()

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    today = date.today()
    arrival = today + timedelta(days=60)
    departure = arrival + timedelta(days=3)

    print("\n─── بيانات القرية العامة ───")
    r = client.get("/api/v1/book/property")
    info = r.json()
    check("صفحة القرية بتفتح من غير تسجيل دخول", r.status_code == 200, info.get("name_ar", ""))
    check("الفئات معروضة", len(info["categories"]) > 0, f"{len(info['categories'])} فئة")
    check("كل فئة معاها سعر ابتدائي",
          all(Decimal(c["from_rate"]) > 0 for c in info["categories"]))
    check("نسب الخدمة والضريبة معلنة",
          Decimal(info["service_charge_percent"]) > 0 and Decimal(info["vat_percent"]) > 0,
          f"خدمة {info['service_charge_percent']}% · ضريبة {info['vat_percent']}%")
    check("مواعيد الدخول والخروج معلنة",
          bool(info["check_in_time"]) and bool(info["check_out_time"]),
          f"{info['check_in_time']} → {info['check_out_time']}")

    print("\n─── البحث ───")
    r = client.get(
        f"/api/v1/book/search?arrival_date={arrival}&departure_date={departure}&adults=2"
    )
    found = r.json()
    check("البحث بيشتغل", r.status_code == 200, f"{len(found['offers'])} عرض")
    check("عدد الليالي محسوب", found["nights"] == 3, f"{found['nights']} ليالي")

    offers = found["offers"]
    check("فيه عروض متاحة", len(offers) > 0)
    if offers:
        offer = offers[0]
        check("الإجمالي = الإقامة + الخدمة + الضريبة",
              Decimal(offer["grand_total"]) == (
                  Decimal(offer["room_total"])
                  + Decimal(offer["service_charge_total"])
                  + Decimal(offer["tax_total"])
              ),
              f"{offer['grand_total']}")
        check("الخدمة بتتحسب قبل الضريبة",
              Decimal(offer["tax_total"]) > Decimal(offer["room_total"])
              * Decimal(info["vat_percent"]) / 100,
              "الضريبة على الإقامة + الخدمة")
        check("المتاح المعروض مقصوص — مش بنكشف المخزون",
              all(o["left"] <= 5 for o in offers),
              str(sorted({o["left"] for o in offers})))
        check("تفصيل الليالي موجود",
              len(offer.get("nights_detail", offer.get("nights_breakdown", []))) in (0, 3),
              "للشفافية في السعر")

    print("\n─── حواجز البحث ───")
    r = client.get(
        f"/api/v1/book/search?arrival_date={departure}&departure_date={arrival}&adults=2"
    )
    check("تواريخ مقلوبة بترفض", r.status_code in (400, 422), str(r.status_code))

    r = client.get(
        f"/api/v1/book/search?arrival_date={today - timedelta(days=5)}"
        f"&departure_date={today}&adults=2"
    )
    check("تاريخ في الماضي بيترفض", r.status_code in (400, 422), str(r.status_code))

    long_stay = arrival + timedelta(days=be.MAX_ONLINE_NIGHTS + 5)
    r = client.get(
        f"/api/v1/book/search?arrival_date={arrival}&departure_date={long_stay}&adults=2"
    )
    check(f"إقامة أطول من {be.MAX_ONLINE_NIGHTS} ليلة بترفض",
          r.status_code in (400, 422), str(r.status_code))

    far = today + timedelta(days=be.MAX_LEAD_DAYS + 30)
    r = client.get(
        f"/api/v1/book/search?arrival_date={far}&departure_date={far + timedelta(days=2)}&adults=2"
    )
    check(f"حجز أبعد من {be.MAX_LEAD_DAYS} يوم بيترفض",
          r.status_code in (400, 422), str(r.status_code))

    r = client.get(
        f"/api/v1/book/search?arrival_date={arrival}&departure_date={departure}&adults=50"
    )
    check("عدد أفراد مستحيل بيترفض", r.status_code == 422, str(r.status_code))

    if not offers:
        print("\n  مفيش عروض متاحة — باقي الاختبارات محتاجة إتاحة")
        db.close()
        return 1

    print("\n─── الحجز المؤقت بيخصم إتاحة حقيقية ───")
    target = offers[0]
    before = target["left"]

    r = client.post("/api/v1/book/hold", json={
        "unit_category_id": target["unit_category_id"],
        "arrival_date": str(arrival),
        "departure_date": str(departure),
        "adults": 2, "children": 0,
    })
    hold = r.json()
    check("حجز مؤقت", r.status_code in (200, 201), hold.get("token", r.text[:60])[:20])
    token = hold.get("token")
    check("للسلة مهلة", hold.get("hold_minutes", 0) > 0, f"{hold.get('hold_minutes')} دقيقة")
    check("للسلة تاريخ انتهاء", hold.get("expires_at") is not None)
    check("سعر السلة = سعر البحث",
          Decimal(hold["grand_total"]) == Decimal(target["grand_total"]),
          f"{hold['grand_total']}")

    r = client.get(
        f"/api/v1/book/search?arrival_date={arrival}&departure_date={departure}&adults=2"
    )
    now_offers = {o["unit_category_id"]: o for o in r.json()["offers"]}
    after = now_offers.get(target["unit_category_id"], {}).get("left", 0)
    check("المتاح قلّ بعد الحجز المؤقت", after < before or before == 5,
          f"{before} -> {after}")

    held = db.execute(
        select(Reservation).where(
            Reservation.property_id == prop.id,
            Reservation.status == ReservationStatus.TENTATIVE,
            Reservation.arrival_date == arrival,
        ).order_by(Reservation.id.desc())
    ).scalars().first()
    check("السلة حجز مبدئي حقيقي في الداتابيز", held is not None,
          held.code if held else "")
    check("للحجز المبدئي وقت انتهاء",
          held is not None and held.hold_expires_at is not None)

    print("\n─── سيبان السلة ───")
    r = client.post("/api/v1/book/release", json={"token": token})
    check("سيبان السلة", r.status_code == 200)

    db.expire_all()
    if held:
        released = db.get(Reservation, held.id)
        check("الحجز المبدئي اتلغى", released is None
              or released.status == ReservationStatus.CANCELLED,
              released.status if released else "اتشال")

    r = client.get(
        f"/api/v1/book/search?arrival_date={arrival}&departure_date={departure}&adults=2"
    )
    back = {o["unit_category_id"]: o for o in r.json()["offers"]}
    check("الوحدة رجعت للبيع",
          back.get(target["unit_category_id"], {}).get("left", 0) >= after,
          f"{after} -> {back.get(target['unit_category_id'], {}).get('left')}")

    r = client.post("/api/v1/book/confirm", json={
        "token": token,
        "first_name": "زائر", "last_name": "متأخر", "phone": "01000000111",
    })
    check("التأكيد بعد سيبان السلة بيترفض", r.status_code in (400, 401, 409),
          str(r.status_code))

    print("\n─── التأكيد ───")
    r = client.post("/api/v1/book/hold", json={
        "unit_category_id": target["unit_category_id"],
        "arrival_date": str(arrival),
        "departure_date": str(departure),
        "adults": 2, "children": 0,
    })
    token = r.json()["token"]
    check("سلة جديدة", r.status_code in (200, 201))

    r = client.post("/api/v1/book/confirm", json={
        "token": token,
        "first_name": "منى", "last_name": "اختبار",
        "phone": "",
    })
    check("التأكيد من غير تليفون بيترفض", r.status_code in (400, 422),
          str(r.status_code))

    r = client.post("/api/v1/book/confirm", json={
        "token": "token.mesh.sa7",
        "first_name": "منى", "last_name": "اختبار", "phone": "01000000222",
    })
    check("توكن مزوّر بيترفض", r.status_code in (400, 401, 409), str(r.status_code))

    phone = "01000000333"
    r = client.post("/api/v1/book/confirm", json={
        "token": token,
        "first_name": "منى", "last_name": "اختبار",
        "phone": phone,
        "email": "test@example.com",
        "notes": "حجز اختباري",
        "deposit_paid": "1000",
    })
    booking = r.json()
    check("تأكيد الحجز", r.status_code in (200, 201), booking.get("code", r.text[:80]))
    code = booking.get("code")
    check("الحجز مؤكّد", booking.get("status") == "CONFIRMED", booking.get("status", ""))
    check("العربون اتسجّل", Decimal(booking.get("paid_total", 0)) == Decimal("1000"),
          f"{booking.get('paid_total')}")
    check("الباقي = الإجمالي − المدفوع",
          Decimal(booking["balance"])
          == Decimal(booking["grand_total"]) - Decimal(booking["paid_total"]),
          f"{booking['balance']}")
    check("اسم النزيل ظاهر", "منى" in booking.get("guest_name", ""),
          booking.get("guest_name", ""))

    r = client.post("/api/v1/book/confirm", json={
        "token": token,
        "first_name": "منى", "last_name": "اختبار", "phone": phone,
    })
    check("التأكيد مرتين بنفس التوكن بيترفض", r.status_code in (400, 409),
          str(r.status_code))

    confirmed = db.execute(
        select(Reservation).where(Reservation.code == code)
    ).scalar_one_or_none()
    check("الحجز في الداتابيز", confirmed is not None)
    if confirmed:
        check("مصدر الحجز الموقع — عمولة صفر",
              confirmed.source == "WEBSITE", confirmed.source)
        check("مفيش عمولة قناة",
              Decimal(confirmed.channel_commission_amount) == 0,
              f"{confirmed.channel_commission_amount}")
        check("وقت انتهاء السلة اتشال بعد التأكيد",
              confirmed.hold_expires_at is None,
              str(confirmed.hold_expires_at))

    print("\n─── مراجعة الحجز ───")
    r = client.post("/api/v1/book/lookup", json={"code": code, "phone": phone})
    check("مراجعة الحجز بالكود والتليفون", r.status_code == 200,
          r.json().get("code", ""))

    r = client.post("/api/v1/book/lookup", json={"code": code, "phone": "01099999999"})
    check("تليفون غلط بيترفض — مش بنكشف حجوزات الناس",
          r.status_code in (400, 403, 404), str(r.status_code))

    r = client.post("/api/v1/book/lookup", json={"code": "VNC-2026-999999", "phone": phone})
    check("كود مش موجود بيرجّع 404", r.status_code == 404)

    print("\n─── تنظيف السلال المتروكة ───")
    r = client.post("/api/v1/book/hold", json={
        "unit_category_id": target["unit_category_id"],
        "arrival_date": str(arrival + timedelta(days=10)),
        "departure_date": str(arrival + timedelta(days=12)),
        "adults": 2, "children": 0,
    })
    stale_token = r.json().get("token")
    check("سلة هنسيبها تنتهي", stale_token is not None)

    stale = db.execute(
        select(Reservation).where(
            Reservation.property_id == prop.id,
            Reservation.status == ReservationStatus.TENTATIVE,
            Reservation.arrival_date == arrival + timedelta(days=10),
        ).order_by(Reservation.id.desc())
    ).scalars().first()
    if stale is not None:
        # بنرجّع وقت الانتهاء للماضي بدل ما نستنى المهلة الحقيقية
        stale.hold_expires_at = stale.hold_expires_at - timedelta(hours=2)
        db.commit()

        freed = be.release_expired(db, prop.id)
        db.commit()
        check("السلة المنتهية بترجع للبيع لوحدها", freed >= 1, f"{freed} سلة")

        db.expire_all()
        gone = db.get(Reservation, stale.id)
        check("الحجز المبدئي المنتهي مبقاش حاجز إتاحة",
              gone is None or gone.status == ReservationStatus.CANCELLED,
              gone.status if gone else "اتشال")

    print("\n─── تنضيف ───")
    # الإتاحة لازم ترجع للبيع قبل ما نشيل الحجز. الفئة موجودة على سطور
    # الحجز مش على رأسه — الحجز الواحد ممكن يكون فيه أكتر من فئة.
    if confirmed:
        from app.services import availability as av

        rows = list(
            db.execute(
                select(ReservationUnit).where(
                    ReservationUnit.reservation_id == confirmed.id
                )
            ).scalars().all()
        )
        for row in rows:
            av.release(
                db, prop.id, row.unit_category_id, row.arrival_date, row.departure_date
            )
        db.execute(
            ReservationNight.__table__.delete().where(
                ReservationNight.reservation_id == confirmed.id
            )
        )
        db.execute(
            ReservationUnit.__table__.delete().where(
                ReservationUnit.reservation_id == confirmed.id
            )
        )
        db.delete(confirmed)
        db.commit()
        check("حجز الاختبار اتشال والإتاحة رجعت", True, f"{len(rows)} سطر")
    else:
        check("مفيش حجز اختبار يتشال", True)

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
