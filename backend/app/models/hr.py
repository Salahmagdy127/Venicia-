"""شؤون العاملين والمرتبات — Employees and payroll.

المرتبات هي أكبر بند مصروف في أي فندق، ومع ذلك بتتحسب في أغلب القرى
على إكسل. المشكلة مش الحساب — المشكلة إن الرقم اللي بيطلع من الإكسل
مالوش أثر: مفيش حد يقدر يرجع بعد سنة ويقول ليه الموظف ده اتخصم منه كذا.

الموديول ده بيخلّي المسيّر مستند: بيتحسب من عناصر مكتوبة، بيتعتمد،
بيترحّل للدفتر قيد مزدوج، وبيفضل محفوظ بتفاصيله سطر سطر.

**والحتة اللي بتفرق في مصر تحديداً**: الخدمة 12% اللي بتتحصّل من النزيل
مش إيراد للفندق — دي حق العاملين. النظام بيجمّعها في حساب التزام مع كل
فاتورة، والمسيّر بيوزّعها عليهم بالنقاط. يعني الرقم اللي بيتوزّع محسوب
من الفواتير الفعلية، مش تقدير.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Percent, TZDateTime
from app.models.enums import (
    ContractType,
    EmploymentStatus,
    Gender,
    LeaveKind,
    PayrollStatus,
)
from app.models.mixins import ActiveMixin, BilingualNameMixin

ZERO = Decimal("0")


class Department(Base, PKMixin, TimestampMixin, BilingualNameMixin, ActiveMixin):
    """قسم — بيربط الموظف بمركز التكلفة، فمرتبه بيروح على القسم الصح."""

    __tablename__ = "department"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    cost_center_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    manager_employee_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("property_id", "code", name="uq_department_code"),
    )


class Employee(Base, PKMixin, TimestampMixin, BilingualNameMixin):
    """موظف."""

    __tablename__ = "employee"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("department.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: حساب الدخول على النظام — مش كل موظف ليه حساب
    user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    job_title_ar: Mapped[str] = mapped_column(String(120), nullable=False)
    job_title_en: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[EmploymentStatus] = mapped_column(
        String(12), nullable=False, default=EmploymentStatus.ACTIVE, index=True
    )
    contract_type: Mapped[ContractType] = mapped_column(
        String(10), nullable=False, default=ContractType.FULL_TIME
    )

    national_id: Mapped[Optional[str]] = mapped_column(String(20))
    #: الرقم التأميني — مطلوب في نموذج 1 و2 للتأمينات
    insurance_number: Mapped[Optional[str]] = mapped_column(String(20))
    gender: Mapped[Gender] = mapped_column(String(12), nullable=False, default=Gender.MALE)
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    address: Mapped[Optional[str]] = mapped_column(String(300))

    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)

    # --- الأجر ---
    basic_salary: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    #: بدلات ثابتة — انتقال وسكن ووجبة
    allowances: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    #: الأجر التأميني — بيختلف عن الأساسي وله حد أدنى وأقصى بالقانون
    insurance_salary: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    #: نقاط توزيع الخدمة — الكابتن بياخد أكتر من الكوميز
    service_points: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("1")
    )
    is_insured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    bank_name: Mapped[Optional[str]] = mapped_column(String(80))
    bank_account: Mapped[Optional[str]] = mapped_column(String(40))

    #: رصيد الإجازة السنوية المتبقّي
    annual_leave_balance: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("21")
    )
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("property_id", "code", name="uq_employee_code"),
        Index("ix_employee_dept", "property_id", "department_id", "status"),
    )

    @property
    def gross_salary(self) -> Decimal:
        return self.basic_salary + self.allowances

    @property
    def is_working(self) -> bool:
        return self.status in (EmploymentStatus.ACTIVE, EmploymentStatus.PROBATION)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Employee {self.code} {self.name_ar}>"


class LeaveRequest(Base, PKMixin, TimestampMixin):
    """طلب إجازة — بيخصم من الرصيد، والإجازة بدون أجر بتخصم من المرتب."""

    __tablename__ = "leave_request"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    employee_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("employee.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[LeaveKind] = mapped_column(String(10), nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=ZERO)

    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    approved_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    reason: Mapped[Optional[str]] = mapped_column(String(300))

    __table_args__ = (
        Index("ix_leave_employee_date", "employee_id", "from_date"),
    )


class PayrollRun(Base, PKMixin, TimestampMixin):
    """مسيّر شهر — بيتحسب مرة، بيتراجع، وبعدين بيتعتمد ويترحّل.

    المسودة قابلة لإعادة الحساب بالكامل. بعد الاعتماد بتتقفل: التصحيح
    بيبقى بمسيّر تسويات في الشهر اللي بعده — عشان الرقم اللي اترحّل
    للدفتر ما يتغيّرش من ورا المحاسب.
    """

    __tablename__ = "payroll_run"

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[PayrollStatus] = mapped_column(
        String(10), nullable=False, default=PayrollStatus.DRAFT, index=True
    )

    #: مجموع الخدمة اللي اتجمّعت في الشهر واتوزّعت في المسيّر ده
    service_pool: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)

    total_gross: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    total_insurance_employee: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    total_insurance_employer: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    total_tax: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    total_deductions: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    total_net: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    headcount: Mapped[int] = mapped_column(nullable=False, default=0)

    approved_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    paid_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    #: القيد اللي اترحّل للدفتر — الوصلة بين المسيّر والحسابات
    journal_entry_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    payslips: Mapped[list["Payslip"]] = relationship(
        back_populates="run", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("property_id", "year", "month", name="uq_payroll_period"),
    )

    @property
    def label(self) -> str:
        return f"{self.year}-{self.month:02d}"

    @property
    def total_cost(self) -> Decimal:
        """التكلفة الحقيقية على المنشأة — الإجمالي + حصة صاحب العمل."""
        return self.total_gross + self.total_insurance_employer


class Payslip(Base, PKMixin):
    """قسيمة موظف في مسيّر — كل عنصر مكتوب لوحده عشان الرقم يبقى مفسَّر."""

    __tablename__ = "payslip"

    payroll_run_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("payroll_run.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    employee_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)

    # --- المستحق ---
    basic_salary: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    allowances: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    overtime: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    #: نصيبه من الخدمة 12% — محسوب بالنقاط من المحصّل فعلاً
    service_share: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    bonus: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    gross: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)

    # --- المستقطع ---
    insurance_employee: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    insurance_employer: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    income_tax: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    #: خصم أيام الإجازة بدون أجر
    unpaid_leave: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    #: سلف وخصومات جزائية
    advances: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    penalties: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    total_deductions: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)

    net_pay: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)

    unpaid_days: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=ZERO)
    notes: Mapped[Optional[str]] = mapped_column(String(300))

    run: Mapped[PayrollRun] = relationship(back_populates="payslips", lazy="noload")

    __table_args__ = (
        UniqueConstraint("payroll_run_id", "employee_id", name="uq_payslip_employee"),
        Index("ix_payslip_run", "payroll_run_id"),
    )
