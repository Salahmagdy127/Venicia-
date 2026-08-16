"""يوم شغل ميداني للعرض — Field app demo day.

    python -m scripts.seed_field
    python -m scripts.seed_field --reset      # يمسح شغل اليوم ويبدأ من أول

بيبني جولة اليوم وبيمشّي عليها يوم واقعي: فيه مهام خلصت بصورها، وفيه
واحدة لسه شغّالة، وفيه أوضة النزيل معلّق عليها «عدم إزعاج» تلات مرات،
وفيه عطل اتبلّغ من التليفون وشال وحدة من البيع.

الصور اللي بتتولّد هنا **مش صور غرف** — دي مستطيلات ملوّنة عليها اسم
الوحدة والتوقيت. المقصود إثبات إن السلسلة كاملة شغّالة: الصورة اتاخدت
على التليفون، اترفعت ببصمتها، واتربطت بالمهمة، وبتتعرض للسوبرفايزر.
حط صور حقيقية بدل دي قبل أي عرض لعميل.
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.base import Base, SessionLocal, engine
from app.models.enums import (
    PhotoPhase,
    TaskEventKind,
    TaskKind,
    TaskStatus,
    TicketCategory,
    TicketPriority,
    TicketSource,
)
from app.models.organization import Property
from app.models.security import User
from app.models.tasks import FieldPhoto, HousekeepingTask, TaskEvent
from app.models.units import Unit
from app.services import housekeeping as hk
from app.services import maintenance as mt
from app.services import media

random.seed(20260816)

#: الأعطال اللي الهاوس كيبينج بتلاقيها فعلاً وهي بتنضّف
FINDINGS: list[tuple[str, TicketCategory, TicketPriority, bool]] = [
    ("التكييف بيسرّب مية على الأرض", TicketCategory.AC, TicketPriority.HIGH, True),
    ("مخلوط الدش مكسور", TicketCategory.PLUMBING, TicketPriority.NORMAL, False),
    ("لمبة الشرفة مش نوّرة", TicketCategory.ELECTRICAL, TicketPriority.LOW, False),
    ("ريموت التليفزيون ضايع", TicketCategory.APPLIANCE, TicketPriority.LOW, False),
]

BLOCK_REASONS = ["الباب مقفول والمفتاح مش معايا", "مفيش مية في الدور"]

NOTES = [
    "الشرفة كانت مليانة رمل — كنستها كمان",
    "المفارش الزيادة خلصت من العربية",
    "النزيل ساب حاجته، بلّغت الريسبشن",
]


def synthetic_photo(label: str, phase: PhotoPhase, moment: datetime) -> bytes:
    """صورة عرض — لون ثابت مشتق من اسم الوحدة عشان تفضل هي هي."""
    from PIL import Image, ImageDraw

    seed = int(hashlib.sha256(f"{label}{phase}".encode()).hexdigest()[:6], 16)
    if phase == PhotoPhase.BEFORE:
        base = (46 + seed % 30, 40 + seed % 24, 38 + seed % 20)      # داكنة
    else:
        base = (150 + seed % 60, 158 + seed % 50, 152 + seed % 46)   # فاتحة

    image = Image.new("RGB", (800, 600), base)
    draw = ImageDraw.Draw(image)
    for i in range(0, 600, 3):
        shade = int(18 * (i / 600))
        draw.line(
            [(0, i), (800, i)],
            fill=(
                max(0, min(255, base[0] - shade)),
                max(0, min(255, base[1] - shade)),
                max(0, min(255, base[2] - shade)),
            ),
        )
    ink = (240, 246, 244) if phase == PhotoPhase.BEFORE else (26, 42, 44)
    draw.rectangle([40, 40, 760, 190], outline=ink, width=3)
    draw.text((70, 78), label, fill=ink)
    draw.text((70, 112), "BEFORE" if phase == PhotoPhase.BEFORE else "AFTER", fill=ink)
    draw.text((70, 146), moment.strftime("%Y-%m-%d %H:%M"), fill=ink)

    import io

    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=78)
    return buffer.getvalue()


def attach(db, user: User, property_id: int, task: HousekeepingTask,
           phase: PhotoPhase, moment: datetime) -> None:
    data = synthetic_photo(task_label(db, task), phase, moment)
    stored = media.store(
        data, property_id=property_id, year=moment.year, month=moment.month
    )
    hk.attach_photo(
        db, user, property_id,
        client_uuid=f"demo:{task.id}:{phase}",
        phase=phase,
        stored_path=stored.path,
        thumb_path=stored.thumb_path,
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        content_type="image/jpeg",
        width=stored.width,
        height=stored.height,
        task_id=task.id,
        taken_at=moment,
        device_id=f"demo-{user.username}",
    )


_labels: dict[int, str] = {}


def task_label(db, task: HousekeepingTask) -> str:
    if task.unit_id not in _labels:
        unit = db.get(Unit, task.unit_id)
        _labels[task.unit_id] = unit.label if unit else str(task.unit_id)
    return _labels[task.unit_id]


def reset(db, property_id: int, business_date: date) -> int:
    """يمسح شغل اليوم — المهام وصورها وأحداثها والملفات."""
    tasks = db.execute(
        select(HousekeepingTask).where(
            HousekeepingTask.property_id == property_id,
            HousekeepingTask.task_date == business_date,
        )
    ).scalars().all()
    ids = [t.id for t in tasks]
    if not ids:
        return 0
    for photo in db.execute(
        select(FieldPhoto).where(FieldPhoto.task_id.in_(ids))
    ).scalars().all():
        for relative in (photo.storage_path, photo.thumb_path):
            if not relative:
                continue
            try:
                media.resolve(relative).unlink(missing_ok=True)
            except Exception:
                pass
    db.execute(delete(FieldPhoto).where(FieldPhoto.task_id.in_(ids)))
    db.execute(delete(TaskEvent).where(TaskEvent.task_id.in_(ids)))
    db.execute(delete(HousekeepingTask).where(HousekeepingTask.id.in_(ids)))
    db.commit()
    return len(ids)


def run(business_date: date | None = None, do_reset: bool = False) -> None:  # noqa: PLR0915
    Base.metadata.create_all(engine)
    db = SessionLocal()
    business_date = business_date or date.today()

    try:
        prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()

        if do_reset:
            removed = reset(db, prop.id, business_date)
            print(f"اتمسح شغل {business_date}: {removed} مهمة")

        print("توليد جولة اليوم...")
        result = hk.generate_day(db, prop.id, business_date)
        assigned = hk.auto_assign(db, prop.id, business_date)
        db.commit()
        print(f"  {result.created} مهمة جديدة · {result.existing} موجودة"
              f" · اتوزّعت على {len(set(assigned.values())) or '—'}")

        supervisor = db.execute(
            select(User).where(User.username == "samia")
        ).scalar_one_or_none()

        views = hk.day_tasks(db, prop.id, business_date)
        live = [v for v in views if v.task.status == TaskStatus.PENDING]
        if not live:
            print("مفيش مهام مفتوحة — شكل اليوم اتعمل خلاص.")
            return

        keepers = {
            u.id: u
            for u in db.execute(
                select(User).where(User.property_id == prop.id)
            ).scalars().all()
        }

        # اليوم بيتبني **بالنسبة للحظة دي** مش من الساعة ٨ الصبح: العرض
        # ممكن يتشغّل الساعة ٤ الفجر أو ١١ بالليل، ولازم اللوحة تبان
        # حيّة في الحالتين. فبنعتبر إن خمس ساعات شغل عدّت، وبنوزّع
        # الجولة عليها — اللي خلص خلص واللي لسه شغّال بيبان شغّال.
        now = hk.utcnow()
        clock = now - timedelta(hours=5)

        done = dnd = blocked = running = issues = photos = 0
        finding_pool = list(FINDINGS)

        for index, view in enumerate(live):
            task = view.task
            worker = keepers.get(task.assigned_to_user_id or 0) or supervisor
            if worker is None:
                continue

            start_at = clock + timedelta(minutes=index * 3 + random.randint(0, 6))
            if start_at > now:
                break   # الوقت الحالي عدّى — الباقي لسه في الطابور

            roll = random.random()

            # ٧٪ عدم إزعاج — نسبة واقعية في قرية فيها إقامات عيلات
            if roll < 0.07 and task.kind in (TaskKind.STAYOVER, TaskKind.DEPARTURE):
                attempts = random.choice([1, 1, 2, 3])
                for attempt in range(attempts):
                    hk.report_dnd(
                        db, task, worker,
                        at=start_at + timedelta(minutes=attempt * 55),
                        client_uuid=f"demo:dnd:{task.id}:{attempt}",
                        device_id=f"demo-{worker.username}",
                    )
                dnd += 1
                continue

            # ٣٪ متعذّرة
            if roll < 0.10:
                hk.block(
                    db, task, worker,
                    reason=random.choice(BLOCK_REASONS),
                    at=start_at,
                    client_uuid=f"demo:block:{task.id}",
                    device_id=f"demo-{worker.username}",
                )
                blocked += 1
                continue

            hk.start(
                db, task, worker, at=start_at,
                client_uuid=f"demo:start:{task.id}",
                device_id=f"demo-{worker.username}",
            )

            if task.photos_required:
                attach(db, worker, prop.id, task, PhotoPhase.BEFORE, start_at)
                photos += 1

            spent = timedelta(
                minutes=task.expected_minutes + random.randint(-8, 14)
            )
            end_at = start_at + spent

            # مهمة أو اتنين لسه شغّالة دلوقتي — اللوحة المفروض تبان حيّة
            if end_at > now or (running < 2 and random.random() < 0.05):
                running += 1
                continue

            # الهاوس كيبينج بتلاقي أعطال وهي بتنضّف
            if finding_pool and random.random() < 0.06:
                title, category, priority, blocks = finding_pool.pop()
                ticket = mt.open_ticket(
                    db, prop.id,
                    title=title,
                    unit_id=task.unit_id,
                    category=category,
                    priority=priority,
                    source=TicketSource.HOUSEKEEPING,
                    blocks_unit=blocks,
                    user=worker,
                )
                task.ticket_id = ticket.id
                db.add(
                    TaskEvent(
                        property_id=prop.id,
                        task_id=task.id,
                        ticket_id=ticket.id,
                        unit_id=task.unit_id,
                        kind=TaskEventKind.ISSUE_REPORTED,
                        client_uuid=f"demo:issue:{task.id}",
                        device_id=f"demo-{worker.username}",
                        happened_at=start_at + spent / 2,
                        received_at=start_at + spent / 2,
                        user_id=worker.id,
                        payload={"ticket": ticket.number},
                        note=title,
                    )
                )
                issues += 1

            if task.photos_required:
                attach(db, worker, prop.id, task, PhotoPhase.AFTER, end_at)
                photos += 1

            hk.complete(
                db, task, worker,
                at=end_at,
                client_uuid=f"demo:done:{task.id}",
                device_id=f"demo-{worker.username}",
                linen_changed=task.kind != TaskKind.STAYOVER or random.random() < 0.4,
                amenities_restocked=random.random() < 0.8,
                minibar_checked=random.random() < 0.5,
                note=random.choice(NOTES) if random.random() < 0.12 else None,
            )
            done += 1

            # السوبرفايزر بيفحص عيّنة — مش كل حاجة
            if supervisor is not None and random.random() < 0.3:
                hk.inspect(
                    db, task, supervisor,
                    score=random.choice([5, 5, 5, 4, 4, 2]),
                    at=end_at + timedelta(minutes=random.randint(10, 90)),
                    client_uuid=f"demo:check:{task.id}",
                )

            if index % 12 == 0:
                db.commit()

        db.commit()

        board = hk.board(db, prop.id, business_date)
        print("\n" + "─" * 52)
        print(f"  يوم {business_date}")
        print(f"  المهام            {board.total}")
        print(f"  خلصت              {board.done}  ·  اتفحصت {board.inspected}")
        print(f"  شغّالة دلوقتي     {board.in_progress}")
        print(f"  عدم إزعاج         {board.dnd}  ·  متعذّرة {board.blocked}")
        print(f"  في الطابور        {board.pending}")
        print(f"  محتاجة تدخّل      {board.escalated}")
        print(f"  الصور             {board.photos}")
        print(f"  الوقت             {board.minutes_worked} / {board.minutes_planned} دقيقة")
        print(f"  أعطال اتبلّغت      {issues}")
        print("─" * 52)
        print("\n  التطبيق:  /field")
        print("  دخول:     fatma / venicia2026")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="يوم شغل ميداني للعرض")
    parser.add_argument("--reset", action="store_true", help="امسح شغل اليوم الأول")
    parser.add_argument("--date", help="YYYY-MM-DD (افتراضي: النهاردة)")
    args = parser.parse_args()
    target = date.fromisoformat(args.date) if args.date else None
    run(target, args.reset)
    sys.exit(0)
