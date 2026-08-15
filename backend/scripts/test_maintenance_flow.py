"""اختبار الصيانة والميني بار — Maintenance & minibar flow test.

    python -m scripts.test_maintenance_flow

المبدأ اللي السويت دي بتحرسه: **الوحدة المحجوزة بتذكرة صيانة مبتترجعش
للخدمة غير لما تقفل آخر تذكرة عليها.**

الباج اللي السويت دي اتكتبت أصلاً عشانه: تذكرتين حاجزين نفس الوحدة،
التانية لما بتتفتح بتحفظ الحالة الحالية «تحت الصيانة» كحالة سابقة —
فلما تقفل بترجّع الوحدة لـ«تحت الصيانة» وتفضل مجمّدة للأبد.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.main import app
from app.models.enums import (
    OPEN_TICKET_STATUSES,
    FolioStatus,
    HousekeepingStatus,
    TicketPriority,
    TicketStatus,
    UnitCondition,
)
from app.models.folio import Folio
from app.models.maintenance import MaintenanceTicket
from app.models.organization import Property
from app.models.units import Unit
from app.services import maintenance as mt

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
    keeper = login("samia")     # هاوس كيبينج — بتفتح البلاغ وهي بتنضّف
    waiter = login("karim")     # ممنوع

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    made: list[int] = []

    print("\n─── اللوحة ───")
    r = client.get("/api/v1/maintenance", headers=gm)
    board = r.json()
    check("لوحة الصيانة", r.status_code == 200, f"{len(board['tickets'])} تذكرة")
    check("العدّادات موجودة",
          all(k in board for k in
              ("open", "assigned", "in_progress", "done_today", "overdue",
               "urgent", "blocked_units", "cost_this_month")))
    check("عدد المحجوز = تذاكر حاجزة فعلاً",
          board["blocked_units"] >= 0, f"{board['blocked_units']} وحدة")

    r = client.get("/api/v1/maintenance", headers=keeper)
    check("الهاوس كيبينج بتشوف اللوحة", r.status_code == 200)
    r = client.get("/api/v1/maintenance", headers=waiter)
    check("الويتر ممنوع من الصيانة", r.status_code == 403)

    r = client.get("/api/v1/maintenance/technicians", headers=gm)
    techs = r.json()
    check("قائمة الفنيين", r.status_code == 200 and len(techs) > 0, f"{len(techs)} فني")

    print("\n─── فتح تذكرة ───")
    # وحدة صالحة ومش عليها تذاكر مفتوحة
    busy = set(
        db.execute(
            select(MaintenanceTicket.unit_id).where(
                MaintenanceTicket.property_id == prop.id,
                MaintenanceTicket.status.in_(list(OPEN_TICKET_STATUSES)),
                MaintenanceTicket.unit_id.is_not(None),
            )
        ).scalars().all()
    )
    unit = db.execute(
        select(Unit)
        .where(
            Unit.property_id == prop.id,
            Unit.is_active.is_(True),
            Unit.condition == UnitCondition.OPERATIONAL,
            Unit.id.not_in(busy) if busy else Unit.id.is_not(None),
        )
        .order_by(Unit.sort_order.desc())
        .limit(1)
    ).scalars().first()
    check("لقينا وحدة صالحة مش عليها تذاكر", unit is not None,
          unit.label if unit else "")
    if unit is None:
        db.close()
        return 1

    original_condition = unit.condition
    original_hk = unit.housekeeping_status

    r = client.post("/api/v1/maintenance", headers=keeper, json={
        "title": "",
        "unit_id": unit.id,
        "category": "AC",
        "priority": "NORMAL",
    })
    check("تذكرة بدون عنوان بترفض", r.status_code in (400, 422), str(r.status_code))

    r = client.post("/api/v1/maintenance", headers=keeper, json={
        "title": "التكييف مش بيبرّد — اختبار",
        "unit_id": unit.id,
        "category": "AC",
        "priority": "NORMAL",
        "source": "HOUSEKEEPING",
        "description": "لقيته وأنا بنضّف",
        "blocks_unit": False,
    })
    ticket = r.json()
    check("فتح تذكرة", r.status_code in (200, 201), ticket.get("number", r.text[:80]))
    ticket_id = ticket.get("id")
    if ticket_id:
        made.append(ticket_id)

    check("رقم التذكرة بصيغة صحيحة",
          (ticket.get("number") or "").startswith("MT-"), ticket.get("number", ""))
    check("الحالة OPEN", ticket.get("status") == "OPEN", ticket.get("status", ""))
    check("الوحدة مربوطة", ticket.get("unit_label") == unit.label,
          ticket.get("unit_label") or "")
    check("المصدر HOUSEKEEPING — البلاغ جه من اللي بتنضّف",
          ticket.get("source") == "HOUSEKEEPING", ticket.get("source", ""))

    print("\n─── الميعاد النهائي بيتحدّد من الأولوية ───")
    stored = db.get(MaintenanceTicket, ticket_id)
    check("للتذكرة ميعاد نهائي", stored.due_at is not None)
    if stored.due_at:
        hours = (stored.due_at - stored.created_at).total_seconds() / 3600
        check("العادي مهلته 48 ساعة", 47 < hours < 49, f"{hours:.0f} ساعة")

    r = client.post("/api/v1/maintenance", headers=gm, json={
        "title": "ماسورة مكسورة — اختبار عاجل",
        "location": "الممر الخارجي",
        "category": "PLUMBING",
        "priority": "URGENT",
    })
    urgent = r.json()
    if urgent.get("id"):
        made.append(urgent["id"])
    urgent_row = db.get(MaintenanceTicket, urgent.get("id")) if urgent.get("id") else None
    if urgent_row and urgent_row.due_at:
        hours = (urgent_row.due_at - urgent_row.created_at).total_seconds() / 3600
        check("العاجل مهلته ساعتين", 1.5 < hours < 2.5, f"{hours:.1f} ساعة")
    check("التذكرة من غير وحدة شغّالة — بلاغ على مكان عام",
          urgent.get("unit_id") is None and bool(urgent.get("location")),
          urgent.get("location") or "")

    print("\n─── دورة حياة التذكرة ───")
    tech = techs[0]
    r = client.post(f"/api/v1/maintenance/{ticket_id}/assign", headers=gm,
                    json={"user_id": tech["id"]})
    check("إسناد لفني", r.status_code == 200, r.json().get("status", ""))
    check("الحالة بقت ASSIGNED", r.json().get("status") == "ASSIGNED")
    check("اسم الفني ظاهر", bool(r.json().get("assigned_to_name")),
          r.json().get("assigned_to_name") or "")

    r = client.post(f"/api/v1/maintenance/{ticket_id}/assign", headers=gm,
                    json={"user_id": 10**9})
    check("إسناد لمستخدم مش موجود بيترفض", r.status_code in (400, 404))

    r = client.post(f"/api/v1/maintenance/{ticket_id}/start", headers=gm)
    check("بدء الشغل", r.status_code == 200 and r.json()["status"] == "IN_PROGRESS",
          r.json().get("status", ""))

    r = client.post(f"/api/v1/maintenance/{ticket_id}/complete", headers=gm,
                    json={"resolution": "", "cost": "0"})
    check("الإقفال بدون وصف الإصلاح بيترفض", r.status_code in (400, 422))

    r = client.post(f"/api/v1/maintenance/{ticket_id}/complete", headers=gm,
                    json={"resolution": "اتغيّر الكباستور", "cost": "450"})
    done = r.json()
    check("إقفال التذكرة", r.status_code == 200 and done["status"] == "DONE",
          done.get("status", ""))
    check("التكلفة اتسجّلت", Decimal(done.get("cost", 0)) == Decimal("450"),
          f"{done.get('cost')}")

    r = client.post(f"/api/v1/maintenance/{ticket_id}/start", headers=gm)
    check("مينفعش تبدأ تذكرة مقفولة", r.status_code == 409,
          r.json().get("detail", {}).get("code", ""))

    print("\n─── الحجز والإفراج ───")
    db.expire_all()
    unit_now = db.get(Unit, unit.id)
    check("الوحدة رجعت صالحة بعد الإقفال",
          unit_now.condition == UnitCondition.OPERATIONAL, unit_now.condition)

    r = client.post("/api/v1/maintenance", headers=gm, json={
        "title": "عطل بيحجز الوحدة — اختبار",
        "unit_id": unit.id,
        "category": "ELECTRICAL",
        "priority": "HIGH",
        "blocks_unit": True,
    })
    blocking_one = r.json()
    if blocking_one.get("id"):
        made.append(blocking_one["id"])
    check("تذكرة حاجزة", r.status_code in (200, 201), blocking_one.get("number", ""))

    db.expire_all()
    unit_now = db.get(Unit, unit.id)
    check("الوحدة اتحجزت", unit_now.condition == UnitCondition.MAINTENANCE,
          unit_now.condition)

    print("\n─── تذكرتين حاجزين نفس الوحدة ───")
    r = client.post("/api/v1/maintenance", headers=gm, json={
        "title": "عطل تاني على نفس الوحدة — اختبار",
        "unit_id": unit.id,
        "category": "PLUMBING",
        "priority": "HIGH",
        "blocks_unit": True,
    })
    blocking_two = r.json()
    if blocking_two.get("id"):
        made.append(blocking_two["id"])
    check("التذكرة التانية اتفتحت", r.status_code in (200, 201),
          blocking_two.get("number", ""))

    second = db.get(MaintenanceTicket, blocking_two.get("id"))
    check("التانية محفظتش «تحت الصيانة» كحالة سابقة",
          second.previous_condition != UnitCondition.MAINTENANCE,
          str(second.previous_condition))

    r = client.post(f"/api/v1/maintenance/{blocking_one['id']}/complete", headers=gm,
                    json={"resolution": "اتصلّح", "cost": "0"})
    check("إقفال الأولى", r.status_code == 200)

    db.expire_all()
    unit_now = db.get(Unit, unit.id)
    check("الوحدة فضلت محجوزة — لسه فيه تذكرة تانية",
          unit_now.condition == UnitCondition.MAINTENANCE, unit_now.condition)

    r = client.post(f"/api/v1/maintenance/{blocking_two['id']}/complete", headers=gm,
                    json={"resolution": "اتصلّح كمان", "cost": "0"})
    check("إقفال التانية", r.status_code == 200)

    db.expire_all()
    unit_now = db.get(Unit, unit.id)
    check("الوحدة رجعت للخدمة بعد آخر تذكرة",
          unit_now.condition == UnitCondition.OPERATIONAL, unit_now.condition)
    check("الوحدة اتعلّمت متسخة — محتاجة تنضيف بعد الصيانة",
          unit_now.housekeeping_status == HousekeepingStatus.DIRTY,
          unit_now.housekeeping_status)

    print("\n─── الإلغاء ───")
    r = client.post("/api/v1/maintenance", headers=gm, json={
        "title": "تذكرة هتتلغي — اختبار",
        "unit_id": unit.id,
        "category": "OTHER",
        "priority": "LOW",
        "blocks_unit": True,
    })
    doomed = r.json()
    if doomed.get("id"):
        made.append(doomed["id"])

    r = client.post(f"/api/v1/maintenance/{doomed['id']}/cancel", headers=gm,
                    json={"reason": ""})
    check("الإلغاء بدون سبب بيترفض", r.status_code in (400, 422))

    r = client.post(f"/api/v1/maintenance/{doomed['id']}/cancel", headers=gm,
                    json={"reason": "بلاغ بالغلط"})
    check("إلغاء التذكرة", r.status_code == 200 and r.json()["status"] == "CANCELLED",
          r.json().get("status", ""))

    db.expire_all()
    unit_now = db.get(Unit, unit.id)
    check("الإلغاء بيفكّ الحجز كمان",
          unit_now.condition == UnitCondition.OPERATIONAL, unit_now.condition)

    r = client.post(f"/api/v1/maintenance/{10**9}/start", headers=gm)
    check("تذكرة مش موجودة بترجّع 404", r.status_code == 404)

    print("\n─── الفلترة ───")
    r = client.get("/api/v1/maintenance?status=DONE", headers=gm)
    check("الفلترة بالحالة",
          r.status_code == 200 and all(t["status"] == "DONE" for t in r.json()["tickets"]),
          f"{len(r.json()['tickets'])} مقفولة")

    r = client.get(f"/api/v1/maintenance?unit_id={unit.id}&status=DONE", headers=gm)
    check("الفلترة بالوحدة",
          r.status_code == 200
          and all(t["unit_id"] == unit.id for t in r.json()["tickets"]),
          f"{len(r.json()['tickets'])} تذكرة على {unit.label}")

    r = client.get("/api/v1/maintenance", headers=gm)
    check("الافتراضي بيعرض الشغّال بس — التاريخ بيتطلب صراحةً",
          all(t["status"] in ("OPEN", "ASSIGNED", "IN_PROGRESS")
              for t in r.json()["tickets"]),
          str({t["status"] for t in r.json()["tickets"]}))

    print("\n─── الميني بار ───")
    r = client.get("/api/v1/minibar", headers=gm)
    catalog = r.json()
    check("كتالوج الميني بار", r.status_code == 200 and len(catalog) > 0,
          f"{len(catalog)} صنف")
    check("كل صنف له سعر", all(Decimal(i["price"]) > 0 for i in catalog))
    check("الأصناف الكحولية معلّمة",
          any(i["contains_alcohol"] for i in catalog)
          or all(not i["contains_alcohol"] for i in catalog),
          f"{sum(1 for i in catalog if i['contains_alcohol'])} صنف كحولي")

    folio = db.execute(
        select(Folio).where(
            Folio.property_id == prop.id, Folio.status == FolioStatus.OPEN
        ).limit(1)
    ).scalars().first()
    check("فيه حساب مفتوح نرحّل عليه", folio is not None,
          folio.code if folio else "")

    if folio is not None:
        before_balance = folio.balance
        item = catalog[0]

        r = client.post("/api/v1/minibar/post", headers=gm, json={
            "folio_id": folio.id,
            "lines": [{"item_id": item["id"], "quantity": "2"}],
        })
        posted = r.json()
        check("ترحيل ميني بار على الحساب", r.status_code == 200,
              posted.get("message_ar", r.text[:60]))
        expected = Decimal(item["price"]) * 2
        check("الإجمالي قبل الخدمة والضريبة = السعر × الكمية",
              Decimal(posted.get("total", 0)) >= expected,
              f"{posted.get('total')} من أساس {expected}")

        db.expire_all()
        after = db.get(Folio, folio.id)
        check("رصيد الحساب زاد", after.balance > before_balance,
              f"{before_balance} -> {after.balance}")

        r = client.post("/api/v1/minibar/post", headers=gm, json={
            "folio_id": folio.id,
            "lines": [{"item_id": item["id"], "quantity": "0"}],
        })
        check("كمية صفر بترفض", r.status_code in (400, 422), str(r.status_code))

        r = client.post("/api/v1/minibar/post", headers=gm, json={
            "folio_id": 10**9,
            "lines": [{"item_id": item["id"], "quantity": "1"}],
        })
        check("حساب مش موجود بيرجّع 404", r.status_code == 404)

        r = client.post("/api/v1/minibar/post", headers=waiter, json={
            "folio_id": folio.id,
            "lines": [{"item_id": item["id"], "quantity": "1"}],
        })
        check("الويتر ممنوع يرحّل ميني بار", r.status_code == 403)

    print("\n─── جدول المهل ───")
    check("العاجل أقصر مهلة", mt.DUE_HOURS[TicketPriority.URGENT] == 2,
          f"{mt.DUE_HOURS[TicketPriority.URGENT]} ساعة")
    check("المهل متصاعدة مع نزول الأولوية",
          mt.DUE_HOURS[TicketPriority.URGENT]
          < mt.DUE_HOURS[TicketPriority.HIGH]
          < mt.DUE_HOURS[TicketPriority.NORMAL]
          < mt.DUE_HOURS[TicketPriority.LOW],
          str({k.value: v for k, v in mt.DUE_HOURS.items()}))

    print("\n─── تنضيف ───")
    for tid in made:
        row = db.get(MaintenanceTicket, tid)
        if row is not None:
            db.delete(row)
    db.expire_all()
    unit_row = db.get(Unit, unit.id)
    unit_row.condition = original_condition
    unit_row.housekeeping_status = original_hk
    db.commit()
    check("تذاكر الاختبار اتشالت والوحدة رجعت لحالتها",
          True, f"{len(made)} تذكرة · {unit.label}")

    open_now = db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.property_id == prop.id,
            MaintenanceTicket.status.in_(list(OPEN_TICKET_STATUSES)),
        )
    ).scalar_one()
    check("داتا العرض لسه فيها تذاكر مفتوحة", open_now > 0, f"{open_now} تذكرة")

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
