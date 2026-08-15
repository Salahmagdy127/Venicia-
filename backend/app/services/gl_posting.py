"""الترحيل التلقائي للدفتر — Operational activity → double-entry journals.

الملف ده هو الجسر. الموظف في الاستقبال مبيعرفش يعني إيه «مدين ودائن»،
والكاشير كمان. هما بيعملوا شغلهم — بيرحّلوا ليلة، بيقفلوا أوردر، بيستلموا
فاتورة مورد — والملف ده بيقرا الحركة دي آخر اليوم ويحوّلها قيود.

**قرار معماري:** الترحيل بيتم في دفعة يومية مش لحظة بلحظة. السبب عملي:
الأوردر وهو مفتوح ممكن يتعدّل أو يتلغي، والليلة ممكن تتعكس، فالترحيل
اللحظي كان هيملا الدفتر بقيود وعكوسها. الدفعة اليومية بتترحّل بعد ما
اليوم يقفل، فاللي بيتكتب هو الخلاصة النهائية.

**التكرار مستحيل**: كل قيد بيتولّد بمفتاح مصدر فريد، والقيد بيترفض لو
المفتاح موجود. يعني تشغيل النايت أوديت مرتين على نفس اليوم مبيكرّرش
ولا مليم.

**والمعادلة اللي بتثبت إن الربط صح:** قيمة المخزون في المركز المالي
لازم تساوي بالظبط قيمة المخزون في شاشة المخازن — لأن الاتنين اتولّدوا
من نفس الحركة.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    CREDIT_CHARGE_KINDS,
    ChargeKind,
    JournalSource,
    MovementKind,
    OutletType,
    PaymentMethod,
    PosOrderStatus,
    SettlementType,
)
from app.models.folio import FolioLine, Payment
from app.models.pos import Outlet, PosOrder
from app.models.security import User
from app.models.stock import StockItem, StockMovement
from app.services.accounting import Entry, credit, debit, post
from app.services.pricing import money

ZERO = Decimal("0")


# ═══════════════════════════════════════════════════ خريطة الحسابات
#: نوع الحركة على حساب النزيل ← حساب الإيراد
REVENUE_ACCOUNT: dict[ChargeKind, str] = {
    ChargeKind.ROOM: "4110",
    ChargeKind.FNB: "4210",
    ChargeKind.SPA: "4310",
    ChargeKind.ACTIVITY: "4320",
    ChargeKind.MINIBAR: "4410",
    ChargeKind.LAUNDRY: "4420",
    ChargeKind.TELEPHONE: "4490",
    ChargeKind.CITY_TAX: "4490",
    ChargeKind.ADJUSTMENT: "4490",
    ChargeKind.CANCELLATION_FEE: "4910",
    ChargeKind.NO_SHOW_FEE: "4910",
}

#: مركز التكلفة اللي الإيراد بينتسب له
REVENUE_CENTER: dict[ChargeKind, str] = {
    ChargeKind.ROOM: "ROOMS",
    ChargeKind.FNB: "FNB",
    ChargeKind.SPA: "SPA",
    ChargeKind.ACTIVITY: "ACT",
    ChargeKind.MINIBAR: "ROOMS",
    ChargeKind.LAUNDRY: "ROOMS",
}

#: طريقة الدفع ← الحساب اللي الفلوس بتدخله
CASH_ACCOUNT: dict[PaymentMethod, str] = {
    PaymentMethod.CASH: "1110",
    PaymentMethod.CARD: "1120",
    PaymentMethod.FAWRY: "1120",
    PaymentMethod.PAYMOB: "1120",
    PaymentMethod.INSTAPAY: "1120",
    PaymentMethod.BANK_TRANSFER: "1120",
    PaymentMethod.CHEQUE: "1130",
    # الآجل مش فلوس — بيتحوّل من حساب النزيل لحساب الشركة
    PaymentMethod.CITY_LEDGER: "1220",
    # المحصّل من القناة لسه عندها — مديونية علينا لها
    PaymentMethod.OTA_PREPAID: "1220",
    # الضيافة مصروف مش تحصيل
    PaymentMethod.COMPLIMENTARY: "5510",
}

GUEST_LEDGER = "1210"
CITY_LEDGER = "1220"
VAT_PAYABLE = "2210"
SERVICE_PAYABLE = "2230"
SUPPLIERS = "2110"
DISCOUNTS_GIVEN = "5610"
COMPLIMENTARY_EXPENSE = "5510"

#: تصنيف الصنف المخزني ← حساب المخزون وحساب التكلفة
BEVERAGE_CATEGORIES = frozenset({"مشروبات"})
SUPPLY_CATEGORIES = frozenset({"مستهلكات", "نظافة"})


def _inventory_account(category_ar: str) -> str:
    return "1320" if category_ar in SUPPLY_CATEGORIES else "1310"


def _cogs_account(category_ar: str) -> str:
    if category_ar in BEVERAGE_CATEGORIES:
        return "5120"
    if category_ar in SUPPLY_CATEGORIES:
        return "5910"
    return "5110"


@dataclass(slots=True)
class PostingResult:
    """حصيلة ترحيل يوم — بتتعرض في النايت أوديت وشاشة الحسابات."""

    business_date: date
    entries: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total_debit: Decimal = ZERO
    errors: list[str] = field(default_factory=list)

    @property
    def posted(self) -> int:
        return len(self.entries)


# ═══════════════════════════════════════════════════ 1) الإيراد من حساب النزيل
def post_folio_revenue(
    db: Session, property_id: int, business_date: date, *, user: User | None = None
):
    """ليالي الإقامة والترحيلات على الغرف ← إيراد + مديونية نزلاء.

    الدفعات مش بتتقرا من هنا رغم إنها بتظهر كسطور على الحساب — دي
    بتترحّل من جدول الدفعات اللي فيه طريقة الدفع. لو قريناها من
    المكانين كنا هنعدّ الفلوس مرتين.
    """
    lines = list(
        db.execute(
            select(FolioLine).where(
                FolioLine.property_id == property_id,
                FolioLine.business_date == business_date,
                FolioLine.is_void.is_(False),
            )
        ).scalars().all()
    )
    if not lines:
        return None

    revenue: dict[ChargeKind, Decimal] = defaultdict(lambda: ZERO)
    service = ZERO
    tax = ZERO
    discount = ZERO
    receivable = ZERO

    for line in lines:
        if line.charge_kind == ChargeKind.DISCOUNT:
            # الخصم بيقلّل مديونية النزيل وبيتحمّل كمصروف — مش إيراد بالسالب
            discount += abs(line.total_amount)
            receivable -= abs(line.total_amount)
            continue
        if line.charge_kind in CREDIT_CHARGE_KINDS:
            continue  # دفعة أو استرداد — بتترحّل من جدول الدفعات

        revenue[line.charge_kind] += line.amount
        service += line.service_charge_amount
        tax += line.tax_amount
        receivable += line.total_amount

    entries: list[Entry] = []
    if receivable:
        entries.append(
            debit(GUEST_LEDGER, receivable, "مديونية النزلاء عن اليوم", cost_center_code="ROOMS")
        )
    if discount:
        entries.append(debit(DISCOUNTS_GIVEN, discount, "خصومات ممنوحة"))

    for kind, amount in revenue.items():
        if not amount:
            continue
        entries.append(
            credit(
                REVENUE_ACCOUNT.get(kind, "4490"),
                amount,
                f"إيراد {kind}",
                cost_center_code=REVENUE_CENTER.get(kind, "ADMIN"),
            )
        )
    if service:
        entries.append(credit(SERVICE_PAYABLE, service, "خدمة 12% مستحقة للعاملين"))
    if tax:
        entries.append(credit(VAT_PAYABLE, tax, "ضريبة القيمة المضافة المستحقة"))

    return post(
        db,
        property_id,
        business_date=business_date,
        lines=entries,
        description_ar=f"إيراد الإقامة والترحيلات — {business_date}",
        description_en=f"Room and folio revenue — {business_date}",
        source=JournalSource.ROOM_REVENUE,
        source_key=str(business_date),
        user=user,
        skip_if_duplicate=True,
    )


# ═══════════════════════════════════════════════════ 2) إيراد نقاط البيع
def post_pos_revenue(
    db: Session, property_id: int, business_date: date, *, user: User | None = None
):
    """الأوردرات المتحاسبة كاش أو كارت.

    الأوردرات المرحّلة على الغرفة مش بتتقرا هنا — دي بقت سطر على حساب
    النزيل واترحّلت مع إيراد الفوليو.
    """
    rows = db.execute(
        select(PosOrder, Outlet)
        .join(Outlet, Outlet.id == PosOrder.outlet_id)
        .where(
            PosOrder.property_id == property_id,
            PosOrder.business_date == business_date,
            PosOrder.status == PosOrderStatus.SETTLED,
            PosOrder.is_void.is_(False),
            PosOrder.settlement_type != SettlementType.ROOM_CHARGE,
        )
    ).all()
    if not rows:
        return None

    by_account: dict[str, Decimal] = defaultdict(lambda: ZERO)
    food = ZERO
    beverage = ZERO
    spa = ZERO
    service = ZERO
    tax = ZERO
    discount = ZERO

    for order, outlet in rows:
        # الإيراد بيتقيّد بالسعر الكامل والخصم بيتحمّل مصروف لوحده —
        # كده حساب الخصومات بيقول آخر الشهر «إدّينا كام»، بدل ما الخصم
        # يختفي جوه رقم الإيراد ومحدش يشوفه
        gross = order.subtotal
        if outlet.outlet_type == OutletType.SPA:
            spa += gross
        elif outlet.outlet_type == OutletType.BAR:
            beverage += gross
        else:
            food += gross

        service += order.service_charge_total
        tax += order.tax_total
        discount += order.discount_total

        settlement = order.settlement_type
        if settlement == SettlementType.CASH:
            by_account["1110"] += order.grand_total
        elif settlement == SettlementType.CARD:
            by_account["1120"] += order.grand_total
        elif settlement == SettlementType.CITY_LEDGER:
            by_account[CITY_LEDGER] += order.grand_total
        else:
            # ضيافة أو على الموظفين — مصروف مش تحصيل
            by_account[COMPLIMENTARY_EXPENSE] += order.grand_total

    entries: list[Entry] = [
        debit(code, amount, "تحصيل نقاط البيع", cost_center_code="FNB")
        for code, amount in by_account.items()
        if amount
    ]
    if discount:
        entries.append(debit(DISCOUNTS_GIVEN, discount, "خصومات نقاط البيع"))
    if food:
        entries.append(credit("4210", food, "إيراد المأكولات", cost_center_code="FNB"))
    if beverage:
        entries.append(credit("4220", beverage, "إيراد المشروبات", cost_center_code="FNB"))
    if spa:
        entries.append(credit("4310", spa, "إيراد السبا", cost_center_code="SPA"))
    if service:
        entries.append(credit(SERVICE_PAYABLE, service, "خدمة 12% مستحقة للعاملين"))
    if tax:
        entries.append(credit(VAT_PAYABLE, tax, "ضريبة القيمة المضافة المستحقة"))

    if not entries:
        return None

    return post(
        db,
        property_id,
        business_date=business_date,
        lines=entries,
        description_ar=f"إيراد نقاط البيع — {business_date}",
        description_en=f"Point of sale revenue — {business_date}",
        source=JournalSource.POS_REVENUE,
        source_key=str(business_date),
        user=user,
        skip_if_duplicate=True,
    )


# ═══════════════════════════════════════════════════ 3) التحصيل
def post_payments(
    db: Session, property_id: int, business_date: date, *, user: User | None = None
):
    """الدفعات على حسابات النزلاء ← نقدية أو بنك مقابل تقليل المديونية.

    دفعات نقاط البيع مستبعدة — الأوردر بتاعها اترحّل بالكامل في قيد
    نقاط البيع، فلو حسبناها هنا كمان كانت الفلوس هتتعدّ مرتين.
    """
    payments = list(
        db.execute(
            select(Payment).where(
                Payment.property_id == property_id,
                Payment.business_date == business_date,
                Payment.is_void.is_(False),
                Payment.pos_order_id.is_(None),
            )
        ).scalars().all()
    )
    if not payments:
        return None

    received: dict[str, Decimal] = defaultdict(lambda: ZERO)
    refunded: dict[str, Decimal] = defaultdict(lambda: ZERO)

    for payment in payments:
        account = CASH_ACCOUNT.get(payment.method, "1110")
        amount = money(payment.amount_base or payment.amount)
        if payment.is_refund:
            refunded[account] += amount
        else:
            received[account] += amount

    net_receivable = money(
        sum(received.values(), ZERO) - sum(refunded.values(), ZERO)
    )

    entries: list[Entry] = []
    for account, amount in received.items():
        if amount:
            entries.append(debit(account, amount, "تحصيل"))
    for account, amount in refunded.items():
        if amount:
            entries.append(credit(account, amount, "استرداد"))

    if net_receivable > 0:
        entries.append(credit(GUEST_LEDGER, net_receivable, "سداد على حسابات النزلاء"))
    elif net_receivable < 0:
        entries.append(debit(GUEST_LEDGER, -net_receivable, "استرداد لحسابات النزلاء"))

    if not entries:
        return None

    return post(
        db,
        property_id,
        business_date=business_date,
        lines=entries,
        description_ar=f"تحصيلات اليوم — {business_date}",
        description_en=f"Daily collections — {business_date}",
        source=JournalSource.PAYMENT,
        source_key=str(business_date),
        user=user,
        skip_if_duplicate=True,
    )


# ═══════════════════════════════════════════════════ 4) المشتريات
def post_purchases(
    db: Session, property_id: int, business_date: date, *, user: User | None = None
):
    """استلام البضاعة ← مخزون مدين وموردون دائن.

    القيد بيتولّد من حركة المخزن مش من أمر الشراء، لأن اللي بيتحاسب
    عليه هو اللي وصل فعلاً — الاستلام الجزئي بيرحّل الجزء بس.
    """
    rows = db.execute(
        select(StockMovement, StockItem)
        .join(StockItem, StockItem.id == StockMovement.stock_item_id)
        .where(
            StockMovement.property_id == property_id,
            StockMovement.business_date == business_date,
            StockMovement.kind == MovementKind.PURCHASE,
        )
    ).all()
    if not rows:
        return None

    by_account: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for movement, item in rows:
        by_account[_inventory_account(item.category_ar)] += movement.total_cost

    total = money(sum(by_account.values(), ZERO))
    if not total:
        return None

    entries = [
        debit(code, amount, "استلام مشتريات") for code, amount in by_account.items() if amount
    ]
    entries.append(credit(SUPPLIERS, total, "مستحقات الموردين"))

    return post(
        db,
        property_id,
        business_date=business_date,
        lines=entries,
        description_ar=f"استلام مشتريات — {business_date}",
        description_en=f"Goods received — {business_date}",
        source=JournalSource.PURCHASE,
        source_key=str(business_date),
        user=user,
        skip_if_duplicate=True,
    )


# ═══════════════════════════════════════════════════ 5) تكلفة المبيعات
def post_consumption(
    db: Session, property_id: int, business_date: date, *, user: User | None = None
):
    """الصرف من المخزن ← تكلفة مبيعات مدينة والمخزون دائن.

    ده الرقم اللي كان بيتكتب بالإيد في كل مكان تاني. هنا بيتولّد من
    الوصفات: باع كام طبق، الطبق فيه كام جرام، الجرام بكام.
    """
    rows = db.execute(
        select(StockMovement, StockItem)
        .join(StockItem, StockItem.id == StockMovement.stock_item_id)
        .where(
            StockMovement.property_id == property_id,
            StockMovement.business_date == business_date,
            StockMovement.kind == MovementKind.ISSUE,
        )
    ).all()
    if not rows:
        return None

    cost: dict[str, Decimal] = defaultdict(lambda: ZERO)
    inventory: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for movement, item in rows:
        cost[_cogs_account(item.category_ar)] += movement.total_cost
        inventory[_inventory_account(item.category_ar)] += movement.total_cost

    if not money(sum(cost.values(), ZERO)):
        return None

    entries = [
        debit(code, amount, "تكلفة المبيعات", cost_center_code="FNB")
        for code, amount in cost.items()
        if amount
    ]
    entries += [
        credit(code, amount, "صرف من المخزن") for code, amount in inventory.items() if amount
    ]

    return post(
        db,
        property_id,
        business_date=business_date,
        lines=entries,
        description_ar=f"تكلفة المبيعات — {business_date}",
        description_en=f"Cost of sales — {business_date}",
        source=JournalSource.CONSUMPTION,
        source_key=str(business_date),
        user=user,
        skip_if_duplicate=True,
    )


# ═══════════════════════════════════════════════════ 6) الهالك وفروق الجرد
def post_waste(
    db: Session, property_id: int, business_date: date, *, user: User | None = None
):
    """الهالك وتسويات الجرد ← مصروف مقابل تخفيض المخزون.

    التسوية بالزيادة بتتقيّد بالعكس — مخزون مدين ومصروف الهالك دائن —
    فحساب الهالك آخر الشهر بيقول الصافي: اللي ضاع ناقص اللي ظهر.
    """
    rows = db.execute(
        select(StockMovement, StockItem)
        .join(StockItem, StockItem.id == StockMovement.stock_item_id)
        .where(
            StockMovement.property_id == property_id,
            StockMovement.business_date == business_date,
            StockMovement.kind.in_([MovementKind.WASTE, MovementKind.ADJUSTMENT]),
        )
    ).all()
    if not rows:
        return None

    #: موجب = نقص (هالك) · سالب = زيادة ظهرت في الجرد
    net: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for movement, item in rows:
        sign = 1 if movement.kind == MovementKind.WASTE else -1
        net[_inventory_account(item.category_ar)] += sign * movement.total_cost

    entries: list[Entry] = []
    total_loss = ZERO
    for inventory_account, amount in net.items():
        if not amount:
            continue
        if amount > 0:
            entries.append(credit(inventory_account, amount, "نقص بالجرد"))
        else:
            entries.append(debit(inventory_account, -amount, "زيادة بالجرد"))
        total_loss += amount

    if not entries or not total_loss:
        return None

    if total_loss > 0:
        entries.append(debit("5190", total_loss, "هالك وفروق جرد", cost_center_code="FNB"))
    else:
        entries.append(credit("5190", -total_loss, "رد فروق جرد", cost_center_code="FNB"))

    return post(
        db,
        property_id,
        business_date=business_date,
        lines=entries,
        description_ar=f"الهالك وفروق الجرد — {business_date}",
        description_en=f"Waste and stock variances — {business_date}",
        source=JournalSource.WASTE,
        source_key=str(business_date),
        user=user,
        skip_if_duplicate=True,
    )


# ═══════════════════════════════════════════════════ التشغيل
#: الترتيب مقصود — الإيراد قبل التحصيل، والمخزون قبل التكلفة
STEPS = (
    ("إيراد الإقامة", post_folio_revenue),
    ("إيراد نقاط البيع", post_pos_revenue),
    ("التحصيلات", post_payments),
    ("المشتريات", post_purchases),
    ("تكلفة المبيعات", post_consumption),
    ("الهالك", post_waste),
)


def post_day(
    db: Session, property_id: int, business_date: date, *, user: User | None = None
) -> PostingResult:
    """ترحيل يوم كامل — بيتنادى من النايت أوديت.

    كل خطوة جوه نقطة حفظ لوحدها: لو واحدة وقعت بترجع هي بس والباقي
    بيكمّل، عشان مشكلة في قيد المشتريات متمنعش ترحيل إيراد اليوم —
    ومن غير ما ترجّع القيود اللي اترحّلت قبلها في نفس المعاملة.
    """
    result = PostingResult(business_date=business_date)
    for label, step in STEPS:
        savepoint = db.begin_nested()
        try:
            entry = step(db, property_id, business_date, user=user)
            savepoint.commit()
        except Exception as exc:  # noqa: BLE001 — الخطأ بيتعرض للمحاسب
            savepoint.rollback()
            result.errors.append(f"{label}: {exc}")
            continue
        if entry is None:
            result.skipped.append(label)
        else:
            result.entries.append(entry.number)
            result.total_debit = money(result.total_debit + entry.total_debit)
    return result


#: القيود اللي الملف ده بيولّدها — دي بس اللي إعادة الترحيل بتلمسها
AUTO_SOURCES = (
    JournalSource.ROOM_REVENUE,
    JournalSource.POS_REVENUE,
    JournalSource.PAYMENT,
    JournalSource.PURCHASE,
    JournalSource.CONSUMPTION,
    JournalSource.WASTE,
)


def repost_day(
    db: Session, property_id: int, business_date: date, *, user: User | None = None
) -> PostingResult:
    """إعادة ترحيل يوم بعد ما حصلت فيه حركة متأخرة.

    السيناريو الحقيقي: اليوم اترحّل الساعة 2 الفجر، وبعدها اتسجّل أوردر
    كان ناسي أو استلام مورد متأخر. الترحيل العادي بيتخطّى اليوم لأنه
    مرحّل، فالحركة الجديدة كانت هتفضل بره الدفتر للأبد.

    الحل مش تعديل القيد القديم — ده ممنوع. الحل إن القيود التلقائية
    بتتعكس بقيود مضادة، وبعدين اليوم بيتبني من الأول. الدفتر بيفضل
    شايل الحكاية كاملة: اترحّل، اتعكس، اترحّل تاني.

    القيود اليدوية مبتتلمسش — المحاسب كتبها بإيده ومحدش يلغيها غيره.
    """
    from app.models.accounting import JournalEntry
    from app.models.enums import JournalStatus
    from app.services import accounting as gl

    existing = list(
        db.execute(
            select(JournalEntry).where(
                JournalEntry.property_id == property_id,
                JournalEntry.business_date == business_date,
                JournalEntry.source.in_(list(AUTO_SOURCES)),
                JournalEntry.status == JournalStatus.POSTED,
                JournalEntry.reverses_entry_id.is_(None),
            )
        ).scalars().all()
    )

    for entry in existing:
        gl.reverse(
            db,
            property_id,
            entry.id,
            reason="إعادة ترحيل اليوم بعد حركة متأخرة",
            business_date=business_date,
            user=user,
        )
        # المفتاح بيتفكّ من القيد الملغي عشان البناء الجديد ياخده. القيد
        # نفسه بيفضل مكانه بمفتاحه القديم مكتوب فيه رقمه، فالأثر مش بيضيع.
        entry.source_key = f"{entry.source_key}~{entry.id}"
    db.flush()

    result = post_day(db, property_id, business_date, user=user)
    result.skipped.extend(f"اتعكس {e.number}" for e in existing)
    return result


def post_range(
    db: Session,
    property_id: int,
    since: date,
    until: date,
    *,
    user: User | None = None,
) -> list[PostingResult]:
    """ترحيل فترة — بيستخدم في تحميل التاريخ أول مرة."""
    from datetime import timedelta

    out: list[PostingResult] = []
    day = since
    while day <= until:
        out.append(post_day(db, property_id, day, user=user))
        db.commit()
        day += timedelta(days=1)
    return out
