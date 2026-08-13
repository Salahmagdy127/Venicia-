"""الحالة اللحظية للعرض — Live-state seeder.

الداتا التاريخية بتخلّي الأرقام حقيقية، بس الشاشات التشغيلية بتفتح فاضية:
الصالة من غير أوردرات مفتوحة، وشاشة الحجوزات من غير حجوزات تستنى تخصيص.
السكربت ده بيحطّ الحالة اللحظية اللي بتخلي الشاشات تبان زي ما هي وسط اليوم.

    python -m scripts.seed_live

بيشتغل أكتر من مرة من غير ما يكرّر: لو لقى أوردرات مفتوحة بالفعل بيسيبها.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.base import SessionLocal
from app.models.enums import (
    BLOCKING_RESERVATION_STATUSES,
    OutletType,
    PosOrderStatus,
)
from app.models.organization import Property
from app.models.pos import MenuItem, Outlet, PosOrder, PosTable
from app.models.reservations import ReservationUnit
from app.models.security import User
from app.services import pos as pos_svc

RNG = random.Random(20260812)

#: نسبة الطاولات المشغولة في كل منفذ — أرقام وقت الغدا في قرية على البحيرة
BUSY_RATIO = 0.45
#: كام حجز قادم نسيبه من غير تخصيص وحدة عشان شريط «لم تُخصص» يبان
UNASSIGNED_TARGET = 5


def pick_property(db: Session) -> Property:
    prop = db.execute(select(Property).order_by(Property.id)).scalars().first()
    if prop is None:
        raise SystemExit("مفيش منشأة — شغّل scripts.seed_master الأول")
    return prop


def pick_waiter(db: Session, prop: Property) -> User:
    user = db.execute(
        select(User).where(User.property_id == prop.id, User.username == "sayed")
    ).scalar_one_or_none()
    if user is None:
        user = db.execute(select(User).order_by(User.id)).scalars().first()
    if user is None:
        raise SystemExit("مفيش مستخدمين — شغّل scripts.seed_master الأول")
    return user


def open_live_orders(db: Session, prop: Property, waiter: User) -> tuple[int, int]:
    """يفتح أوردرات على جزء من طاولات كل منفذ، وبيبعت نص الأصناف للمطبخ."""
    existing = db.execute(
        select(func.count(PosOrder.id)).where(
            PosOrder.property_id == prop.id,
            PosOrder.status.in_(
                [PosOrderStatus.OPEN, PosOrderStatus.SENT, PosOrderStatus.SERVED]
            ),
        )
    ).scalar_one()
    if existing:
        return 0, 0

    outlets = db.execute(
        select(Outlet).where(Outlet.property_id == prop.id, Outlet.is_active.is_(True))
    ).scalars().all()

    orders = lines = 0
    for outlet in outlets:
        if outlet.outlet_type == OutletType.SPA:
            continue

        tables = db.execute(
            select(PosTable)
            .where(PosTable.outlet_id == outlet.id, PosTable.is_active.is_(True))
            .order_by(PosTable.id)
        ).scalars().all()
        if not tables:
            continue

        items = db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.outlets))
            .where(
                MenuItem.property_id == prop.id,
                MenuItem.is_available.is_(True),
                MenuItem.is_out_of_stock.is_(False),
            )
        ).scalars().unique().all()
        menu = [i for i in items if any(o.id == outlet.id for o in i.outlets)]
        if not menu:
            continue

        busy = RNG.sample(tables, k=max(1, round(len(tables) * BUSY_RATIO)))
        for table in busy:
            order = pos_svc.open_order(
                db,
                property_id=prop.id,
                outlet_id=outlet.id,
                user_id=waiter.id,
                table_id=table.id,
                covers=RNG.randint(1, max(1, table.seats)),
            )
            for item in RNG.sample(menu, k=min(len(menu), RNG.randint(2, 5))):
                pos_svc.add_line(
                    db,
                    order.id,
                    menu_item_id=item.id,
                    quantity=Decimal(RNG.choice([1, 1, 1, 2])),
                )
                lines += 1

            # تلت الطاولات لسه بتطلب، والباقي أكلهم في المطبخ
            if RNG.random() > 0.34:
                pos_svc.send_to_kitchen(db, order.id)
            orders += 1

    return orders, lines


def unassign_upcoming(db: Session, prop: Property) -> int:
    """بيسيب حجوزات قادمة من غير وحدة — زي اللي بيجي من القنوات ولسه محتاج تخصيص."""
    today = date.today()
    already = db.execute(
        select(func.count(ReservationUnit.id)).where(
            ReservationUnit.property_id == prop.id,
            ReservationUnit.unit_id.is_(None),
            ReservationUnit.arrival_date >= today,
            ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
        )
    ).scalar_one()
    if already >= UNASSIGNED_TARGET:
        return 0

    candidates = db.execute(
        select(ReservationUnit)
        .where(
            ReservationUnit.property_id == prop.id,
            ReservationUnit.unit_id.isnot(None),
            ReservationUnit.arrival_date > today + timedelta(days=1),
            ReservationUnit.arrival_date <= today + timedelta(days=10),
            ReservationUnit.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
        )
        .order_by(ReservationUnit.arrival_date)
        .limit(60)
    ).scalars().all()
    if not candidates:
        return 0

    chosen = RNG.sample(candidates, k=min(UNASSIGNED_TARGET - already, len(candidates)))
    for line in chosen:
        line.unit_id = None
    return len(chosen)


def run() -> None:
    db = SessionLocal()
    try:
        prop = pick_property(db)
        waiter = pick_waiter(db, prop)

        orders, lines = open_live_orders(db, prop, waiter)
        unassigned = unassign_upcoming(db, prop)
        db.commit()

        print("─" * 46)
        print(f"  أوردرات مفتوحة على الطاولات   {orders:>6,}")
        print(f"  أصناف عليها                   {lines:>6,}")
        print(f"  حجوزات بقت من غير تخصيص       {unassigned:>6,}")
        print("─" * 46)
        if orders == 0:
            print("  (فيه أوردرات مفتوحة بالفعل — مش هيتكرّر)")
    finally:
        db.close()


if __name__ == "__main__":
    run()
