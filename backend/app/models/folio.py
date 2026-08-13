"""حساب النزيل المفتوح — Guest folio, charges, payments, split & transfer."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Percent, TZDateTime
from app.models.enums import ChargeKind, FolioStatus, FolioType, PaymentMethod


class Folio(Base, PKMixin, TimestampMixin):
    """الحساب المفتوح — كل نقاط البيع بترحّل عليه.

    الحجز الواحد ممكن يبقى له أكتر من فوليو (تقسيم الفاتورة): واحد على
    النزيل وواحد على الشركة، أو فوليو لكل ساكن في الشاليه.
    """

    __tablename__ = "folio"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    folio_type: Mapped[FolioType] = mapped_column(
        String(20), nullable=False, default=FolioType.GUEST
    )
    status: Mapped[FolioStatus] = mapped_column(
        String(20), nullable=False, default=FolioStatus.OPEN
    )

    reservation_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("reservation.id", ondelete="RESTRICT"), index=True
    )
    reservation_unit_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    guest_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("guest.id", ondelete="RESTRICT"), index=True
    )
    company_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    #: الوحدة وقت فتح الحساب — محفوظة كنص عشان تفضل صحيحة في التقارير القديمة
    unit_label: Mapped[Optional[str]] = mapped_column(String(40), index=True)

    # --- الأرصدة (بتتحدّث مع كل حركة — القوائم مبتعملش SUM) ---
    charges_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    payments_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    service_charge_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    balance: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    credit_limit: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    opened_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    closed_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    notes: Mapped[Optional[str]] = mapped_column(String(1000))

    lines: Mapped[list["FolioLine"]] = relationship(
        back_populates="folio", lazy="noload", order_by="FolioLine.id"
    )

    __table_args__ = (
        # "الحسابات المفتوحة دلوقتي" — شاشة الريسبشن الرئيسية
        Index("ix_folio_property_status", "property_id", "status", "opened_at"),
        Index("ix_folio_property_unit", "property_id", "unit_label", "status"),
    )

    @property
    def is_open(self) -> bool:
        return self.status == FolioStatus.OPEN


class FolioLine(Base, PKMixin):
    """حركة على حساب النزيل — جدول عالي الحجم (ملايين الصفوف).

    إضافة فقط: التصحيح بيتم بحركة عكسية مش بتعديل أو حذف، عشان سلامة
    التدقيق المحاسبي.
    """

    __tablename__ = "folio_line"

    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    folio_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("folio.id", ondelete="RESTRICT"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)

    #: اليوم الفندقي اللي الحركة اتسجلت فيه (مش بالضرورة تاريخ الساعة)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    charge_kind: Mapped[ChargeKind] = mapped_column(String(25), nullable=False)

    description_ar: Mapped[str] = mapped_column(String(300), nullable=False)
    description_en: Mapped[Optional[str]] = mapped_column(String(300))

    quantity: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: موجب = مدين على النزيل · سالب = دائن (دفعة/خصم)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    service_charge_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_percent: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    # --- الربط بالمصدر ---
    outlet_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    pos_order_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    reservation_night_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    payment_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    # --- التحويل بين الغرف / تقسيم الفاتورة ---
    is_transferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transferred_to_folio_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    transferred_from_folio_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    transferred_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    # --- الإلغاء والتدقيق ---
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[Optional[str]] = mapped_column(String(300))
    voided_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    #: الحركة العكسية المقابلة
    reverses_line_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    posted_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    folio: Mapped[Folio] = relationship(back_populates="lines", lazy="noload")

    __table_args__ = (
        # عرض كشف حساب النزيل — أهم استعلام على الجدول ده
        Index("ix_folio_line_folio", "folio_id", "id"),
        # تقارير الإيراد اليومي حسب نوع الحركة
        Index("ix_folio_line_property_date_kind", "property_id", "business_date", "charge_kind"),
        # تتبّع إيراد كل منفذ بيع
        Index("ix_folio_line_outlet_date", "outlet_id", "business_date"),
    )


class Payment(Base, PKMixin, TimestampMixin):
    """دفعة مستلمة — نقدي، كارت، فوري، باي موب، تحويل."""

    __tablename__ = "payment"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)

    folio_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("folio.id", ondelete="RESTRICT"), index=True
    )
    reservation_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    pos_order_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    guest_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    method: Mapped[PaymentMethod] = mapped_column(String(25), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EGP")
    exchange_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("1"))
    amount_base: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    #: عربون مقدّم مقابل دفعة إقامة
    is_deposit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: مرجع بوابة الدفع أو رقم عملية الـ POS terminal
    gateway: Mapped[Optional[str]] = mapped_column(String(40))
    gateway_reference: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    card_last4: Mapped[Optional[str]] = mapped_column(String(4))
    cheque_number: Mapped[Optional[str]] = mapped_column(String(40))
    cheque_due_date: Mapped[Optional[date]] = mapped_column(Date)

    shift_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    received_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[Optional[str]] = mapped_column(String(300))
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        # تقفيل الدرج ومطابقة العهدة
        Index("ix_payment_property_date_method", "property_id", "business_date", "method"),
        Index("ix_payment_shift", "shift_id", "method"),
    )
