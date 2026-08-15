"""دفتر الأستاذ العام — General ledger, chart of accounts, journals.

الموديول ده بيقفل الدايرة على كل اللي فات. كل حركة تشغيلية في النظام —
ليلة مباعة، أوردر في المطعم، دفعة اتحصّلت، فاتورة مورد اتستلمت، كيلو
لحمة اتصرف — بتتحوّل لقيد مزدوج، والقيود دي مجموعها بيطلّع ميزان
المراجعة وقائمة الدخل والمركز المالي.

تلات قواعد محكومة:

**١. القيد المرحّل مبيتعدّلش.** الغلط بيتصحّح بقيد عكسي ليه سبب مكتوب.
ده مش تشدّد — ده الفرق بين دفتر ينفع في فحص ضريبي ودفتر ملوش قيمة.

**٢. القيد لازم يتوازن.** مجموع المدين = مجموع الدائن، والخدمة بتتحقّق
منها قبل الحفظ. مفيش قيد نص.

**٣. الأرصدة نسخة محسوبة.** ``account.balance`` مخزّن عشان السرعة،
لكن ``rebuild_balances`` بيبنيه من القيود من الصفر — فلو حصل اختلاف
فيه مرجع واحد صحيح نرجعله. نفس مبدأ المخزن بالظبط.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, TZDateTime
from app.models.enums import (
    DEBIT_NORMAL_ACCOUNTS,
    AccountType,
    JournalSource,
    JournalStatus,
    PeriodStatus,
)
from app.models.mixins import ActiveMixin, BilingualNameMixin

ZERO = Decimal("0")


class Account(Base, PKMixin, TimestampMixin, BilingualNameMixin, ActiveMixin):
    """حساب في دليل الحسابات — شجرة بترقيم مصري متعارف عليه.

    ``1`` أصول · ``2`` التزامات · ``3`` حقوق ملكية · ``4`` إيرادات ·
    ``5`` مصروفات. الترحيل بيتم على الحسابات الطرفية بس (``is_postable``)،
    والحسابات الأب بتجمّع أولادها في القوائم.
    """

    __tablename__ = "account"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    account_type: Mapped[AccountType] = mapped_column(String(10), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    #: الترحيل على الحسابات الطرفية بس — الأب بيجمّع ومش بيستقبل قيود
    is_postable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: حساب من دليل النظام — مينفعش يتشال لأن فيه كود بيرحّل عليه
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: الرصيد الحالي بإشارة الطبيعة (مدين موجب في الأصول والمصروفات)
    balance: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    #: مجاميع خام — بتخلّي ميزان المراجعة يتعرض من غير حساب
    debit_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    credit_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)

    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("property_id", "code", name="uq_account_code"),
        Index("ix_account_tree", "property_id", "account_type", "code"),
    )

    @property
    def is_debit_normal(self) -> bool:
        """طبيعة الرصيد — بتحدّد إشارة الحركة على الحساب."""
        return self.account_type in DEBIT_NORMAL_ACCOUNTS

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Account {self.code} {self.name_ar}>"


class CostCenter(Base, PKMixin, TimestampMixin, BilingualNameMixin, ActiveMixin):
    """مركز تكلفة — الإيراد والمصروف بيتنسبوا لقسم.

    من غيره القائمة بتقول «إيراد 2 مليون ومصروف 1.4» وخلاص. معاه بتقول
    إن المطعم بيكسب والسبا بيخسر — وده اللي بيتاخد عليه قرار.
    """

    __tablename__ = "cost_center"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    #: المنفذ المرتبط — أوردرات المطعم بتتنسب لمركز تكلفة المطعم تلقائياً
    outlet_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("property_id", "code", name="uq_cost_center_code"),
    )


class AccountingPeriod(Base, PKMixin, TimestampMixin):
    """فترة محاسبية شهرية — القفل بيمنع الترحيل بأثر رجعي.

    من غير القفل ده أي حد يقدر يرحّل قيد في شهر اتقفلت حساباته واتقدّم
    عنه إقرار ضريبي، والأرقام تتغيّر من ورا المحاسب. القفل بيخلّي
    التصحيح يتم بقيد في الشهر المفتوح — وده الأصول.
    """

    __tablename__ = "accounting_period"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[PeriodStatus] = mapped_column(
        String(8), nullable=False, default=PeriodStatus.OPEN
    )

    closed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    closed_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("property_id", "year", "month", name="uq_period"),
    )

    @property
    def label(self) -> str:
        return f"{self.year}-{self.month:02d}"


class JournalEntry(Base, PKMixin, TimestampMixin):
    """قيد يومية — رأس القيد."""

    __tablename__ = "journal_entry"

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[JournalStatus] = mapped_column(
        String(10), nullable=False, default=JournalStatus.POSTED
    )
    source: Mapped[JournalSource] = mapped_column(
        String(14), nullable=False, default=JournalSource.MANUAL
    )

    #: مفتاح المستند اللي طلّع القيد — بيمنع الترحيل مرتين
    source_key: Mapped[Optional[str]] = mapped_column(String(80), index=True)

    description_ar: Mapped[str] = mapped_column(String(300), nullable=False)
    description_en: Mapped[Optional[str]] = mapped_column(String(300))

    total_debit: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    total_credit: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)

    posted_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    posted_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    # --- العكس: القيد المرحّل مبيتعدّلش، بيتعكس ---
    reverses_entry_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    reversed_by_entry_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    reversal_reason: Mapped[Optional[str]] = mapped_column(String(300))

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="JournalLine.id",
    )

    __table_args__ = (
        # اليومية المعروضة على الشاشة — أهم استعلام
        Index("ix_journal_property_date", "property_id", "business_date", "id"),
        Index("ix_journal_source", "property_id", "source", "business_date"),
        # منع الترحيل مرتين لنفس المستند
        UniqueConstraint("property_id", "source", "source_key", name="uq_journal_source_key"),
    )

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit


class JournalLine(Base, PKMixin):
    """سطر في قيد — إما مدين أو دائن، مش الاتنين.

    الفصل ده مقصود: عمود واحد بإشارة بيخلّي غلط الإشارة صامت، وعمودين
    بيخلّوا الميزان يكشفه فوراً.
    """

    __tablename__ = "journal_line"

    journal_entry_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("journal_entry.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    account_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    cost_center_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    debit: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    credit: Mapped[Decimal] = mapped_column(Money, nullable=False, default=ZERO)
    description_ar: Mapped[Optional[str]] = mapped_column(String(300))

    #: مرجع نصّي للمستند — رقم فاتورة أو حجز، عشان الكشف يبقى مقروء
    reference: Mapped[Optional[str]] = mapped_column(String(60))

    entry: Mapped[JournalEntry] = relationship(back_populates="lines", lazy="noload")

    __table_args__ = (
        # كشف حساب الأستاذ — بيمشي على الحساب بترتيب التاريخ
        Index("ix_journal_line_account", "account_id", "business_date", "id"),
        Index("ix_journal_line_entry", "journal_entry_id"),
        Index("ix_journal_line_center", "property_id", "cost_center_id", "business_date"),
    )

    @property
    def amount(self) -> Decimal:
        """قيمة السطر بغض النظر عن اتجاهه."""
        return self.debit if self.debit else self.credit
