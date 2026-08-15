"""ترحيل القيود والقوائم المالية — Posting engine and financial statements.

المسار الوحيد للكتابة في الدفتر هو ``post()``. أي قيد بيعدّي عليه بيتحقّق
من أربع حاجات قبل ما يتحفظ:

1. **متوازن** — مجموع المدين = مجموع الدائن بالمليم.
2. **على حسابات طرفية** — الحساب الأب بيجمّع، مبيستقبلش.
3. **في فترة مفتوحة** — الشهر المقفول مبيقبلش ترحيل.
4. **مش مكرّر** — نفس المستند مبيترحّلش مرتين.

والتصحيح بيتم بـ ``reverse()`` اللي بيعمل قيد مضاد. القيد الأصلي بيفضل
مكانه بحالة ``REVERSED`` — كده الدفتر بيحكي اللي حصل فعلاً، بما فيه الغلط.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.accounting import (
    Account,
    AccountingPeriod,
    CostCenter,
    JournalEntry,
    JournalLine,
)
from app.models.enums import (
    DEBIT_NORMAL_ACCOUNTS,
    INCOME_STATEMENT_ACCOUNTS,
    AccountType,
    JournalSource,
    JournalStatus,
    PeriodStatus,
)
from app.models.security import User
from app.services.pricing import money
from app.services.sequences import next_number

ZERO = Decimal("0")


class AccountingError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "accounting_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


class DuplicatePosting(AccountingError):
    """المستند ده اترحّل قبل كده — مش خطأ، بس مش هنكرّره."""

    def __init__(self, entry: JournalEntry):
        super().__init__(
            f"المستند مرحّل قبل كده في القيد {entry.number}",
            f"Already posted in journal {entry.number}",
            "duplicate",
        )
        self.entry = entry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════ الحسابات
def get_account(db: Session, property_id: int, code: str) -> Account:
    """بيجيب حساب بالكود — بيقع لو مش موجود، لأن الكود بيتكتب في الترحيل."""
    account = db.execute(
        select(Account).where(Account.property_id == property_id, Account.code == code)
    ).scalar_one_or_none()
    if account is None:
        raise AccountingError(
            f"الحساب {code} مش موجود في دليل الحسابات",
            f"Account {code} is not in the chart of accounts",
            "no_account",
        )
    return account


def accounts_by_code(db: Session, property_id: int) -> dict[str, Account]:
    return {
        a.code: a
        for a in db.execute(
            select(Account).where(Account.property_id == property_id)
        ).scalars()
    }


def chart(db: Session, property_id: int, *, only_active: bool = True) -> list[Account]:
    stmt = select(Account).where(Account.property_id == property_id)
    if only_active:
        stmt = stmt.where(Account.is_active.is_(True))
    return list(db.execute(stmt.order_by(Account.code)).scalars().all())


# ═══════════════════════════════════════════════════════ الفترات
def period_for(db: Session, property_id: int, on: date) -> AccountingPeriod:
    """بيجيب فترة الشهر ويفتحها لو أول مرة."""
    row = db.execute(
        select(AccountingPeriod).where(
            AccountingPeriod.property_id == property_id,
            AccountingPeriod.year == on.year,
            AccountingPeriod.month == on.month,
        )
    ).scalar_one_or_none()
    if row is None:
        row = AccountingPeriod(
            property_id=property_id, year=on.year, month=on.month, status=PeriodStatus.OPEN
        )
        db.add(row)
        db.flush()
    return row


def close_period(
    db: Session, property_id: int, year: int, month: int, *, user: User | None = None
) -> AccountingPeriod:
    period = period_for(db, property_id, date(year, month, 1))
    if period.status == PeriodStatus.CLOSED:
        return period

    # مفيش قفل والدفتر مش متوازن — ده بيخبّي غلط مش بيحلّه
    balance = trial_balance(db, property_id, until=_month_end(year, month))
    if balance.difference != ZERO:
        raise AccountingError(
            f"الميزان مش متوازن — فرق {balance.difference}",
            f"Trial balance is off by {balance.difference}",
            "unbalanced",
        )

    period.status = PeriodStatus.CLOSED
    period.closed_at = utcnow()
    period.closed_by_user_id = user.id if user else None
    db.flush()
    return period


def reopen_period(
    db: Session, property_id: int, year: int, month: int, *, reason: str
) -> AccountingPeriod:
    if not reason.strip():
        raise AccountingError("سبب إعادة الفتح مطلوب", "A reason is required", "no_reason")
    period = period_for(db, property_id, date(year, month, 1))
    period.status = PeriodStatus.OPEN
    period.notes = reason.strip()[:500]
    period.closed_at = None
    period.closed_by_user_id = None
    db.flush()
    return period


def _month_end(year: int, month: int) -> date:
    """آخر يوم في الشهر — بدون تقويم، بالرجوع يوم من أول الشهر اللي بعده."""
    return date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)


# ═══════════════════════════════════════════════════════ الترحيل
@dataclass(slots=True)
class Entry:
    """سطر قيد جاهز للترحيل — الخدمة بتاخد قايمة منه."""

    account_code: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description_ar: str | None = None
    cost_center_code: str | None = None
    reference: str | None = None


def debit(code: str, amount: Decimal, description: str | None = None, **kw) -> Entry:
    return Entry(account_code=code, debit=money(amount), description_ar=description, **kw)


def credit(code: str, amount: Decimal, description: str | None = None, **kw) -> Entry:
    return Entry(account_code=code, credit=money(amount), description_ar=description, **kw)


def post(
    db: Session,
    property_id: int,
    *,
    business_date: date,
    lines: Sequence[Entry],
    description_ar: str,
    description_en: str | None = None,
    source: JournalSource = JournalSource.MANUAL,
    source_key: str | None = None,
    user: User | None = None,
    skip_if_duplicate: bool = False,
) -> JournalEntry | None:
    """المسار الوحيد للكتابة في الدفتر.

    ``skip_if_duplicate`` بيخلّي الترحيل التلقائي يتنادى مرتين من غير
    ضرر — لو المستند اترحّل قبل كده بيرجّع ``None`` بدل ما يقع. ده اللي
    بيخلّي إعادة تشغيل النايت أوديت آمنة.
    """
    if not lines:
        raise AccountingError("القيد فاضي", "Journal entry has no lines", "empty")

    # ١) التكرار — قبل أي شغل تاني
    if source_key:
        existing = db.execute(
            select(JournalEntry).where(
                JournalEntry.property_id == property_id,
                JournalEntry.source == source,
                JournalEntry.source_key == source_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if skip_if_duplicate:
                return None
            raise DuplicatePosting(existing)

    # ٢) الفترة
    period = period_for(db, property_id, business_date)
    if period.status == PeriodStatus.CLOSED:
        raise AccountingError(
            f"شهر {period.label} مقفول — رحّل التصحيح في الشهر المفتوح",
            f"Period {period.label} is closed",
            "period_closed",
        )

    catalog = accounts_by_code(db, property_id)
    centers = {
        c.code: c
        for c in db.execute(
            select(CostCenter).where(CostCenter.property_id == property_id)
        ).scalars()
    }

    total_debit = ZERO
    total_credit = ZERO
    prepared: list[tuple[Entry, Account, CostCenter | None]] = []

    for line in lines:
        account = catalog.get(line.account_code)
        if account is None:
            raise AccountingError(
                f"الحساب {line.account_code} مش موجود",
                f"Account {line.account_code} not found",
                "no_account",
            )
        # ٣) الحسابات الطرفية بس
        if not account.is_postable:
            raise AccountingError(
                f"{account.code} حساب تجميعي — الترحيل بيتم على الحسابات الطرفية",
                f"{account.code} is a summary account",
                "not_postable",
            )
        if not account.is_active:
            raise AccountingError(
                f"الحساب {account.code} موقوف", f"Account {account.code} is inactive", "inactive"
            )

        amount_debit = money(line.debit)
        amount_credit = money(line.credit)
        if amount_debit < 0 or amount_credit < 0:
            raise AccountingError(
                "القيمة مينفعش تكون بالسالب — استخدم الاتجاه المقابل",
                "Negative amounts are not allowed — use the opposite side",
                "negative",
            )
        if amount_debit and amount_credit:
            raise AccountingError(
                "السطر إما مدين أو دائن مش الاتنين",
                "A line is either debit or credit, not both",
                "both_sides",
            )
        if not amount_debit and not amount_credit:
            continue  # سطر بصفر — بنتجاهله بدل ما نلوّث الكشف

        center = centers.get(line.cost_center_code) if line.cost_center_code else None
        total_debit += amount_debit
        total_credit += amount_credit
        prepared.append((line, account, center))

    if not prepared:
        raise AccountingError("القيد كله أصفار", "All lines are zero", "empty")

    # ٤) التوازن
    total_debit = money(total_debit)
    total_credit = money(total_credit)
    if total_debit != total_credit:
        raise AccountingError(
            f"القيد مش متوازن — مدين {total_debit} مقابل دائن {total_credit}",
            f"Unbalanced entry — debit {total_debit} vs credit {total_credit}",
            "unbalanced",
        )

    entry = JournalEntry(
        number=next_number(db, property_id, "JOURNAL", on_date=business_date),
        property_id=property_id,
        business_date=business_date,
        status=JournalStatus.POSTED,
        source=source,
        source_key=source_key,
        description_ar=description_ar.strip()[:300],
        description_en=(description_en or "").strip()[:300] or None,
        total_debit=total_debit,
        total_credit=total_credit,
        posted_at=utcnow(),
        posted_by_user_id=user.id if user else None,
    )
    db.add(entry)
    db.flush()

    for line, account, center in prepared:
        db.add(
            JournalLine(
                journal_entry_id=entry.id,
                property_id=property_id,
                account_id=account.id,
                cost_center_id=center.id if center else None,
                business_date=business_date,
                debit=money(line.debit),
                credit=money(line.credit),
                description_ar=(line.description_ar or description_ar)[:300],
                reference=line.reference,
            )
        )
        _apply_to_balance(account, money(line.debit), money(line.credit))

    db.flush()
    return entry


def _apply_to_balance(account: Account, amount_debit: Decimal, amount_credit: Decimal) -> None:
    """بيحرّك رصيد الحساب بإشارة طبيعته."""
    account.debit_total = money(account.debit_total + amount_debit)
    account.credit_total = money(account.credit_total + amount_credit)
    change = (
        amount_debit - amount_credit
        if account.account_type in DEBIT_NORMAL_ACCOUNTS
        else amount_credit - amount_debit
    )
    account.balance = money(account.balance + change)


def reverse(
    db: Session,
    property_id: int,
    entry_id: int,
    *,
    reason: str,
    business_date: date | None = None,
    user: User | None = None,
) -> JournalEntry:
    """قيد مضاد — الأصلي بيفضل مكانه.

    تاريخ العكس بيبقى النهارده مش تاريخ القيد الأصلي، عشان مايتحطّش في
    شهر مقفول. المحاسب يقدر يحدّد تاريخ تاني لو الشهر لسه مفتوح.
    """
    if not reason.strip():
        raise AccountingError("سبب العكس مطلوب", "A reason is required", "no_reason")

    entry = db.get(JournalEntry, entry_id)
    if entry is None or entry.property_id != property_id:
        raise AccountingError("القيد مش موجود", "Journal entry not found", "not_found")
    if entry.status == JournalStatus.REVERSED:
        raise AccountingError("القيد اتعكس قبل كده", "Entry is already reversed", "already")

    catalog = {a.id: a for a in db.execute(select(Account)).scalars()}
    lines = list(
        db.execute(
            select(JournalLine).where(JournalLine.journal_entry_id == entry.id)
        ).scalars().all()
    )
    mirrored = [
        Entry(
            account_code=catalog[line.account_id].code,
            debit=line.credit,
            credit=line.debit,
            description_ar=f"عكس — {line.description_ar or ''}".strip()[:300],
            reference=line.reference,
        )
        for line in lines
    ]

    reversal = post(
        db,
        property_id,
        business_date=business_date or date.today(),
        lines=mirrored,
        description_ar=f"عكس القيد {entry.number} — {reason.strip()}",
        description_en=f"Reversal of {entry.number}",
        source=entry.source,
        source_key=f"REV:{entry.id}",
        user=user,
    )
    assert reversal is not None

    reversal.reverses_entry_id = entry.id
    entry.reversed_by_entry_id = reversal.id
    entry.status = JournalStatus.REVERSED
    entry.reversal_reason = reason.strip()[:300]
    db.flush()
    return reversal


def rebuild_balances(db: Session, property_id: int) -> int:
    """بناء أرصدة الحسابات من القيود — الحكم النهائي لو حصل اختلاف."""
    rows = db.execute(
        select(
            JournalLine.account_id,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .where(JournalLine.property_id == property_id)
        .group_by(JournalLine.account_id)
    ).all()
    totals = {int(a): (money(Decimal(str(d))), money(Decimal(str(c)))) for a, d, c in rows}

    touched = 0
    for account in db.execute(
        select(Account).where(Account.property_id == property_id)
    ).scalars():
        debit_total, credit_total = totals.get(account.id, (ZERO, ZERO))
        account.debit_total = debit_total
        account.credit_total = credit_total
        account.balance = (
            money(debit_total - credit_total)
            if account.account_type in DEBIT_NORMAL_ACCOUNTS
            else money(credit_total - debit_total)
        )
        touched += 1
    db.flush()
    return touched


# ═══════════════════════════════════════════════════════ القوائم
@dataclass(slots=True)
class TrialRow:
    account: Account
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass(slots=True)
class TrialBalance:
    rows: list[TrialRow]
    total_debit: Decimal
    total_credit: Decimal

    @property
    def difference(self) -> Decimal:
        return money(self.total_debit - self.total_credit)

    @property
    def is_balanced(self) -> bool:
        return self.difference == ZERO


def _line_totals(
    db: Session,
    property_id: int,
    *,
    since: date | None = None,
    until: date | None = None,
    cost_center_id: int | None = None,
) -> dict[int, tuple[Decimal, Decimal]]:
    stmt = (
        select(
            JournalLine.account_id,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .where(JournalLine.property_id == property_id)
        .group_by(JournalLine.account_id)
    )
    if since:
        stmt = stmt.where(JournalLine.business_date >= since)
    if until:
        stmt = stmt.where(JournalLine.business_date <= until)
    if cost_center_id:
        stmt = stmt.where(JournalLine.cost_center_id == cost_center_id)
    return {
        int(a): (money(Decimal(str(d))), money(Decimal(str(c))))
        for a, d, c in db.execute(stmt).all()
    }


def trial_balance(
    db: Session,
    property_id: int,
    *,
    since: date | None = None,
    until: date | None = None,
) -> TrialBalance:
    """ميزان المراجعة — الاختبار الأول على سلامة الدفتر."""
    totals = _line_totals(db, property_id, since=since, until=until)
    rows: list[TrialRow] = []
    total_debit = ZERO
    total_credit = ZERO

    for account in chart(db, property_id, only_active=False):
        debit_total, credit_total = totals.get(account.id, (ZERO, ZERO))
        if not debit_total and not credit_total:
            continue
        balance = (
            money(debit_total - credit_total)
            if account.is_debit_normal
            else money(credit_total - debit_total)
        )
        rows.append(TrialRow(account, debit_total, credit_total, balance))
        total_debit += debit_total
        total_credit += credit_total

    return TrialBalance(rows, money(total_debit), money(total_credit))


@dataclass(slots=True)
class StatementLine:
    code: str
    name_ar: str
    name_en: str
    amount: Decimal


@dataclass(slots=True)
class IncomeStatement:
    since: date
    until: date
    revenue: list[StatementLine] = field(default_factory=list)
    expenses: list[StatementLine] = field(default_factory=list)
    total_revenue: Decimal = ZERO
    total_expenses: Decimal = ZERO

    @property
    def net_profit(self) -> Decimal:
        return money(self.total_revenue - self.total_expenses)

    @property
    def margin_percent(self) -> Decimal:
        if not self.total_revenue:
            return ZERO
        return money(self.net_profit / self.total_revenue * 100)


def income_statement(
    db: Session,
    property_id: int,
    since: date,
    until: date,
    *,
    cost_center_id: int | None = None,
) -> IncomeStatement:
    """قائمة الدخل — الإيراد ناقص المصروف عن فترة."""
    totals = _line_totals(
        db, property_id, since=since, until=until, cost_center_id=cost_center_id
    )
    out = IncomeStatement(since=since, until=until)

    for account in chart(db, property_id, only_active=False):
        if account.account_type not in INCOME_STATEMENT_ACCOUNTS:
            continue
        debit_total, credit_total = totals.get(account.id, (ZERO, ZERO))
        if not debit_total and not credit_total:
            continue
        if account.account_type == AccountType.REVENUE:
            amount = money(credit_total - debit_total)
            out.revenue.append(
                StatementLine(account.code, account.name_ar, account.name_en, amount)
            )
            out.total_revenue += amount
        else:
            amount = money(debit_total - credit_total)
            out.expenses.append(
                StatementLine(account.code, account.name_ar, account.name_en, amount)
            )
            out.total_expenses += amount

    out.revenue.sort(key=lambda r: r.amount, reverse=True)
    out.expenses.sort(key=lambda r: r.amount, reverse=True)
    out.total_revenue = money(out.total_revenue)
    out.total_expenses = money(out.total_expenses)
    return out


@dataclass(slots=True)
class BalanceSheet:
    as_of: date
    assets: list[StatementLine] = field(default_factory=list)
    liabilities: list[StatementLine] = field(default_factory=list)
    equity: list[StatementLine] = field(default_factory=list)
    total_assets: Decimal = ZERO
    total_liabilities: Decimal = ZERO
    total_equity: Decimal = ZERO
    #: الأرباح المحتجزة من قائمة الدخل — مش حساب مرحّل عليه لسه
    retained_profit: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        """الأصول ناقص (التزامات + حقوق ملكية) — لازم صفر."""
        return money(
            self.total_assets
            - (self.total_liabilities + self.total_equity + self.retained_profit)
        )

    @property
    def is_balanced(self) -> bool:
        return self.difference == ZERO


def balance_sheet(db: Session, property_id: int, as_of: date) -> BalanceSheet:
    """المركز المالي — الأصول = الالتزامات + حقوق الملكية + الربح.

    الربح بيتضاف كسطر محسوب مش كرصيد حساب، لأن الإقفال السنوي هو اللي
    بيرحّله فعلاً لحساب الأرباح المحتجزة. كده الميزانية بتتوازن في أي
    يوم في السنة مش آخرها بس.
    """
    totals = _line_totals(db, property_id, until=as_of)
    out = BalanceSheet(as_of=as_of)
    revenue = ZERO
    expenses = ZERO

    for account in chart(db, property_id, only_active=False):
        debit_total, credit_total = totals.get(account.id, (ZERO, ZERO))
        if not debit_total and not credit_total:
            continue

        if account.account_type == AccountType.ASSET:
            amount = money(debit_total - credit_total)
            out.assets.append(
                StatementLine(account.code, account.name_ar, account.name_en, amount)
            )
            out.total_assets += amount
        elif account.account_type == AccountType.LIABILITY:
            amount = money(credit_total - debit_total)
            out.liabilities.append(
                StatementLine(account.code, account.name_ar, account.name_en, amount)
            )
            out.total_liabilities += amount
        elif account.account_type == AccountType.EQUITY:
            amount = money(credit_total - debit_total)
            out.equity.append(
                StatementLine(account.code, account.name_ar, account.name_en, amount)
            )
            out.total_equity += amount
        elif account.account_type == AccountType.REVENUE:
            revenue += money(credit_total - debit_total)
        else:
            expenses += money(debit_total - credit_total)

    out.total_assets = money(out.total_assets)
    out.total_liabilities = money(out.total_liabilities)
    out.total_equity = money(out.total_equity)
    out.retained_profit = money(revenue - expenses)
    return out


@dataclass(slots=True)
class LedgerRow:
    line: JournalLine
    entry: JournalEntry
    running_balance: Decimal


def account_ledger(
    db: Session,
    property_id: int,
    account_id: int,
    *,
    since: date | None = None,
    until: date | None = None,
    limit: int = 200,
) -> list[LedgerRow]:
    """كشف حساب الأستاذ — بالرصيد المتحرّك.

    الرصيد الافتتاحي بيتحسب من كل الحركة قبل ``since``، فالكشف بيبدأ من
    رقم صحيح مش من صفر.
    """
    account = db.get(Account, account_id)
    if account is None or account.property_id != property_id:
        raise AccountingError("الحساب مش موجود", "Account not found", "not_found")

    opening = ZERO
    if since:
        before = db.execute(
            select(
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            ).where(
                JournalLine.account_id == account_id,
                JournalLine.business_date < since,
            )
        ).one()
        debit_before, credit_before = money(Decimal(str(before[0]))), money(
            Decimal(str(before[1]))
        )
        opening = (
            money(debit_before - credit_before)
            if account.is_debit_normal
            else money(credit_before - debit_before)
        )

    stmt = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalLine.account_id == account_id)
    )
    if since:
        stmt = stmt.where(JournalLine.business_date >= since)
    if until:
        stmt = stmt.where(JournalLine.business_date <= until)

    rows = db.execute(
        stmt.order_by(JournalLine.business_date, JournalLine.id).limit(limit)
    ).all()

    out: list[LedgerRow] = []
    running = opening
    for line, entry in rows:
        change = (
            line.debit - line.credit if account.is_debit_normal else line.credit - line.debit
        )
        running = money(running + change)
        out.append(LedgerRow(line=line, entry=entry, running_balance=running))
    return out


def journal(
    db: Session,
    property_id: int,
    *,
    since: date | None = None,
    until: date | None = None,
    sources: Iterable[JournalSource] | None = None,
    limit: int = 100,
) -> list[JournalEntry]:
    stmt = select(JournalEntry).where(JournalEntry.property_id == property_id)
    if since:
        stmt = stmt.where(JournalEntry.business_date >= since)
    if until:
        stmt = stmt.where(JournalEntry.business_date <= until)
    if sources:
        stmt = stmt.where(JournalEntry.source.in_(list(sources)))
    return list(
        db.execute(
            stmt.order_by(JournalEntry.business_date.desc(), JournalEntry.id.desc()).limit(
                limit
            )
        ).scalars().all()
    )
