"""البيانات الأساسية لقرية فينيسيا — Master data seed.

بينشئ المنشأة والصلاحيات والمستخدمين وفئات الوحدات والوحدات وخطط الأسعار
والمواسم ومنافذ البيع والمنيو. آمن التكرار: لو اتشغّل تاني مبيكرّرش حاجة.

    python -m scripts.seed_master
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.base import Base, SessionLocal, engine
from app.models.channels import Channel, ChannelMapping
from app.models.maintenance import MinibarItem
from app.models.enums import (
    AdjustmentMethod,
    BookingSource,
    HousekeepingStatus,
    MealPlan,
    OutletType,
    RateRuleType,
    UnitCondition,
    UnitKind,
)
from app.models.organization import Property
from app.models.pos import (
    KitchenStation,
    MenuCategory,
    MenuItem,
    Outlet,
    PosTable,
    menu_item_outlet,
)
from app.models.rates import CancellationPolicy, RatePlan, RateRule, Season
from app.models.security import Permission, Role, User
from app.models.units import Unit, UnitCategory
from app.services import availability as av
from app.services import pricing

# ═══════════════════════════════════════════════════════════ المنشأة
def create_property(db: Session) -> Property:
    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one_or_none()
    if prop:
        return prop

    prop = Property(
        code="VNC",
        name_ar="قرية فينيسيا",
        name_en="Venicia Resort",
        legal_name="شركة فينيسيا للاستثمار السياحي",
        country="EG",
        city="الفيوم",
        address="طريق البحيرة، الفيوم، جمهورية مصر العربية",
        phone="+20 84 123 4567",
        email="reservations@venicia.example",
        website="https://venicia.example",
        timezone="Africa/Cairo",
        currency="EGP",
        default_locale="ar",
        tax_registration_number="123-456-789",
        commercial_register="98765",
        vat_percent=Decimal("14"),
        service_charge_percent=Decimal("12"),
        municipality_tax_percent=Decimal("0"),
        service_charge_before_tax=True,
        eta_enabled=True,
        eta_branch_code="0",
        eta_activity_code="5510",
        business_day_start_hour=6,
        check_in_time="14:00",
        check_out_time="12:00",
        overbooking_percent=Decimal("0"),
    )
    db.add(prop)
    db.flush()
    return prop


# ═══════════════════════════════════════════════════ الصلاحيات والأدوار
PERMISSIONS: list[tuple[str, str, str, str]] = [
    # (code, module, name_ar, name_en)
    ("reservation.view", "reservation", "عرض الحجوزات", "View reservations"),
    ("reservation.create", "reservation", "إنشاء حجز", "Create reservation"),
    ("reservation.edit", "reservation", "تعديل حجز", "Edit reservation"),
    ("reservation.cancel", "reservation", "إلغاء حجز", "Cancel reservation"),
    ("reservation.checkin", "reservation", "تسجيل النزول", "Check in"),
    ("reservation.checkout", "reservation", "تسجيل المغادرة", "Check out"),
    ("reservation.assign_unit", "reservation", "تخصيص وحدة", "Assign unit"),
    ("rate.view", "rate", "عرض الأسعار", "View rates"),
    ("rate.edit", "rate", "تعديل الأسعار", "Edit rates"),
    ("rate.override", "rate", "تعديل سعر يدوي", "Override rate"),
    ("folio.view", "folio", "عرض حساب النزيل", "View folio"),
    ("folio.post", "folio", "ترحيل حركة", "Post charge"),
    ("folio.void", "folio", "إلغاء حركة", "Void charge"),
    ("folio.transfer", "folio", "تحويل حركة", "Transfer charge"),
    ("folio.split", "folio", "تقسيم الفاتورة", "Split folio"),
    ("folio.settle", "folio", "تحصيل", "Settle folio"),
    ("pos.view", "pos", "عرض الكاشير", "View POS"),
    ("pos.order", "pos", "إنشاء أوردر", "Create order"),
    ("pos.void", "pos", "إلغاء أوردر", "Void order"),
    ("pos.discount", "pos", "منح خصم", "Apply discount"),
    ("pos.discount.approve", "pos", "اعتماد خصم", "Approve discount"),
    ("pos.room_charge", "pos", "ترحيل على الغرفة", "Room charge"),
    ("pos.shift.close", "pos", "تقفيل الوردية", "Close shift"),
    ("housekeeping.view", "housekeeping", "عرض الهاوس كيبينج", "View housekeeping"),
    ("housekeeping.update", "housekeeping", "تحديث حالة الوحدة", "Update unit status"),
    ("guest.view", "guest", "عرض النزلاء", "View guests"),
    ("guest.edit", "guest", "تعديل بيانات النزيل", "Edit guest"),
    ("report.operational", "report", "التقارير التشغيلية", "Operational reports"),
    ("report.financial", "report", "التقارير المالية", "Financial reports"),
    ("report.audit", "report", "سجل التدقيق", "Audit trail"),
    ("invoice.issue", "invoice", "إصدار فاتورة", "Issue invoice"),
    ("invoice.cancel", "invoice", "إلغاء فاتورة", "Cancel invoice"),
    ("nightaudit.run", "nightaudit", "تشغيل النايت أوديت", "Run night audit"),
    ("channel.view", "channel", "عرض القنوات", "View channels"),
    ("channel.manage", "channel", "إدارة القنوات والربط", "Manage channels & mapping"),
    ("maintenance.view", "maintenance", "عرض بلاغات الصيانة", "View maintenance tickets"),
    ("maintenance.manage", "maintenance", "إدارة بلاغات الصيانة", "Manage maintenance tickets"),
    ("admin.users", "admin", "إدارة المستخدمين", "Manage users"),
    ("admin.settings", "admin", "إعدادات النظام", "System settings"),
]

ROLES: list[tuple[str, str, str, int, list[str]]] = [
    # (code, name_ar, name_en, max_discount_percent, permission codes)
    (
        "OWNER",
        "المالك",
        "Owner",
        100,
        ["*"],
    ),
    (
        "GM",
        "المدير العام",
        "General Manager",
        50,
        ["*"],
    ),
    (
        "FRONT_DESK",
        "استقبال",
        "Front Desk",
        5,
        [
            "reservation.view", "reservation.create", "reservation.edit",
            "reservation.checkin", "reservation.checkout", "reservation.assign_unit",
            "rate.view", "folio.view", "folio.post", "folio.settle",
            "housekeeping.view", "guest.view", "guest.edit",
            "invoice.issue", "report.operational",
        ],
    ),
    (
        "FRONT_OFFICE_MANAGER",
        "مدير الاستقبال",
        "Front Office Manager",
        20,
        [
            "reservation.view", "reservation.create", "reservation.edit",
            "reservation.cancel", "reservation.checkin", "reservation.checkout",
            "reservation.assign_unit", "rate.view", "rate.override",
            "folio.view", "folio.post", "folio.void", "folio.transfer",
            "folio.split", "folio.settle", "housekeeping.view",
            "housekeeping.update", "guest.view", "guest.edit",
            "invoice.issue", "invoice.cancel", "report.operational",
            "channel.view", "maintenance.view", "maintenance.manage",
        ],
    ),
    (
        "CASHIER",
        "كاشير",
        "Cashier",
        0,
        ["pos.view", "pos.order", "pos.room_charge", "folio.view", "invoice.issue"],
    ),
    (
        "WAITER",
        "ويتر",
        "Waiter",
        0,
        ["pos.view", "pos.order"],
    ),
    (
        "RESTAURANT_MANAGER",
        "مدير المطعم",
        "Restaurant Manager",
        25,
        [
            "pos.view", "pos.order", "pos.void", "pos.discount",
            "pos.discount.approve", "pos.room_charge", "pos.shift.close",
            "report.operational",
        ],
    ),
    (
        "HOUSEKEEPING",
        "سوبرفايزر هاوس كيبينج",
        "Housekeeping Supervisor",
        0,
        # الهاوس كيبينج بتلاقي الأعطال وهي بتنضّف — فبتفتح البلاغ بنفسها
        [
            "housekeeping.view", "housekeeping.update", "reservation.view",
            "maintenance.view", "maintenance.manage",
        ],
    ),
    (
        "ACCOUNTANT",
        "محاسب",
        "Accountant",
        0,
        [
            "folio.view", "report.financial", "report.operational", "report.audit",
            "invoice.issue", "invoice.cancel", "nightaudit.run", "channel.view",
        ],
    ),
]


def create_security(db: Session, prop: Property) -> dict[str, Role]:
    existing_perms = {
        p.code: p for p in db.execute(select(Permission)).scalars().all()
    }
    for code, module, name_ar, name_en in PERMISSIONS:
        if code not in existing_perms:
            perm = Permission(code=code, module=module, name_ar=name_ar, name_en=name_en)
            db.add(perm)
            existing_perms[code] = perm
    db.flush()

    # صلاحية شاملة لكل موديول — تسهّل أدوار الإدارة
    for module in sorted({m for _, m, _, _ in PERMISSIONS}):
        wildcard = f"{module}.*"
        if wildcard not in existing_perms:
            perm = Permission(
                code=wildcard,
                module=module,
                name_ar=f"كل صلاحيات {module}",
                name_en=f"All {module} permissions",
            )
            db.add(perm)
            existing_perms[wildcard] = perm
    db.flush()

    roles: dict[str, Role] = {
        r.code: r for r in db.execute(select(Role)).scalars().all()
    }
    for code, name_ar, name_en, max_discount, perm_codes in ROLES:
        role = roles.get(code)
        if role is None:
            role = Role(
                code=code,
                name_ar=name_ar,
                name_en=name_en,
                is_system=True,
                max_discount_percent=max_discount,
            )
            db.add(role)
            roles[code] = role

        # الصلاحيات بتتظبّط في كل تشغيل مش عند الإنشاء بس: أي موديول جديد
        # بيتضاف بعدين لازم يوصل للأدوار الموجودة، وإلا المالك نفسه يلاقي
        # شاشة جديدة مقفولة في وشه.
        wanted = (
            list(existing_perms.values())
            if perm_codes == ["*"]
            else [existing_perms[c] for c in perm_codes if c in existing_perms]
        )
        have = {p.code for p in role.permissions}
        for perm in wanted:
            if perm.code not in have:
                role.permissions.append(perm)
    db.flush()
    return roles


USERS: list[tuple[str, str, str, str, str]] = [
    # (username, full_name_ar, full_name_en, role_code, password)
    ("owner", "محمود الشربيني", "Mahmoud El-Sherbiny", "OWNER", "venicia2026"),
    ("gm", "هالة عبد العزيز", "Hala Abdelaziz", "GM", "venicia2026"),
    ("ahmed", "أحمد شريف", "Ahmed Sherif", "FRONT_DESK", "venicia2026"),
    ("mona", "منى رأفت", "Mona Raafat", "FRONT_DESK", "venicia2026"),
    ("nourhan", "نورهان سامي", "Nourhan Samy", "FRONT_OFFICE_MANAGER", "venicia2026"),
    ("karim", "كريم فتحي", "Karim Fathy", "WAITER", "venicia2026"),
    ("sayed", "سيد عبد الله", "Sayed Abdallah", "CASHIER", "venicia2026"),
    ("tarek", "طارق منير", "Tarek Mounir", "RESTAURANT_MANAGER", "venicia2026"),
    ("samia", "سامية جمال", "Samia Gamal", "HOUSEKEEPING", "venicia2026"),
    ("hesham", "هشام لطفي", "Hesham Lotfy", "ACCOUNTANT", "venicia2026"),
]


def create_users(db: Session, prop: Property, roles: dict[str, Role]) -> dict[str, User]:
    users: dict[str, User] = {
        u.username: u for u in db.execute(select(User)).scalars().all()
    }
    for username, name_ar, name_en, role_code, password in USERS:
        if username in users:
            continue
        user = User(
            username=username,
            email=f"{username}@venicia.example",
            full_name_ar=name_ar,
            full_name_en=name_en,
            hashed_password=hash_password(password),
            pos_pin_hash=hash_password(f"{abs(hash(username)) % 9000 + 1000}"),
            property_id=prop.id,
            preferred_locale="ar",
            is_superuser=role_code == "OWNER",
        )
        if role_code in roles:
            user.roles = [roles[role_code]]
        db.add(user)
        users[username] = user
    db.flush()
    return users


# ═══════════════════════════════════════════════ فئات الوحدات والوحدات
# (code, ar, en, kind, count, prefix, zone_ar, zone_en, base_occ, max_occ, rate, extra_adult)
CATEGORIES: list[tuple] = [
    ("LAKE-CH", "شاليه على البحيرة", "Lake Chalet", UnitKind.CHALET, 12, "A",
     "على البحيرة", "Lakefront", 2, 4, Decimal("2400"), Decimal("450")),
    ("GRDN-CH", "شاليه الحديقة", "Garden Chalet", UnitKind.CHALET, 18, "G",
     "الحديقة", "Garden", 2, 4, Decimal("1750"), Decimal("400")),
    ("VILLA", "فيلا", "Villa", UnitKind.VILLA, 6, "V",
     "الفيلات", "Villas", 4, 8, Decimal("5200"), Decimal("600")),
    ("SUITE", "جناح", "Suite", UnitKind.SUITE, 8, "S",
     "المبنى الرئيسي", "Main Building", 2, 3, Decimal("3100"), Decimal("500")),
    ("TENT", "خيمة البحيرة", "Lake Tent", UnitKind.LAKE_TENT, 10, "T",
     "الخيام", "Tents", 2, 3, Decimal("1450"), Decimal("350")),
    ("CLASSIC", "غرفة كلاسيك", "Classic Room", UnitKind.ROOM, 24, "R",
     "المبنى الرئيسي", "Main Building", 2, 3, Decimal("1200"), Decimal("300")),
]


def create_categories(db: Session, prop: Property) -> dict[str, UnitCategory]:
    cats: dict[str, UnitCategory] = {
        c.code: c
        for c in db.execute(
            select(UnitCategory).where(UnitCategory.property_id == prop.id)
        ).scalars().all()
    }
    for order, (code, ar, en, kind, _count, _prefix, _zar, _zen, base_occ, max_occ,
                rate, extra) in enumerate(CATEGORIES):
        if code in cats:
            continue
        cat = UnitCategory(
            property_id=prop.id,
            code=code,
            name_ar=ar,
            name_en=en,
            kind=kind,
            base_occupancy=base_occ,
            max_occupancy=max_occ,
            max_adults=max_occ,
            max_children=2,
            base_rate=rate,
            extra_adult_rate=extra,
            extra_child_rate=extra / 2,
            sort_order=order,
        )
        db.add(cat)
        cats[code] = cat
    db.flush()
    return cats


def create_units(db: Session, prop: Property, cats: dict[str, UnitCategory]) -> list[Unit]:
    existing = {
        u.code
        for u in db.execute(select(Unit).where(Unit.property_id == prop.id)).scalars().all()
    }
    created: list[Unit] = []
    for (code, _ar, _en, _kind, count, prefix, zone_ar, zone_en, *_rest) in CATEGORIES:
        cat = cats[code]
        for i in range(1, count + 1):
            unit_code = f"{prefix}-{i:02d}"
            if unit_code in existing:
                continue
            unit = Unit(
                property_id=prop.id,
                category_id=cat.id,
                code=unit_code,
                label=unit_code,
                zone_ar=zone_ar,
                zone_en=zone_en,
                has_minibar=code in ("VILLA", "SUITE", "LAKE-CH"),
                sort_order=i,
            )
            db.add(unit)
            created.append(unit)
    db.flush()
    return created


def assign_unit_states(db: Session, prop: Property) -> tuple[int, int]:
    """حالة نظافة واقعية + وحدتين خارج الخدمة.

    **لازم تتنفّذ قبل تهيئة عدّاد الإتاحة** عشان الوحدات المعطّلة تتخصم من
    السعة، وميحصلش إشغال أكبر من 100%.
    """
    import random as _random

    rng = _random.Random(20260812)
    units = list(
        db.execute(select(Unit).where(Unit.property_id == prop.id).order_by(Unit.id))
        .scalars()
        .all()
    )
    if not units:
        return 0, 0

    already_ooo = sum(1 for u in units if u.condition != UnitCondition.OPERATIONAL)
    if already_ooo:
        return len(units), already_ooo

    shuffled = list(units)
    rng.shuffle(shuffled)
    for i, unit in enumerate(shuffled):
        if i < 2:
            unit.condition = UnitCondition.OUT_OF_ORDER
            unit.housekeeping_status = HousekeepingStatus.CLEANING
            unit.block_reason = "تكييف تحت الإصلاح" if i == 0 else "تجديد الحمام"
        else:
            unit.housekeeping_status = rng.choices(
                [
                    HousekeepingStatus.CLEAN,
                    HousekeepingStatus.DIRTY,
                    HousekeepingStatus.INSPECTED,
                    HousekeepingStatus.CLEANING,
                ],
                weights=[0.55, 0.24, 0.13, 0.08],
            )[0]
    db.flush()
    return len(units), 2


# ═══════════════════════════════════════════ السياسات وخطط الأسعار
def create_policies(db: Session, prop: Property) -> dict[str, CancellationPolicy]:
    policies: dict[str, CancellationPolicy] = {
        p.code: p
        for p in db.execute(
            select(CancellationPolicy).where(CancellationPolicy.property_id == prop.id)
        ).scalars().all()
    }
    specs = [
        ("FLEX", "مرن", "Flexible", 48, Decimal("100"), Decimal("0"), True),
        ("STD", "قياسي", "Standard", 168, Decimal("100"), Decimal("25"), True),
        ("NONREF", "غير قابل للاسترداد", "Non-refundable", 0, Decimal("100"),
         Decimal("100"), False),
    ]
    for code, ar, en, free_hours, penalty, deposit, refundable in specs:
        if code in policies:
            continue
        policy = CancellationPolicy(
            property_id=prop.id,
            code=code,
            name_ar=ar,
            name_en=en,
            free_cancellation_hours=free_hours,
            penalty_method=AdjustmentMethod.PERCENT,
            penalty_value=penalty,
            no_show_nights=1,
            deposit_percent=deposit,
            deposit_due_hours=24,
            is_refundable=refundable,
        )
        db.add(policy)
        policies[code] = policy
    db.flush()
    return policies


def create_rate_plans(
    db: Session, prop: Property, policies: dict[str, CancellationPolicy]
) -> dict[str, RatePlan]:
    plans: dict[str, RatePlan] = {
        p.code: p
        for p in db.execute(
            select(RatePlan).where(RatePlan.property_id == prop.id)
        ).scalars().all()
    }
    specs = [
        ("BAR", "السعر المعلن", "Best Available Rate", MealPlan.BB, "FLEX", True, True, 0),
        ("EGY", "المقيمين في مصر", "Egyptian Residents", MealPlan.BB, "STD", True, False, 1),
        ("NONREF", "عرض غير قابل للاسترداد", "Non-refundable Deal", MealPlan.BB,
         "NONREF", True, True, 2),
        ("HB", "نصف إقامة", "Half Board", MealPlan.HB, "STD", True, True, 3),
        ("CORP", "أسعار الشركات", "Corporate Rate", MealPlan.BB, "STD", False, False, 4),
    ]
    for code, ar, en, meal, policy_code, public, channel, order in specs:
        if code in plans:
            continue
        plan = RatePlan(
            property_id=prop.id,
            code=code,
            name_ar=ar,
            name_en=en,
            meal_plan=meal,
            cancellation_policy_id=policies[policy_code].id,
            is_public=public,
            is_channel_distributed=channel,
            sort_order=order,
        )
        db.add(plan)
        plans[code] = plan
    db.flush()
    return plans


def create_seasons(db: Session, prop: Property, start: date, end: date) -> list[Season]:
    existing = {
        s.code
        for s in db.execute(select(Season).where(Season.property_id == prop.id))
        .scalars()
        .all()
    }
    created: list[Season] = []
    # (suffix, ar, en, month_day_from, month_day_to, priority, is_peak)
    templates = [
        ("SUM", "الموسم الصيفي", "Summer", (6, 15), (9, 15), 10, True),
        ("WIN", "الموسم الشتوي", "Winter", (12, 15), (1, 15), 10, True),
        ("SPR", "الربيع", "Spring", (3, 1), (5, 31), 5, False),
        ("LOW", "الموسم المنخفض", "Low Season", (10, 1), (11, 30), 1, False),
    ]
    for year in range(start.year, end.year + 1):
        for suffix, ar, en, (m1, d1), (m2, d2), priority, peak in templates:
            code = f"{suffix}-{year}"
            if code in existing:
                continue
            from_date = date(year, m1, d1)
            to_year = year + 1 if m2 < m1 else year
            to_date = date(to_year, m2, d2)
            season = Season(
                property_id=prop.id,
                code=code,
                name_ar=f"{ar} {year}",
                name_en=f"{en} {year}",
                start_date=from_date,
                end_date=to_date,
                priority=priority,
                is_peak=peak,
            )
            db.add(season)
            created.append(season)
    db.flush()
    return created


def create_rate_rules(db: Session, prop: Property) -> list[RateRule]:
    existing = {
        r.code
        for r in db.execute(select(RateRule).where(RateRule.property_id == prop.id))
        .scalars()
        .all()
    }
    specs = [
        ("WKND", "زيادة الويك إند", "Weekend uplift", RateRuleType.WEEKEND,
         AdjustmentMethod.PERCENT, Decimal("25"), None, None, 10),
        ("MIDWEEK", "خصم منتصف الأسبوع", "Midweek discount", RateRuleType.MIDWEEK,
         AdjustmentMethod.PERCENT, Decimal("-8"), None, None, 20),
        ("HIGHOCC", "زيادة الإشغال العالي", "High occupancy uplift",
         RateRuleType.OCCUPANCY, AdjustmentMethod.PERCENT, Decimal("15"),
         Decimal("85"), None, 30),
        ("LOWOCC", "خصم الإشغال المنخفض", "Low occupancy discount",
         RateRuleType.OCCUPANCY, AdjustmentMethod.PERCENT, Decimal("-10"),
         None, Decimal("40"), 31),
        ("LOS7", "خصم الإقامة الطويلة", "Long stay discount",
         RateRuleType.LENGTH_OF_STAY, AdjustmentMethod.PERCENT, Decimal("-12"),
         Decimal("7"), None, 40),
        ("LASTMIN", "عرض اللحظة الأخيرة", "Last minute deal",
         RateRuleType.LEAD_TIME, AdjustmentMethod.PERCENT, Decimal("-15"),
         None, Decimal("3"), 50),
    ]
    created: list[RateRule] = []
    for code, ar, en, rtype, method, value, tmin, tmax, priority in specs:
        if code in existing:
            continue
        rule = RateRule(
            property_id=prop.id,
            code=code,
            name_ar=ar,
            name_en=en,
            rule_type=rtype,
            method=method,
            value=value,
            threshold_min=tmin,
            threshold_max=tmax,
            priority=priority,
        )
        db.add(rule)
        created.append(rule)
    db.flush()
    return created


# ═════════════════════════════════════════════════════ منافذ البيع
OUTLETS: list[tuple] = [
    # (code, ar, en, type, prefix, floor_plan, room_charge, qr, tables)
    ("REST", "مطعم البحيرة", "Lake Restaurant", OutletType.RESTAURANT, "R", True, True, True, 22),
    ("BAR", "بار الغروب", "Sunset Bar", OutletType.BAR, "B", True, True, False, 14),
    ("CAFE", "كافيه الميدان", "Piazza Café", OutletType.CAFE, "C", True, True, True, 12),
    ("SPA", "سبا فينيسيا", "Venicia Spa", OutletType.SPA, "S", False, True, False, 0),
    ("BEACH", "خيام الشاطئ", "Beach Tents", OutletType.BEACH, "T", True, True, True, 10),
    ("RSVC", "خدمة الغرف", "Room Service", OutletType.ROOM_SERVICE, "K", False, True, True, 0),
]

STATIONS: list[tuple[str, str, str, str]] = [
    ("HOT", "المطبخ الساخن", "Hot Kitchen", "REST"),
    ("COLD", "المطبخ البارد", "Cold Kitchen", "REST"),
    ("GRILL", "المشويات", "Grill", "REST"),
    ("PASTRY", "الحلويات", "Pastry", "REST"),
    ("BARST", "محطة البار", "Bar Station", "BAR"),
    ("COFFEE", "محطة القهوة", "Coffee Station", "CAFE"),
]


def create_outlets(
    db: Session, prop: Property
) -> tuple[dict[str, Outlet], dict[str, KitchenStation]]:
    outlets: dict[str, Outlet] = {
        o.code: o
        for o in db.execute(select(Outlet).where(Outlet.property_id == prop.id))
        .scalars()
        .all()
    }
    for order, (code, ar, en, otype, prefix, floor, charge, qr, _tables) in enumerate(OUTLETS):
        if code in outlets:
            continue
        outlet = Outlet(
            property_id=prop.id,
            code=code,
            name_ar=ar,
            name_en=en,
            outlet_type=otype,
            service_charge_percent=Decimal("12"),
            vat_percent=Decimal("14"),
            has_floor_plan=floor,
            allows_room_charge=charge,
            qr_ordering_enabled=qr,
            opens_at="08:00" if otype != OutletType.BAR else "16:00",
            closes_at="23:30",
            order_prefix=prefix,
            sort_order=order,
        )
        db.add(outlet)
        outlets[code] = outlet
    db.flush()

    stations: dict[str, KitchenStation] = {
        s.code: s
        for s in db.execute(
            select(KitchenStation).where(KitchenStation.property_id == prop.id)
        ).scalars().all()
    }
    for code, ar, en, outlet_code in STATIONS:
        if code in stations:
            continue
        station = KitchenStation(
            property_id=prop.id,
            code=code,
            name_ar=ar,
            name_en=en,
            outlet_id=outlets[outlet_code].id,
            printer_name=f"PRN-{code}",
        )
        db.add(station)
        stations[code] = station
    db.flush()
    return outlets, stations


def create_tables(db: Session, prop: Property, outlets: dict[str, Outlet]) -> int:
    existing = {
        (t.outlet_id, t.label)
        for t in db.execute(select(PosTable)).scalars().all()
    }
    zones = [("داخلي", "Indoor"), ("تراس", "Terrace"), ("على البحيرة", "Lakeside")]
    count = 0
    for code, _ar, _en, _t, _p, has_floor, _rc, _qr, table_count in OUTLETS:
        if not has_floor or table_count == 0:
            continue
        outlet = outlets[code]
        for i in range(1, table_count + 1):
            label = str(i)
            if (outlet.id, label) in existing:
                continue
            zone_ar, zone_en = zones[(i - 1) % len(zones)]
            db.add(
                PosTable(
                    outlet_id=outlet.id,
                    property_id=prop.id,
                    label=label,
                    zone_ar=zone_ar,
                    zone_en=zone_en,
                    seats=[2, 4, 4, 6, 8][(i - 1) % 5],
                    pos_x=60 + ((i - 1) % 6) * 110,
                    pos_y=60 + ((i - 1) // 6) * 110,
                    width=80,
                    height=80,
                    shape="ROUND" if i % 3 == 0 else "SQUARE",
                )
            )
            count += 1
    db.flush()
    return count


# ═════════════════════════════════════════════════════════ المنيو
MENU_CATEGORIES: list[tuple[str, str, str, int]] = [
    ("APP", "مقبلات", "Appetizers", 0),
    ("SOUP", "شوربة", "Soups", 1),
    ("GRILL", "مشويات", "Grills", 2),
    ("FISH", "أسماك ومأكولات بحرية", "Fish & Seafood", 3),
    ("PASTA", "باستا ورز", "Pasta & Rice", 4),
    ("SALAD", "سلطات", "Salads", 5),
    ("DESSERT", "حلويات", "Desserts", 6),
    ("HOTDRINK", "مشروبات ساخنة", "Hot Drinks", 7),
    ("COLDDRINK", "مشروبات باردة", "Cold Drinks", 8),
    ("COCKTAIL", "كوكتيلات", "Cocktails", 9),
    ("SPATREAT", "جلسات السبا", "Spa Treatments", 10),
]

# (code, ar, en, category, price, cost, station, outlets)
MENU_ITEMS: list[tuple] = [
    ("APP01", "طحينة بلدي", "Tahina", "APP", 45, 12, "COLD", ["REST", "BEACH"]),
    ("APP02", "بابا غنوج", "Baba Ghanoush", "APP", 55, 15, "COLD", ["REST", "BEACH"]),
    ("APP03", "سمبوسك جبنة", "Cheese Sambousek", "APP", 75, 22, "HOT", ["REST", "CAFE"]),
    ("APP04", "كبدة إسكندراني", "Alexandrian Liver", "APP", 145, 52, "HOT", ["REST"]),
    ("APP05", "حمص بالصنوبر", "Hummus with Pine Nuts", "APP", 65, 18, "COLD", ["REST", "BEACH"]),
    ("SOUP01", "شوربة عدس", "Lentil Soup", "SOUP", 60, 14, "HOT", ["REST"]),
    ("SOUP02", "شوربة مأكولات بحرية", "Seafood Soup", "SOUP", 130, 45, "HOT", ["REST"]),
    ("GRL01", "كفتة مشوية", "Grilled Kofta", "GRILL", 265, 95, "GRILL", ["REST", "BEACH"]),
    ("GRL02", "ريش ضاني", "Lamb Chops", "GRILL", 480, 190, "GRILL", ["REST"]),
    ("GRL03", "فراخ مشوية", "Grilled Chicken", "GRILL", 220, 72, "GRILL", ["REST", "BEACH"]),
    ("GRL04", "مشاوي مشكلة", "Mixed Grill", "GRILL", 520, 205, "GRILL", ["REST"]),
    ("FSH01", "سمك بلطي مشوي", "Grilled Tilapia", "FISH", 280, 98, "GRILL", ["REST", "BEACH"]),
    ("FSH02", "جمبري بالثوم", "Garlic Shrimp", "FISH", 420, 175, "HOT", ["REST"]),
    ("FSH03", "كاليماري مقلي", "Fried Calamari", "FISH", 310, 120, "HOT", ["REST", "BAR"]),
    ("FSH04", "صيادية سمك", "Sayadeya", "FISH", 340, 128, "HOT", ["REST"]),
    ("PST01", "مكرونة بالمأكولات البحرية", "Seafood Pasta", "PASTA", 295, 105, "HOT", ["REST"]),
    ("PST02", "باستا ألفريدو", "Alfredo Pasta", "PASTA", 210, 62, "HOT", ["REST", "CAFE"]),
    ("PST03", "رز بالخلطة", "Egyptian Rice", "PASTA", 70, 16, "HOT", ["REST"]),
    ("SLD01", "سلطة سيزر", "Caesar Salad", "SALAD", 165, 48, "COLD", ["REST", "CAFE", "BEACH"]),
    ("SLD02", "سلطة يونانية", "Greek Salad", "SALAD", 150, 44, "COLD", ["REST", "CAFE"]),
    ("SLD03", "سلطة بلدي", "Baladi Salad", "SALAD", 55, 14, "COLD", ["REST", "BEACH"]),
    ("DST01", "أم علي", "Om Ali", "DESSERT", 110, 28, "PASTRY", ["REST", "CAFE"]),
    ("DST02", "كنافة بالمانجو", "Mango Konafa", "DESSERT", 135, 38, "PASTRY", ["REST", "CAFE"]),
    ("DST03", "تشيز كيك", "Cheesecake", "DESSERT", 125, 36, "PASTRY", ["REST", "CAFE"]),
    ("HOT01", "قهوة تركي", "Turkish Coffee", "HOTDRINK", 45, 8, "COFFEE", ["REST", "CAFE", "BAR"]),
    ("HOT02", "إسبريسو", "Espresso", "HOTDRINK", 55, 11, "COFFEE", ["REST", "CAFE", "BAR"]),
    ("HOT03", "كابتشينو", "Cappuccino", "HOTDRINK", 75, 18, "COFFEE", ["REST", "CAFE", "BAR"]),
    ("HOT04", "شاي بالنعناع", "Mint Tea", "HOTDRINK", 40, 6, "COFFEE", ["REST", "CAFE", "BEACH"]),
    ("CLD01", "عصير مانجو طازة", "Fresh Mango Juice", "COLDDRINK", 85, 26, "COFFEE",
     ["REST", "CAFE", "BEACH", "BAR"]),
    ("CLD02", "عصير ليمون بالنعناع", "Lemon Mint", "COLDDRINK", 70, 16, "COFFEE",
     ["REST", "CAFE", "BEACH", "BAR"]),
    ("CLD03", "مياه معدنية", "Mineral Water", "COLDDRINK", 25, 7, "COFFEE",
     ["REST", "CAFE", "BEACH", "BAR"]),
    ("CLD04", "مشروبات غازية", "Soft Drinks", "COLDDRINK", 35, 12, "COFFEE",
     ["REST", "CAFE", "BEACH", "BAR"]),
    ("CKT01", "موهيتو كلاسيك", "Classic Mojito", "COCKTAIL", 165, 42, "BARST", ["BAR", "BEACH"]),
    ("CKT02", "بينا كولادا", "Pina Colada", "COCKTAIL", 180, 48, "BARST", ["BAR", "BEACH"]),
    ("CKT03", "صن سيت سبيشيال", "Sunset Special", "COCKTAIL", 210, 55, "BARST", ["BAR"]),
    ("SPA01", "مساج استرخاء 60 دقيقة", "Relaxing Massage 60min", "SPATREAT", 850, 260, None, ["SPA"]),
    ("SPA02", "مساج حجر ساخن 90 دقيقة", "Hot Stone 90min", "SPATREAT", 1250, 380, None, ["SPA"]),
    ("SPA03", "جلسة ساونا", "Sauna Session", "SPATREAT", 400, 95, None, ["SPA"]),
    ("SPA04", "باديكير ومانيكير", "Mani & Pedi", "SPATREAT", 550, 165, None, ["SPA"]),
]


def create_menu(
    db: Session,
    prop: Property,
    outlets: dict[str, Outlet],
    stations: dict[str, KitchenStation],
) -> int:
    cats: dict[str, MenuCategory] = {
        c.code: c
        for c in db.execute(
            select(MenuCategory).where(MenuCategory.property_id == prop.id)
        ).scalars().all()
    }
    for code, ar, en, order in MENU_CATEGORIES:
        if code in cats:
            continue
        cat = MenuCategory(
            property_id=prop.id, code=code, name_ar=ar, name_en=en, sort_order=order
        )
        db.add(cat)
        cats[code] = cat
    db.flush()

    existing_items = {
        i.code: i
        for i in db.execute(
            select(MenuItem).where(MenuItem.property_id == prop.id)
        ).scalars().all()
    }
    created = 0
    for order, (code, ar, en, cat_code, price, cost, station_code, outlet_codes) in enumerate(
        MENU_ITEMS
    ):
        if code in existing_items:
            continue
        item = MenuItem(
            property_id=prop.id,
            code=code,
            name_ar=ar,
            name_en=en,
            category_id=cats[cat_code].id,
            kitchen_station_id=stations[station_code].id if station_code else None,
            price=Decimal(str(price)),
            cost=Decimal(str(cost)),
            contains_alcohol=cat_code == "COCKTAIL",
            is_vegetarian=cat_code in ("SALAD", "SOUP") and "سيزر" not in ar,
            preparation_minutes=15 if cat_code in ("GRILL", "FISH") else 8,
            sort_order=order,
        )
        item.outlets = [outlets[c] for c in outlet_codes if c in outlets]
        db.add(item)
        created += 1
    db.flush()
    return created


# ═══════════════════════════════════════════ الأسعار والإتاحة للفترة
def publish_calendar(
    db: Session,
    prop: Property,
    cats: dict[str, UnitCategory],
    plans: dict[str, RatePlan],
    start: date,
    end: date,
) -> tuple[int, int]:
    """نشر أسعار الفترة كلها + تهيئة عدّاد الإتاحة."""
    # معامل خصم/زيادة لكل خطة سعر مقارنة بالسعر المعلن
    plan_factor = {
        "BAR": Decimal("1.00"),
        "EGY": Decimal("0.85"),
        "NONREF": Decimal("0.82"),
        "HB": Decimal("1.28"),
        "CORP": Decimal("0.78"),
    }
    # معامل الموسم حسب الشهر (يناير .. ديسمبر)
    month_factor = {
        1: Decimal("1.05"), 2: Decimal("0.95"), 3: Decimal("1.00"),
        4: Decimal("1.10"), 5: Decimal("1.05"), 6: Decimal("1.20"),
        7: Decimal("1.35"), 8: Decimal("1.40"), 9: Decimal("1.15"),
        10: Decimal("0.90"), 11: Decimal("0.85"), 12: Decimal("1.25"),
    }

    published = 0
    cursor = date(start.year, start.month, 1)
    while cursor < end:
        # نهاية الشهر الحالي
        next_month = (
            date(cursor.year + 1, 1, 1) if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
        chunk_start = max(cursor, start)
        chunk_end = min(next_month, end)
        factor = month_factor[cursor.month]

        for cat_code, cat in cats.items():
            base = cat.base_rate * factor
            for plan_code, plan in plans.items():
                rate = (base * plan_factor[plan_code]).quantize(Decimal("1"))
                published += pricing.publish_rates(
                    db,
                    property_id=prop.id,
                    unit_category_id=cat.id,
                    rate_plan_id=plan.id,
                    start=chunk_start,
                    end=chunk_end,
                    rate=rate,
                    extra_adult_rate=cat.extra_adult_rate,
                    extra_child_rate=cat.extra_child_rate,
                )
        db.flush()
        cursor = next_month

    slots = av.ensure_calendar(db, prop.id, start, end)
    return published, slots


# ═══════════════════════════════════════════════════════ الميني بار
#: (الكود، عربي، إنجليزي، السعر، فيه كحول)
MINIBAR: list[tuple[str, str, str, str, bool]] = [
    ("MB-WTR", "مياه معدنية", "Mineral water", "25", False),
    ("MB-SPK", "مياه غازية", "Sparkling water", "35", False),
    ("MB-COL", "مشروب غازي", "Soft drink", "40", False),
    ("MB-JUI", "عصير طبيعي", "Fresh juice", "55", False),
    ("MB-NES", "نسكافيه", "Instant coffee", "45", False),
    ("MB-TEA", "شاي", "Tea", "30", False),
    ("MB-NUT", "مكسرات", "Mixed nuts", "85", False),
    ("MB-CHP", "شيبسي", "Crisps", "40", False),
    ("MB-CHO", "شوكولاتة", "Chocolate bar", "60", False),
    ("MB-BEE", "بيرة محلية", "Local beer", "120", True),
]


def create_minibar(db: Session, prop: Property) -> int:
    existing = {
        i.code for i in db.execute(
            select(MinibarItem).where(MinibarItem.property_id == prop.id)
        ).scalars().all()
    }
    made = 0
    for order, (code, name_ar, name_en, price, alcohol) in enumerate(MINIBAR):
        if code in existing:
            continue
        db.add(
            MinibarItem(
                property_id=prop.id,
                code=code,
                name_ar=name_ar,
                name_en=name_en,
                price=Decimal(price),
                contains_alcohol=alcohol,
                sort_order=order,
                is_active=True,
            )
        )
        made += 1
    db.flush()
    return made


# ═══════════════════════════════════════════════════ القنوات والربط
#: (المصدر، الاسم بالعربي، الاسم بالإنجليزي، العمولة، بادئة رقم الغرفة)
CHANNELS: list[tuple[BookingSource, str, str, str, str]] = [
    (BookingSource.BOOKING_COM, "بوكينج", "Booking.com", "17", "BDC"),
    (BookingSource.AGODA, "أجودا", "Agoda", "15", "AGD"),
    (BookingSource.EXPEDIA, "إكسبيديا", "Expedia", "16", "EXP"),
    (BookingSource.AIRBNB, "إير بي إن بي", "Airbnb", "14", "ABB"),
]


def create_channels(
    db: Session, prop: Property, cats: dict[str, UnitCategory], plans: list[RatePlan]
) -> tuple[int, int]:
    """القنوات وربط الغرف — بيتعمل مرة واحدة وبيتخطّى لو موجود.

    الربط بيتعمل على الفئات القابلة للبيع أونلاين بس: الخيام والجلسات
    بتتباع على الطبيعة، فمالهاش لازمة على بوكينج.
    """
    existing = {
        c.source: c
        for c in db.execute(
            select(Channel).where(Channel.property_id == prop.id)
        ).scalars().all()
    }
    public_plan = next((p for p in plans if p.is_public), plans[0] if plans else None)
    online_cats = [
        c for c in cats.values()
        if c.kind in (UnitKind.ROOM, UnitKind.CHALET, UnitKind.VILLA, UnitKind.SUITE)
    ]

    made = mapped = 0
    for source, name_ar, name_en, commission, prefix in CHANNELS:
        channel = existing.get(source)
        if channel is None:
            channel = Channel(
                property_id=prop.id,
                source=source,
                name_ar=name_ar,
                name_en=name_en,
                is_active=True,
                # بوكينج وأجودا متوصّلين، والباقي مستني اعتماد — ده الواقع
                is_connected=source in (BookingSource.BOOKING_COM, BookingSource.AGODA),
                commission_percent=Decimal(commission),
                external_property_id=f"{prefix}-{prop.code}-{prop.id:04d}",
            )
            db.add(channel)
            db.flush()
            made += 1

        if channel.mappings:
            continue
        for category in online_cats:
            db.add(
                ChannelMapping(
                    channel_id=channel.id,
                    property_id=prop.id,
                    unit_category_id=category.id,
                    rate_plan_id=public_plan.id if public_plan else None,
                    external_room_id=f"{prefix}-{category.code}",
                    external_rate_id=f"{prefix}-RATE-{public_plan.code}" if public_plan else None,
                    allocation=0,
                    is_active=True,
                )
            )
            mapped += 1
    db.flush()
    return made, mapped


# ═══════════════════════════════════════════════════════════ التشغيل
def run(years_back: int = 2, months_forward: int = 6) -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        today = date.today()
        start = date(today.year - years_back, 1, 1)
        end = today + timedelta(days=30 * months_forward)

        print("المنشأة...")
        prop = create_property(db)

        print("الصلاحيات والأدوار...")
        roles = create_security(db, prop)

        print("المستخدمون...")
        users = create_users(db, prop, roles)

        print("فئات الوحدات...")
        cats = create_categories(db, prop)

        print("الوحدات...")
        units = create_units(db, prop, cats)

        print("حالة الوحدات (نظافة + خارج الخدمة)...")
        _total_units, ooo_units = assign_unit_states(db, prop)

        print("سياسات الإلغاء وخطط الأسعار...")
        policies = create_policies(db, prop)
        plans = create_rate_plans(db, prop, policies)

        print("المواسم وقواعد التسعير...")
        seasons = create_seasons(db, prop, start, end)
        rules = create_rate_rules(db, prop)

        print("منافذ البيع والمحطات...")
        outlets, stations = create_outlets(db, prop)
        tables = create_tables(db, prop, outlets)

        print("المنيو...")
        items = create_menu(db, prop, outlets, stations)

        print("الميني بار...")
        minibar_items = create_minibar(db, prop)

        print("القنوات وربط الغرف...")
        made_channels, mapped_rooms = create_channels(db, prop, cats, plans)

        print(f"نشر الأسعار والإتاحة من {start} إلى {end} (ممكن ياخد شوية)...")
        published, slots = publish_calendar(db, prop, cats, plans, start, end)

        db.commit()

        total_units = sum(c[4] for c in CATEGORIES)
        print()
        print("─" * 52)
        print(f"  المنشأة              {prop.name_ar}")
        print(f"  الأدوار              {len(roles)}")
        print(f"  المستخدمون           {len(users)}")
        print(f"  فئات الوحدات         {len(cats)}")
        print(f"  الوحدات              {total_units}  (جديد: {len(units)})")
        print(f"  خارج الخدمة          {ooo_units}")
        print(f"  خطط الأسعار          {len(plans)}")
        print(f"  المواسم              {len(seasons)}")
        print(f"  قواعد التسعير        {len(rules)}")
        print(f"  منافذ البيع          {len(outlets)}")
        print(f"  محطات المطبخ         {len(stations)}")
        print(f"  الطاولات             {tables}")
        print(f"  أصناف المنيو         {items}")
        print(f"  قنوات البيع          {made_channels}  (ربط: {mapped_rooms})")
        print(f"  أصناف الميني بار     {minibar_items}")
        print(f"  أسعار منشورة         {published:,}")
        print(f"  صفوف عدّاد الإتاحة   {slots:,}")
        print("─" * 52)
        print()
        print("  دخول:  owner / venicia2026")
    finally:
        db.close()


if __name__ == "__main__":
    run()
