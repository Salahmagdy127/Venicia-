"""بناء الدفتر المحاسبي لداتا العرض — Ledger seed.

    python -m scripts.seed_ledger

**القرار المعماري اللي الملف ده بيجسّده:** النظام بيبدأ الترحيل من
تاريخ تشغيل محدّد، مش من أول يوم في تاريخ القرية.

السبب مش تعسّف. تكلفة المبيعات بتتولّد من حركة المخزن، وحركة المخزن
موجودة من ``GO_LIVE`` وبس. لو رحّلنا سنتين إيراد من غير تكلفة، قائمة
الدخل هتقول هامش 96% — رقم مالوش أي معنى وبيحرق مصداقية العرض كله.

فبنعمل اللي بيحصل في أي تركيب حقيقي: بندخّل **أرصدة افتتاحية** بتلخّص
وضع القرية يوم التشغيل، وبنرحّل من بعده. والأرصدة دي مش مخترعة —
المخزون بيتحسب بالرجوع للخلف من حركة الفترة، ومديونية النزلاء من
الحسابات اللي كانت لسه مفتوحة.

بيتشغّل بعد ``seed_master`` و``seed_history`` و``seed_live``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.accounting import (
    Account,
    AccountingPeriod,
    JournalEntry,
    JournalLine,
)
from app.models.billing import DocumentSequence
from app.models.channels import Channel
from app.models.enums import (
    INBOUND_MOVEMENTS,
    FolioStatus,
    JournalSource,
)
from app.models.folio import Folio
from app.models.hr import PayrollRun, Payslip
from app.models.organization import Property
from app.models.reservations import Reservation
from app.models.stock import StockLevel, StockMovement
from app.services import accounting as gl
from app.services import gl_posting as posting
from app.services import payroll as pr

#: يوم بدء التشغيل — أول يوم فيه تكلفة مخزنية حقيقية
GO_LIVE = date(2026, 8, 1)

#: الأصول الثابتة ورأس المال — أرقام تقديرية لقرية 78 وحدة على البحيرة
BUILDINGS = Decimal("180000000")
FURNITURE = Decimal("24000000")
OPENING_CASH = Decimal("450000")
OPENING_BANK = Decimal("6800000")
OPENING_SUPPLIERS = Decimal("380000")
CAPITAL = Decimal("150000000")

#: مصروفات شهرية بتتكتب يدوي في الواقع — (الحساب، القيمة الشهرية، البيان)
MONTHLY_EXPENSES: list[tuple[str, Decimal, str]] = [
    ("5310", Decimal("620000"), "كهرباء ومياه"),
    ("5320", Decimal("145000"), "قطع غيار وصيانة"),
    ("5910", Decimal("210000"), "مصروفات إدارية وتأمين ونظافة"),
]

TWO = Decimal("0.01")


def q(value) -> Decimal:
    return Decimal(str(value)).quantize(TWO)


def clear(db: Session, prop: Property) -> None:
    """تفضية الدفتر — مسموحة هنا لأننا بنعيد بناء داتا عرض.

    في التشغيل الحقيقي مفيش حذف: التصحيح بيتم بقيد عكسي بس.
    """
    db.execute(delete(Payslip).where(Payslip.property_id == prop.id))
    db.execute(delete(PayrollRun).where(PayrollRun.property_id == prop.id))
    db.execute(delete(JournalLine).where(JournalLine.property_id == prop.id))
    db.execute(delete(JournalEntry).where(JournalEntry.property_id == prop.id))
    db.execute(delete(AccountingPeriod).where(AccountingPeriod.property_id == prop.id))
    db.execute(
        delete(DocumentSequence).where(
            DocumentSequence.property_id == prop.id,
            DocumentSequence.doc_type.in_(["JOURNAL", "PAYROLL"]),
        )
    )
    for account in db.execute(
        select(Account).where(Account.property_id == prop.id)
    ).scalars():
        account.balance = Decimal("0")
        account.debit_total = Decimal("0")
        account.credit_total = Decimal("0")
    db.commit()


def opening_inventory(db: Session, prop: Property) -> Decimal:
    """قيمة المخزون يوم التشغيل — رصيد النهاردة ناقص حركة الفترة.

    مش الرصيد الحالي زي ما هو: الرصيد الحالي بيشمل مشتريات وصرف حصلوا
    بعد التشغيل. لو حطّيناه افتتاحي كنا هنعدّهم مرتين، والمخزون في
    الميزانية كان هيطلع أعلى من المخزون في المخازن.
    """
    current = Decimal(str(db.execute(
        select(func.coalesce(func.sum(StockLevel.value), 0)).where(
            StockLevel.property_id == prop.id
        )
    ).scalar_one()))

    net = Decimal("0")
    rows = db.execute(
        select(StockMovement.kind, func.coalesce(func.sum(StockMovement.total_cost), 0))
        .where(
            StockMovement.property_id == prop.id,
            StockMovement.business_date >= GO_LIVE,
        )
        .group_by(StockMovement.kind)
    ).all()
    for kind, value in rows:
        amount = Decimal(str(value))
        net += amount if kind in INBOUND_MOVEMENTS else -amount

    return q(max(Decimal("0"), current - net))


def opening_guest_ledger(db: Session, prop: Property) -> Decimal:
    """مديونية النزلاء يوم التشغيل — الحسابات اللي لسه مفتوحة بس.

    المقفولة اتسدّدت خلاص، فلو حسبناها كانت المديونية هتطلع أضعاف
    الحقيقة وتخرّب الميزانية.
    """
    cutoff = datetime(GO_LIVE.year, GO_LIVE.month, GO_LIVE.day, tzinfo=timezone.utc)
    total = db.execute(
        select(func.coalesce(func.sum(Folio.balance), 0)).where(
            Folio.property_id == prop.id,
            Folio.status == FolioStatus.OPEN,
            Folio.opened_at < cutoff,
        )
    ).scalar_one()
    return q(max(Decimal("0"), Decimal(str(total))))


def post_opening(db: Session, prop: Property) -> Decimal:
    """قيد الأرصدة الافتتاحية — الأرباح المحتجزة بتقفل المعادلة."""
    inventory = opening_inventory(db, prop)
    guests = opening_guest_ledger(db, prop)

    assets = BUILDINGS + FURNITURE + OPENING_CASH + OPENING_BANK + inventory + guests
    retained = assets - OPENING_SUPPLIERS - CAPITAL

    gl.post(
        db,
        prop.id,
        business_date=GO_LIVE - timedelta(days=1),
        lines=[
            gl.debit("1410", BUILDINGS, "مباني القرية"),
            gl.debit("1420", FURNITURE, "أثاث وتجهيزات"),
            gl.debit("1110", OPENING_CASH, "رصيد الخزينة"),
            gl.debit("1120", OPENING_BANK, "رصيد البنك"),
            gl.debit("1310", inventory, "المخزون بالجرد"),
            gl.debit("1210", guests, "حسابات نزلاء مفتوحة"),
            gl.credit("2110", OPENING_SUPPLIERS, "مستحقات موردين"),
            gl.credit("3100", CAPITAL, "رأس المال"),
            gl.credit("3900", retained, "أرباح محتجزة"),
        ],
        description_ar=f"الأرصدة الافتتاحية عند بدء التشغيل — {GO_LIVE}",
        description_en=f"Opening balances at go-live — {GO_LIVE}",
        source=JournalSource.OPENING,
        source_key="GO-LIVE",
    )
    db.commit()
    return assets


def post_operations(db: Session, prop: Property, until: date) -> int:
    """ترحيل كل يوم تشغيل من بدء التشغيل للنهاردة."""
    posted = 0
    day = GO_LIVE
    while day <= until:
        result = posting.post_day(db, prop.id, day)
        db.commit()
        posted += result.posted
        for message in result.errors:
            print(f"  ✗ {day}: {message}")
        day += timedelta(days=1)
    return posted


def post_expenses(db: Session, prop: Property, until: date) -> Decimal:
    """مصروفات التشغيل بالتناسب مع أيام الفترة.

    دي بتتكتب يدوي في الواقع لما الفاتورة توصل. بنحسبها بالتناسب عشان
    قائمة نص الشهر تبقى صادقة: مينفعش تحمّل نص شهر بفاتورة كهرباء شهر.
    """
    days = (until - GO_LIVE).days + 1
    share = Decimal(days) / Decimal("31")

    lines = []
    total = Decimal("0")
    for code, monthly, label in MONTHLY_EXPENSES:
        part = q(monthly * share)
        if part <= 0:
            continue
        lines.append(gl.debit(code, part, label, cost_center_code="ADMIN"))
        total += part

    if not lines:
        return Decimal("0")

    lines.append(gl.credit("2110", total, "فواتير مرافق وخدمات مستحقة"))
    gl.post(
        db,
        prop.id,
        business_date=until,
        lines=lines,
        description_ar=f"مصروفات تشغيل عن {days} يوم",
        description_en=f"Operating expenses for {days} days",
        source=JournalSource.MANUAL,
        source_key=f"OPEX:{until}",
    )
    db.commit()
    return q(total)


def post_commissions(db: Session, prop: Property, until: date) -> Decimal:
    """عمولات القنوات — بتتحسب من حجوزات الفترة بنسبة كل قناة.

    العمولة مش بتتخصم من الإيراد: الإيراد بيتقيّد كامل والعمولة مصروف
    لوحدها. كده المالك يقدر يقارن «بعت بكام من بوكينج» بـ«دفعت كام
    عمولة» — وده أساس قرار الدفع للقناة ولا للموقع المباشر.
    """
    channels = {
        c.source: c
        for c in db.execute(
            select(Channel).where(Channel.property_id == prop.id)
        ).scalars()
    }
    rows = db.execute(
        select(Reservation.source, func.coalesce(func.sum(Reservation.grand_total), 0))
        .where(
            Reservation.property_id == prop.id,
            Reservation.arrival_date >= GO_LIVE,
            Reservation.arrival_date <= until,
        )
        .group_by(Reservation.source)
    ).all()

    total = Decimal("0")
    for source, revenue in rows:
        channel = channels.get(source)
        if channel is None or not channel.commission_percent:
            continue
        total += Decimal(str(revenue)) * channel.commission_percent / 100
    total = q(total)

    if total <= 0:
        return Decimal("0")

    gl.post(
        db,
        prop.id,
        business_date=until,
        lines=[
            gl.debit("5410", total, "عمولات القنوات", cost_center_code="ROOMS"),
            gl.credit("1220", total, "خصم العمولة من مستحقات القنوات"),
        ],
        description_ar="عمولات قنوات البيع عن الفترة",
        description_en="Channel commissions for the period",
        source=JournalSource.MANUAL,
        source_key=f"COMM:{until}",
    )
    db.commit()
    return total


def run() -> None:
    db = SessionLocal()
    try:
        prop = db.execute(
            select(Property).where(Property.code == "VNC")
        ).scalar_one_or_none()
        if prop is None:
            print("المنشأة مش موجودة — شغّل seed_master الأول")
            return

        if not gl.chart(db, prop.id):
            print("دليل الحسابات فاضي — شغّل seed_master الأول")
            return

        today = date.today()
        if today < GO_LIVE:
            print(f"تاريخ بدء التشغيل {GO_LIVE} لسه ماجاش")
            return

        print("تفضية الدفتر...")
        clear(db, prop)

        print(f"الأرصدة الافتتاحية في {GO_LIVE - timedelta(days=1)}...")
        assets = post_opening(db, prop)

        print(f"ترحيل التشغيل من {GO_LIVE} إلى {today}...")
        entries = post_operations(db, prop, today)

        print("مصروفات التشغيل والعمولات...")
        expenses = post_expenses(db, prop, today)
        commissions = post_commissions(db, prop, today)

        print("مسيّر المرتبات...")
        payroll = pr.build(db, prop.id, today.year, today.month)
        db.commit()
        pr.approve(db, prop.id, payroll.id)
        db.commit()

        trial = gl.trial_balance(db, prop.id)
        sheet = gl.balance_sheet(db, prop.id, today)
        income = gl.income_statement(db, prop.id, GO_LIVE, today)

        print()
        print("─" * 56)
        print(f"  بدء التشغيل         {GO_LIVE}")
        print(f"  الأصول الافتتاحية   {assets:>18,.0f}")
        print(f"  قيود التشغيل        {entries}")
        print(f"  مصروفات تشغيل       {expenses:>18,.0f}")
        print(f"  عمولات القنوات      {commissions:>18,.0f}")
        print(f"  مسيّر {payroll.label}       {payroll.headcount} موظف · "
              f"تكلفة {payroll.total_cost:,.0f}")
        print("─" * 56)
        print(f"  ميزان المراجعة      {trial.total_debit:>18,.2f}")
        print(f"  متوازن              {trial.is_balanced}")
        print(f"  المركز المالي متوازن {sheet.is_balanced}")
        print("─" * 56)
        print(f"  إيراد الفترة        {income.total_revenue:>18,.0f}")
        print(f"  مصروف الفترة        {income.total_expenses:>18,.0f}")
        print(f"  صافي الربح          {income.net_profit:>18,.0f}"
              f"   ({income.margin_percent}%)")
        print("─" * 56)
    finally:
        db.close()


if __name__ == "__main__":
    run()
