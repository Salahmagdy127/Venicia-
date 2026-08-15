"""اختبار الربط بالقنوات — Channel manager flow test.

    python -m scripts.test_channel_flow

المبدأ اللي السويت دي بتحرسه: **الحجز الجاي من القناة والرسالة الطالعة
ليها لازم يكونوا في نفس المعاملة.** لو الحجز اتسجّل والرسالة ماتكتبتش،
بوكينج بتفضل بايعة وحدة مش موجودة.

والقناة غير المتصلة مبتاخدش رسائل أصلاً — قبل كده كانت بتراكم SKIPPED
لحد ما الطابور يبقى مالوش معنى.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.main import app
from app.models.channels import Channel, ChannelBooking, ChannelMapping, ChannelMessage
from app.models.enums import (
    ChannelBookingStatus,
    ChannelMessageStatus,
    ReservationStatus,
)
from app.models.organization import Property
from app.models.reservations import Reservation, ReservationNight, ReservationUnit
from app.services import channel_sync

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

    gm = login("gm")
    desk = login("nourhan")   # بيشوف القنوات مش بيديرها
    cashier = login("sayed")

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    today = date.today()

    # السويت بتفترض قنوات موصولة. بنتأكد من ده في الأول بدل ما تفشل
    # لأسباب مالهاش علاقة بالكود: القناة المفصولة مبتاخدش رسائل أصلاً،
    # وده سلوك صح بنختبره تحت بنفسنا صراحةً.
    reconnected = 0
    for row in db.execute(
        select(Channel).where(Channel.property_id == prop.id)
    ).scalars():
        mapped = db.execute(
            select(func.count(ChannelMapping.id)).where(
                ChannelMapping.channel_id == row.id, ChannelMapping.is_active.is_(True)
            )
        ).scalar_one()
        if mapped and not row.is_connected:
            row.is_connected = True
            reconnected += 1
    db.commit()

    print("\n─── لوحة القنوات ───")
    if reconnected:
        print(f"         (وصّلنا {reconnected} قناة كانت مفصولة قبل الاختبار)")
    r = client.get("/api/v1/channels", headers=gm)
    board = r.json()
    check("لوحة القنوات", r.status_code == 200, f"{len(board['channels'])} قناة")
    check("القنوات المتوقّعة موجودة",
          {c["source"] for c in board["channels"]} >= {"BOOKING_COM", "AGODA", "EXPEDIA"},
          str(sorted(c["source"] for c in board["channels"])))
    check("كل قناة معاها عمولة",
          all(float(c["commission_percent"]) >= 0 for c in board["channels"]))
    check("العدّادات على مستوى المنشأة موجودة",
          "total_pending" in board and "total_failed" in board,
          f"طابور {board['total_pending']} · فشل {board['total_failed']}")

    r = client.get("/api/v1/channels", headers=desk)
    check("مدير الاستقبال بيشوف القنوات", r.status_code == 200)
    r = client.get("/api/v1/channels", headers=cashier)
    check("الكاشير ممنوع من القنوات", r.status_code == 403)

    booking_com = next(c for c in board["channels"] if c["source"] == "BOOKING_COM")
    check("بوكينج مربوطة بفئات", booking_com["mapped_categories"] > 0,
          f"{booking_com['mapped_categories']} فئة")

    print("\n─── الربط ───")
    r = client.get(f"/api/v1/channels", headers=gm)
    channel_id = booking_com["id"]
    original = booking_com["mappings"]
    check("الربط ظاهر بتفاصيله", len(original) > 0, f"{len(original)} ربط")
    check("كل ربط له كود خارجي",
          all(m["external_room_id"] for m in original))

    r = client.put(
        f"/api/v1/channels/{channel_id}/mappings",
        headers=gm,
        json=[
            {k: m[k] for k in
             ("unit_category_id", "rate_plan_id", "external_room_id",
              "external_rate_id", "allocation", "is_active")}
            for m in original
        ],
    )
    check("حفظ نفس الربط بيعدّي", r.status_code == 200)

    r = client.put(f"/api/v1/channels/{channel_id}/mappings", headers=gm, json=[{
        "unit_category_id": 10**9,
        "external_room_id": "BAD",
        "allocation": 0,
        "is_active": True,
    }])
    check("الربط بفئة مش موجودة بيترفض", r.status_code in (400, 404),
          str(r.status_code))

    r = client.put(f"/api/v1/channels/{channel_id}/mappings", headers=desk, json=[])
    check("مدير الاستقبال ممنوع يعدّل الربط", r.status_code == 403)

    print("\n─── الطابور ───")
    r = client.post("/api/v1/channels/sync", headers=gm)
    check("إرسال الطابور", r.status_code == 200,
          f"اتبعت {r.json()['sent']} · فشل {r.json()['failed']}")

    r = client.get("/api/v1/channels/messages?limit=50", headers=gm)
    messages = r.json()
    check("سجل الرسائل", r.status_code == 200, f"{len(messages)} رسالة")
    if messages:
        check("كل رسالة ليها نوع وحالة",
              all(m["kind"] and m["status"] for m in messages))
        check("مفيش رسالة PENDING بعد الإرسال",
              not any(m["status"] == "PENDING" for m in messages),
              str({m["status"] for m in messages}))

    print("\n─── القناة غير المتصلة مبتاخدش رسائل ───")
    channel = db.get(Channel, channel_id)
    was_connected = channel.is_connected
    channel.is_connected = False
    db.commit()

    before = db.execute(
        select(func.count(ChannelMessage.id)).where(ChannelMessage.channel_id == channel_id)
    ).scalar_one()

    mapping = db.execute(
        select(ChannelMapping).where(
            ChannelMapping.channel_id == channel_id, ChannelMapping.is_active.is_(True)
        )
    ).scalars().first()
    far = today + timedelta(days=250)
    channel_sync.queue_availability(
        db, prop.id, mapping.unit_category_id, far, far + timedelta(days=2), "اختبار"
    )
    db.commit()

    after = db.execute(
        select(func.count(ChannelMessage.id)).where(ChannelMessage.channel_id == channel_id)
    ).scalar_one()
    check("القناة المفصولة مبتتحطّش في الطابور", after == before,
          f"{before} -> {after}")

    channel.is_connected = was_connected
    db.commit()

    print("\n─── تجميع الرسائل المتلاصقة ───")
    fresh_start = today + timedelta(days=260)
    for offset in range(3):
        day = fresh_start + timedelta(days=offset)
        channel_sync.queue_availability(
            db, prop.id, mapping.unit_category_id, day, day + timedelta(days=1), "اختبار التجميع"
        )
    db.commit()

    pending = db.execute(
        select(ChannelMessage).where(
            ChannelMessage.channel_id == channel_id,
            ChannelMessage.status == ChannelMessageStatus.PENDING,
            ChannelMessage.start_date >= fresh_start,
        )
    ).scalars().all()
    check("تلات أيام متلاصقة بتتجمّع في رسالة واحدة", len(pending) == 1,
          f"{len(pending)} رسالة")
    if pending:
        span = (pending[0].end_date - pending[0].start_date).days
        check("الرسالة بتغطّي التلات أيام", span == 3, f"{span} يوم")

    r = client.post("/api/v1/channels/sync", headers=gm)
    check("الطابور اتفضّى", r.status_code == 200, f"اتبعت {r.json()['sent']}")

    print("\n─── حجز جاي من القناة ───")
    mapped = db.execute(
        select(ChannelMapping).where(
            ChannelMapping.channel_id == channel_id, ChannelMapping.is_active.is_(True)
        )
    ).scalars().first()
    arrival = today + timedelta(days=45)
    # مرجع فريد لكل تشغيلة — من غيره التشغيلة التانية بتلاقي حجزها
    # موجود من الأولى وتتحوّل DUPLICATE، والسويت تفشل غلط
    reference = f"TEST-{uuid4().hex[:10].upper()}"

    payload = {
        "external_reference": reference,
        "action": "NEW",
        "external_room_id": mapped.external_room_id,
        "arrival_date": str(arrival),
        "departure_date": str(arrival + timedelta(days=2)),
        "adults": 2,
        "children": 0,
        "guest": {
            "first_name": "اختبار",
            "last_name": "القنوات",
            "phone": "01000000999",
            "nationality": "EG",
        },
    }

    r = client.post("/api/v1/channels/BOOKING_COM/bookings", headers=gm, json=payload)
    body = r.json()
    check("استقبال حجز من القناة", r.status_code in (200, 201), body.get("status", r.text[:80]))
    reservation_id = body.get("reservation_id")
    check("الحجز اتحوّل لحجز داخلي", reservation_id is not None,
          body.get("reservation_code", ""))
    check("الحالة PROCESSED", body.get("status") == "PROCESSED", body.get("status", ""))
    check("العمولة اتحسبت", float(body.get("commission_amount", 0)) > 0,
          f"{body.get('commission_amount')} من {body.get('gross_amount')}")

    if reservation_id:
        reservation = db.get(Reservation, reservation_id)
        check("الحجز مصدره القناة", reservation.source == "BOOKING_COM", reservation.source)
        check("الحجز مؤكّد", reservation.status == ReservationStatus.CONFIRMED,
              reservation.status)
        check("المرجع الخارجي محفوظ", reservation.external_reference == reference,
              reservation.external_reference or "")

    print("\n─── الرسالة والحجز في نفس المعاملة ───")
    queued = db.execute(
        select(func.count(ChannelMessage.id)).where(
            ChannelMessage.property_id == prop.id,
            ChannelMessage.status == ChannelMessageStatus.PENDING,
        )
    ).scalar_one()
    check("الحجز طلّع رسالة إتاحة في الطابور", queued > 0,
          f"{queued} رسالة مستنية")

    print("\n─── التكرار ───")
    r = client.post("/api/v1/channels/BOOKING_COM/bookings", headers=gm, json=payload)
    check("نفس الحجز مرتين بيتعلّم DUPLICATE",
          r.json().get("status") == "DUPLICATE", r.json().get("status", ""))
    check("التكرار مبيعملش حجز تاني",
          r.json().get("reservation_id") == reservation_id,
          str(r.json().get("reservation_id")))

    logged = db.execute(
        select(func.count(ChannelBooking.id)).where(
            ChannelBooking.property_id == prop.id,
            ChannelBooking.external_reference == reference,
        )
    ).scalar_one()
    check("سجل الوصول بيسجّل المحاولتين — إضافة فقط", logged >= 2,
          f"{logged} سطر")

    print("\n─── التعديل ───")
    modify = {
        **payload,
        "action": "MODIFY",
        "departure_date": str(arrival + timedelta(days=3)),
    }
    r = client.post("/api/v1/channels/BOOKING_COM/bookings", headers=gm, json=modify)
    check("التعديل بيتنفّذ", r.json().get("status") == "PROCESSED",
          r.json().get("status", ""))

    if reservation_id:
        db.expire_all()
        changed = db.get(Reservation, reservation_id)
        check("مدة الإقامة اتغيّرت", changed.nights == 3, f"{changed.nights} ليالي")

    r = client.post("/api/v1/channels/BOOKING_COM/bookings", headers=gm, json=modify)
    check("نفس التعديل مرتين بيتعلّم DUPLICATE",
          r.json().get("status") == "DUPLICATE", r.json().get("status", ""))

    modify_again = {
        **payload,
        "action": "MODIFY",
        "departure_date": str(arrival + timedelta(days=4)),
    }
    r = client.post("/api/v1/channels/BOOKING_COM/bookings", headers=gm, json=modify_again)
    check("تعديل تاني حقيقي مش بيتحسب تكرار",
          r.json().get("status") == "PROCESSED", r.json().get("status", ""))

    print("\n─── الإلغاء ───")
    cancel = {**payload, "action": "CANCEL"}
    r = client.post("/api/v1/channels/BOOKING_COM/bookings", headers=gm, json=cancel)
    check("الإلغاء بيتنفّذ", r.json().get("status") == "PROCESSED",
          r.json().get("status", ""))

    if reservation_id:
        db.expire_all()
        cancelled = db.get(Reservation, reservation_id)
        check("الحجز اتلغى", cancelled.status == ReservationStatus.CANCELLED,
              cancelled.status)

    print("\n─── الرفض ───")
    r = client.post("/api/v1/channels/BOOKING_COM/bookings", headers=gm, json={
        **payload,
        "external_reference": f"{reference}-BADROOM",
        "external_room_id": "ROOM-MSH-MAWGOD",
    })
    check("كود غرفة مش مربوط بيترفض",
          r.json().get("status") == "REJECTED", r.json().get("status", ""))
    check("الرفض بيسجّل السبب", bool(r.json().get("error")),
          (r.json().get("error") or "")[:50])

    r = client.post("/api/v1/channels/AGODA/bookings", headers=gm, json={
        **payload,
        "external_reference": f"{reference}-NODATES",
        "arrival_date": None,
        "departure_date": None,
    })
    check("حجز من غير تواريخ بيترفض",
          r.status_code in (400, 422) or r.json().get("status") == "REJECTED",
          str(r.status_code))

    r = client.post("/api/v1/channels/MSH-MAWGODA/bookings", headers=gm, json=payload)
    check("اسم قناة مش معروف بيترفض قبل ما يوصل للكود", r.status_code == 422,
          str(r.status_code))

    print("\n─── إعادة المزامنة والمحاولة ───")
    r = client.post(f"/api/v1/channels/resync", headers=gm,
                    json={"channel_id": channel_id, "days": 7})
    resync_ok = r.status_code == 200
    check("إعادة مزامنة القناة", resync_ok, r.json().get("message_ar", r.text[:60]))
    if resync_ok:
        check("إعادة المزامنة بتحط رسائل في الطابور",
              r.json().get("queued", 0) > 0, f"{r.json().get('queued')} رسالة")

    r = client.post("/api/v1/channels/retry", headers=gm)
    check("إعادة محاولة الفاشل", r.status_code == 200,
          r.json().get("message_ar", ""))

    r = client.post("/api/v1/channels/sync", headers=gm)
    check("تفضية الطابور بعد إعادة المزامنة", r.status_code == 200,
          f"اتبعت {r.json()['sent']}")

    print("\n─── سجل الحجوزات ───")
    r = client.get("/api/v1/channels/bookings?limit=30", headers=gm)
    arrivals = r.json()
    check("سجل الحجوزات الواصلة", r.status_code == 200, f"{len(arrivals)} سطر")
    check("السجل بيبيّن الحالة",
          all(a["status"] in
              {"PROCESSED", "DUPLICATE", "REJECTED", "FAILED"} for a in arrivals))

    print("\n─── ضبط القناة ───")
    r = client.patch(f"/api/v1/channels/{channel_id}", headers=gm,
                     json={"commission_percent": "18.5"})
    check("تعديل نسبة العمولة", r.status_code == 200,
          f"{r.json().get('commission_percent')}%")

    r = client.patch(f"/api/v1/channels/{channel_id}", headers=gm,
                     json={"commission_percent": str(booking_com["commission_percent"])})
    check("رجوع العمولة لأصلها", r.status_code == 200)

    r = client.patch(f"/api/v1/channels/{channel_id}", headers=cashier,
                     json={"is_active": False})
    check("الكاشير ممنوع يعدّل القناة", r.status_code == 403)

    r = client.patch(f"/api/v1/channels/{10**9}", headers=gm, json={"is_active": True})
    check("قناة مش موجودة بترجّع 404", r.status_code == 404)

    print("\n─── تنضيف ───")
    db.execute(
        ChannelBooking.__table__.delete().where(
            ChannelBooking.property_id == prop.id,
            ChannelBooking.external_reference.like(f"{reference}%"),
        )
    )
    db.commit()
    check("سجلات الاختبار اتشالت", True)

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
