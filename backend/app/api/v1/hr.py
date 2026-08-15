"""واجهات شؤون العاملين والمرتبات — HR and payroll endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.enums import (
    AuditAction,
    ContractType,
    EmploymentStatus,
    Gender,
    LeaveKind,
    PayrollStatus,
)
from app.models.hr import Department, Employee, LeaveRequest, PayrollRun, Payslip
from app.schemas.common import ApiModel
from app.services import audit
from app.services import payroll as pr
from app.services.pricing import money

router = APIRouter(prefix="/hr", tags=["شؤون العاملين — HR"])


# ═══════════════════════════════════════════════════════════ النماذج
class DepartmentOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    cost_center_id: int | None = None
    headcount: int = 0


class EmployeeOut(ApiModel):
    id: int
    code: str
    name_ar: str
    name_en: str
    department_id: int
    department_name_ar: str
    job_title_ar: str
    job_title_en: str
    status: EmploymentStatus
    contract_type: ContractType
    hire_date: date
    basic_salary: Decimal
    allowances: Decimal
    gross_salary: Decimal
    insurance_salary: Decimal
    service_points: Decimal
    is_insured: bool
    phone: str | None = None
    annual_leave_balance: Decimal


class EmployeeIn(ApiModel):
    code: str
    name_ar: str
    name_en: str
    department_id: int
    job_title_ar: str
    job_title_en: str
    hire_date: date
    basic_salary: Decimal
    allowances: Decimal = Decimal("0")
    insurance_salary: Decimal = Decimal("0")
    service_points: Decimal = Decimal("1")
    contract_type: ContractType = ContractType.FULL_TIME
    gender: Gender = Gender.MALE
    is_insured: bool = True
    national_id: str | None = None
    phone: str | None = None


class EmployeePatch(ApiModel):
    department_id: int | None = None
    job_title_ar: str | None = None
    job_title_en: str | None = None
    status: EmploymentStatus | None = None
    basic_salary: Decimal | None = None
    allowances: Decimal | None = None
    insurance_salary: Decimal | None = None
    service_points: Decimal | None = None
    is_insured: bool | None = None
    phone: str | None = None
    end_date: date | None = None


class StaffBoard(ApiModel):
    headcount: int
    monthly_payroll_cost: Decimal
    departments: list[DepartmentOut]
    employees: list[EmployeeOut]


class PayslipOut(ApiModel):
    employee_id: int
    employee_code: str
    employee_name_ar: str
    job_title_ar: str
    department_id: int
    basic_salary: Decimal
    allowances: Decimal
    overtime: Decimal
    service_share: Decimal
    bonus: Decimal
    gross: Decimal
    insurance_employee: Decimal
    insurance_employer: Decimal
    income_tax: Decimal
    unpaid_leave: Decimal
    unpaid_days: Decimal
    advances: Decimal
    penalties: Decimal
    total_deductions: Decimal
    net_pay: Decimal


class DepartmentCostOut(ApiModel):
    department_id: int
    name_ar: str
    headcount: int
    gross: Decimal
    employer_cost: Decimal


class PayrollRunOut(ApiModel):
    id: int
    number: str
    year: int
    month: int
    label: str
    status: PayrollStatus
    headcount: int
    service_pool: Decimal
    total_gross: Decimal
    total_insurance_employee: Decimal
    total_insurance_employer: Decimal
    total_tax: Decimal
    total_deductions: Decimal
    total_net: Decimal
    total_cost: Decimal
    approved_at: datetime | None = None
    paid_at: datetime | None = None
    journal_entry_id: int | None = None


class PayrollDetail(PayrollRunOut):
    payslips: list[PayslipOut] = []
    by_department: list[DepartmentCostOut] = []


class BuildPayrollIn(ApiModel):
    year: int
    month: int


class LeaveIn(ApiModel):
    employee_id: int
    kind: LeaveKind
    from_date: date
    to_date: date
    reason: str | None = None


class LeaveOut(ApiModel):
    id: int
    employee_id: int
    employee_name_ar: str
    kind: LeaveKind
    from_date: date
    to_date: date
    days: Decimal
    is_approved: bool
    reason: str | None = None


class TaxPreviewOut(ApiModel):
    """معاينة الشرايح — بتخلّي رقم الضريبة مفسَّر مش سحري."""

    monthly_gross: Decimal
    annual_taxable: Decimal
    personal_exemption: Decimal
    monthly_tax: Decimal
    annual_tax: Decimal
    effective_percent: Decimal


# ═══════════════════════════════════════════════════════════ أدوات
def _fail(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "error")
    http = {"not_found": 404, "approved": 409, "not_approved": 409}.get(code, 400)
    return HTTPException(
        status_code=http,
        detail={
            "ar": getattr(exc, "message_ar", str(exc)),
            "en": getattr(exc, "message_en", str(exc)),
            "code": code,
        },
    )


def _departments(db, property_id: int) -> dict[int, Department]:
    return {
        d.id: d
        for d in db.execute(
            select(Department).where(Department.property_id == property_id)
        ).scalars()
    }


def _employee_out(employee: Employee, departments: dict[int, Department]) -> EmployeeOut:
    department = departments.get(employee.department_id)
    return EmployeeOut(
        id=employee.id,
        code=employee.code,
        name_ar=employee.name_ar,
        name_en=employee.name_en,
        department_id=employee.department_id,
        department_name_ar=department.name_ar if department else "",
        job_title_ar=employee.job_title_ar,
        job_title_en=employee.job_title_en,
        status=employee.status,
        contract_type=employee.contract_type,
        hire_date=employee.hire_date,
        basic_salary=employee.basic_salary,
        allowances=employee.allowances,
        gross_salary=employee.gross_salary,
        insurance_salary=employee.insurance_salary,
        service_points=employee.service_points,
        is_insured=employee.is_insured,
        phone=employee.phone,
        annual_leave_balance=employee.annual_leave_balance,
    )


def _run_out(run: PayrollRun) -> PayrollRunOut:
    return PayrollRunOut(
        id=run.id,
        number=run.number,
        year=run.year,
        month=run.month,
        label=run.label,
        status=run.status,
        headcount=run.headcount,
        service_pool=run.service_pool,
        total_gross=run.total_gross,
        total_insurance_employee=run.total_insurance_employee,
        total_insurance_employer=run.total_insurance_employer,
        total_tax=run.total_tax,
        total_deductions=run.total_deductions,
        total_net=run.total_net,
        total_cost=run.total_cost,
        approved_at=run.approved_at,
        paid_at=run.paid_at,
        journal_entry_id=run.journal_entry_id,
    )


# ═══════════════════════════════════════════════════════════ العاملون
@router.get(
    "",
    response_model=StaffBoard,
    summary="لوحة العاملين",
    dependencies=[Depends(require("hr.view"))],
)
def board(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    department_id: int | None = None,
    search: str | None = None,
) -> StaffBoard:
    departments = _departments(db, prop.id)

    stmt = select(Employee).where(Employee.property_id == prop.id)
    if department_id:
        stmt = stmt.where(Employee.department_id == department_id)
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            Employee.name_ar.like(needle)
            | Employee.name_en.like(needle)
            | Employee.code.like(needle)
        )
    employees = list(
        db.execute(stmt.order_by(Employee.department_id, Employee.code)).scalars().all()
    )

    counts = dict(
        db.execute(
            select(Employee.department_id, func.count(Employee.id))
            .where(
                Employee.property_id == prop.id,
                Employee.status.in_([EmploymentStatus.ACTIVE, EmploymentStatus.PROBATION]),
            )
            .group_by(Employee.department_id)
        ).all()
    )

    working = [e for e in employees if e.is_working]
    monthly = sum(
        (e.gross_salary + pr.insurance_base(e) * pr.INSURANCE_EMPLOYER_PERCENT / 100)
        for e in working
    )

    return StaffBoard(
        headcount=len(working),
        monthly_payroll_cost=Decimal(monthly).quantize(Decimal("0.01")),
        departments=[
            DepartmentOut(
                id=d.id,
                code=d.code,
                name_ar=d.name_ar,
                name_en=d.name_en,
                cost_center_id=d.cost_center_id,
                headcount=int(counts.get(d.id, 0)),
            )
            for d in sorted(departments.values(), key=lambda x: x.sort_order)
        ],
        employees=[_employee_out(e, departments) for e in employees],
    )


@router.post(
    "/employees",
    response_model=EmployeeOut,
    status_code=status.HTTP_201_CREATED,
    summary="إضافة موظف",
    dependencies=[Depends(require("hr.manage"))],
)
def create_employee(
    payload: EmployeeIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> EmployeeOut:
    departments = _departments(db, prop.id)
    if payload.department_id not in departments:
        raise HTTPException(status_code=404, detail={"ar": "القسم مش موجود", "en": "No department"})

    exists = db.execute(
        select(Employee).where(
            Employee.property_id == prop.id, Employee.code == payload.code.strip()
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(
            status_code=409,
            detail={"ar": "كود الموظف مستخدم قبل كده", "en": "Employee code already used"},
        )

    employee = Employee(
        property_id=prop.id,
        code=payload.code.strip(),
        name_ar=payload.name_ar.strip(),
        name_en=payload.name_en.strip(),
        department_id=payload.department_id,
        job_title_ar=payload.job_title_ar.strip(),
        job_title_en=payload.job_title_en.strip(),
        hire_date=payload.hire_date,
        basic_salary=payload.basic_salary,
        allowances=payload.allowances,
        # الأجر التأميني بيساوي الأساسي لو ماتحدّدش — ده العرف الشائع
        insurance_salary=payload.insurance_salary or payload.basic_salary,
        service_points=payload.service_points,
        contract_type=payload.contract_type,
        gender=payload.gender,
        is_insured=payload.is_insured,
        national_id=payload.national_id,
        phone=payload.phone,
        status=EmploymentStatus.PROBATION,
    )
    db.add(employee)
    db.flush()

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="employee",
        entity_id=employee.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إضافة موظف {employee.name_ar}",
        summary_en=f"Added employee {employee.name_en}",
        request=request,
    )
    db.commit()
    return _employee_out(employee, departments)


@router.patch(
    "/employees/{employee_id}",
    response_model=EmployeeOut,
    summary="تعديل بيانات موظف",
    dependencies=[Depends(require("hr.manage"))],
)
def update_employee(
    employee_id: int,
    payload: EmployeePatch,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> EmployeeOut:
    employee = db.get(Employee, employee_id)
    if employee is None or employee.property_id != prop.id:
        raise HTTPException(status_code=404, detail={"ar": "الموظف مش موجود", "en": "Not found"})

    before = {
        "basic_salary": employee.basic_salary,
        "allowances": employee.allowances,
        "status": employee.status,
        "department_id": employee.department_id,
    }
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(employee, field, value)
    db.flush()

    departments = _departments(db, prop.id)
    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="employee",
        entity_id=employee.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"تعديل بيانات {employee.name_ar}",
        summary_en=f"Updated {employee.name_en}",
        changes=audit.diff(
            before,
            {
                "basic_salary": employee.basic_salary,
                "allowances": employee.allowances,
                "status": employee.status,
                "department_id": employee.department_id,
            },
        ),
        request=request,
    )
    db.commit()
    return _employee_out(employee, departments)


# ═══════════════════════════════════════════════════════════ الإجازات
@router.get(
    "/leave",
    response_model=list[LeaveOut],
    summary="طلبات الإجازة",
    dependencies=[Depends(require("hr.view"))],
)
def leave_requests(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    limit: int = Query(50, ge=1, le=200),
) -> list[LeaveOut]:
    rows = db.execute(
        select(LeaveRequest, Employee)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .where(LeaveRequest.property_id == prop.id)
        .order_by(LeaveRequest.from_date.desc())
        .limit(limit)
    ).all()
    return [
        LeaveOut(
            id=leave.id,
            employee_id=leave.employee_id,
            employee_name_ar=employee.name_ar,
            kind=leave.kind,
            from_date=leave.from_date,
            to_date=leave.to_date,
            days=leave.days,
            is_approved=leave.is_approved,
            reason=leave.reason,
        )
        for leave, employee in rows
    ]


@router.post(
    "/leave",
    response_model=LeaveOut,
    status_code=status.HTTP_201_CREATED,
    summary="طلب إجازة",
    dependencies=[Depends(require("hr.manage"))],
)
def request_leave(
    payload: LeaveIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> LeaveOut:
    employee = db.get(Employee, payload.employee_id)
    if employee is None or employee.property_id != prop.id:
        raise HTTPException(status_code=404, detail={"ar": "الموظف مش موجود", "en": "Not found"})
    if payload.to_date < payload.from_date:
        raise HTTPException(
            status_code=422, detail={"ar": "تاريخ النهاية قبل البداية", "en": "Bad range"}
        )

    days = Decimal((payload.to_date - payload.from_date).days + 1)
    if payload.kind == LeaveKind.ANNUAL and employee.annual_leave_balance < days:
        raise HTTPException(
            status_code=409,
            detail={
                "ar": f"الرصيد {employee.annual_leave_balance} يوم بس",
                "en": f"Only {employee.annual_leave_balance} days left",
            },
        )

    leave = LeaveRequest(
        property_id=prop.id,
        employee_id=employee.id,
        kind=payload.kind,
        from_date=payload.from_date,
        to_date=payload.to_date,
        days=days,
        is_approved=True,
        approved_by_user_id=user.id,
        approved_at=datetime.now().astimezone(),
        reason=payload.reason,
    )
    db.add(leave)
    if payload.kind == LeaveKind.ANNUAL:
        employee.annual_leave_balance = employee.annual_leave_balance - days
    db.flush()

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="leave_request",
        entity_id=leave.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إجازة {payload.kind} لـ {employee.name_ar} — {days} يوم",
        summary_en=f"{payload.kind} leave for {employee.name_en} — {days} days",
        request=request,
    )
    db.commit()
    return LeaveOut(
        id=leave.id,
        employee_id=leave.employee_id,
        employee_name_ar=employee.name_ar,
        kind=leave.kind,
        from_date=leave.from_date,
        to_date=leave.to_date,
        days=leave.days,
        is_approved=leave.is_approved,
        reason=leave.reason,
    )


# ═══════════════════════════════════════════════════════════ المرتبات
@router.get(
    "/payroll",
    response_model=list[PayrollRunOut],
    summary="مسيّرات المرتبات",
    dependencies=[Depends(require("payroll.view"))],
)
def payroll_runs(db: DbSession, user: CurrentUser, prop: CurrentProperty):
    return [_run_out(r) for r in pr.runs(db, prop.id)]


@router.get(
    "/payroll/{run_id}",
    response_model=PayrollDetail,
    summary="تفاصيل مسيّر",
    dependencies=[Depends(require("payroll.view"))],
)
def payroll_detail(
    run_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> PayrollDetail:
    run = db.get(PayrollRun, run_id)
    if run is None or run.property_id != prop.id:
        raise HTTPException(status_code=404, detail={"ar": "المسيّر مش موجود", "en": "Not found"})

    employees = {
        e.id: e
        for e in db.execute(
            select(Employee).where(Employee.property_id == prop.id)
        ).scalars()
    }
    base = _run_out(run)
    return PayrollDetail(
        **base.model_dump(),
        payslips=[
            PayslipOut(
                employee_id=s.employee_id,
                employee_code=employees[s.employee_id].code if s.employee_id in employees else "",
                employee_name_ar=(
                    employees[s.employee_id].name_ar if s.employee_id in employees else ""
                ),
                job_title_ar=(
                    employees[s.employee_id].job_title_ar if s.employee_id in employees else ""
                ),
                department_id=s.department_id,
                basic_salary=s.basic_salary,
                allowances=s.allowances,
                overtime=s.overtime,
                service_share=s.service_share,
                bonus=s.bonus,
                gross=s.gross,
                insurance_employee=s.insurance_employee,
                insurance_employer=s.insurance_employer,
                income_tax=s.income_tax,
                unpaid_leave=s.unpaid_leave,
                unpaid_days=s.unpaid_days,
                advances=s.advances,
                penalties=s.penalties,
                total_deductions=s.total_deductions,
                net_pay=s.net_pay,
            )
            for s in sorted(run.payslips, key=lambda x: x.net_pay, reverse=True)
        ],
        by_department=[
            DepartmentCostOut(
                department_id=row.department.id,
                name_ar=row.department.name_ar,
                headcount=row.headcount,
                gross=row.gross,
                employer_cost=row.employer_cost,
            )
            for row in pr.cost_by_department(db, prop.id, run_id)
        ],
    )


@router.post(
    "/payroll/build",
    response_model=PayrollDetail,
    summary="حساب مسيّر شهر",
    dependencies=[Depends(require("payroll.run"))],
)
def build_payroll(
    payload: BuildPayrollIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> PayrollDetail:
    try:
        run = pr.build(db, prop.id, payload.year, payload.month, user=user)
    except pr.PayrollError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="payroll_run",
        entity_id=run.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"حساب مسيّر {run.label} — {run.headcount} موظف",
        summary_en=f"Built payroll {run.label}",
        request=request,
    )
    db.commit()
    return payroll_detail(run.id, db, user, prop)


@router.post(
    "/payroll/{run_id}/approve",
    response_model=PayrollRunOut,
    summary="اعتماد وترحيل مسيّر",
    dependencies=[Depends(require("payroll.approve"))],
)
def approve_payroll(
    run_id: int,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> PayrollRunOut:
    from app.services.accounting import AccountingError

    try:
        run = pr.approve(db, prop.id, run_id, user=user)
    except (pr.PayrollError, AccountingError) as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="payroll_run",
        entity_id=run.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"اعتماد مسيّر {run.label} بصافي {run.total_net}",
        summary_en=f"Approved payroll {run.label}",
        request=request,
    )
    db.commit()
    return _run_out(run)


@router.post(
    "/payroll/{run_id}/pay",
    response_model=PayrollRunOut,
    summary="صرف مسيّر",
    dependencies=[Depends(require("payroll.approve"))],
)
def pay_payroll(
    run_id: int,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
    from_bank: bool = True,
) -> PayrollRunOut:
    try:
        run = pr.mark_paid(db, prop.id, run_id, from_bank=from_bank, user=user)
    except pr.PayrollError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.UPDATE,
        entity_type="payroll_run",
        entity_id=run.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"صرف مسيّر {run.label}",
        summary_en=f"Paid payroll {run.label}",
        request=request,
    )
    db.commit()
    return _run_out(run)


@router.get(
    "/tax-preview",
    response_model=TaxPreviewOut,
    summary="معاينة حساب الضريبة",
    dependencies=[Depends(require("hr.view"))],
)
def tax_preview(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    monthly_gross: Decimal = Query(..., gt=0),
) -> TaxPreviewOut:
    """بيوضّح الشرايح على مرتب معيّن — المحاسب بيتأكد من الرقم قبل المسيّر."""
    annual = money(monthly_gross * 12)
    annual_tax = pr.annual_income_tax(annual)
    monthly = money(annual_tax / 12)
    return TaxPreviewOut(
        monthly_gross=monthly_gross,
        annual_taxable=annual,
        personal_exemption=pr.PERSONAL_EXEMPTION,
        monthly_tax=monthly,
        annual_tax=annual_tax,
        effective_percent=(
            money(annual_tax / annual * 100) if annual else Decimal("0")
        ),
    )
