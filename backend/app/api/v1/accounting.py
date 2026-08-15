"""واجهات الحسابات والقوائم المالية — Ledger and statements endpoints."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.accounting import Account, AccountingPeriod, CostCenter, JournalEntry
from app.models.enums import (
    AccountType,
    AuditAction,
    JournalSource,
    JournalStatus,
    PeriodStatus,
)
from app.schemas.common import ApiModel
from app.services import accounting as gl
from app.services import audit
from app.services import gl_posting as posting

router = APIRouter(prefix="/accounting", tags=["الحسابات — Accounting"])

#: أقصى مدى للقوائم — سنتين كفاية لأي مقارنة، وأكتر من كده بيتقل الاستعلام
MAX_RANGE_DAYS = 730


# ═══════════════════════════════════════════════════════════ النماذج
class AccountOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    account_type: AccountType
    parent_id: int | None = None
    is_postable: bool
    balance: Decimal
    debit_total: Decimal
    credit_total: Decimal


class CostCenterOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str


class TrialRowOut(ApiModel):
    account_id: int
    code: str
    name_ar: str
    name_en: str
    account_type: AccountType
    debit: Decimal
    credit: Decimal
    balance: Decimal


class TrialBalanceOut(ApiModel):
    since: date | None = None
    until: date | None = None
    rows: list[TrialRowOut]
    total_debit: Decimal
    total_credit: Decimal
    difference: Decimal
    is_balanced: bool


class StatementLineOut(ApiModel):
    code: str
    name_ar: str
    name_en: str
    amount: Decimal


class IncomeStatementOut(ApiModel):
    since: date
    until: date
    revenue: list[StatementLineOut]
    expenses: list[StatementLineOut]
    total_revenue: Decimal
    total_expenses: Decimal
    net_profit: Decimal
    margin_percent: Decimal


class BalanceSheetOut(ApiModel):
    as_of: date
    assets: list[StatementLineOut]
    liabilities: list[StatementLineOut]
    equity: list[StatementLineOut]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    retained_profit: Decimal
    difference: Decimal
    is_balanced: bool


class JournalLineOut(ApiModel):
    account_id: int
    account_code: str
    account_name_ar: str
    debit: Decimal
    credit: Decimal
    description_ar: str | None = None
    cost_center_id: int | None = None
    reference: str | None = None


class JournalEntryOut(ApiModel):
    id: int
    number: str
    business_date: date
    status: JournalStatus
    source: JournalSource
    description_ar: str
    total_debit: Decimal
    total_credit: Decimal
    posted_at: datetime | None = None
    reverses_entry_id: int | None = None
    reversed_by_entry_id: int | None = None
    reversal_reason: str | None = None
    lines: list[JournalLineOut] = []


class LedgerRowOut(ApiModel):
    entry_id: int
    entry_number: str
    business_date: date
    description_ar: str | None = None
    reference: str | None = None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal


class AccountLedgerOut(ApiModel):
    account: AccountOut
    since: date | None = None
    until: date | None = None
    rows: list[LedgerRowOut]


class PeriodOut(ApiModel):
    year: int
    month: int
    label: str
    status: PeriodStatus
    closed_at: datetime | None = None


class ManualLineIn(ApiModel):
    account_code: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description_ar: str | None = None
    cost_center_code: str | None = None
    reference: str | None = None


class ManualEntryIn(ApiModel):
    business_date: date
    description_ar: str
    lines: list[ManualLineIn]


class ReasonIn(ApiModel):
    reason: str


class PostDayIn(ApiModel):
    business_date: date
    #: اليوم مرحّل وجت فيه حركة متأخرة — بيعكس القيود التلقائية ويبنيها من الأول
    repost: bool = False


class PostingResultOut(ApiModel):
    business_date: date
    posted: int
    entries: list[str]
    skipped: list[str]
    errors: list[str]
    total_debit: Decimal


class BoardOut(ApiModel):
    """اللوحة الأولى — الأرقام اللي المالك بيسأل عنها قبل أي تفصيل."""

    as_of: date
    month_revenue: Decimal
    month_expenses: Decimal
    month_profit: Decimal
    margin_percent: Decimal
    cash_on_hand: Decimal
    bank: Decimal
    guest_ledger: Decimal
    city_ledger: Decimal
    suppliers_due: Decimal
    inventory_value: Decimal
    vat_payable: Decimal
    service_payable: Decimal
    is_balanced: bool
    unposted_days: list[date]


# ═══════════════════════════════════════════════════════════ أدوات
def _fail(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "error")
    http = {
        "not_found": 404,
        "no_account": 404,
        "duplicate": 409,
        "period_closed": 409,
        "already": 409,
    }.get(code, 400)
    return HTTPException(
        status_code=http,
        detail={
            "ar": getattr(exc, "message_ar", str(exc)),
            "en": getattr(exc, "message_en", str(exc)),
            "code": code,
        },
    )


def _clamp(since: date, until: date) -> tuple[date, date]:
    if until < since:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"ar": "تاريخ النهاية قبل البداية", "en": "End is before start"},
        )
    if (until - since).days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "ar": f"المدى أكبر من {MAX_RANGE_DAYS} يوم",
                "en": f"Range exceeds {MAX_RANGE_DAYS} days",
            },
        )
    return since, until


def _account_out(account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        code=account.code,
        name_ar=account.name_ar,
        name_en=account.name_en,
        account_type=account.account_type,
        parent_id=account.parent_id,
        is_postable=account.is_postable,
        balance=account.balance,
        debit_total=account.debit_total,
        credit_total=account.credit_total,
    )


def _entry_out(entry: JournalEntry, catalog: dict[int, Account]) -> JournalEntryOut:
    return JournalEntryOut(
        id=entry.id,
        number=entry.number,
        business_date=entry.business_date,
        status=entry.status,
        source=entry.source,
        description_ar=entry.description_ar,
        total_debit=entry.total_debit,
        total_credit=entry.total_credit,
        posted_at=entry.posted_at,
        reverses_entry_id=entry.reverses_entry_id,
        reversed_by_entry_id=entry.reversed_by_entry_id,
        reversal_reason=entry.reversal_reason,
        lines=[
            JournalLineOut(
                account_id=line.account_id,
                account_code=catalog[line.account_id].code if line.account_id in catalog else "",
                account_name_ar=(
                    catalog[line.account_id].name_ar if line.account_id in catalog else ""
                ),
                debit=line.debit,
                credit=line.credit,
                description_ar=line.description_ar,
                cost_center_id=line.cost_center_id,
                reference=line.reference,
            )
            for line in entry.lines
        ],
    )


def _balance_of(db, property_id: int, code: str) -> Decimal:
    account = db.execute(
        select(Account).where(Account.property_id == property_id, Account.code == code)
    ).scalar_one_or_none()
    return account.balance if account else Decimal("0")


# ═══════════════════════════════════════════════════════════ اللوحة
@router.get(
    "",
    response_model=BoardOut,
    summary="لوحة الحسابات",
    dependencies=[Depends(require("gl.view"))],
)
def board(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> BoardOut:
    today = date.today()
    month_start = today.replace(day=1)

    income = gl.income_statement(db, prop.id, month_start, today)
    sheet = gl.balance_sheet(db, prop.id, today)

    # الأيام اللي فيها حركة ومترحّلتش — ده اللي بيخلّي المحاسب يعرف
    # إن فيه يوم فايت من غير ما يقارن بالإيد
    posted_days = {
        row[0]
        for row in db.execute(
            select(JournalEntry.business_date).where(
                JournalEntry.property_id == prop.id,
                JournalEntry.source == JournalSource.ROOM_REVENUE,
                JournalEntry.business_date >= today - timedelta(days=14),
            )
        ).all()
    }
    unposted = [
        day
        for offset in range(1, 15)
        if (day := today - timedelta(days=offset)) not in posted_days
    ]

    return BoardOut(
        as_of=today,
        month_revenue=income.total_revenue,
        month_expenses=income.total_expenses,
        month_profit=income.net_profit,
        margin_percent=income.margin_percent,
        cash_on_hand=_balance_of(db, prop.id, "1110"),
        bank=_balance_of(db, prop.id, "1120"),
        guest_ledger=_balance_of(db, prop.id, "1210"),
        city_ledger=_balance_of(db, prop.id, "1220"),
        suppliers_due=_balance_of(db, prop.id, "2110"),
        inventory_value=(
            _balance_of(db, prop.id, "1310") + _balance_of(db, prop.id, "1320")
        ),
        vat_payable=_balance_of(db, prop.id, "2210"),
        service_payable=_balance_of(db, prop.id, "2230"),
        is_balanced=sheet.is_balanced,
        unposted_days=sorted(unposted),
    )


# ═══════════════════════════════════════════════════════════ الدليل
@router.get(
    "/chart",
    response_model=list[AccountOut],
    summary="دليل الحسابات",
    dependencies=[Depends(require("gl.view"))],
)
def chart(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[AccountOut]:
    return [_account_out(a) for a in gl.chart(db, prop.id, only_active=False)]


@router.get(
    "/cost-centers",
    response_model=list[CostCenterOut],
    summary="مراكز التكلفة",
    dependencies=[Depends(require("gl.view"))],
)
def cost_centers(db: DbSession, user: CurrentUser, prop: CurrentProperty):
    rows = db.execute(
        select(CostCenter)
        .where(CostCenter.property_id == prop.id, CostCenter.is_active.is_(True))
        .order_by(CostCenter.sort_order)
    ).scalars().all()
    return [
        CostCenterOut(id=c.id, code=c.code, name_ar=c.name_ar, name_en=c.name_en)
        for c in rows
    ]


# ═══════════════════════════════════════════════════════════ القوائم
@router.get(
    "/trial-balance",
    response_model=TrialBalanceOut,
    summary="ميزان المراجعة",
    dependencies=[Depends(require("gl.view"))],
)
def trial_balance(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    since: date | None = None,
    until: date | None = None,
) -> TrialBalanceOut:
    if since and until:
        _clamp(since, until)
    result = gl.trial_balance(db, prop.id, since=since, until=until)
    return TrialBalanceOut(
        since=since,
        until=until,
        rows=[
            TrialRowOut(
                account_id=row.account.id,
                code=row.account.code,
                name_ar=row.account.name_ar,
                name_en=row.account.name_en,
                account_type=row.account.account_type,
                debit=row.debit,
                credit=row.credit,
                balance=row.balance,
            )
            for row in result.rows
        ],
        total_debit=result.total_debit,
        total_credit=result.total_credit,
        difference=result.difference,
        is_balanced=result.is_balanced,
    )


@router.get(
    "/income-statement",
    response_model=IncomeStatementOut,
    summary="قائمة الدخل",
    dependencies=[Depends(require("gl.view"))],
)
def income_statement(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    since: date,
    until: date,
    cost_center_id: int | None = None,
) -> IncomeStatementOut:
    _clamp(since, until)
    result = gl.income_statement(db, prop.id, since, until, cost_center_id=cost_center_id)
    return IncomeStatementOut(
        since=result.since,
        until=result.until,
        revenue=[
            StatementLineOut(code=r.code, name_ar=r.name_ar, name_en=r.name_en, amount=r.amount)
            for r in result.revenue
        ],
        expenses=[
            StatementLineOut(code=r.code, name_ar=r.name_ar, name_en=r.name_en, amount=r.amount)
            for r in result.expenses
        ],
        total_revenue=result.total_revenue,
        total_expenses=result.total_expenses,
        net_profit=result.net_profit,
        margin_percent=result.margin_percent,
    )


@router.get(
    "/balance-sheet",
    response_model=BalanceSheetOut,
    summary="المركز المالي",
    dependencies=[Depends(require("gl.view"))],
)
def balance_sheet(
    db: DbSession, user: CurrentUser, prop: CurrentProperty, as_of: date | None = None
) -> BalanceSheetOut:
    result = gl.balance_sheet(db, prop.id, as_of or date.today())
    return BalanceSheetOut(
        as_of=result.as_of,
        assets=[
            StatementLineOut(code=r.code, name_ar=r.name_ar, name_en=r.name_en, amount=r.amount)
            for r in result.assets
        ],
        liabilities=[
            StatementLineOut(code=r.code, name_ar=r.name_ar, name_en=r.name_en, amount=r.amount)
            for r in result.liabilities
        ],
        equity=[
            StatementLineOut(code=r.code, name_ar=r.name_ar, name_en=r.name_en, amount=r.amount)
            for r in result.equity
        ],
        total_assets=result.total_assets,
        total_liabilities=result.total_liabilities,
        total_equity=result.total_equity,
        retained_profit=result.retained_profit,
        difference=result.difference,
        is_balanced=result.is_balanced,
    )


# ═══════════════════════════════════════════════════════════ اليومية
@router.get(
    "/journal",
    response_model=list[JournalEntryOut],
    summary="دفتر اليومية",
    dependencies=[Depends(require("gl.view"))],
)
def journal(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    since: date | None = None,
    until: date | None = None,
    source: JournalSource | None = None,
    limit: int = Query(60, ge=1, le=200),
) -> list[JournalEntryOut]:
    entries = gl.journal(
        db,
        prop.id,
        since=since,
        until=until,
        sources=[source] if source else None,
        limit=limit,
    )
    catalog = {a.id: a for a in gl.chart(db, prop.id, only_active=False)}
    return [_entry_out(e, catalog) for e in entries]


@router.get(
    "/ledger/{account_id}",
    response_model=AccountLedgerOut,
    summary="كشف حساب الأستاذ",
    dependencies=[Depends(require("gl.view"))],
)
def account_ledger(
    account_id: int,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    since: date | None = None,
    until: date | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> AccountLedgerOut:
    account = db.get(Account, account_id)
    if account is None or account.property_id != prop.id:
        raise HTTPException(status_code=404, detail={"ar": "الحساب مش موجود", "en": "Not found"})
    try:
        rows = gl.account_ledger(
            db, prop.id, account_id, since=since, until=until, limit=limit
        )
    except gl.AccountingError as exc:
        raise _fail(exc) from exc

    return AccountLedgerOut(
        account=_account_out(account),
        since=since,
        until=until,
        rows=[
            LedgerRowOut(
                entry_id=row.entry.id,
                entry_number=row.entry.number,
                business_date=row.line.business_date,
                description_ar=row.line.description_ar,
                reference=row.line.reference,
                debit=row.line.debit,
                credit=row.line.credit,
                running_balance=row.running_balance,
            )
            for row in rows
        ],
    )


@router.post(
    "/journal",
    response_model=JournalEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="قيد يدوي",
    dependencies=[Depends(require("gl.post"))],
)
def create_entry(
    payload: ManualEntryIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> JournalEntryOut:
    try:
        entry = gl.post(
            db,
            prop.id,
            business_date=payload.business_date,
            lines=[
                gl.Entry(
                    account_code=line.account_code,
                    debit=line.debit,
                    credit=line.credit,
                    description_ar=line.description_ar,
                    cost_center_code=line.cost_center_code,
                    reference=line.reference,
                )
                for line in payload.lines
            ],
            description_ar=payload.description_ar,
            source=JournalSource.MANUAL,
            user=user,
        )
    except gl.AccountingError as exc:
        raise _fail(exc) from exc

    assert entry is not None
    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="journal_entry",
        entity_id=entry.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"قيد يدوي {entry.number} بمبلغ {entry.total_debit}",
        summary_en=f"Manual journal {entry.number} for {entry.total_debit}",
        request=request,
    )
    db.commit()
    catalog = {a.id: a for a in gl.chart(db, prop.id, only_active=False)}
    return _entry_out(entry, catalog)


@router.post(
    "/journal/{entry_id}/reverse",
    response_model=JournalEntryOut,
    summary="عكس قيد",
    dependencies=[Depends(require("gl.post"))],
)
def reverse_entry(
    entry_id: int,
    payload: ReasonIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> JournalEntryOut:
    try:
        reversal = gl.reverse(db, prop.id, entry_id, reason=payload.reason, user=user)
    except gl.AccountingError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.VOID,
        entity_type="journal_entry",
        entity_id=entry_id,
        user=user,
        property_id=prop.id,
        summary_ar=f"عكس القيد — {payload.reason}",
        summary_en=f"Reversed journal — {payload.reason}",
        request=request,
    )
    db.commit()
    catalog = {a.id: a for a in gl.chart(db, prop.id, only_active=False)}
    return _entry_out(reversal, catalog)


# ═══════════════════════════════════════════════════════════ الترحيل
@router.post(
    "/post-day",
    response_model=PostingResultOut,
    summary="ترحيل يوم",
    dependencies=[Depends(require("gl.post"))],
)
def post_day(
    payload: PostDayIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> PostingResultOut:
    if payload.business_date > date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"ar": "مينفعش ترحّل يوم لسه ماجاش", "en": "Cannot post a future date"},
        )
    run = posting.repost_day if payload.repost else posting.post_day
    result = run(db, prop.id, payload.business_date, user=user)
    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="gl_posting",
        user=user,
        property_id=prop.id,
        summary_ar=(
            f"{'إعادة ترحيل' if payload.repost else 'ترحيل'} {payload.business_date}"
            f" — {result.posted} قيد"
        ),
        summary_en=f"Posted {payload.business_date} — {result.posted} entries",
        request=request,
    )
    db.commit()
    return PostingResultOut(
        business_date=result.business_date,
        posted=result.posted,
        entries=result.entries,
        skipped=result.skipped,
        errors=result.errors,
        total_debit=result.total_debit,
    )


@router.post(
    "/rebuild",
    summary="إعادة بناء الأرصدة من القيود",
    dependencies=[Depends(require("gl.post"))],
)
def rebuild(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> dict:
    touched = gl.rebuild_balances(db, prop.id)
    db.commit()
    return {"accounts": touched}


# ═══════════════════════════════════════════════════════════ الفترات
@router.get(
    "/periods",
    response_model=list[PeriodOut],
    summary="الفترات المحاسبية",
    dependencies=[Depends(require("gl.view"))],
)
def periods(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> list[PeriodOut]:
    rows = db.execute(
        select(AccountingPeriod)
        .where(AccountingPeriod.property_id == prop.id)
        .order_by(AccountingPeriod.year.desc(), AccountingPeriod.month.desc())
        .limit(36)
    ).scalars().all()
    return [
        PeriodOut(
            year=p.year,
            month=p.month,
            label=p.label,
            status=p.status,
            closed_at=p.closed_at,
        )
        for p in rows
    ]


@router.post(
    "/periods/{year}/{month}/close",
    response_model=PeriodOut,
    summary="إقفال شهر",
    dependencies=[Depends(require("gl.close"))],
)
def close_period(
    year: int,
    month: int,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> PeriodOut:
    if not 1 <= month <= 12:
        raise HTTPException(status_code=422, detail={"ar": "شهر غير صحيح", "en": "Bad month"})
    try:
        period = gl.close_period(db, prop.id, year, month, user=user)
    except gl.AccountingError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="accounting_period",
        entity_id=period.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إقفال شهر {period.label}",
        summary_en=f"Closed period {period.label}",
        request=request,
    )
    db.commit()
    return PeriodOut(
        year=period.year,
        month=period.month,
        label=period.label,
        status=period.status,
        closed_at=period.closed_at,
    )


@router.post(
    "/periods/{year}/{month}/reopen",
    response_model=PeriodOut,
    summary="إعادة فتح شهر",
    dependencies=[Depends(require("gl.close"))],
)
def reopen_period(
    year: int,
    month: int,
    payload: ReasonIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> PeriodOut:
    try:
        period = gl.reopen_period(db, prop.id, year, month, reason=payload.reason)
    except gl.AccountingError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="accounting_period",
        entity_id=period.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إعادة فتح شهر {period.label} — {payload.reason}",
        summary_en=f"Reopened period {period.label}",
        request=request,
    )
    db.commit()
    return PeriodOut(
        year=period.year,
        month=period.month,
        label=period.label,
        status=period.status,
        closed_at=period.closed_at,
    )
