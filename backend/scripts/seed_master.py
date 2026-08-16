"""البيانات الأساسية لقرية فينيسيا — Master data seed.

بينشئ المنشأة والصلاحيات والمستخدمين وفئات الوحدات والوحدات وخطط الأسعار
والمواسم ومنافذ البيع والمنيو. آمن التكرار: لو اتشغّل تاني مبيكرّرش حاجة.

    python -m scripts.seed_master
"""

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import hash_password
from app.db.base import Base, SessionLocal, engine
from app.models.accounting import Account, CostCenter
from app.models.channels import Channel, ChannelMapping
from app.models.leisure import Service, ServiceResourceItem, Venue
from app.models.maintenance import MinibarItem
from app.models.stock import StockItem, Supplier, Warehouse
from app.models.enums import (
    AccountType,
    AdjustmentMethod,
    BookingSource,
    HousekeepingStatus,
    MealPlan,
    OutletType,
    RateRuleType,
    ResourceKind,
    ServiceCategory,
    VenueKind,
    StockUnit,
    UnitCondition,
    UnitKind,
    WarehouseKind,
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
    # صلاحيات تطبيق الموبايل. منفصلة عن صلاحيات الشاشات عن قصد: الهاوس
    # كيبر بيقدر ينضّف ويصوّر من تليفونه، ومبيقدرش يفتح شاشة إدارية.
    ("field.clean", "field", "تنفيذ مهام التنضيف من التطبيق", "Field cleaning tasks"),
    ("field.fix", "field", "تنفيذ تذاكر الصيانة من التطبيق", "Field maintenance tickets"),
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
    ("stock.view", "stock", "عرض المخزن", "View inventory"),
    ("stock.manage", "stock", "حركات المخزن والمشتريات", "Manage stock & purchasing"),
    ("gl.view", "gl", "عرض الحسابات والقوائم", "View ledger & statements"),
    ("gl.post", "gl", "ترحيل قيود", "Post journal entries"),
    ("gl.close", "gl", "إقفال الفترات المحاسبية", "Close accounting periods"),
    ("hr.view", "hr", "عرض بيانات العاملين", "View employees"),
    ("hr.manage", "hr", "إدارة العاملين والإجازات", "Manage employees & leave"),
    ("payroll.view", "payroll", "عرض المرتبات", "View payroll"),
    ("payroll.run", "payroll", "حساب مسيّر المرتبات", "Run payroll"),
    ("payroll.approve", "payroll", "اعتماد وصرف المرتبات", "Approve & pay payroll"),
    ("leisure.view", "leisure", "عرض السبا والمناسبات", "View spa & events"),
    ("leisure.book", "leisure", "حجز مواعيد السبا والأنشطة", "Book spa & activities"),
    ("leisure.manage", "leisure", "إدارة المناسبات والأسعار", "Manage events & pricing"),
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
            # الاستقبال بيحجز السبا والأنشطة للنزيل وهو واقف قدامه
            "leisure.view", "leisure.book",
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
            "leisure.view", "leisure.book", "leisure.manage",
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
            # مدير المطعم هو اللي بيمسك المخزن والوصفات فعلياً
            "stock.view", "stock.manage",
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
            # السوبرفايزر بيشتغل من التليفون كمان — بيفحص وهو واقف
            "field.clean", "field.fix",
        ],
    ),
    (
        "HOUSEKEEPER",
        "هاوس كيبر",
        "Housekeeper",
        0,
        # الحد الأدنى المطلق: مهامي، وأصوّر، وأبلّغ عن عطل. مفيش شاشة
        # إدارية ولا أسعار ولا حسابات نزلاء. الموبايل مش بيتحط في درج
        # مقفول — بيتنسي على طرابيزة، فالحساب اللي عليه لازم يكون فقير.
        ["field.clean", "maintenance.view"],
    ),
    (
        "TECHNICIAN",
        "فني صيانة",
        "Technician",
        0,
        ["field.fix", "maintenance.view"],
    ),
    (
        "ACCOUNTANT",
        "محاسب",
        "Accountant",
        0,
        [
            "folio.view", "report.financial", "report.operational", "report.audit",
            "invoice.issue", "invoice.cancel", "nightaudit.run", "channel.view",
            "stock.view",
            # المحاسب هو صاحب الدفتر — بيرحّل ويقفل الشهور
            "gl.view", "gl.post", "gl.close",
            # وبيحسب المسيّر، بس الاعتماد مش من حقه
            "hr.view", "payroll.view", "payroll.run",
        ],
    ),
    (
        "HR_MANAGER",
        "مدير شؤون العاملين",
        "HR Manager",
        0,
        [
            "hr.view", "hr.manage", "payroll.view", "payroll.run",
            "report.operational",
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
    ("nadia", "نادية القاضي", "Nadia El-Kady", "HR_MANAGER", "venicia2026"),
    # فريق الميدان — دول اللي بيشتغلوا من التليفون
    ("fatma", "فاطمة السيد", "Fatma El-Sayed", "HOUSEKEEPER", "venicia2026"),
    ("zeinab", "زينب مرسي", "Zeinab Morsy", "HOUSEKEEPER", "venicia2026"),
    ("amira", "أميرة رجب", "Amira Ragab", "HOUSEKEEPER", "venicia2026"),
    ("shaimaa", "شيماء فؤاد", "Shaimaa Fouad", "HOUSEKEEPER", "venicia2026"),
    ("mahmoud", "محمود عبد الحميد", "Mahmoud Abdelhamid", "TECHNICIAN", "venicia2026"),
    ("ibrahim", "إبراهيم صابر", "Ibrahim Saber", "TECHNICIAN", "venicia2026"),
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

    # خدمة الغرف مالهاش منيو خاص بيها — بتقدّم منيو المطعم والكافيه.
    # من غير الربط ده كود الـ QR بتاعها بيفتح صفحة فاضية.
    _link_room_service(db, prop, outlets)
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


def _link_room_service(db: Session, prop: Property, outlets: dict[str, Outlet]) -> int:
    """خدمة الغرف بتقدّم أصناف المطعم والكافيه — من غير أصناف خاصة بيها."""
    room_service = outlets.get("RSVC")
    sources = [outlets[c] for c in ("REST", "CAFE") if c in outlets]
    if room_service is None or not sources:
        return 0

    source_ids = {o.id for o in sources}
    items = db.execute(
        select(MenuItem)
        .options(selectinload(MenuItem.outlets))
        .where(MenuItem.property_id == prop.id)
    ).scalars().unique().all()

    linked = 0
    for item in items:
        current = {o.id for o in item.outlets}
        if room_service.id in current or not (current & source_ids):
            continue
        item.outlets.append(room_service)
        linked += 1
    db.flush()
    return linked


# ═══════════════════════════════════════════ المخازن والموردين والأصناف
#: (الكود، عربي، إنجليزي، النوع، كود المنفذ)
WAREHOUSES: list[tuple[str, str, str, WarehouseKind, str | None]] = [
    ("WH-MAIN", "المخزن الرئيسي", "Main store", WarehouseKind.MAIN, None),
    ("WH-KIT", "مخزن المطبخ", "Kitchen store", WarehouseKind.KITCHEN, "REST"),
    ("WH-BAR", "مخزن البار", "Bar store", WarehouseKind.BAR, "BAR"),
    ("WH-HK", "مخزن الهاوس كيبينج", "Housekeeping store", WarehouseKind.HOUSEKEEPING, None),
]

#: (الكود، عربي، إنجليزي، الموبايل، مهلة السداد)
SUPPLIERS: list[tuple[str, str, str, str, int]] = [
    ("SUP-MEAT", "الفيوم للحوم", "Fayoum Meats", "+20 84 220 1100", 30),
    ("SUP-FISH", "أسماك البحيرة", "Lake Fisheries", "+20 84 220 2200", 15),
    ("SUP-VEG", "مزارع الواحة", "Oasis Farms", "+20 84 220 3300", 7),
    ("SUP-DRY", "التموين المصري", "Egyptian Provisions", "+20 2 3855 4400", 30),
    ("SUP-BEV", "توزيع المشروبات", "Beverage Distributors", "+20 2 3855 5500", 21),
]

#: (الكود، عربي، إنجليزي، التصنيف، الوحدة، التكلفة، حد الطلب، كمية الطلب، المورد، حرج)
STOCK_ITEMS: list[tuple] = [
    # لحوم وأسماك
    ("ST-BEEF", "لحم بقري", "Beef", "لحوم", "Meat", StockUnit.KG, "320", "25", "40", "SUP-MEAT", True),
    ("ST-LAMB", "لحم ضاني", "Lamb", "لحوم", "Meat", StockUnit.KG, "410", "15", "25", "SUP-MEAT", True),
    ("ST-CHICK", "دجاج", "Chicken", "لحوم", "Meat", StockUnit.KG, "110", "30", "50", "SUP-MEAT", False),
    ("ST-BASS", "قاروص", "Sea bass", "أسماك", "Fish", StockUnit.KG, "260", "20", "35", "SUP-FISH", True),
    ("ST-SHRMP", "جمبري", "Shrimp", "أسماك", "Fish", StockUnit.KG, "480", "10", "20", "SUP-FISH", True),
    # خضار
    ("ST-TOM", "طماطم", "Tomato", "خضار", "Vegetables", StockUnit.KG, "18", "20", "40", "SUP-VEG", False),
    ("ST-ONION", "بصل", "Onion", "خضار", "Vegetables", StockUnit.KG, "15", "20", "40", "SUP-VEG", False),
    ("ST-POT", "بطاطس", "Potato", "خضار", "Vegetables", StockUnit.KG, "16", "30", "60", "SUP-VEG", False),
    ("ST-LETT", "خس", "Lettuce", "خضار", "Vegetables", StockUnit.KG, "22", "8", "15", "SUP-VEG", False),
    ("ST-LEMON", "ليمون", "Lemon", "خضار", "Vegetables", StockUnit.KG, "28", "10", "20", "SUP-VEG", False),
    # جافة ومستهلكات
    ("ST-RICE", "أرز", "Rice", "جافة", "Dry goods", StockUnit.KG, "34", "40", "80", "SUP-DRY", False),
    ("ST-OIL", "زيت", "Cooking oil", "جافة", "Dry goods", StockUnit.LITRE, "62", "25", "50", "SUP-DRY", False),
    ("ST-BUTTER", "زبدة", "Butter", "ألبان", "Dairy", StockUnit.KG, "185", "10", "20", "SUP-DRY", False),
    ("ST-CHEESE", "جبنة", "Cheese", "ألبان", "Dairy", StockUnit.KG, "210", "8", "15", "SUP-DRY", False),
    ("ST-FLOUR", "دقيق", "Flour", "جافة", "Dry goods", StockUnit.KG, "21", "30", "60", "SUP-DRY", False),
    ("ST-SPICE", "بهارات مشكلة", "Mixed spices", "جافة", "Dry goods", StockUnit.KG, "140", "5", "10", "SUP-DRY", False),
    # مشروبات
    ("ST-COFFEE", "بن", "Coffee beans", "مشروبات", "Beverages", StockUnit.KG, "380", "8", "15", "SUP-BEV", False),
    ("ST-TEA", "شاي", "Tea", "مشروبات", "Beverages", StockUnit.KG, "160", "5", "10", "SUP-BEV", False),
    ("ST-SODA", "مشروبات غازية", "Soft drinks", "مشروبات", "Beverages", StockUnit.BOTTLE, "9", "120", "240", "SUP-BEV", False),
    ("ST-WATER", "مياه معدنية", "Bottled water", "مشروبات", "Beverages", StockUnit.BOTTLE, "4", "200", "400", "SUP-BEV", False),
]


def create_warehouses(
    db: Session, prop: Property, outlets: dict[str, Outlet]
) -> tuple[int, int, int]:
    """المخازن والموردين والأصناف — كلهم آمنين التكرار."""
    made_wh = made_sup = made_item = 0

    existing = {
        w.code for w in db.execute(
            select(Warehouse).where(Warehouse.property_id == prop.id)
        ).scalars().all()
    }
    for order, (code, ar, en, kind, outlet_code) in enumerate(WAREHOUSES):
        if code in existing:
            continue
        db.add(
            Warehouse(
                property_id=prop.id, code=code, name_ar=ar, name_en=en, kind=kind,
                outlet_id=outlets[outlet_code].id if outlet_code in outlets else None,
                sort_order=order, is_active=True,
            )
        )
        made_wh += 1
    db.flush()

    have_sup = {
        s.code: s for s in db.execute(
            select(Supplier).where(Supplier.property_id == prop.id)
        ).scalars().all()
    }
    for code, ar, en, phone, terms in SUPPLIERS:
        if code in have_sup:
            continue
        supplier = Supplier(
            property_id=prop.id, code=code, name_ar=ar, name_en=en,
            phone=phone, payment_terms_days=terms, is_active=True,
        )
        db.add(supplier)
        have_sup[code] = supplier
        made_sup += 1
    db.flush()

    have_items = {
        s.code for s in db.execute(
            select(StockItem).where(StockItem.property_id == prop.id)
        ).scalars().all()
    }
    for order, row in enumerate(STOCK_ITEMS):
        (code, ar, en, cat_ar, cat_en, unit, cost, reorder, qty, sup_code, critical) = row
        if code in have_items:
            continue
        db.add(
            StockItem(
                property_id=prop.id, code=code, name_ar=ar, name_en=en,
                category_ar=cat_ar, category_en=cat_en, unit=unit,
                average_cost=Decimal(cost), last_purchase_cost=Decimal(cost),
                reorder_level=Decimal(reorder), reorder_quantity=Decimal(qty),
                preferred_supplier_id=have_sup[sup_code].id if sup_code in have_sup else None,
                is_critical=critical, sort_order=order, is_active=True,
            )
        )
        made_item += 1
    db.flush()
    return made_wh, made_sup, made_item


def reset_stock_costs(db: Session, prop: Property) -> int:
    """رجوع تكاليف الأصناف لأسعار البذرة وإعادة بناء قيمة المخزون.

    **مبيتشغّلش إلا بطلب صريح** (``--reset-costs``). السبب إن متوسط
    التكلفة في التشغيل الحقيقي نتيجة مشتريات فعلية، ومسحه بيضيّع معلومة
    صحيحة.

    بس في داتا العرض بيحصل انحراف: كل تشغيلة اختبار بتستلم بضاعة بسعر
    أعلى عشان تثبت إن المتوسط بيتحرّك، والتراكم بيوصل الخس لـ112 جنيه
    للكيلو. الدالة دي بترجّع الأساس وتعيد حساب قيمة المخزون منه.
    """
    from app.services import stock as stock_svc

    baseline = {row[0]: Decimal(row[6]) for row in STOCK_ITEMS}
    changed = 0
    for item in db.execute(
        select(StockItem).where(StockItem.property_id == prop.id)
    ).scalars():
        base = baseline.get(item.code)
        if base is None or item.average_cost == base:
            continue
        item.average_cost = base
        item.last_purchase_cost = base
        changed += 1
    db.flush()
    # قيمة الرصيد محسوبة من التكلفة، فلازم تتبني تاني بعد التعديل
    stock_svc.rebuild_levels(db, prop.id)
    db.flush()
    return changed


# ═══════════════════════════════════════════════════ دليل الحسابات
#: (كود، عربي، إنجليزي، النوع، طرفي؟)
#: الترقيم المصري المتعارف عليه: 1 أصول · 2 التزامات · 3 ملكية · 4 إيراد · 5 مصروف
ACCOUNTS: list[tuple[str, str, str, AccountType, bool]] = [
    # ── الأصول ──
    ("1", "الأصول", "Assets", AccountType.ASSET, False),
    ("11", "النقدية وما في حكمها", "Cash and equivalents", AccountType.ASSET, False),
    ("1110", "الخزينة", "Cash on hand", AccountType.ASSET, True),
    ("1120", "البنك", "Bank", AccountType.ASSET, True),
    ("1130", "شيكات تحت التحصيل", "Cheques in hand", AccountType.ASSET, True),
    ("12", "المدينون", "Receivables", AccountType.ASSET, False),
    ("1210", "حسابات النزلاء", "Guest ledger", AccountType.ASSET, True),
    ("1220", "حسابات الشركات والقنوات", "City ledger", AccountType.ASSET, True),
    ("13", "المخزون", "Inventory", AccountType.ASSET, False),
    ("1310", "مخزون أغذية ومشروبات", "F&B inventory", AccountType.ASSET, True),
    ("1320", "مخزون مستهلكات", "Supplies inventory", AccountType.ASSET, True),
    ("14", "الأصول الثابتة", "Fixed assets", AccountType.ASSET, False),
    ("1410", "مبانٍ ومنشآت", "Buildings", AccountType.ASSET, True),
    ("1420", "أثاث وتجهيزات", "Furniture and equipment", AccountType.ASSET, True),
    # ── الالتزامات ──
    ("2", "الالتزامات", "Liabilities", AccountType.LIABILITY, False),
    ("21", "الدائنون", "Payables", AccountType.LIABILITY, False),
    ("2110", "الموردون", "Suppliers", AccountType.LIABILITY, True),
    ("22", "المستحقات", "Accruals", AccountType.LIABILITY, False),
    ("2210", "ضريبة القيمة المضافة المستحقة", "VAT payable", AccountType.LIABILITY, True),
    ("2230", "الخدمة المستحقة للعاملين", "Service charge payable", AccountType.LIABILITY, True),
    ("2410", "مرتبات مستحقة", "Salaries payable", AccountType.LIABILITY, True),
    ("2420", "التأمينات الاجتماعية مستحقة", "Social insurance payable", AccountType.LIABILITY, True),
    ("2430", "ضريبة كسب العمل مستحقة", "Payroll tax payable", AccountType.LIABILITY, True),
    # ── حقوق الملكية ──
    ("3", "حقوق الملكية", "Equity", AccountType.EQUITY, False),
    ("3100", "رأس المال", "Capital", AccountType.EQUITY, True),
    ("3900", "أرباح محتجزة", "Retained earnings", AccountType.EQUITY, True),
    # ── الإيرادات ──
    ("4", "الإيرادات", "Revenue", AccountType.REVENUE, False),
    ("41", "إيراد الإقامة", "Rooms revenue", AccountType.REVENUE, False),
    ("4110", "إيراد الإقامة", "Room revenue", AccountType.REVENUE, True),
    ("42", "إيراد الأغذية والمشروبات", "F&B revenue", AccountType.REVENUE, False),
    ("4210", "إيراد المأكولات", "Food revenue", AccountType.REVENUE, True),
    ("4220", "إيراد المشروبات", "Beverage revenue", AccountType.REVENUE, True),
    ("43", "إيراد الخدمات", "Service revenue", AccountType.REVENUE, False),
    ("4310", "إيراد السبا", "Spa revenue", AccountType.REVENUE, True),
    ("4320", "إيراد الأنشطة والرحلات", "Activities revenue", AccountType.REVENUE, True),
    ("44", "إيرادات أخرى", "Other revenue", AccountType.REVENUE, False),
    ("4410", "الميني بار", "Minibar", AccountType.REVENUE, True),
    ("4420", "المغسلة", "Laundry", AccountType.REVENUE, True),
    ("4490", "إيرادات متنوعة", "Miscellaneous revenue", AccountType.REVENUE, True),
    ("4910", "غرامات إلغاء وعدم حضور", "Cancellation and no-show fees", AccountType.REVENUE, True),
    # ── المصروفات ──
    ("5", "المصروفات", "Expenses", AccountType.EXPENSE, False),
    ("51", "تكلفة المبيعات", "Cost of sales", AccountType.EXPENSE, False),
    ("5110", "تكلفة المأكولات", "Food cost", AccountType.EXPENSE, True),
    ("5120", "تكلفة المشروبات", "Beverage cost", AccountType.EXPENSE, True),
    ("5190", "الهالك وفروق الجرد", "Waste and stock variance", AccountType.EXPENSE, True),
    ("52", "تكاليف العاملين", "Payroll costs", AccountType.EXPENSE, False),
    ("5210", "المرتبات والأجور", "Salaries and wages", AccountType.EXPENSE, True),
    ("5220", "حصة صاحب العمل — تأمينات", "Employer social insurance", AccountType.EXPENSE, True),
    ("5230", "الخدمة الموزّعة على العاملين", "Service charge distributed", AccountType.EXPENSE, True),
    ("53", "مصروفات التشغيل", "Operating expenses", AccountType.EXPENSE, False),
    ("5310", "الكهرباء والمياه", "Utilities", AccountType.EXPENSE, True),
    ("5320", "الصيانة والإصلاح", "Repairs and maintenance", AccountType.EXPENSE, True),
    ("5410", "عمولات القنوات", "Channel commissions", AccountType.EXPENSE, True),
    ("5510", "الضيافة والمجاملات", "Complimentary", AccountType.EXPENSE, True),
    ("5610", "الخصومات الممنوحة", "Discounts given", AccountType.EXPENSE, True),
    ("5910", "مصروفات إدارية", "Administrative expenses", AccountType.EXPENSE, True),
]

#: (كود، عربي، إنجليزي، كود المنفذ المرتبط)
COST_CENTERS: list[tuple[str, str, str, str | None]] = [
    ("ROOMS", "الإقامة", "Rooms", None),
    ("FNB", "الأغذية والمشروبات", "Food and beverage", "REST"),
    ("SPA", "السبا", "Spa", "SPA"),
    ("ACT", "الأنشطة", "Activities", None),
    ("ADMIN", "الإدارة", "Administration", None),
]


def create_chart_of_accounts(
    db: Session, prop: Property, outlets: dict[str, Outlet]
) -> tuple[int, int]:
    """دليل الحسابات ومراكز التكلفة — آمن التكرار.

    الحسابات دي مرجعية: كود الترحيل بينادي عليها بالكود النصّي، فلو
    واحد اتشال الترحيل بيقع بصوت عالي بدل ما يترحّل في حساب غلط.
    """
    have = {
        a.code: a
        for a in db.execute(
            select(Account).where(Account.property_id == prop.id)
        ).scalars().all()
    }
    made = 0
    for order, (code, name_ar, name_en, kind, postable) in enumerate(ACCOUNTS):
        if code in have:
            continue
        parent = have.get(code[:-2]) or have.get(code[:1]) if len(code) > 1 else None
        account = Account(
            property_id=prop.id,
            code=code,
            name_ar=name_ar,
            name_en=name_en,
            account_type=kind,
            parent_id=parent.id if parent else None,
            is_postable=postable,
            is_system=True,
            sort_order=order,
            is_active=True,
        )
        db.add(account)
        have[code] = account
        made += 1
    db.flush()

    have_centers = {
        c.code
        for c in db.execute(
            select(CostCenter).where(CostCenter.property_id == prop.id)
        ).scalars().all()
    }
    made_centers = 0
    for order, (code, name_ar, name_en, outlet_code) in enumerate(COST_CENTERS):
        if code in have_centers:
            continue
        db.add(
            CostCenter(
                property_id=prop.id,
                code=code,
                name_ar=name_ar,
                name_en=name_en,
                outlet_id=outlets[outlet_code].id if outlet_code in outlets else None,
                sort_order=order,
                is_active=True,
            )
        )
        made_centers += 1
    db.flush()
    return made, made_centers


# ═══════════════════════════════════════════════════ العاملون
#: (كود، عربي، إنجليزي، مركز التكلفة)
DEPARTMENTS: list[tuple[str, str, str, str]] = [
    ("FO", "الاستقبال", "Front office", "ROOMS"),
    ("HK", "الإشراف الداخلي", "Housekeeping", "ROOMS"),
    ("FNB", "الأغذية والمشروبات", "Food and beverage", "FNB"),
    ("KIT", "المطبخ", "Kitchen", "FNB"),
    ("ENG", "الصيانة", "Engineering", "ADMIN"),
    ("SPA", "السبا والأنشطة", "Spa and activities", "SPA"),
    ("ADM", "الإدارة والحسابات", "Administration", "ADMIN"),
    ("SEC", "الأمن", "Security", "ADMIN"),
]

#: (كود القسم، الوظيفة عربي، إنجليزي، العدد، الأساسي، البدلات، نقاط الخدمة)
#: المرتبات على مستويات السوق المصري لقرية سياحية متوسطة
STAFF_PLAN: list[tuple[str, str, str, int, str, str, str]] = [
    ("ADM", "المدير العام", "General manager", 1, "45000", "12000", "3"),
    ("ADM", "مدير مالي", "Financial controller", 1, "28000", "6000", "2"),
    ("ADM", "محاسب", "Accountant", 2, "12000", "2500", "1.5"),
    ("ADM", "أخصائي موارد بشرية", "HR specialist", 1, "11000", "2000", "1.5"),
    ("FO", "مدير الاستقبال", "Front office manager", 1, "18000", "4000", "2.5"),
    ("FO", "موظف استقبال", "Receptionist", 6, "7500", "1800", "1.5"),
    ("FO", "حجوزات", "Reservations agent", 2, "8000", "1800", "1.5"),
    ("FO", "بل بوي", "Bell boy", 3, "5000", "1200", "1"),
    ("HK", "سوبرفايزر إشراف داخلي", "Housekeeping supervisor", 2, "9000", "2000", "1.5"),
    ("HK", "عامل نظافة", "Room attendant", 14, "5000", "1200", "1"),
    ("HK", "عامل غسيل", "Laundry attendant", 3, "5000", "1000", "1"),
    ("FNB", "مدير المطعم", "Restaurant manager", 1, "16000", "3500", "2.5"),
    ("FNB", "كابتن", "Captain", 3, "8000", "1800", "2"),
    ("FNB", "ويتر", "Waiter", 12, "5200", "1200", "1.5"),
    ("FNB", "بارتندر", "Bartender", 3, "6500", "1500", "1.5"),
    ("FNB", "كاشير", "Cashier", 3, "6500", "1500", "1"),
    ("KIT", "شيف تنفيذي", "Executive chef", 1, "24000", "5000", "3"),
    ("KIT", "سو شيف", "Sous chef", 2, "13000", "2800", "2"),
    ("KIT", "طباخ", "Line cook", 8, "7000", "1600", "1.5"),
    ("KIT", "مساعد مطبخ", "Kitchen helper", 6, "4800", "1000", "1"),
    ("KIT", "أمين مخزن", "Storekeeper", 2, "7000", "1500", "1"),
    ("ENG", "مهندس صيانة", "Maintenance engineer", 1, "15000", "3200", "2"),
    ("ENG", "فني تكييف", "AC technician", 2, "7500", "1600", "1"),
    ("ENG", "فني كهرباء", "Electrician", 2, "7000", "1500", "1"),
    ("ENG", "فني سباكة", "Plumber", 2, "6800", "1500", "1"),
    ("ENG", "عامل حدائق", "Gardener", 4, "4800", "1000", "1"),
    ("SPA", "مدير السبا", "Spa manager", 1, "14000", "3000", "2"),
    ("SPA", "معالج سبا", "Spa therapist", 4, "7500", "1600", "1.5"),
    ("SPA", "منقذ", "Lifeguard", 3, "5500", "1200", "1"),
    ("SPA", "منسق أنشطة", "Activities coordinator", 2, "6500", "1400", "1.5"),
    ("SEC", "مشرف أمن", "Security supervisor", 1, "9000", "2000", "1"),
    ("SEC", "فرد أمن", "Security guard", 8, "5000", "1100", "1"),
]

#: أسماء لتوليد بيانات العرض
FIRST_NAMES = [
    ("أحمد", "Ahmed"), ("محمد", "Mohamed"), ("محمود", "Mahmoud"), ("مصطفى", "Mostafa"),
    ("كريم", "Karim"), ("عمرو", "Amr"), ("خالد", "Khaled"), ("طارق", "Tarek"),
    ("سيد", "Sayed"), ("حسن", "Hassan"), ("إبراهيم", "Ibrahim"), ("يوسف", "Youssef"),
    ("منى", "Mona"), ("سارة", "Sara"), ("هبة", "Heba"), ("نورا", "Nora"),
    ("دينا", "Dina"), ("مريم", "Mariam"), ("فاطمة", "Fatma"), ("إيمان", "Eman"),
]
LAST_NAMES = [
    ("عبد الرحمن", "Abdelrahman"), ("السيد", "Elsayed"), ("فتحي", "Fathy"),
    ("شعبان", "Shaaban"), ("زكي", "Zaki"), ("رمضان", "Ramadan"), ("عوض", "Awad"),
    ("سليمان", "Soliman"), ("الشناوي", "Elshennawy"), ("منصور", "Mansour"),
    ("الحسيني", "Elhusseiny"), ("بدر", "Badr"), ("سالم", "Salem"), ("قنديل", "Kandil"),
]


def create_staff(db: Session, prop: Property) -> tuple[int, int]:
    """الأقسام والموظفين — آمن التكرار.

    الأسماء بتتولّد من قوايم مصرية عشان داتا العرض تبان طبيعية. الأجر
    التأميني بيتحط مساوي للأساسي وهو العرف الشائع، والحساب بيقصّه على
    الحد الأقصى القانوني لوحده.
    """
    import random

    from app.models.accounting import CostCenter as _CostCenter
    from app.models.enums import ContractType as _ContractType
    from app.models.enums import EmploymentStatus as _Status
    from app.models.enums import Gender as _Gender
    from app.models.hr import Department as _Department
    from app.models.hr import Employee as _Employee

    centers = {
        c.code: c
        for c in db.execute(
            select(_CostCenter).where(_CostCenter.property_id == prop.id)
        ).scalars().all()
    }
    have_departments = {
        d.code: d
        for d in db.execute(
            select(_Department).where(_Department.property_id == prop.id)
        ).scalars().all()
    }
    made_departments = 0
    for order, (code, name_ar, name_en, center_code) in enumerate(DEPARTMENTS):
        if code in have_departments:
            continue
        department = _Department(
            property_id=prop.id, code=code, name_ar=name_ar, name_en=name_en,
            cost_center_id=centers[center_code].id if center_code in centers else None,
            sort_order=order, is_active=True,
        )
        db.add(department)
        have_departments[code] = department
        made_departments += 1
    db.flush()

    have_employees = {
        e.code for e in db.execute(
            select(_Employee).where(_Employee.property_id == prop.id)
        ).scalars().all()
    }
    if have_employees:
        return made_departments, 0

    rng = random.Random(1979)
    today = date.today()
    made = 0
    serial = 0
    for dept_code, title_ar, title_en, count, basic, allowance, points in STAFF_PLAN:
        for _ in range(count):
            serial += 1
            code = f"EMP{serial:03d}"
            if code in have_employees:
                continue
            first_ar, first_en = rng.choice(FIRST_NAMES)
            last_ar, last_en = rng.choice(LAST_NAMES)
            # الأقدمية بتتوزّع على 6 سنين — الإدارة أقدم من العمالة
            senior = Decimal(basic) > Decimal("12000")
            years = rng.uniform(2.0, 6.0) if senior else rng.uniform(0.3, 4.0)
            hire = today - timedelta(days=int(years * 365))
            female = first_ar in {"منى", "سارة", "هبة", "نورا", "دينا", "مريم", "فاطمة", "إيمان"}
            db.add(
                _Employee(
                    property_id=prop.id,
                    code=code,
                    name_ar=f"{first_ar} {last_ar}",
                    name_en=f"{first_en} {last_en}",
                    department_id=have_departments[dept_code].id,
                    job_title_ar=title_ar,
                    job_title_en=title_en,
                    status=(
                        _Status.PROBATION if hire > today - timedelta(days=90)
                        else _Status.ACTIVE
                    ),
                    contract_type=_ContractType.FULL_TIME,
                    gender=_Gender.FEMALE if female else _Gender.MALE,
                    hire_date=hire,
                    basic_salary=Decimal(basic),
                    allowances=Decimal(allowance),
                    insurance_salary=Decimal(basic),
                    service_points=Decimal(points),
                    is_insured=True,
                    phone=f"01{rng.randint(0, 2)}{rng.randint(10000000, 99999999)}",
                    annual_leave_balance=Decimal(21 if years < 10 else 30),
                )
            )
            made += 1
    db.flush()
    return made_departments, made


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


# ═══════════════════════════════════════════ السبا والأنشطة والمناسبات
#: (الكود، النوع، بالعربي، بالإنجليزي، السعة، بداية الوردية، نهايتها)
RESOURCES: list[tuple[str, ResourceKind, str, str, int, str, str]] = [
    ("TH-01", ResourceKind.STAFF, "منى عادل — معالجة", "Mona Adel", 1, "10:00", "20:00"),
    ("TH-02", ResourceKind.STAFF, "هدى صابر — معالجة", "Hoda Saber", 1, "12:00", "22:00"),
    ("TH-03", ResourceKind.STAFF, "عمرو حلمي — معالج", "Amr Helmy", 1, "10:00", "20:00"),
    ("CAB-1", ResourceKind.ROOM, "كابينة ١", "Cabin 1", 1, "10:00", "22:00"),
    ("CAB-2", ResourceKind.ROOM, "كابينة ٢ (زوجية)", "Cabin 2 (couples)", 2, "10:00", "22:00"),
    ("YOGA", ResourceKind.ROOM, "شرفة اليوجا", "Yoga deck", 14, "06:00", "20:00"),
    ("BOAT-1", ResourceKind.EQUIPMENT, "مركب النيل ١", "Nile boat 1", 10, "08:00", "20:00"),
    ("BOAT-2", ResourceKind.EQUIPMENT, "مركب النيل ٢", "Nile boat 2", 8, "08:00", "20:00"),
    ("KAYAK", ResourceKind.EQUIPMENT, "أسطول الكياك", "Kayak fleet", 6, "07:00", "18:00"),
    ("GUIDE", ResourceKind.STAFF, "مرشد الرحلات", "Excursion guide", 20, "06:00", "18:00"),
]

#: (الكود، بالعربي، بالإنجليزي، الفئة، المدة، التجهيز، السعر، سعر الطفل،
#:  التكلفة، السعة، الفتح، القفل، الموارد)
SERVICES: list[tuple] = [
    ("SPA-SWED", "مساج سويدي ٦٠ د", "Swedish massage 60min", ServiceCategory.SPA,
     60, 20, "950", "0", "180", 1, "10:00", "22:00", ["TH-01", "TH-02", "TH-03"]),
    ("SPA-DEEP", "مساج علاجي ٩٠ د", "Deep tissue 90min", ServiceCategory.SPA,
     90, 20, "1400", "0", "240", 1, "10:00", "22:00", ["TH-01", "TH-03"]),
    ("SPA-HOT", "الحجر الساخن", "Hot stone therapy", ServiceCategory.SPA,
     75, 25, "1250", "0", "260", 1, "12:00", "22:00", ["TH-02"]),
    ("SPA-COUP", "جلسة زوجية", "Couples ritual", ServiceCategory.SPA,
     90, 30, "2400", "0", "480", 2, "12:00", "21:00", ["CAB-2"]),
    ("SPA-FACE", "تنظيف بشرة", "Signature facial", ServiceCategory.SPA,
     45, 15, "700", "0", "160", 1, "10:00", "20:00", ["TH-02", "TH-01"]),
    ("FIT-YOGA", "يوجا الشروق", "Sunrise yoga", ServiceCategory.FITNESS,
     60, 15, "180", "120", "40", 14, "06:00", "09:00", ["YOGA"]),
    ("ACT-SUNSET", "رحلة الغروب بالمركب", "Sunset boat cruise", ServiceCategory.ACTIVITY,
     90, 30, "450", "250", "110", 10, "16:00", "20:00", ["BOAT-1", "BOAT-2"]),
    ("ACT-FISH", "رحلة صيد الفجر", "Dawn fishing trip", ServiceCategory.ACTIVITY,
     180, 45, "800", "500", "220", 8, "05:00", "12:00", ["BOAT-2"]),
    ("ACT-KAYAK", "كياك على البحيرة", "Lake kayaking", ServiceCategory.ACTIVITY,
     60, 15, "300", "200", "45", 6, "07:00", "18:00", ["KAYAK"]),
    ("EXC-FAYOUM", "رحلة وادي الريان", "Wadi El-Rayan excursion", ServiceCategory.EXCURSION,
     360, 60, "1200", "700", "420", 20, "07:00", "18:00", ["GUIDE"]),
    ("EXC-DESERT", "سفاري الصحرا وقت الغروب", "Desert sunset safari", ServiceCategory.EXCURSION,
     240, 60, "900", "550", "320", 16, "14:00", "21:00", ["GUIDE"]),
    ("KID-CLUB", "نادي الأطفال — نص يوم", "Kids club half day", ServiceCategory.KIDS,
     240, 30, "0", "350", "90", 12, "10:00", "18:00", ["YOGA"]),
]

#: (الكود، بالعربي، بالإنجليزي، النوع، جلوس، وقوف، متر، سعر اليوم، الساعة،
#:  الحد الأدنى للإنفاق)
VENUES: list[tuple] = [
    ("V-LAWN", "حديقة البحيرة", "Lakeside lawn", VenueKind.LAWN,
     400, 600, 1200, "45000", "0", "220000"),
    ("V-HALL", "قاعة فينيسيا الكبرى", "Venicia grand hall", VenueKind.HALL,
     300, 450, 700, "60000", "0", "280000"),
    ("V-BEACH", "شاطئ المناسبات", "Event beach", VenueKind.BEACH,
     150, 250, 800, "28000", "0", "120000"),
    ("V-TERR", "تراس الغروب", "Sunset terrace", VenueKind.TERRACE,
     80, 120, 240, "15000", "0", "45000"),
    ("V-MEET", "قاعة الاجتماعات", "Boardroom", VenueKind.MEETING,
     40, 60, 90, "9000", "1500", "0"),
]


def _clock(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(int(hour), int(minute))


def create_leisure(db: Session, prop: Property) -> tuple[int, int, int]:
    """السبا والأنشطة وأماكن المناسبات — آمن التكرار."""
    resources = {
        r.code: r
        for r in db.execute(
            select(ServiceResourceItem).where(
                ServiceResourceItem.property_id == prop.id
            )
        ).scalars().all()
    }
    made_resources = 0
    for code, kind, name_ar, name_en, capacity, start, end in RESOURCES:
        if code in resources:
            continue
        row = ServiceResourceItem(
            property_id=prop.id, code=code, kind=kind, name_ar=name_ar,
            name_en=name_en, capacity=capacity,
            shift_start=_clock(start), shift_end=_clock(end), is_active=True,
        )
        db.add(row)
        resources[code] = row
        made_resources += 1
    db.flush()

    existing_services = {
        s.code: s
        for s in db.execute(
            select(Service).where(Service.property_id == prop.id)
        ).scalars().all()
    }
    made_services = 0
    for order, row in enumerate(SERVICES):
        (code, name_ar, name_en, category, duration, buffer, price, price_child,
         cost, capacity, opens, closes, resource_codes) = row
        if code in existing_services:
            continue
        service = Service(
            property_id=prop.id, code=code, name_ar=name_ar, name_en=name_en,
            category=category, duration_minutes=duration, buffer_minutes=buffer,
            price=Decimal(price), price_child=Decimal(price_child),
            unit_cost=Decimal(cost), capacity=capacity,
            requires_resource=True,
            opens_at=_clock(opens), closes_at=_clock(closes),
            sort_order=order, is_active=True,
        )
        service.resources = [
            resources[c] for c in resource_codes if c in resources
        ]
        db.add(service)
        made_services += 1
    db.flush()

    existing_venues = {
        v.code for v in db.execute(
            select(Venue).where(Venue.property_id == prop.id)
        ).scalars().all()
    }
    made_venues = 0
    for order, row in enumerate(VENUES):
        (code, name_ar, name_en, kind, seated, standing, area, day_rate,
         hourly, minimum) = row
        if code in existing_venues:
            continue
        db.add(
            Venue(
                property_id=prop.id, code=code, name_ar=name_ar, name_en=name_en,
                kind=kind, capacity_seated=seated, capacity_standing=standing,
                area_sqm=area, day_rate=Decimal(day_rate),
                hourly_rate=Decimal(hourly), minimum_spend=Decimal(minimum),
                sort_order=order, is_active=True,
            )
        )
        made_venues += 1
    db.flush()
    return made_resources, made_services, made_venues


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
    # ``plans`` قاموس بالكود — لازم نمشي على القيم مش المفاتيح
    ordered = list(plans.values())
    public_plan = next((p for p in ordered if p.is_public), ordered[0] if ordered else None)
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
def run(
    years_back: int = 2, months_forward: int = 6, reset_costs: bool = False
) -> None:
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

        print("المخازن والموردين والأصناف...")
        made_wh, made_sup, made_item = create_warehouses(db, prop, outlets)

        reset_items = 0
        if reset_costs:
            print("رجوع تكاليف الأصناف لأسعار البذرة...")
            reset_items = reset_stock_costs(db, prop)

        print("دليل الحسابات ومراكز التكلفة...")
        made_accounts, made_centers = create_chart_of_accounts(db, prop, outlets)

        print("الأقسام والعاملون...")
        made_departments, made_staff = create_staff(db, prop)

        print("الميني بار...")
        minibar_items = create_minibar(db, prop)

        print("السبا والأنشطة وأماكن المناسبات...")
        made_resources, made_services, made_venues = create_leisure(db, prop)

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
        print(
            f"  السبا والأنشطة       {made_services} خدمة  ·  {made_resources} مورد"
            f"  ·  {made_venues} مكان مناسبات"
        )
        print(f"  المخازن              {made_wh}  ·  موردين {made_sup}  ·  أصناف {made_item}")
        print(f"  دليل الحسابات        {made_accounts}  ·  مراكز تكلفة {made_centers}")
        print(f"  الأقسام              {made_departments}  ·  العاملون {made_staff}")
        if reset_costs:
            print(f"  تكاليف اترجّعت       {reset_items} صنف")
        print(f"  أسعار منشورة         {published:,}")
        print(f"  صفوف عدّاد الإتاحة   {slots:,}")
        print("─" * 52)
        print()
        print("  دخول:  owner / venicia2026")
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    # ``--reset-costs`` بيرجّع متوسط تكلفة الأصناف لأسعار البذرة. مطلوب
    # بعد تشغيلات اختبار كتير لأنها بتستلم بضاعة بسعر أعلى فالمتوسط بيتراكم.
    run(reset_costs="--reset-costs" in sys.argv)
