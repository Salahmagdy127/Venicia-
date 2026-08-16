"""اختبار تطبيق الميدان — Field app (housekeeper & technician) flow test.

    python -m scripts.test_field_flow

السويت دي بتحرس تلات وعود، وكلها بتخص **الأوفلاين**:

١. **العملية اللي وصلت مرتين بتتنفّذ مرة.** التليفون بيعيد الإرسال لما
   الشبكة تقطع في نص الرد، ولو السيرفر نفّذ تاني يبقى الغرفة اتقفلت
   مرتين والوقت اتحسب مرتين.

٢. **العملية الوحشة مبتوقّعش الدفعة.** الهاوس كيبر ممكن يبعت شغل ست
   ساعات في طلب واحد. لو عملية واحدة فيهم مرفوضة ورجّعت الدفعة كلها،
   شغل اليوم كله بيضيع.

٣. **وقت الشغل هو وقت التليفون مش وقت الوصول.** لو خلطناهم، تقرير
   «الغرفة اتنضفت الساعة كام» بيقيس الشبكة مش الشغل.

وكمان بتتأكد إن التطبيق **مش** بيفتح باب على النظام: الهاوس كيبر
مبيشوفش أسعار ولا حسابات ولا شاشات إدارية، حتى لو التليفون ضاع.

آمنة التكرار: كل حاجة بتتعمل على تاريخ بعيد مخصّص للاختبار، وبتتنضّف
في الآخر — الأرصدة والحالات بترجع زي ما كانت.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.main import app
from app.models.enums import (
    HousekeepingStatus,
    TaskKind,
    TaskStatus,
    TicketStatus,
    UnitCondition,
)
from app.models.maintenance import MaintenanceTicket
from app.models.organization import Property
from app.models.security import User
from app.models.tasks import FieldPhoto, HousekeepingTask, TaskEvent
from app.models.units import Unit, UnitStatusLog

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []

#: تاريخ مخصّص للاختبار — بعيد عن أي شغل حقيقي فمفيش تصادم
SANDBOX = date.today() + timedelta(days=400)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


#: عنوان مميّز لتذاكر الاختبار — عشان التنضيف يعرف يلاقيها
TEST_TICKET_TITLE = "[اختبار] التكييف بيسرّب مية"


def purge(db) -> tuple[int, int]:
    """يمسح أي أثر من تشغيلة سابقة — حتى لو التشغيلة دي وقعت في النص.

    التنضيف في الآخر مش كفاية: أول اختبار بيقع بيسيب صفوف وراه،
    والتشغيلة اللي بعدها بتقع على قيد التكرار بدل ما تختبر حاجة.
    فالتنضيف بيتعمل **قبل** كمان.
    """
    from app.services import media

    tasks = db.execute(
        select(HousekeepingTask).where(HousekeepingTask.task_date == SANDBOX)
    ).scalars().all()
    ids = [t.id for t in tasks]

    files = 0
    if ids:
        for photo in db.execute(
            select(FieldPhoto).where(FieldPhoto.task_id.in_(ids))
        ).scalars().all():
            for relative in (photo.storage_path, photo.thumb_path):
                if not relative:
                    continue
                try:
                    media.resolve(relative).unlink(missing_ok=True)
                    files += 1
                except Exception:
                    pass
        db.execute(delete(FieldPhoto).where(FieldPhoto.task_id.in_(ids)))
        db.execute(delete(TaskEvent).where(TaskEvent.task_id.in_(ids)))
    db.execute(delete(HousekeepingTask).where(HousekeepingTask.task_date == SANDBOX))

    stale = db.execute(
        select(MaintenanceTicket).where(MaintenanceTicket.title == TEST_TICKET_TITLE)
    ).scalars().all()
    stale_ids = [t.id for t in stale]
    stale_units = {t.unit_id for t in stale if t.unit_id}
    if stale_ids:
        db.execute(delete(TaskEvent).where(TaskEvent.ticket_id.in_(stale_ids)))
        db.execute(delete(FieldPhoto).where(FieldPhoto.ticket_id.in_(stale_ids)))
        db.execute(delete(MaintenanceTicket).where(MaintenanceTicket.id.in_(stale_ids)))

    # وحدة اتحجبت بتذكرة اختبار اتمسحت هتفضل محجوبة للأبد لو ماردّناهاش
    for unit_id in stale_units:
        row = db.get(Unit, unit_id)
        if row is None or row.condition != UnitCondition.MAINTENANCE:
            continue
        still = db.execute(
            select(MaintenanceTicket).where(
                MaintenanceTicket.unit_id == unit_id,
                MaintenanceTicket.blocks_unit.is_(True),
                MaintenanceTicket.status.notin_(
                    [TicketStatus.DONE, TicketStatus.CANCELLED]
                ),
            )
        ).scalars().first()
        if still is None:
            row.condition = UnitCondition.OPERATIONAL
            row.block_reason = None

    db.commit()
    return len(ids), files


def jpeg(color: tuple[int, int, int] = (40, 90, 100), size: int = 64) -> bytes:
    """صورة حقيقية صغيرة — الرفع بيتحقق من النوع فمينفعش بايتس عشوائية."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, "JPEG", quality=70)
    return buffer.getvalue()


