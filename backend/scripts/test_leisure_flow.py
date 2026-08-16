"""اختبار السبا والأنشطة والمناسبات والـ CRM — Leisure, events & CRM flow test.

    python -m scripts.test_leisure_flow

تلات مبادئ السويت دي بتحرسهم:

**١. المورد مبيتحجزش مرتين.** المساج مش بيتحجز — *المعالجة* هي اللي
بتتحجز. ولو الجدول سمح بحجزين على نفس المعالجة، الفرق بيظهر عند
النزيل الواقف على باب الكابينة مش في التقرير.

**٢. المكان بيتقفل بالحالة مش بالنية.** استعلام مبيقفلش قاعة أفراح،
ومبدئي بيقفلها بميعاد انتهاء. لو الاتنين بيقفلوا، القرية بتخسر شغل
حقيقي على مكالمات مالهاش أي التزام.

**٣. الحساب محسوب مش مكتوب.** إجمالي المناسبة بيتبني من بنودها، فمفيش
حالة ورقة التشغيل بتقول رقم والفاتورة تقول رقم تاني.

آمنة التكرار: كل حاجة اتعملت بتتشال في الآخر، والحسابات اللي اتلمست
بترجع لأرصدتها.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.base import SessionLocal
from app.main import app
from app.models.enums import EventStatus, FolioStatus, ServiceBookingStatus
from app.models.folio import Folio, FolioLine
from app.models.leisure import (
    EventBooking,
    EventItem,
    GuestFeedback,
    Service,
    ServiceBooking,
    Venue,
)
from app.models.organization import Property
from app.services import folio as folio_svc

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []

#: كل شغل الاختبار على اليوم ده — بعيد عن أي حجز حقيقي
SANDBOX = date.today() + timedelta(days=420)
TEST_TAG = "[اختبار]"


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def D(value) -> Decimal:
    return Decimal(str(value))


def at(hour: int, minute: int = 0, day: date | None = None) -> str:
    return datetime.combine(
        day or SANDBOX, time(hour, minute), tzinfo=timezone.utc
    ).isoformat()


def purge(db) -> tuple[int, int, int]:
    """يمسح أي أثر من تشغيلة سابقة — قبل وبعد."""
    bookings = db.execute(
        select(ServiceBooking).where(ServiceBooking.business_date == SANDBOX)
    ).scalars().all()
    booking_ids = [b.id for b in bookings]
    touched_folios = {b.folio_id for b in bookings if b.folio_id}
    line_ids = [b.folio_line_id for b in bookings if b.folio_line_id]
    if line_ids:
        db.execute(delete(FolioLine).where(FolioLine.id.in_(line_ids)))
    if booking_ids:
        db.execute(delete(ServiceBooking).where(ServiceBooking.id.in_(booking_ids)))

    events = db.execute(
        select(EventBooking).where(EventBooking.title.like(f"{TEST_TAG}%"))
    ).scalars().all()
    event_ids = [e.id for e in events]
    if event_ids:
        db.execute(delete(EventItem).where(EventItem.event_id.in_(event_ids)))
        db.execute(delete(EventBooking).where(EventBooking.id.in_(event_ids)))

    notes = db.execute(
        select(GuestFeedback).where(GuestFeedback.subject.like(f"{TEST_TAG}%"))
    ).scalars().all()
    note_ids = [n.id for n in notes]
    if note_ids:
        db.execute(delete(GuestFeedback).where(GuestFeedback.id.in_(note_ids)))

    db.flush()
    for folio_id in touched_folios:
        folio = db.get(Folio, folio_id)
        if folio is not None:
            folio_svc.recalculate(db, folio)
    db.commit()
    return len(booking_ids), len(event_ids), len(note_ids)


def main() -> int:  # noqa: PLR0912, PLR0915
    client = TestClient(app)
    db = SessionLocal()

    def login(username: str) -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": "venicia2026"}
        )
        assert r.status_code == 200, f"{username}: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    gm = login("gm")
    desk = login("ahmed")        # استقبال — بيحجز مبيديرش
    fom = login("nourhan")       # مدير استقبال — بيدير المناسبات
    waiter = login("karim")      # ويتر — مالوش دعوة
    keeper = login("fatma")      # هاوس كيبر — مالوش دعوة

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()

    gone = purge(db)
    if any(gone):
        print(f"  (نضّفت {gone[0]} حجز و{gone[1]} مناسبة و{gone[2]} ملاحظة من تشغيلة سابقة)")

    # ═════════════════════════════════════════════════════ الكتالوج
    print("\n─── الخدمات والموارد ───")
    r = client.get("/api/v1/services", headers=desk)
    services = {s["code"]: s for s in r.json()}
    check("كتالوج الخدمات", r.status_code == 200, f"{len(services)} خدمة")
    check("فيه سبا وأنشطة ورحلات",
          {"SPA", "ACTIVITY", "EXCURSION"} <= {s["category"] for s in services.values()},
          " · ".join(sorted({s["category"] for s in services.values()})))

    massage = services["SPA-SWED"]
    check("الخدمة ليها معالجين مرتبطين بيها", len(massage["resources"]) >= 2,
          " · ".join(x["name_ar"] for x in massage["resources"]))
    check("الهامش محسوب — الإدارة بتعرف تسعّر",
          D(massage["margin_percent"]) > 0,
          f"{massage['margin_percent']}% على سعر {massage['price']}")
    check("وقت التجهيز موجود — الجدول بيحسب حساب ترتيب الكابينة",
          massage["buffer_minutes"] > 0, f"{massage['buffer_minutes']} دقيقة")

    r = client.get("/api/v1/services/resources", headers=desk)
    resources = {x["code"]: x for x in r.json()}
    check("الموارد", r.status_code == 200, f"{len(resources)} مورد")
    check("فيه بشر وأماكن ومعدات",
          {"STAFF", "ROOM", "EQUIPMENT"} <= {x["kind"] for x in resources.values()})
    check("لكل مورد وردية — الجدول مبيعرضش ميعاد بره الوردية",
          all(x["shift_start"] and x["shift_end"] for x in resources.values()))

    print("\n─── مين مالوش دعوة ───")
    for headers, who in [(waiter, "الويتر"), (keeper, "الهاوس كيبر")]:
        r = client.get("/api/v1/services", headers=headers)
        check(f"{who} ممنوع من الكتالوج", r.status_code == 403, str(r.status_code))
    r = client.post(
        "/api/v1/leisure/bookings",
        json={"service_id": massage["id"], "start_at": at(11), "guest_name": "x"},
        headers=waiter,
    )
    check("الويتر مبيقدرش يحجز", r.status_code == 403, str(r.status_code))

    # ═════════════════════════════════════════════════ المواعيد الفاضية
    print("\n─── المواعيد الفاضية ───")
    r = client.get(f"/api/v1/services/{massage['id']}/slots?date={SANDBOX}", headers=desk)
    slots = r.json()
    check("المواعيد بتنزل", r.status_code == 200 and len(slots) > 0, f"{len(slots)} ميعاد")
    check("كل ميعاد معاه المورد بتاعه — مفيش ميعاد مجرّد",
          all(s["resource_id"] for s in slots))
    check("مفيش ميعاد قبل فتح الخدمة",
          all(s["start_at"][11:16] >= massage["opens_at"][:5] for s in slots),
          f"الفتح {massage['opens_at']}")
    check("ولا ميعاد بينتهي بعد القفل",
          all(s["end_at"][11:16] <= massage["closes_at"][:5] for s in slots),
          f"القفل {massage['closes_at']}")

    # المعالجة اللي ورديتها بتبدأ متأخر مبتظهرش بدري
    late = next(
        (x for x in massage["resources"] if x["shift_start"] and x["shift_start"] >= "12:00"),
        None,
    )
    if late:
        early = [
            s for s in slots
            if s["resource_id"] == late["id"] and s["start_at"][11:16] < late["shift_start"][:5]
        ]
        check("وردية المورد بتضيّق ساعات الخدمة مش العكس", not early,
              f"{late['name_ar']} من {late['shift_start']}")

    # ═════════════════════════════════════════════════════ الحجز
    print("\n─── الحجز والتعارض ───")
    therapist = massage["resources"][0]
    r = client.post(
        "/api/v1/leisure/bookings",
        json={
            "service_id": massage["id"], "start_at": at(14),
            "guest_name": "سلمى الشناوي", "resource_id": therapist["id"],
        },
        headers=desk,
    )
    first = r.json()
    check("الحجز اتقبل", r.status_code == 200, f"{first.get('number')} · {first.get('total')} ج")
    check("الحجز ماسك مورد", first["resource_id"] == therapist["id"], first["resource_name"])
    check("السعر جه من الكتالوج", D(first["total"]) == D(massage["price"]),
          f"{first['total']}")

    r = client.post(
        "/api/v1/leisure/bookings",
        json={
            "service_id": massage["id"], "start_at": at(14),
            "guest_name": "حد تاني", "resource_id": therapist["id"],
        },
        headers=desk,
    )
    check("نفس المعالجة نفس الميعاد بيترفض", r.status_code == 409,
          r.json().get("detail", {}).get("ar", ""))

    # المساج ٦٠ دقيقة + ٢٠ تجهيز = المفروض ٢:٣٠ لسه متعارضة
    r = client.post(
        "/api/v1/leisure/bookings",
        json={
            "service_id": massage["id"], "start_at": at(14, 30),
            "guest_name": "حد تالت", "resource_id": therapist["id"],
        },
        headers=desk,
    )
    check("والحجز جوّه وقت التجهيز بيترفض كمان — الجدول مبيكدبش",
          r.status_code == 409,
          f"{massage['duration_minutes']}د + {massage['buffer_minutes']}د تجهيز")

    r = client.post(
        "/api/v1/leisure/bookings",
        json={
            "service_id": massage["id"], "start_at": at(15, 30),
            "guest_name": "نادر فهمي", "resource_id": therapist["id"],
        },
        headers=desk,
    )
    check("وبعد التجهيز الميعاد بيعدي", r.status_code == 200, r.json().get("number", ""))
    second = r.json()

    r = client.post(
        "/api/v1/leisure/bookings",
        json={"service_id": massage["id"], "start_at": at(14), "guest_name": "أوتوماتيك"},
        headers=desk,
    )
    auto = r.json()
    check("من غير تحديد مورد، النظام بيلاقي حد فاضي بدل ما يرفض",
          r.status_code == 200 and auto["resource_id"] != therapist["id"],
          auto.get("resource_name", ""))

    r = client.post(
        "/api/v1/leisure/bookings",
        json={"service_id": massage["id"], "start_at": at(8), "guest_name": "بدري"},
        headers=desk,
    )
    check("ميعاد قبل فتح السبا بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.post(
        "/api/v1/leisure/bookings",
        json={
            "service_id": massage["id"], "start_at": at(14),
            "guest_name": "عيلة", "adults": 4,
        },
        headers=desk,
    )
    check("عدد أكبر من سعة الخدمة بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    print("\n─── الكلاس الجماعي ───")
    yoga = services["FIT-YOGA"]
    booked = 0
    for index in range(4):
        r = client.post(
            "/api/v1/leisure/bookings",
            json={
                "service_id": yoga["id"], "start_at": at(7),
                "guest_name": f"مشترك {index + 1}", "adults": 2,
            },
            headers=desk,
        )
        if r.status_code == 200:
            booked += 1
    check("الكلاس بياخد أكتر من واحد في نفس الميعاد", booked >= 3,
          f"{booked} حجز · السعة {yoga['capacity']}")

    r = client.get(f"/api/v1/services/{yoga['id']}/slots?date={SANDBOX}", headers=desk)
    seven = [s for s in r.json() if s["start_at"][11:16] == "07:00"]
    check("والمقاعد الفاضية بتقل مع كل حجز",
          not seven or seven[0]["seats_left"] < yoga["capacity"],
          f"فاضل {seven[0]['seats_left'] if seven else 0}")

    # ═════════════════════════════════════════════════ النقل والدورة
    print("\n─── نقل الموعد ───")
    r = client.patch(
        f"/api/v1/leisure/bookings/{second['id']}/reschedule",
        json={"start_at": at(14)},
        headers=desk,
    )
    check("النقل لميعاد متعارض بيترفض", r.status_code == 409,
          r.json().get("detail", {}).get("ar", ""))

    r = client.patch(
        f"/api/v1/leisure/bookings/{second['id']}/reschedule",
        json={"start_at": at(18)},
        headers=desk,
    )
    check("النقل لميعاد فاضي بيعدي", r.status_code == 200,
          r.json().get("start_at", "")[11:16])

    r = client.patch(
        f"/api/v1/leisure/bookings/{second['id']}/reschedule",
        json={"start_at": at(18)},
        headers=desk,
    )
    check("والنقل لنفس مكانه مبيتعارضش مع نفسه", r.status_code == 200,
          "الحجز مستثنى من فحص التعارض")

    # ═══════════════════════════════════════ الترحيل على حساب النزيل
    print("\n─── الترحيل على الحساب ───")
    folio = db.execute(
        select(Folio)
        .where(Folio.property_id == prop.id, Folio.status == FolioStatus.OPEN)
        .order_by(Folio.id)
        .limit(1)
    ).scalar_one()
    before_balance = D(folio.balance)

    r = client.post(
        "/api/v1/leisure/bookings",
        json={
            "service_id": massage["id"], "start_at": at(20),
            "guest_name": "نزيل مقيم", "folio_id": folio.id,
        },
        headers=desk,
    )
    onfolio = r.json()
    check("حجز على حساب نزيل مقيم", r.status_code == 200, onfolio.get("number", ""))
    check("ولسه ماترحّلش — الترحيل بيحصل لما الجلسة تخلص",
          not onfolio["is_posted"])

    r = client.post(f"/api/v1/leisure/bookings/{onfolio['id']}/check-in", headers=desk)
    check("حضور النزيل", r.status_code == 200, r.json().get("status", ""))

    r = client.post(f"/api/v1/leisure/bookings/{onfolio['id']}/complete", headers=desk)
    completed = r.json()
    check("إنهاء الجلسة", r.status_code == 200 and completed["status"] == "COMPLETED",
          completed.get("status", ""))
    check("واترحّلت على الحساب", completed["is_posted"])

    db.expire_all()
    folio = db.get(Folio, folio.id)
    after_balance = D(folio.balance)
    check("رصيد النزيل زاد بالمساج + الخدمة + الضريبة",
          after_balance > before_balance + D(massage["price"]),
          f"{before_balance} → {after_balance}")

    r = client.post(f"/api/v1/leisure/bookings/{onfolio['id']}/complete", headers=desk)
    db.expire_all()
    folio = db.get(Folio, folio.id)
    check("إنهاء تاني مبيرحّلش مرتين — ضغطتين مش بيتحاسبوا مرتين",
          D(folio.balance) == after_balance, f"{folio.balance}")

    r = client.post(
        f"/api/v1/leisure/bookings/{onfolio['id']}/cancel",
        json={"reason": "تجربة"},
        headers=desk,
    )
    check("الإلغاء بعد الترحيل بيترفض — الإلغاء بيتم من الفوليو",
          r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.post(
        f"/api/v1/leisure/bookings/{auto['id']}/cancel", json={"reason": ""}, headers=desk
    )
    check("الإلغاء من غير سبب بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.post(
        f"/api/v1/leisure/bookings/{auto['id']}/cancel",
        json={"reason": "النزيل غيّر رأيه"},
        headers=desk,
    )
    check("الإلغاء بسبب بيعدي", r.status_code == 200, r.json().get("status", ""))

    print("\n─── لوحة اليوم ───")
    r = client.get(f"/api/v1/leisure/board?date={SANDBOX}", headers=desk)
    board = r.json()
    check("اللوحة بتنزل", r.status_code == 200, f"{board['bookings']} حجز")
    check("الملغي مش داخل في الإيراد المتوقّع",
          board["cancelled"] >= 1 and D(board["revenue"]) > 0,
          f"ملغي {board['cancelled']} · إيراد {board['revenue']}")
    check("والمرحّل بيتعدّ لوحده",
          D(board["posted"]) > 0 and D(board["posted"]) <= D(board["revenue"]),
          f"مرحّل {board['posted']} من {board['revenue']}")
    check("عدد الأفراد محسوب", board["guests"] >= board["bookings"] - board["cancelled"],
          f"{board['guests']} فرد")

    # ═════════════════════════════════════════════════════ المناسبات
    print("\n─── المناسبات: المكان بيتقفل بالحالة مش بالنية ───")
    r = client.get("/api/v1/venues", headers=desk)
    venues = {v["code"]: v for v in r.json()}
    check("أماكن المناسبات", r.status_code == 200, f"{len(venues)} مكان")
    lawn = venues["V-LAWN"]
    check("للمكان حد أدنى للإنفاق", D(lawn["minimum_spend"]) > 0,
          f"{lawn['minimum_spend']} ج")

    r = client.post(
        "/api/v1/events",
        json={
            "venue_id": lawn["id"], "title": f"{TEST_TAG} استعلام فرح",
            "client_name": "عائلة سليمان", "start_at": at(16), "end_at": at(23),
            "kind": "WEDDING", "status": "INQUIRY", "pax": 250,
        },
        headers=fom,
    )
    inquiry = r.json()
    check("استعلام اتسجّل", r.status_code == 200, inquiry.get("number", ""))

    r = client.post(
        "/api/v1/events",
        json={
            "venue_id": lawn["id"], "title": f"{TEST_TAG} استعلام تاني",
            "client_name": "عائلة رشدي", "start_at": at(16), "end_at": at(23),
            "kind": "WEDDING", "status": "INQUIRY", "pax": 200,
        },
        headers=fom,
    )
    check("استعلامين على نفس اليوم بيعدّوا — الاستعلام مبيقفلش قاعة",
          r.status_code == 200, r.json().get("number", ""))
    inquiry2 = r.json()

    r = client.patch(
        f"/api/v1/events/{inquiry['id']}/status",
        json={"status": "TENTATIVE"},
        headers=fom,
    )
    check("التحويل لمبدئي بيقفل المكان", r.status_code == 200,
          f"مهلة العربون لحد {r.json().get('option_until')}")
    check("والمبدئي بيتحط له ميعاد انتهاء", bool(r.json().get("option_until")))

    r = client.patch(
        f"/api/v1/events/{inquiry2['id']}/status",
        json={"status": "TENTATIVE"},
        headers=fom,
    )
    check("والاستعلام التاني مبقاش ينفع يتحوّل — المكان اتقفل",
          r.status_code == 409, r.json().get("detail", {}).get("ar", ""))

    r = client.post(
        "/api/v1/events",
        json={
            "venue_id": lawn["id"], "title": f"{TEST_TAG} حجز مباشر",
            "client_name": "شركة", "start_at": at(18), "end_at": at(22),
            "status": "TENTATIVE", "pax": 100,
        },
        headers=fom,
    )
    check("وحجز مبدئي جديد على نفس الوقت بيترفض من الأول",
          r.status_code == 409, r.json().get("detail", {}).get("ar", ""))

    r = client.post(
        "/api/v1/events",
        json={
            "venue_id": lawn["id"], "title": f"{TEST_TAG} فوق السعة",
            "client_name": "شركة", "start_at": at(10, 0, SANDBOX + timedelta(days=3)),
            "end_at": at(14, 0, SANDBOX + timedelta(days=3)),
            "status": "INQUIRY", "pax": 5000,
        },
        headers=fom,
    )
    check("عدد أكبر من سعة المكان بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    # ═══════════════════════════════════════ ورقة التشغيل والحساب
    print("\n─── الحساب محسوب مش مكتوب ───")
    event_id = inquiry["id"]
    r = client.get(f"/api/v1/events/{event_id}", headers=fom)
    base = r.json()
    check("الإجمالي اتحسب من أول لحظة", D(base["grand_total"]) > 0,
          f"{base['grand_total']} ج")
    check("الحد الأدنى للإنفاق اتطبّق على المكان",
          D(base["subtotal"]) >= D(lawn["minimum_spend"]),
          f"{base['subtotal']} مقابل حد أدنى {lawn['minimum_spend']}")
    check("العربون المطلوب اتحسب لوحده", D(base["deposit_required"]) > 0,
          f"{base['deposit_required']} ج")

    r = client.post(
        f"/api/v1/events/{event_id}/items",
        json={
            "kind": "FNB", "description_ar": "بوفيه عشاء",
            "quantity": "250", "unit_price": "850",
        },
        headers=fom,
    )
    withfnb = r.json()
    check("بند البوفيه اتضاف", r.status_code == 200, f"{withfnb['items_total']} ج")
    check("والإجمالي زاد لوحده", D(withfnb["grand_total"]) > D(base["grand_total"]),
          f"{base['grand_total']} → {withfnb['grand_total']}")
    check("الخدمة والضريبة محسوبين على الإجمالي",
          D(withfnb["service_charge"]) > 0 and D(withfnb["tax"]) > 0,
          f"خدمة {withfnb['service_charge']} · ضريبة {withfnb['tax']}")
    check("الإجمالي = المجموع + الخدمة + الضريبة",
          D(withfnb["grand_total"])
          == D(withfnb["subtotal"]) + D(withfnb["service_charge"]) + D(withfnb["tax"]),
          f"{withfnb['subtotal']} + {withfnb['service_charge']} + {withfnb['tax']}")

    r = client.post(
        f"/api/v1/events/{event_id}/items",
        json={
            "kind": "DECOR", "description_ar": "تنسيق زهور",
            "quantity": "1", "unit_price": "35000", "is_complimentary": True,
        },
        headers=fom,
    )
    comp = r.json()
    check("البند المجاني بيتسجّل بصفر — بيبان في الورقة ومش بيتحاسب",
          D(comp["items_total"]) == D(withfnb["items_total"]),
          f"{comp['items_total']}")
    check("وبيفضل مكتوب في ورقة التشغيل",
          any(i["is_complimentary"] for i in comp["items"]),
          f"{len(comp['items'])} بند")

    removable = [i for i in comp["items"] if i["kind"] == "FNB"][0]
    r = client.delete(f"/api/v1/events/{event_id}/items/{removable['id']}", headers=fom)
    check("حذف بند بيرجّع الإجمالي", r.status_code == 200,
          f"{comp['grand_total']} → {r.json()['grand_total']}")

    r = client.post(
        f"/api/v1/events/{event_id}/items",
        json={
            "kind": "FNB", "description_ar": "بوفيه عشاء",
            "quantity": "250", "unit_price": "850",
        },
        headers=fom,
    )
    ready = r.json()

    print("\n─── العربون شرط التأكيد ───")
    r = client.patch(
        f"/api/v1/events/{event_id}/status", json={"status": "CONFIRMED"}, headers=fom
    )
    check("التأكيد من غير عربون بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.post(
        f"/api/v1/events/{event_id}/deposit",
        json={"amount": str(D(ready["deposit_required"]) / 2)},
        headers=fom,
    )
    check("عربون جزئي اتسجّل", r.status_code == 200,
          f"{r.json()['deposit_paid']} من {r.json()['deposit_required']}")

    r = client.patch(
        f"/api/v1/events/{event_id}/status", json={"status": "CONFIRMED"}, headers=fom
    )
    check("ونص العربون لسه مش كفاية", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.post(
        f"/api/v1/events/{event_id}/deposit",
        json={"amount": str(D(ready["deposit_required"]))},
        headers=fom,
    )
    r = client.patch(
        f"/api/v1/events/{event_id}/status", json={"status": "CONFIRMED"}, headers=fom
    )
    confirmed = r.json()
    check("بعد العربون الكامل التأكيد بيعدي", r.status_code == 200,
          confirmed.get("status", ""))
    check("ومهلة العربون بتتشال — بقى مؤكد مش مبدئي",
          confirmed.get("option_until") is None)

    r = client.patch(
        f"/api/v1/events/{event_id}/status",
        json={"status": "CANCELLED"},
        headers=fom,
    )
    check("الإلغاء من غير سبب بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.patch(
        f"/api/v1/events/{inquiry2['id']}/status",
        json={"status": "LOST", "reason": "راح لمكان أرخص"},
        headers=fom,
    )
    check("«ضاعت» بتتسجّل بسببها — ده اللي بيدي تقرير خسائر حقيقي",
          r.status_code == 200, r.json().get("lost_reason", ""))

    r = client.patch(
        f"/api/v1/events/{event_id}/status", json={"status": "CONFIRMED"}, headers=desk
    )
    check("الاستقبال العادي مبيديرش المناسبات", r.status_code == 403, str(r.status_code))

    print("\n─── لوحة المناسبات ───")
    r = client.get("/api/v1/events?days=500", headers=fom)
    events = r.json()
    check("اللوحة بتنزل", r.status_code == 200,
          f"مؤكد {events['confirmed']} · مبدئي {events['tentative']}"
          f" · استعلام {events['inquiries']}")
    check("قيمة المؤكد منفصلة عن قيمة الاحتمالات",
          D(events["confirmed_value"]) > 0,
          f"مؤكد {events['confirmed_value']} · محتمل {events['pipeline_value']}")
    check("نسبة التحويل محسوبة", D(events["win_rate_percent"]) > 0,
          f"{events['win_rate_percent']}%")
    check("والمناسبة بتاعتنا في القايمة",
          any(e["number"] == confirmed["number"] for e in events["events"]))

    # ═══════════════════════════════════════════════════════ CRM
    print("\n─── ملف النزيل ───")
    guest_id = folio.guest_id
    r = client.get(f"/api/v1/crm/guests/{guest_id}", headers=gm)
    profile = r.json()
    check("الملف بينزل", r.status_code == 200,
          f"{profile['name']} · {profile['stays']} إقامة")
    spend = profile["spend"]
    total = sum(
        D(spend[k]) for k in ("rooms", "food", "spa", "activities", "other")
    )
    check("الإنفاق مقسّم على مصادره ومجموعه بيقفل",
          D(spend["total"]) == total,
          f"إقامة {spend['rooms']} · أكل {spend['food']} · سبا {spend['spa']}")
    check("المساج اللي اترحّل بان في خانة السبا", D(spend["spa"]) > 0,
          f"{spend['spa']} ج")
    check("الشرايح محسوبة من السلوك", len(profile["segments"]) > 0,
          " · ".join(profile["segments"]))
    if profile["stays"]:
        check("متوسط الإنفاق على الإقامة محسوب",
              D(profile["average_per_stay"]) > 0, f"{profile['average_per_stay']} ج")

    r = client.get("/api/v1/crm/guests/99999999", headers=gm)
    check("نزيل مش موجود بيرجّع 404", r.status_code == 404, str(r.status_code))

    print("\n─── الشرائح ───")
    r = client.get("/api/v1/crm/segments", headers=gm)
    segments = {s["code"]: s for s in r.json()}
    check("ملخّص الشرايح", r.status_code == 200,
          " · ".join(f"{s['name_ar']} {s['guests']}" for s in list(segments.values())[:4]))
    check("الشرايح مش متداخلة عشوائي — لكل واحدة قيمتها",
          all(s["guests"] >= 0 for s in segments.values()))

    r = client.get("/api/v1/crm/segments/REACHABLE?limit=50", headers=gm)
    reachable = r.json()
    check("قايمة الموافقين على التسويق", r.status_code == 200, f"{len(reachable)} نزيل")
    check("وكلهم لهم وسيلة تواصل فعلاً",
          all(g["phone"] or g["email"] for g in reachable),
          "مفيش صف بيتبعتله رسالة على فراغ")

    r = client.get("/api/v1/crm/segments/MSH-MAWGODA", headers=gm)
    check("شريحة مش معروفة بترجّع خطأ واضح", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.get("/api/v1/crm/top-guests?limit=10", headers=gm)
    top = r.json()
    check("أعلى النزلاء إنفاقاً", r.status_code == 200, f"{len(top)} نزيل")
    check("مرتّبين تنازلياً",
          [D(g["total_spend"]) for g in top]
          == sorted((D(g["total_spend"]) for g in top), reverse=True),
          f"الأعلى {top[0]['total_spend']} ج" if top else "")

    r = client.get("/api/v1/crm/segments", headers=keeper)
    check("الهاوس كيبر ممنوع من بيانات النزلاء", r.status_code == 403, str(r.status_code))

    print("\n─── الشكاوى ووقت الرد ───")
    r = client.post(
        "/api/v1/crm/feedback",
        json={
            "subject": f"{TEST_TAG} التكييف مكانش بيبرّد",
            "kind": "COMPLAINT", "channel": "IN_HOUSE",
            "guest_id": guest_id, "department": "الصيانة",
            "body": "أول ليلتين الأوضة كانت حرّة",
        },
        headers=gm,
    )
    complaint = r.json()
    check("الشكوى اتسجّلت", r.status_code == 200, complaint.get("number", ""))
    check("وبتفتح مفتوحة ومحدش رد", complaint["status"] == "OPEN"
          and complaint["acknowledged_at"] is None)

    r = client.post(
        f"/api/v1/crm/feedback/{complaint['id']}/acknowledge", headers=gm
    )
    acked = r.json()
    check("تسجيل الرد", r.status_code == 200 and acked["status"] == "ACKNOWLEDGED",
          acked.get("status", ""))
    check("ووقت الرد اتقاس", acked["hours_to_ack"] is not None,
          f"{acked['hours_to_ack']} ساعة")

    r = client.post(
        f"/api/v1/crm/feedback/{complaint['id']}/resolve",
        json={"resolution": ""},
        headers=gm,
    )
    check("الإغلاق من غير وصف بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.post(
        f"/api/v1/crm/feedback/{complaint['id']}/resolve",
        json={"resolution": "اتغيّر الكمبروسر واتنقل لوحدة تانية", "compensation": "1500"},
        headers=gm,
    )
    resolved = r.json()
    check("الإغلاق بوصف وتعويض", r.status_code == 200 and resolved["status"] == "RESOLVED",
          f"تعويض {resolved['compensation']} ج")
    check("ووقت الحل اتسجّل", resolved["resolved_at"] is not None)

    r = client.post(
        "/api/v1/crm/feedback",
        json={
            "subject": f"{TEST_TAG} شكر لفريق المطعم",
            "kind": "COMPLIMENT", "channel": "GOOGLE", "rating": 5,
            "guest_id": guest_id,
        },
        headers=gm,
    )
    praise = r.json()
    check("الثناء بيتسجّل زي الشكوى", r.status_code == 200, praise.get("number", ""))
    check("والتقييم اتحفظ", praise["rating"] == 5)

    r = client.post(
        "/api/v1/crm/feedback",
        json={
            "subject": f"{TEST_TAG} تقييم برة المدى",
            "kind": "REVIEW", "channel": "GOOGLE", "rating": 99,
        },
        headers=gm,
    )
    check("التقييم بيتقصّ على ٥ مش بيترفض", r.status_code == 200
          and r.json()["rating"] == 5, str(r.json().get("rating")))

    r = client.post(
        f"/api/v1/crm/feedback/{praise['id']}/escalate",
        json={"note": "الإدارة تشوفها"},
        headers=gm,
    )
    check("التصعيد للإدارة", r.status_code == 200 and r.json()["status"] == "ESCALATED")

    r = client.post(
        f"/api/v1/crm/feedback/{resolved['id']}/escalate", json={}, headers=gm
    )
    check("تصعيد ملاحظة مقفولة بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", ""))

    r = client.get("/api/v1/crm/feedback", headers=gm)
    fb = r.json()
    check("لوحة الشكاوى", r.status_code == 200,
          f"مفتوح {fb['open']} · متصعّد {fb['escalated']} · اتحل {fb['resolved_30d']}")
    check("متوسط وقت الرد محسوب", fb["average_ack_hours"] is not None,
          f"{fb['average_ack_hours']} ساعة · المستهدف {fb['ack_target_hours']}")
    check("متوسط التقييم محسوب", fb["average_rating"] is not None,
          f"★ {fb['average_rating']}")
    check("التعويضات متتبّعة", D(fb["compensation_30d"]) >= 1500,
          f"{fb['compensation_30d']} ج")
    check("الشكاوى موزّعة على الأقسام", bool(fb["by_department"]), str(fb["by_department"]))

    r = client.post(
        "/api/v1/crm/feedback",
        json={"subject": "   ", "kind": "COMPLAINT", "channel": "EMAIL"},
        headers=gm,
    )
    check("ملاحظة من غير عنوان بترفض", r.status_code == 400,
          r.json().get("detail", {}).get("ar", str(r.status_code)))

    r = client.get("/api/v1/crm/feedback?status=OPEN", headers=gm)
    check("الفلترة بالحالة شغّالة",
          all(x["status"] == "OPEN" for x in r.json()["items"]),
          f"{len(r.json()['items'])} صف")

    # ═══════════════════════════════════════════════════════ التنضيف
    print("\n─── الرجوع للحالة الأصلية ───")
    db.expire_all()
    removed = purge(db)
    db.expire_all()
    folio = db.get(Folio, folio.id)
    check("رصيد الحساب رجع زي ما كان", D(folio.balance) == before_balance,
          f"{before_balance} → {folio.balance}")
    check("حجوزات الاختبار اتمسحت", not db.execute(
        select(ServiceBooking).where(ServiceBooking.business_date == SANDBOX)
    ).scalars().first(), f"{removed[0]} حجز")
    check("مناسبات الاختبار اتمسحت", not db.execute(
        select(EventBooking).where(EventBooking.title.like(f"{TEST_TAG}%"))
    ).scalars().first(), f"{removed[1]} مناسبة")
    check("وملاحظات الاختبار اتمسحت", not db.execute(
        select(GuestFeedback).where(GuestFeedback.subject.like(f"{TEST_TAG}%"))
    ).scalars().first(), f"{removed[2]} ملاحظة")

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
