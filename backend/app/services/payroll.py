"""حساب المرتبات وترحيلها — Payroll calculation and posting.

الحساب مبني على القانون المصري، **بس مكتوب كإعدادات مش كأرقام مدفونة**.
الشرايح والنِسَب كلها ثوابت في أول الملف: لما القانون يتغيّر — وهو بيتغيّر —
التعديل بيبقى في مكان واحد ومعاه تاريخ سريان، مش رحلة بحث في الكود.

خطوات المسيّر:

1. **الاستحقاق** — أساسي + بدلات + إضافي + مكافأة + نصيبه من الخدمة.
2. **الخدمة** — المحصّل فعلاً في الشهر من حساب الالتزام، متوزّع بالنقاط.
3. **التأمينات** — على الأجر التأميني بحديه الأدنى والأقصى، مش على الإجمالي.
4. **الضريبة** — شرايح سنوية بتتحسب على الشهر بعد خصم التأمينات والإعفاء.
5. **الصافي** — الاستحقاق ناقص المستقطع.

والمسيّر المعتمد بيترحّل قيد واحد بيحرّك ستة حسابات — وده اللي بيخلّي
مصروف المرتبات في قائمة الدخل رقم مستخرج من مستند، مش تقدير.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.accounting import Account, JournalEntry
from app.models.enums import (
    EmploymentStatus,
    JournalSource,
    LeaveKind,
    PayrollStatus,
)
from app.models.hr import Department, Employee, LeaveRequest, Payslip, PayrollRun
from app.models.security import User
from app.services import accounting as gl
from app.services.pricing import money
from app.services.sequences import next_number

ZERO = Decimal("0")

# ═══════════════════════════════════════ ثوابت القانون المصري
#: نسبة اشتراك التأمينات — قانون 148/2019
INSURANCE_EMPLOYEE_PERCENT = Decimal("11")
INSURANCE_EMPLOYER_PERCENT = Decimal("18.75")

#: حدّا الأجر التأميني الشهري — بيتحدّثوا سنوياً بقرار وزاري
INSURANCE_SALARY_MIN = Decimal("2300")
INSURANCE_SALARY_MAX = Decimal("14500")

#: الإعفاء الشخصي السنوي
PERSONAL_EXEMPTION = Decimal("20000")

#: شرايح ضريبة كسب العمل السنوية — (حد الشريحة، النسبة)
#: آخر شريحة حدها ``None`` يعني «وما زاد»
TAX_BRACKETS: list[tuple[Decimal | None, Decimal]] = [
    (Decimal("40000"), Decimal("0")),
    (Decimal("55000"), Decimal("10")),
    (Decimal("70000"), Decimal("15")),
    (Decimal("200000"), Decimal("20")),
    (Decimal("400000"), Decimal("22.5")),
    (Decimal("1200000"), Decimal("25")),
    (None, Decimal("27.5")),
]

#: أيام الشهر المعتمدة في حساب خصم اليوم — عرف متبع في العقود المصرية
WORKING_DAYS_PER_MONTH = Decimal("30")

# ═══════════════════════════════════════ حسابات الترحيل
SALARIES_EXPENSE = "5210"
EMPLOYER_INSURANCE_EXPENSE = "5220"
SERVICE_DISTRIBUTED = "5230"
SERVICE_PAYABLE = "2230"
SALARIES_PAYABLE = "2410"
INSURANCE_PAYABLE = "2420"
TAX_PAYABLE = "2430"
CASH = "1110"
BANK = "1120"


class PayrollError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "payroll_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    return first, last


# ═══════════════════════════════════════════════════ الحسابات الفردية
def insurance_base(employee: Employee) -> Decimal:
    """الأجر التأميني بعد تطبيق الحدين.

    الحدود دي هي اللي بتخلّي اشتراك مدير الفندق مش ضعف اشتراك الشيف
    عشرين مرة — التأمينات بتتوقف عند سقف.
    """
    if not employee.is_insured:
        return ZERO
    base = employee.insurance_salary or employee.basic_salary
    return money(min(max(base, INSURANCE_SALARY_MIN), INSURANCE_SALARY_MAX))


def annual_income_tax(annual_taxable: Decimal) -> Decimal:
    """ضريبة سنوية بالشرايح التصاعدية.

    الشرايح تصاعدية بمعناها الصحيح: كل جنيه بيتحاسب بنسبة شريحته، مش
    الدخل كله بنسبة أعلى شريحة. الخلط ده بيطلّع أرقام غلط بالآلاف.
    """
    taxable = max(ZERO, annual_taxable - PERSONAL_EXEMPTION)
    if taxable <= 0:
        return ZERO

    tax = ZERO
    previous = ZERO
    for ceiling, percent in TAX_BRACKETS:
        upper = taxable if ceiling is None else min(taxable, ceiling)
        slice_amount = upper - previous
        if slice_amount > 0:
            tax += slice_amount * percent / 100
        if ceiling is not None:
            previous = ceiling
            if taxable <= ceiling:
                break
    return money(tax)


def monthly_income_tax(monthly_taxable: Decimal) -> Decimal:
    """الضريبة الشهرية = السنوية ÷ 12، لأن الشرايح سنوية بطبيعتها."""
    return money(annual_income_tax(money(monthly_taxable * 12)) / 12)


@dataclass(slots=True)
class Calculation:
    """نتيجة حساب موظف واحد — كل عنصر منفصل عشان القسيمة تبقى مفسَّرة."""

    employee: Employee
    basic: Decimal = ZERO
    allowances: Decimal = ZERO
    overtime: Decimal = ZERO
    service_share: Decimal = ZERO
    bonus: Decimal = ZERO
    gross: Decimal = ZERO
    insurance_employee: Decimal = ZERO
    insurance_employer: Decimal = ZERO
    income_tax: Decimal = ZERO
    unpaid_leave: Decimal = ZERO
    unpaid_days: Decimal = ZERO
    advances: Decimal = ZERO
    penalties: Decimal = ZERO
    total_deductions: Decimal = ZERO
    net_pay: Decimal = ZERO


def calculate_employee(
    employee: Employee,
    *,
    service_share: Decimal = ZERO,
    overtime: Decimal = ZERO,
    bonus: Decimal = ZERO,
    advances: Decimal = ZERO,
    penalties: Decimal = ZERO,
    unpaid_days: Decimal = ZERO,
) -> Calculation:
    """حساب قسيمة موظف واحد — دالة صافية بلا قاعدة بيانات، فتتختبر لوحدها."""
    calc = Calculation(employee=employee)
    calc.basic = money(employee.basic_salary)
    calc.allowances = money(employee.allowances)
    calc.overtime = money(overtime)
    calc.service_share = money(service_share)
    calc.bonus = money(bonus)
    calc.unpaid_days = unpaid_days

    # خصم الإجازة بدون أجر بيتحسب على الأساسي والبدلات مش على الخدمة —
    # الخدمة نصيبه من شغل فعلي عمله، فمش منطقي تتخصم بيوم غياب
    daily = money((calc.basic + calc.allowances) / WORKING_DAYS_PER_MONTH)
    calc.unpaid_leave = money(daily * unpaid_days)

    calc.gross = money(
        calc.basic + calc.allowances + calc.overtime + calc.service_share + calc.bonus
    )

    base = insurance_base(employee)
    calc.insurance_employee = money(base * INSURANCE_EMPLOYEE_PERCENT / 100)
    calc.insurance_employer = money(base * INSURANCE_EMPLOYER_PERCENT / 100)

    # الوعاء الضريبي = الإجمالي ناقص اشتراك التأمينات وناقص الغياب
    taxable = max(ZERO, calc.gross - calc.insurance_employee - calc.unpaid_leave)
    calc.income_tax = monthly_income_tax(taxable)

    calc.advances = money(advances)
    calc.penalties = money(penalties)
    calc.total_deductions = money(
        calc.insurance_employee
        + calc.income_tax
        + calc.unpaid_leave
        + calc.advances
        + calc.penalties
    )
    calc.net_pay = money(calc.gross - calc.total_deductions)
    return calc


# ═══════════════════════════════════════════════════ حوض الخدمة
def service_pool(db: Session, property_id: int, year: int, month: int) -> Decimal:
    """الخدمة اللي اتجمّعت في الشهر — من قيود الدفتر مش من تقدير.

    بنقرا الجانب الدائن لحساب الالتزام في الشهر: ده بالظبط اللي النزلاء
    دفعوه خدمة. لو الشهر مترحّلش لسه، الحوض بيطلع صفر — وده صحيح، مش عطل.
    """
    from app.models.accounting import JournalLine

    first, last = month_bounds(year, month)
    account = db.execute(
        select(Account).where(
            Account.property_id == property_id, Account.code == SERVICE_PAYABLE
        )
    ).scalar_one_or_none()
    if account is None:
        return ZERO

    total = db.execute(
        select(func.coalesce(func.sum(JournalLine.credit), 0)).where(
            JournalLine.account_id == account.id,
            JournalLine.business_date >= first,
            JournalLine.business_date <= last,
        )
    ).scalar_one()
    return money(Decimal(str(total)))


def distribute(pool: Decimal, employees: Sequence[Employee]) -> dict[int, Decimal]:
    """توزيع حوض الخدمة بالنقاط — بالمليم، من غير ما يضيع ولا يزيد.

    التقريب لكل موظف على حدة بيخلّي المجموع مختلف عن الحوض بجنيهات.
    والفرق ده مش مقبول: الخدمة فلوس محصّلة من النزيل ومحجوزة في حساب
    التزام، فاللي بيتوزّع لازم يساوي اللي اتحصّل بالظبط — وإلا الالتزام
    مبيتصفّرش والدفتر بيفضل شايل رصيد وهمي.

    الحل: نوزّع بالتقريب، وبعدين نضيف الفرق للنصيب الأكبر.
    """
    if pool <= 0 or not employees:
        return {}

    total_points = sum((e.service_points for e in employees), ZERO)
    if total_points <= 0:
        return {}

    shares = {
        e.id: money(pool * e.service_points / total_points) for e in employees
    }
    residual = money(pool - sum(shares.values(), ZERO))
    if residual:
        biggest = max(shares, key=lambda key: shares[key])
        shares[biggest] = money(shares[biggest] + residual)
    return shares


def unpaid_leave_days(
    db: Session, property_id: int, year: int, month: int
) -> dict[int, Decimal]:
    """أيام الإجازة بدون أجر المعتمدة في الشهر لكل موظف."""
    first, last = month_bounds(year, month)
    rows = db.execute(
        select(LeaveRequest.employee_id, func.coalesce(func.sum(LeaveRequest.days), 0))
        .where(
            LeaveRequest.property_id == property_id,
            LeaveRequest.kind == LeaveKind.UNPAID,
            LeaveRequest.is_approved.is_(True),
            LeaveRequest.from_date >= first,
            LeaveRequest.from_date <= last,
        )
        .group_by(LeaveRequest.employee_id)
    ).all()
    return {int(e): Decimal(str(d)) for e, d in rows}


# ═══════════════════════════════════════════════════ المسيّر
def get_run(db: Session, property_id: int, year: int, month: int) -> PayrollRun | None:
    return db.execute(
        select(PayrollRun).where(
            PayrollRun.property_id == property_id,
            PayrollRun.year == year,
            PayrollRun.month == month,
        )
    ).scalar_one_or_none()


def build(
    db: Session,
    property_id: int,
    year: int,
    month: int,
    *,
    user: User | None = None,
    overrides: dict[int, dict[str, Decimal]] | None = None,
) -> PayrollRun:
    """بناء مسيّر الشهر أو إعادة حسابه بالكامل.

    إعادة البناء بتمسح القسايم وتحسبها من الأول — ده آمن ما دام المسيّر
    مسودة. بعد الاعتماد الدالة بترفض، لأن الرقم بقى مرحّل في الدفتر.
    """
    if not 1 <= month <= 12:
        raise PayrollError("شهر غير صحيح", "Invalid month", "bad_month")

    run = get_run(db, property_id, year, month)
    if run and run.status != PayrollStatus.DRAFT:
        raise PayrollError(
            f"مسيّر {run.label} معتمد — التصحيح بيتم بتسوية في الشهر الجاي",
            f"Payroll {run.label} is already approved",
            "approved",
        )

    if run is None:
        run = PayrollRun(
            number=next_number(db, property_id, "PAYROLL", on_date=date(year, month, 1)),
            property_id=property_id,
            year=year,
            month=month,
            status=PayrollStatus.DRAFT,
        )
        db.add(run)
        db.flush()
    else:
        for slip in list(run.payslips):
            db.delete(slip)
        db.flush()

    _, last = month_bounds(year, month)
    employees = list(
        db.execute(
            select(Employee).where(
                Employee.property_id == property_id,
                Employee.status.in_(
                    [EmploymentStatus.ACTIVE, EmploymentStatus.PROBATION]
                ),
                Employee.hire_date <= last,
            )
        ).scalars().all()
    )
    if not employees:
        raise PayrollError("مفيش موظفين على رأس العمل", "No active employees", "empty")

    pool = service_pool(db, property_id, year, month)
    shares = distribute(pool, employees)
    unpaid = unpaid_leave_days(db, property_id, year, month)
    extras = overrides or {}

    totals = {
        "gross": ZERO,
        "insurance_employee": ZERO,
        "insurance_employer": ZERO,
        "tax": ZERO,
        "deductions": ZERO,
        "net": ZERO,
    }

    for employee in employees:
        extra = extras.get(employee.id, {})
        share = shares.get(employee.id, ZERO)
        calc = calculate_employee(
            employee,
            service_share=share,
            overtime=extra.get("overtime", ZERO),
            bonus=extra.get("bonus", ZERO),
            advances=extra.get("advances", ZERO),
            penalties=extra.get("penalties", ZERO),
            unpaid_days=unpaid.get(employee.id, ZERO),
        )
        db.add(
            Payslip(
                payroll_run_id=run.id,
                property_id=property_id,
                employee_id=employee.id,
                department_id=employee.department_id,
                basic_salary=calc.basic,
                allowances=calc.allowances,
                overtime=calc.overtime,
                service_share=calc.service_share,
                bonus=calc.bonus,
                gross=calc.gross,
                insurance_employee=calc.insurance_employee,
                insurance_employer=calc.insurance_employer,
                income_tax=calc.income_tax,
                unpaid_leave=calc.unpaid_leave,
                unpaid_days=calc.unpaid_days,
                advances=calc.advances,
                penalties=calc.penalties,
                total_deductions=calc.total_deductions,
                net_pay=calc.net_pay,
            )
        )
        totals["gross"] += calc.gross
        totals["insurance_employee"] += calc.insurance_employee
        totals["insurance_employer"] += calc.insurance_employer
        totals["tax"] += calc.income_tax
        totals["deductions"] += calc.total_deductions
        totals["net"] += calc.net_pay

    run.service_pool = pool
    run.headcount = len(employees)
    run.total_gross = money(totals["gross"])
    run.total_insurance_employee = money(totals["insurance_employee"])
    run.total_insurance_employer = money(totals["insurance_employer"])
    run.total_tax = money(totals["tax"])
    run.total_deductions = money(totals["deductions"])
    run.total_net = money(totals["net"])
    db.flush()
    return run


def approve(
    db: Session, property_id: int, run_id: int, *, user: User | None = None
) -> PayrollRun:
    """اعتماد المسيّر وترحيله للدفتر — قيد واحد بيحرّك ستة حسابات.

    الأجر بينقسم: الجزء اللي الفندق بيتحمّله بيتقيّد مصروف، والجزء اللي
    من حوض الخدمة بيتقيّد تخفيض للالتزام — لأنه كان محصّل من النزيل أصلاً
    ومحجوز للعاملين، فمش مصروف جديد على المنشأة.
    """
    run = db.get(PayrollRun, run_id)
    if run is None or run.property_id != property_id:
        raise PayrollError("المسيّر مش موجود", "Payroll run not found", "not_found")
    if run.status != PayrollStatus.DRAFT:
        raise PayrollError("المسيّر معتمد قبل كده", "Already approved", "approved")
    if not run.payslips:
        raise PayrollError("المسيّر فاضي", "Payroll run is empty", "empty")

    # تاريخ الترحيل آخر الشهر، أو النهارده لو الشهر لسه شغّال. من غير
    # القيد ده كانت تكلفة العاملين هتفضل بره قائمة الدخل لحد آخر الشهر،
    # وقائمة نص الشهر تطلع بهامش مش حقيقي.
    _, month_end = month_bounds(run.year, run.month)
    last = min(month_end, date.today())
    service_total = money(sum((s.service_share for s in run.payslips), ZERO))
    #: اللي المنشأة بتتحمّله فعلاً — الإجمالي ناقص الخدمة المحصّلة
    employer_salary_cost = money(run.total_gross - service_total)

    lines = []
    if employer_salary_cost:
        lines.append(
            gl.debit(
                SALARIES_EXPENSE, employer_salary_cost, "مرتبات وأجور", cost_center_code="ADMIN"
            )
        )
    if service_total:
        # الالتزام بيتخفّض بقيمة اللي اتوزّع
        lines.append(gl.debit(SERVICE_PAYABLE, service_total, "توزيع الخدمة على العاملين"))
    if run.total_insurance_employer:
        lines.append(
            gl.debit(
                EMPLOYER_INSURANCE_EXPENSE,
                run.total_insurance_employer,
                "حصة صاحب العمل في التأمينات",
                cost_center_code="ADMIN",
            )
        )

    insurance_total = money(run.total_insurance_employee + run.total_insurance_employer)
    if run.total_net:
        lines.append(gl.credit(SALARIES_PAYABLE, run.total_net, "صافي مرتبات مستحقة"))
    if insurance_total:
        lines.append(gl.credit(INSURANCE_PAYABLE, insurance_total, "تأمينات مستحقة"))
    if run.total_tax:
        lines.append(gl.credit(TAX_PAYABLE, run.total_tax, "ضريبة كسب عمل مستحقة"))

    # السلف والجزاءات بتقلّل الصافي بس مش مصروف — بترجع للخزينة
    recovered = money(
        sum((s.advances + s.penalties for s in run.payslips), ZERO)
    )
    if recovered:
        lines.append(gl.credit(CASH, recovered, "استرداد سلف وجزاءات"))

    entry = gl.post(
        db,
        property_id,
        business_date=last,
        lines=lines,
        description_ar=f"مسيّر مرتبات {run.label} — {run.headcount} موظف",
        description_en=f"Payroll {run.label} — {run.headcount} employees",
        source=JournalSource.PAYROLL,
        source_key=run.label,
        user=user,
    )

    run.status = PayrollStatus.APPROVED
    run.approved_at = utcnow()
    run.approved_by_user_id = user.id if user else None
    run.journal_entry_id = entry.id if entry else None
    db.flush()
    return run


def mark_paid(
    db: Session,
    property_id: int,
    run_id: int,
    *,
    from_bank: bool = True,
    user: User | None = None,
) -> PayrollRun:
    """صرف المسيّر — بيقفل الالتزام مقابل خروج فعلي من البنك أو الخزينة."""
    run = db.get(PayrollRun, run_id)
    if run is None or run.property_id != property_id:
        raise PayrollError("المسيّر مش موجود", "Payroll run not found", "not_found")
    if run.status != PayrollStatus.APPROVED:
        raise PayrollError(
            "لازم يتعتمد الأول", "The run must be approved first", "not_approved"
        )

    _, month_end = month_bounds(run.year, run.month)
    gl.post(
        db,
        property_id,
        business_date=min(month_end, date.today()),
        lines=[
            gl.debit(SALARIES_PAYABLE, run.total_net, "صرف المرتبات"),
            gl.credit(BANK if from_bank else CASH, run.total_net, "صرف المرتبات"),
        ],
        description_ar=f"صرف مرتبات {run.label}",
        description_en=f"Payroll payment {run.label}",
        source=JournalSource.PAYROLL,
        source_key=f"PAY:{run.label}",
        user=user,
    )
    run.status = PayrollStatus.PAID
    run.paid_at = utcnow()
    db.flush()
    return run


# ═══════════════════════════════════════════════════ تقارير
@dataclass(slots=True)
class DepartmentCost:
    department: Department
    headcount: int
    gross: Decimal
    employer_cost: Decimal


def cost_by_department(
    db: Session, property_id: int, run_id: int
) -> list[DepartmentCost]:
    """تكلفة العاملين لكل قسم — الرقم اللي بيتقارن بإيراد القسم."""
    run = db.get(PayrollRun, run_id)
    if run is None or run.property_id != property_id:
        raise PayrollError("المسيّر مش موجود", "Payroll run not found", "not_found")

    departments = {
        d.id: d
        for d in db.execute(
            select(Department).where(Department.property_id == property_id)
        ).scalars()
    }
    buckets: dict[int, list[Payslip]] = {}
    for slip in run.payslips:
        buckets.setdefault(slip.department_id, []).append(slip)

    rows = [
        DepartmentCost(
            department=departments[department_id],
            headcount=len(slips),
            gross=money(sum((s.gross for s in slips), ZERO)),
            employer_cost=money(
                sum((s.gross + s.insurance_employer for s in slips), ZERO)
            ),
        )
        for department_id, slips in buckets.items()
        if department_id in departments
    ]
    rows.sort(key=lambda r: r.employer_cost, reverse=True)
    return rows


def runs(db: Session, property_id: int, *, limit: int = 24) -> Sequence[PayrollRun]:
    return list(
        db.execute(
            select(PayrollRun)
            .where(PayrollRun.property_id == property_id)
            .order_by(PayrollRun.year.desc(), PayrollRun.month.desc())
            .limit(limit)
        ).scalars().all()
    )