def main() -> int:  # noqa: PLR0912, PLR0915
    client = TestClient(app)
    db = SessionLocal()
    created_tickets: list[int] = []
    restore_units: dict[int, tuple[HousekeepingStatus, UnitCondition]] = {}

    def login(username: str) -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": "venicia2026"}
        )
        assert r.status_code == 200, f"{username}: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    gm = login("gm")
    keeper = login("fatma")       # هاوس كيبر — التطبيق
    keeper2 = login("zeinab")     # هاوس كيبر تاني
    tech = login("mahmoud")       # فني صيانة
    supervisor = login("samia")   # سوبرفايزر
    cashier = login("sayed")      # مالوش دعوة بالتطبيق

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    users = {u.username: u for u in db.execute(select(User)).scalars().all()}

    left_tasks, left_files = purge(db)
    if left_tasks or left_files:
        print(f"  (نضّفت {left_tasks} مهمة و{left_files} ملف من تشغيلة سابقة)")

    # ═══════════════════════════════════════════════ الحزمة الأساسية
    print("\n─── حزمة العمل الأوفلاين ───")
    r = client.get("/api/v1/field/bootstrap", headers=keeper)
    boot = r.json()
    check("الهاوس كيبر بيسحب الحزمة", r.status_code == 200, boot.get("property_name_ar", ""))
    check("فيها كل الوحدات", len(boot["units"]) > 0, f"{len(boot['units'])} وحدة")
    check("فيها أنواع الأعطال", len(boot["ticket_categories"]) >= 8)
    check("فيها أسباب التعذّر", len(boot["block_reasons"]) >= 5)
    check("فيها سياسة عدم الإزعاج",
          boot["dnd_snooze_minutes"] > 0 and boot["dnd_escalate_after"] >= 2,
          f"تأجيل {boot['dnd_snooze_minutes']} د · تصعيد بعد {boot['dnd_escalate_after']}")
    check("فيها نسخة — التليفون بيعرف يحمّل تاني لما تتغيّر",
          bool(boot["version"]), boot["version"])
    check("الحزمة كلها في طلب واحد — مفيش عشر طلبات على شبكة قرية",
          all(k in boot for k in ("units", "minibar", "ticket_categories", "task_kinds")))

    leaked = {k for u in boot["units"] for k in u} & {"base_rate", "cost", "notes"}
    check("مفيش أسعار ولا تكاليف في حزمة التليفون", not leaked, str(sorted(leaked)) or "نضيفة")

    print("\n─── الكاشير مالوش دعوة بالتطبيق ───")
    r = client.get("/api/v1/field/bootstrap", headers=cashier)
    check("الكاشير ممنوع من الحزمة", r.status_code == 403, str(r.status_code))
    r = client.post("/api/v1/field/sync", json={"actions": []}, headers=cashier)
    check("الكاشير ممنوع من المزامنة", r.status_code == 403, str(r.status_code))

    print("\n─── الهاوس كيبر مبيوصلش للنظام الكبير ───")
    for path, name in [
        ("/api/v1/accounting/trial-balance", "ميزان المراجعة"),
        ("/api/v1/hr/payroll/runs", "المرتبات"),
        ("/api/v1/rate-plans", "خطط الأسعار"),
    ]:
        r = client.get(path, headers=keeper)
        check(f"ممنوع من {name}", r.status_code == 403, str(r.status_code))

    # ═══════════════════════════════════════════════ توليد جولة اليوم
    print("\n─── توليد الجولة ───")
    r = client.post("/api/v1/field/generate", json={"assign": True}, headers=gm)
    first = r.json()
    check("السوبرفايزر بيولّد الجولة", r.status_code == 200,
          f"{first['created']} جديدة · {first['existing']} موجودة")

    r = client.post("/api/v1/field/generate", json={"assign": True}, headers=gm)
    again = r.json()
    check("التوليد آمن التكرار — تشغيله تاني مبيكرّرش مهمة",
          again["created"] == 0 and again["existing"] >= first["created"],
          f"جديد {again['created']} · موجود {again['existing']}")

    r = client.post("/api/v1/field/generate", json={}, headers=keeper)
    check("الهاوس كيبر مبيقدرش يولّد جولة", r.status_code == 403, str(r.status_code))

    # ═══════════════════════════════════════════════════ لوحة اليوم
    print("\n─── جولتي ───")
    r = client.get("/api/v1/field/board", headers=keeper)
    board = r.json()
    check("الجولة بتنزل", r.status_code == 200, f"{len(board['tasks'])} مهمة")
    check("الاسم والدور ظاهرين", bool(board["user_name_ar"]),
          f"{board['user_name_ar']} — {board['role_ar']}")
    check("الهاوس كيبر بيشوف مهامه هو بس",
          all(t["assigned_to_user_id"] in (board["user_id"], None) for t in board["tasks"]))
    check("مرتّبة بالأولوية — المغادرات الأول",
          [t["priority"] for t in board["tasks"]]
          == sorted(t["priority"] for t in board["tasks"])),
    check("المغادرة بتطلب صور والإقامة اليومية لأ",
          all(t["photos_required"] for t in board["tasks"] if t["kind"] == "DEPARTURE")
          and all(not t["photos_required"] for t in board["tasks"] if t["kind"] == "STAYOVER"))
    check("الهاوس كيبر مش شايف تذاكر الصيانة", not board["can_fix"] or not board["tickets"])

    r = client.get("/api/v1/field/board", headers=keeper2)
    other = r.json()
    mine = {t["id"] for t in board["tasks"]}
    theirs = {t["id"] for t in other["tasks"]}
    check("كل واحد بيشوف جولته", not (mine & theirs),
          f"{len(mine)} / {len(theirs)} · مشترك {len(mine & theirs)}")

    r = client.get("/api/v1/field/supervisor", headers=supervisor)
    sup = r.json()
    check("السوبرفايزر بيشوف القرية كلها", r.status_code == 200 and sup["total"] >= len(mine),
          f"{sup['total']} مهمة · {sup['minutes_planned']} دقيقة مخطّطة")
    check("التوزيع متوازن بالوقت مش بالعدد", sup["unassigned"] == 0,
          f"غير موزّع {sup['unassigned']}")

    r = client.get("/api/v1/field/supervisor", headers=keeper)
    check("الهاوس كيبر ممنوع من لوحة السوبرفايزر", r.status_code == 403, str(r.status_code))

    # ═══════════════════════════════ مهمة اختبار على تاريخ الساندبوكس
    print("\n─── مهمة تحت السيطرة ───")
    unit = db.execute(
        select(Unit).where(
            Unit.property_id == prop.id,
            Unit.is_active.is_(True),
            Unit.condition == UnitCondition.OPERATIONAL,
        ).order_by(Unit.id)
    ).scalars().first()
    restore_units[unit.id] = (unit.housekeeping_status, unit.condition)

    task = HousekeepingTask(
        property_id=prop.id,
        unit_id=unit.id,
        task_date=SANDBOX,
        kind=TaskKind.DEPARTURE,
        status=TaskStatus.PENDING,
        priority=10,
        expected_minutes=45,
        photos_required=True,
        assigned_to_user_id=users["fatma"].id,
    )
    db.add(task)
    db.commit()
    check("مهمة اختبار اتعملت على تاريخ بعيد", task.id is not None, f"#{task.id} · {SANDBOX}")

    # ═══════════════════════════════════════════ القفل من غير صور
    print("\n─── الصور شرط مش اقتراح ───")
    r = client.post(
        "/api/v1/field/sync",
        json={"device_id": "test-phone", "actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.start", "task_id": task.id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {}},
        ]},
        headers=keeper,
    )
    check("البداية اتقبلت", r.json()["applied"] == 1, str(r.json()["results"][0]["outcome"]))
    db.refresh(task)
    check("المهمة بقت شغّالة", task.status == TaskStatus.IN_PROGRESS, task.status)
    db.refresh(unit)
    check("الوحدة اتحوّلت «جاري التنضيف» لوحدها",
          unit.housekeeping_status == HousekeepingStatus.CLEANING, unit.housekeeping_status)

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.complete", "task_id": task.id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {"linen_changed": True}},
        ]},
        headers=keeper,
    )
    result = r.json()["results"][0]
    check("القفل من غير صورة «قبل» بيترفض",
          result["outcome"] == "REJECTED" and result["code"] == "no_before_photo",
          result.get("message_ar", ""))
    db.refresh(task)
    check("المهمة فضلت مفتوحة", task.status == TaskStatus.IN_PROGRESS, task.status)

    # ═══════════════════════════════════════════════════ رفع الصور
    print("\n─── الصور ───")
    before_uuid, after_uuid = str(uuid.uuid4()), str(uuid.uuid4())
    r = client.post(
        "/api/v1/field/photos",
        files={"file": ("before.jpg", jpeg((80, 40, 40)), "image/jpeg")},
        data={"client_uuid": before_uuid, "phase": "BEFORE", "task_id": str(task.id),
              "device_id": "test-phone"},
        headers=keeper,
    )
    photo = r.json()
    check("صورة «قبل» اترفعت", r.status_code == 200 and photo["created"],
          f"before={photo['photo_before_count']}")
    check("عدّاد صور «قبل» زاد", photo["photo_before_count"] == 1)

    r = client.post(
        "/api/v1/field/photos",
        files={"file": ("before.jpg", jpeg((80, 40, 40)), "image/jpeg")},
        data={"client_uuid": before_uuid, "phase": "BEFORE", "task_id": str(task.id)},
        headers=keeper,
    )
    again_photo = r.json()
    check("إعادة رفع نفس الصورة مبتتعدّش مرتين",
          not again_photo["created"] and again_photo["photo_before_count"] == 1,
          f"created={again_photo['created']} · count={again_photo['photo_before_count']}")
    check("وبترجّع نفس الصورة مش نسخة", again_photo["photo"]["id"] == photo["photo"]["id"])

    r = client.get(photo["photo"]["url"], headers=keeper)
    check("الصورة بتتعرض", r.status_code == 200, r.headers.get("content-type", ""))
    if photo["photo"]["thumb_url"]:
        r = client.get(photo["photo"]["thumb_url"], headers=keeper)
        check("المصغّرة بتتعرض", r.status_code == 200, r.headers.get("content-type", ""))

    r = client.get(photo["photo"]["url"])
    check("الصورة محتاجة تسجيل دخول", r.status_code in (401, 403), str(r.status_code))

    r = client.post(
        "/api/v1/field/photos",
        files={"file": ("x.txt", b"not an image", "text/plain")},
        data={"client_uuid": str(uuid.uuid4()), "phase": "BEFORE", "task_id": str(task.id)},
        headers=keeper,
    )
    check("ملف مش صورة بيترفض", r.status_code == 400, str(r.status_code))

    r = client.post(
        "/api/v1/field/photos",
        files={"file": ("a.jpg", jpeg(), "image/jpeg")},
        data={"client_uuid": str(uuid.uuid4()), "phase": "AFTER", "task_id": "999999"},
        headers=keeper,
    )
    check("صورة لمهمة مش موجودة بترجّع 404", r.status_code == 404, str(r.status_code))

    r = client.post(
        "/api/v1/field/photos",
        files={"file": ("after.jpg", jpeg((40, 90, 60)), "image/jpeg")},
        data={"client_uuid": after_uuid, "phase": "AFTER", "task_id": str(task.id)},
        headers=keeper,
    )
    check("صورة «بعد» اترفعت", r.json()["photo_after_count"] == 1)

    # ═══════════════════════════════════════ القفل — والتكرار الآمن
    print("\n─── القفل وأمان التكرار ───")
    finish_uuid = str(uuid.uuid4())
    finish_at = datetime.now(timezone.utc)
    body = {
        "device_id": "test-phone",
        "actions": [
            {"uuid": finish_uuid, "type": "task.complete", "task_id": task.id,
             "at": finish_at.isoformat(),
             "payload": {"linen_changed": True, "amenities_restocked": True,
                         "note": "كله تمام"}},
        ],
    }
    r = client.post("/api/v1/field/sync", json=body, headers=keeper)
    first_sync = r.json()
    check("القفل اتقبل بعد الصور", first_sync["applied"] == 1,
          first_sync["results"][0]["outcome"])
    db.refresh(task)
    check("المهمة اتقفلت", task.status == TaskStatus.DONE, task.status)
    check("اللي اتعمل اتسجّل", task.linen_changed and task.amenities_restocked)
    first_completed = task.completed_at

    # نفس الجسم بالحرف — زي ما التليفون بيعمل لما الرد يضيع
    r = client.post("/api/v1/field/sync", json=body, headers=keeper)
    second = r.json()
    check("إعادة إرسال نفس العملية بترجع DUPLICATE مش بتنفّذ تاني",
          second["duplicates"] == 1 and second["applied"] == 0,
          second["results"][0]["outcome"])
    db.refresh(task)
    check("وقت القفل ما اتغيّرش", task.completed_at == first_completed,
          str(task.completed_at))

    events = db.execute(
        select(TaskEvent).where(
            TaskEvent.task_id == task.id, TaskEvent.kind == "COMPLETED"
        )
    ).scalars().all()
    check("وحدث القفل اتسجّل مرة واحدة بس", len(events) == 1, f"{len(events)} حدث")

    db.refresh(unit)
    check("الوحدة بقت نضيفة", unit.housekeeping_status == HousekeepingStatus.CLEAN,
          unit.housekeeping_status)

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.start", "task_id": task.id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {}},
        ]},
        headers=keeper,
    )
    conflict = r.json()["results"][0]
    check("مهمة مقفولة مبتفتحش تاني — بيرجع CONFLICT",
          conflict["outcome"] == "CONFLICT" and conflict["code"] == "closed",
          conflict.get("message_ar", ""))
    check("والرد بيقول الحالة الحالية عشان التليفون يصالح نسخته",
          conflict["status"] == "DONE", str(conflict["status"]))

    # ═══════════════════════════════ الدفعة: عملية وحشة مبتوقّعش الباقي
    print("\n─── دفعة فيها عملية وحشة ───")
    task_b = HousekeepingTask(
        property_id=prop.id, unit_id=unit.id, task_date=SANDBOX,
        kind=TaskKind.STAYOVER, status=TaskStatus.PENDING, priority=50,
        expected_minutes=15, photos_required=False,
        assigned_to_user_id=users["fatma"].id,
    )
    task_c = HousekeepingTask(
        property_id=prop.id, unit_id=unit.id, task_date=SANDBOX,
        kind=TaskKind.TURNDOWN, status=TaskStatus.PENDING, priority=60,
        expected_minutes=10, photos_required=False,
        assigned_to_user_id=users["fatma"].id,
    )
    db.add_all([task_b, task_c])
    db.commit()

    now = datetime.now(timezone.utc)
    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.start", "task_id": task_b.id,
             "at": now.isoformat(), "payload": {}},
            {"uuid": str(uuid.uuid4()), "type": "task.block", "task_id": task_c.id,
             "at": now.isoformat(), "payload": {"reason": ""}},          # مرفوضة
            {"uuid": str(uuid.uuid4()), "type": "task.nonsense", "task_id": task_b.id,
             "at": now.isoformat(), "payload": {}},                      # مش معروفة
            {"uuid": str(uuid.uuid4()), "type": "task.complete", "task_id": task_b.id,
             "at": now.isoformat(), "payload": {"linen_changed": True}},
        ]},
        headers=keeper,
    )
    batch = r.json()
    outcomes = [x["outcome"] for x in batch["results"]]
    check("العمليات السليمة عدّت رغم اللي وقع",
          batch["applied"] == 2 and batch["rejected"] == 2, str(outcomes))
    check("السبب الفاضي اترفض بسبب واضح",
          batch["results"][1]["code"] == "no_reason", batch["results"][1].get("message_ar", ""))
    check("العملية المجهولة اترفضت مش وقّعت السيرفر",
          batch["results"][2]["code"] == "unknown_action")
    db.refresh(task_b)
    db.refresh(task_c)
    check("المهمة السليمة اتقفلت", task_b.status == TaskStatus.DONE, task_b.status)
    check("المهمة اللي عمليتها اترفضت فضلت زي ما هي",
          task_c.status == TaskStatus.PENDING, task_c.status)
    check("الرد بيرجّع اللوحة كلها — التليفون بيستبدل نسخته بيها",
          "board" in batch and isinstance(batch["board"]["tasks"], list))

    # ═══════════════════════════════════════════════════ الوقت والأوفلاين
    print("\n─── الوقت وقت التليفون مش وقت الوصول ───")
    task_d = HousekeepingTask(
        property_id=prop.id, unit_id=unit.id, task_date=SANDBOX,
        kind=TaskKind.DEEP, status=TaskStatus.PENDING, priority=90,
        expected_minutes=90, photos_required=False,
        assigned_to_user_id=users["fatma"].id,
    )
    db.add(task_d)
    db.commit()

    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.start", "task_id": task_d.id,
             "at": two_hours_ago.isoformat(), "payload": {}},
        ]},
        headers=keeper,
    )
    check("عملية عمرها ساعتين اتقبلت", r.json()["applied"] == 1)
    db.refresh(task_d)
    drift = abs((task_d.started_at - two_hours_ago).total_seconds())
    check("وقت البداية اتسجّل بوقت التليفون مش بوقت الوصول",
          drift < 5, f"فرق {drift:.1f} ثانية")

    event = db.execute(
        select(TaskEvent).where(
            TaskEvent.task_id == task_d.id, TaskEvent.kind == "STARTED"
        )
    ).scalar_one()
    check("والسجل بيقول قد إيه فضل أوفلاين",
          6900 < event.offline_seconds < 7500, f"{event.offline_seconds} ثانية")
    check("ووقت الوصول متسجّل منفصل",
          event.received_at > event.happened_at, str(event.received_at))

    far_future = datetime.now(timezone.utc) + timedelta(days=3)
    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.note", "task_id": task_d.id,
             "at": far_future.isoformat(), "payload": {"note": "ساعة التليفون غلط"}},
        ]},
        headers=keeper,
    )
    check("عملية بتاريخ مستقبلي اتقبلت", r.json()["applied"] == 1)
    note_event = db.execute(
        select(TaskEvent).where(
            TaskEvent.task_id == task_d.id, TaskEvent.kind == "NOTE"
        )
    ).scalar_one()
    check("بس وقتها اتصحّح — ساعة تليفون غلط مبتعملش حدث في المستقبل",
          note_event.happened_at <= datetime.now(timezone.utc) + timedelta(seconds=5),
          str(note_event.happened_at))

    # ═══════════════════════════════════════════════════ عدم الإزعاج
    print("\n─── عدم الإزعاج ───")
    task_e = HousekeepingTask(
        property_id=prop.id, unit_id=unit.id, task_date=SANDBOX,
        kind=TaskKind.ARRIVAL_PREP, status=TaskStatus.PENDING, priority=20,
        expected_minutes=20, photos_required=False,
        assigned_to_user_id=users["fatma"].id,
    )
    db.add(task_e)
    db.commit()

    for attempt in range(1, 4):
        r = client.post(
            "/api/v1/field/sync",
            json={"actions": [
                {"uuid": str(uuid.uuid4()), "type": "task.dnd", "task_id": task_e.id,
                 "at": datetime.now(timezone.utc).isoformat(),
                 "payload": {"snooze_minutes": 60}},
            ]},
            headers=keeper,
        )
        assert r.json()["applied"] == 1, r.text
    db.refresh(task_e)
    check("«عدم إزعاج» بتتعدّ مش بتتلغي",
          task_e.dnd_attempts == 3 and task_e.status == TaskStatus.DND,
          f"{task_e.dnd_attempts} محاولات · {task_e.status}")
    check("المهمة بتتأجّل بميعاد رجوع", task_e.snoozed_until is not None,
          str(task_e.snoozed_until))
    check("والوحدة ما اتقالش عليها نضيفة",
          unit.housekeeping_status != HousekeepingStatus.INSPECTED)

    r = client.get(f"/api/v1/field/supervisor?date={SANDBOX}", headers=supervisor)
    sandbox_board = r.json()
    check("السوبرفايزر بيشوف المهمة المتصعّدة",
          sandbox_board["escalated"] >= 1, f"{sandbox_board['escalated']} متصعّدة")
    check("و«عدم إزعاج» ليها عدّاد لوحدها في اللوحة",
          sandbox_board["dnd"] >= 1, f"{sandbox_board['dnd']}")

    # ═══════════════════════════════════════════════════ مهمة مش بتاعتي
    print("\n─── مهمة حد تاني ───")
    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.start", "task_id": task_e.id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {}},
        ]},
        headers=keeper2,
    )
    forbidden = r.json()["results"][0]
    check("هاوس كيبر مبيقدرش يشتغل على مهمة حد تاني",
          forbidden["outcome"] == "REJECTED" and forbidden["code"] == "not_yours",
          forbidden.get("message_ar", ""))

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.skip", "task_id": task_e.id,
             "at": datetime.now(timezone.utc).isoformat(),
             "payload": {"reason": "مش هينفع النهاردة"}},
        ]},
        headers=keeper,
    )
    check("إلغاء المهمة مش من حق الهاوس كيبر",
          r.json()["results"][0]["code"] == "forbidden",
          r.json()["results"][0].get("message_ar", ""))

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.skip", "task_id": task_e.id,
             "at": datetime.now(timezone.utc).isoformat(),
             "payload": {"reason": "النزيل مدّد إقامته"}},
        ]},
        headers=supervisor,
    )
    check("السوبرفايزر بيقدر يلغيها", r.json()["applied"] == 1,
          r.json()["results"][0]["outcome"])

    # ═══════════════════════════════════════════ بلاغ عطل من التليفون
    print("\n─── بلاغ عطل بيشيل الوحدة من البيع ───")
    blocked_unit = db.execute(
        select(Unit).where(
            Unit.property_id == prop.id,
            Unit.is_active.is_(True),
            Unit.condition == UnitCondition.OPERATIONAL,
            Unit.id != unit.id,
        ).order_by(Unit.id)
    ).scalars().first()
    restore_units[blocked_unit.id] = (
        blocked_unit.housekeeping_status, blocked_unit.condition
    )

    task_f = HousekeepingTask(
        property_id=prop.id, unit_id=blocked_unit.id, task_date=SANDBOX,
        kind=TaskKind.DEPARTURE, status=TaskStatus.IN_PROGRESS, priority=10,
        expected_minutes=45, photos_required=False,
        assigned_to_user_id=users["fatma"].id,
    )
    db.add(task_f)
    db.commit()

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "issue.open", "task_id": task_f.id,
             "at": datetime.now(timezone.utc).isoformat(),
             "payload": {"title": TEST_TICKET_TITLE, "category": "AC",
                         "priority": "HIGH", "blocks_unit": True,
                         "description": "مية على الأرض تحت الوحدة الداخلية"}},
        ]},
        headers=keeper,
    )
    issue = r.json()["results"][0]
    check("البلاغ اتفتح من تليفون الهاوس كيبر",
          issue["outcome"] == "APPLIED" and issue["ticket_id"],
          f"تذكرة #{issue['ticket_id']}")
    ticket_id = issue["ticket_id"]
    created_tickets.append(ticket_id)

    ticket = db.get(MaintenanceTicket, ticket_id)
    db.refresh(ticket)
    check("مصدر البلاغ متسجّل إنه هاوس كيبينج", ticket.source == "HOUSEKEEPING",
          ticket.source)
    db.refresh(blocked_unit)
    check("والوحدة اتشالت من البيع فوراً — من غير ما حد يفتح شاشة",
          blocked_unit.condition == UnitCondition.MAINTENANCE, blocked_unit.condition)

    r = client.get("/api/v1/maintenance", headers=gm)
    numbers = {t["number"] for t in r.json()["tickets"]}
    check("والبلاغ ظهر في طابور الصيانة اللي المكتب بيشتغل عليه",
          ticket.number in numbers, ticket.number)

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "issue.open", "task_id": task_f.id,
             "at": datetime.now(timezone.utc).isoformat(),
             "payload": {"title": "  ", "category": "AC"}},
        ]},
        headers=keeper,
    )
    check("بلاغ من غير عنوان بيترفض",
          r.json()["results"][0]["code"] == "no_title",
          r.json()["results"][0].get("message_ar", ""))

    # ═══════════════════════════════════════════════════ تليفون الفني
    print("\n─── تليفون الفني ───")
    r = client.get("/api/v1/field/board", headers=tech)
    tech_board = r.json()
    check("الفني بيفتح على الأعطال", r.status_code == 200 and tech_board["can_fix"],
          f"{len(tech_board['tickets'])} تذكرة · {tech_board['role_ar']}")
    check("الفني مالوش جولة تنضيف", not tech_board["can_clean"])
    check("والتذكرة الجديدة وصلته",
          any(t["id"] == ticket_id for t in tech_board["tickets"]))
    urgent_first = [t["priority"] for t in tech_board["tickets"]]
    order = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
    check("العاجل الأول — مش ترتيب أبجدي",
          urgent_first == sorted(urgent_first, key=lambda p: order.get(p, 4)),
          str(urgent_first[:5]))

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "ticket.start", "ticket_id": ticket_id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {}},
        ]},
        headers=tech,
    )
    check("الفني بيبدأ التذكرة من مكانه", r.json()["applied"] == 1,
          r.json()["results"][0]["outcome"])
    db.refresh(ticket)
    check("والتذكرة اتسجّلت باسمه",
          ticket.assigned_to_user_id == users["mahmoud"].id
          and ticket.status == TicketStatus.IN_PROGRESS, ticket.status)

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "ticket.complete", "ticket_id": ticket_id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {"resolution": ""}},
        ]},
        headers=tech,
    )
    check("القفل من غير وصف اللي اتعمل بيترفض",
          r.json()["results"][0]["code"] == "no_resolution")

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "ticket.complete", "ticket_id": ticket_id,
             "at": datetime.now(timezone.utc).isoformat(),
             "payload": {"resolution": "غيّرت خرطوم الصرف ونضّفت المصفاة",
                         "cost": "180.00"}},
        ]},
        headers=tech,
    )
    check("الفني قفل التذكرة", r.json()["applied"] == 1,
          r.json()["results"][0]["outcome"])
    db.refresh(ticket)
    db.refresh(blocked_unit)
    check("الوحدة رجعت للبيع لوحدها",
          blocked_unit.condition == UnitCondition.OPERATIONAL, blocked_unit.condition)
    check("ورجعت **متسخة** — الفني كان جوّه فمحتاجة مرور هاوس كيبينج",
          blocked_unit.housekeeping_status == HousekeepingStatus.DIRTY,
          blocked_unit.housekeeping_status)
    check("وتكلفة القطع اتسجّلت", float(ticket.cost) == 180.0, str(ticket.cost))

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "ticket.start", "ticket_id": ticket_id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {}},
        ]},
        headers=tech,
    )
    check("تذكرة مقفولة مبتفتحش تاني",
          r.json()["results"][0]["code"] == "closed",
          r.json()["results"][0].get("message_ar", ""))

    print("\n─── الفني مالوش دعوة بالتنضيف ───")
    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.start", "task_id": task_c.id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {}},
        ]},
        headers=tech,
    )
    check("الفني مبيقدرش يقفل مهمة تنضيف حد تاني",
          r.json()["results"][0]["outcome"] in ("REJECTED", "CONFLICT"),
          r.json()["results"][0].get("code", ""))

    # ═══════════════════════════════════════════════════ فحص السوبرفايزر
    print("\n─── الفحص ───")
    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.inspect", "task_id": task.id,
             "at": datetime.now(timezone.utc).isoformat(),
             "payload": {"score": 5, "note": "شغل نضيف"}},
        ]},
        headers=supervisor,
    )
    check("السوبرفايزر بيفحص", r.json()["applied"] == 1, r.json()["results"][0]["outcome"])
    db.refresh(task)
    db.refresh(unit)
    check("المهمة بقت مفحوصة", task.status == TaskStatus.INSPECTED, task.status)
    check("والوحدة بقت «تم الفحص»",
          unit.housekeeping_status == HousekeepingStatus.INSPECTED,
          unit.housekeeping_status)

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.inspect", "task_id": task_b.id,
             "at": datetime.now(timezone.utc).isoformat(),
             "payload": {"score": 2, "note": "الحمام لسه فيه شعر"}},
        ]},
        headers=supervisor,
    )
    check("الفحص الراسب اتسجّل", r.json()["applied"] == 1)
    db.refresh(task_b)
    db.refresh(unit)
    check("المهمة رجعت للطابور مش اتقفلت", task_b.status == TaskStatus.REJECTED,
          task_b.status)
    check("والوحدة رجعت متسخة — حكم «نضيفة» اتلغى",
          unit.housekeeping_status == HousekeepingStatus.DIRTY,
          unit.housekeeping_status)
    check("ووقت القفل اتشال — لأن المهمة مخلصتش",
          task_b.completed_at is None)

    r = client.post(
        "/api/v1/field/sync",
        json={"actions": [
            {"uuid": str(uuid.uuid4()), "type": "task.inspect", "task_id": task_d.id,
             "at": datetime.now(timezone.utc).isoformat(), "payload": {"score": 5}},
        ]},
        headers=keeper,
    )
    check("الهاوس كيبر مبيفحصش شغل نفسه",
          r.json()["results"][0]["code"] == "forbidden",
          r.json()["results"][0].get("message_ar", ""))

    # ═══════════════════════════════════════════════════════ السجل
    print("\n─── سجل المهمة ───")
    r = client.get(f"/api/v1/field/tasks/{task.id}/timeline", headers=supervisor)
    timeline = r.json()
    kinds = [e["kind"] for e in timeline]
    check("السجل بيقول اللي حصل بالترتيب", r.status_code == 200, " → ".join(kinds))
    check("فيه البداية والصور والقفل والفحص",
          {"STARTED", "PHOTO", "COMPLETED", "INSPECTED"} <= set(kinds), str(sorted(set(kinds))))
    check("مرتّب بوقت الحدث",
          [e["happened_at"] for e in timeline]
          == sorted(e["happened_at"] for e in timeline))
    check("وكل حدث معاه وقت وصوله كمان",
          all(e["received_at"] >= e["happened_at"] for e in timeline))

    r = client.get(f"/api/v1/field/tasks/{task.id}/timeline", headers=keeper)
    check("الهاوس كيبر ممنوع من السجل الكامل", r.status_code == 403, str(r.status_code))

    # ═══════════════════════════════════════════════════════ الإسناد
    print("\n─── إسناد يدوي ───")
    r = client.patch(
        f"/api/v1/field/tasks/{task_c.id}/assign",
        json={"user_id": users["zeinab"].id},
        headers=supervisor,
    )
    check("السوبرفايزر بينقل مهمة لحد تاني", r.status_code == 200,
          r.json().get("assigned_to_name", ""))
    check("والاسم الجديد بيظهر", r.json()["assigned_to_user_id"] == users["zeinab"].id)

    r = client.patch(
        f"/api/v1/field/tasks/{task_c.id}/assign",
        json={"user_id": users["zeinab"].id},
        headers=keeper,
    )
    check("الهاوس كيبر مبينقلش مهام", r.status_code == 403, str(r.status_code))

    r = client.patch(
        "/api/v1/field/tasks/999999/assign",
        json={"user_id": users["zeinab"].id},
        headers=supervisor,
    )
    check("مهمة مش موجودة بترجّع 404", r.status_code == 404, str(r.status_code))

    # ═══════════════════════════════════════════════════════ التنضيف
    print("\n─── التنضيف بعد الاختبار ───")
    removed_tasks, removed_files = purge(db)

    for unit_id, (hk_status, condition) in restore_units.items():
        row = db.get(Unit, unit_id)
        if row is not None:
            row.housekeeping_status = hk_status
            row.condition = condition
    db.execute(
        delete(UnitStatusLog).where(
            UnitStatusLog.unit_id.in_(list(restore_units)),
            UnitStatusLog.source == "FIELD_APP",
        )
    )
    db.commit()

    left = db.execute(
        select(HousekeepingTask).where(HousekeepingTask.task_date == SANDBOX)
    ).scalars().all()
    check("مهام الاختبار اتمسحت", not left, f"{removed_tasks} مهمة · {removed_files} ملف")
    check("حالات الوحدات رجعت زي ما كانت",
          all(
              db.get(Unit, uid).housekeeping_status == state
              and db.get(Unit, uid).condition == condition
              for uid, (state, condition) in restore_units.items()
          ))
    left_tickets = db.execute(
        select(MaintenanceTicket).where(MaintenanceTicket.id.in_(created_tickets or [0]))
    ).scalars().all()
    check("تذاكر الاختبار اتمسحت", not left_tickets)

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
