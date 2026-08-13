"""الفاتورة الإلكترونية — E-invoices, e-receipts and ETA submission tracking.

منظومة مصلحة الضرائب المصرية إلزامية، والتصميم هنا بيفصل **إنشاء المستند**
عن **إرساله**: الفاتورة بتتولد وتتطبع فوراً للنزيل، والإرسال بيتم في طابور
منفصل بإعادة محاولة — عشان انقطاع النت مايوقفش الكاشير.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Percent, TZDateTime
from app.models.enums import EtaStatus, InvoiceType


class Invoice(Base, PKMixin, TimestampMixin):
    """مستند ضريبي — فاتورة أو إيصال إلكتروني."""

    __tablename__ = "invoice"

    #: الرقم الداخلي المتسلسل — لا يتكرر ولا ينكسر
    number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    invoice_type: Mapped[InvoiceType] = mapped_column(
        String(20), nullable=False, default=InvoiceType.RECEIPT
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    # --- المصدر ---
    folio_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    pos_order_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    reservation_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    outlet_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    # --- بيانات المستلم (لقطة وقت الإصدار) ---
    customer_name: Mapped[str] = mapped_column(String(300), nullable=False)
    customer_tax_number: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    customer_national_id: Mapped[Optional[str]] = mapped_column(String(40))
    customer_address: Mapped[Optional[str]] = mapped_column(String(500))
    customer_type: Mapped[str] = mapped_column(String(1), nullable=False, default="P")  # B/P/F

    # --- المبالغ ---
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EGP")
    exchange_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("1"))
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    service_charge_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    # --- منظومة مصلحة الضرائب ---
    eta_status: Mapped[EtaStatus] = mapped_column(
        String(15), nullable=False, default=EtaStatus.DRAFT, index=True
    )
    #: المعرّف الداخلي الفريد المرسل للمنظومة
    eta_internal_id: Mapped[Optional[str]] = mapped_column(String(60), index=True)
    eta_uuid: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    eta_long_id: Mapped[Optional[str]] = mapped_column(String(120))
    eta_submission_uuid: Mapped[Optional[str]] = mapped_column(String(80))
    eta_hash_key: Mapped[Optional[str]] = mapped_column(String(120))
    eta_submitted_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    eta_accepted_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    #: رد المنظومة كامل — للمراجعة وقت الرفض
    eta_response: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    eta_error_message: Mapped[Optional[str]] = mapped_column(String(2000))
    eta_retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    #: الموعد التالي لإعادة المحاولة — الطابور بيقرا منه
    eta_next_retry_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime, index=True)

    #: كود QR المطبوع على الإيصال
    qr_payload: Mapped[Optional[str]] = mapped_column(String(1000))

    # --- الإلغاء ---
    is_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(500))
    #: إشعار الخصم المرتبط لو الفاتورة اتعدّلت
    credit_note_for_invoice_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    issued_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    printed_count: Mapped[int] = mapped_column(nullable=False, default=0)

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_invoice_property_date", "property_id", "business_date"),
        # طابور الإرسال: هات اللي لسه متبعتش وحان وقت إعادة محاولته
        Index("ix_invoice_eta_queue", "eta_status", "eta_next_retry_at"),
    )


class InvoiceLine(Base, PKMixin):
    """سطر في المستند الضريبي — بالصيغة اللي المنظومة بتطلبها."""

    __tablename__ = "invoice_line"

    invoice_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("invoice.id", ondelete="CASCADE"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(nullable=False, default=1)

    description_ar: Mapped[str] = mapped_column(String(300), nullable=False)
    description_en: Mapped[Optional[str]] = mapped_column(String(300))
    #: كود GS1 أو كود المنظومة الداخلي — إلزامي للإرسال
    item_code: Mapped[Optional[str]] = mapped_column(String(60))
    item_code_type: Mapped[str] = mapped_column(String(10), nullable=False, default="EGS")
    unit_type: Mapped[str] = mapped_column(String(10), nullable=False, default="EA")

    quantity: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    sales_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    net_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    #: T1 = ضريبة القيمة المضافة · T2 = ضريبة الجدول
    tax_type: Mapped[str] = mapped_column(String(5), nullable=False, default="T1")
    tax_subtype: Mapped[str] = mapped_column(String(10), nullable=False, default="V009")
    tax_percent: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=Decimal("14"))
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    service_charge_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines", lazy="noload")

    __table_args__ = (Index("ix_invoice_line_invoice", "invoice_id", "line_number"),)


class DocumentSequence(Base, PKMixin, TimestampMixin):
    """عدّاد الترقيم المتسلسل — يضمن أرقام متصلة بدون فجوات ولا تكرار."""

    __tablename__ = "document_sequence"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    #: RESERVATION · FOLIO · INVOICE · RECEIPT · PAYMENT · POS_ORDER · KOT · SHIFT
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    #: يتصفّر سنوياً
    period_year: Mapped[int] = mapped_column(nullable=False)
    last_number: Mapped[int] = mapped_column(nullable=False, default=0)
    padding: Mapped[int] = mapped_column(nullable=False, default=6)

    __table_args__ = (
        Index(
            "ix_document_sequence_key",
            "property_id",
            "doc_type",
            "period_year",
            unique=True,
        ),
    )
