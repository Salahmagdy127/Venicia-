"""ملف النزيل وتاريخه — Guest profiles, preferences and stay history."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, TZDateTime
from app.models.enums import Gender, IdentificationType
from app.models.mixins import ActiveMixin


class Guest(Base, PKMixin, TimestampMixin, ActiveMixin):
    """ملف النزيل — النزيل الراجع وتفضيلاته ومناسباته.

    ده أساس الـ CRM وبرنامج الولاء، وبيخلي الاستقبال يعرف الضيف قبل ما يتكلم.
    """

    __tablename__ = "guest"

    property_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="SET NULL"), index=True
    )

    # --- الهوية ---
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    full_name_en: Mapped[Optional[str]] = mapped_column(String(250))
    gender: Mapped[Gender] = mapped_column(String(15), nullable=False, default=Gender.UNSPECIFIED)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    nationality: Mapped[str] = mapped_column(String(2), nullable=False, default="EG")

    id_type: Mapped[IdentificationType] = mapped_column(
        String(20), nullable=False, default=IdentificationType.NATIONAL_ID
    )
    #: الرقم القومي / رقم الباسبور — مطلوب قانوناً عند الـ check-in
    id_number: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    id_issue_country: Mapped[Optional[str]] = mapped_column(String(2))
    id_expiry: Mapped[Optional[date]] = mapped_column(Date)

    # --- التواصل ---
    phone: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    phone_alt: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    city: Mapped[Optional[str]] = mapped_column(String(120))
    country: Mapped[Optional[str]] = mapped_column(String(2))
    #: موافقة صريحة على رسائل الواتساب والتسويق
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- الولاء والتفضيلات ---
    is_vip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    vip_tier: Mapped[Optional[str]] = mapped_column(String(30))
    loyalty_number: Mapped[Optional[str]] = mapped_column(String(40), unique=True, index=True)
    loyalty_points: Mapped[int] = mapped_column(nullable=False, default=0)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    blacklist_reason: Mapped[Optional[str]] = mapped_column(String(500))

    #: تفضيلات حرة: دور عالي، بعيد عن الأسانسير، وسادة إضافية، نباتي...
    preferences: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    #: مناسبات متكررة: عيد جواز، عيد ميلاد — فرصة بيع وتمييز
    occasions: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    #: حساسيات وملاحظات طبية تخص المطعم
    dietary_notes: Mapped[Optional[str]] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(String(1000))

    # --- إحصاءات محسوبة مسبقاً (بيحدّثها الـ Night Audit) ---
    # محفوظة هنا عشان شاشة النزيل متعملش SUM على مليون صف كل مرة تتفتح.
    total_stays: Mapped[int] = mapped_column(nullable=False, default=0)
    total_nights: Mapped[int] = mapped_column(nullable=False, default=0)
    total_revenue: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    total_cancellations: Mapped[int] = mapped_column(nullable=False, default=0)
    total_no_shows: Mapped[int] = mapped_column(nullable=False, default=0)
    first_stay_date: Mapped[Optional[date]] = mapped_column(Date)
    last_stay_date: Mapped[Optional[date]] = mapped_column(Date, index=True)

    company_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("company.id", ondelete="SET NULL"), index=True
    )

    __table_args__ = (
        # البحث السريع في الاستقبال بالاسم
        Index("ix_guest_name", "last_name", "first_name"),
        # منع تكرار نفس الشخص بنفس الهوية في نفس المنشأة
        Index("ix_guest_property_id_number", "property_id", "id_number"),
        # قوائم النزلاء الراجعين
        Index("ix_guest_property_last_stay", "property_id", "last_stay_date"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_returning(self) -> bool:
        return self.total_stays > 1

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Guest {self.full_name}>"


class Company(Base, PKMixin, TimestampMixin, ActiveMixin):
    """شركة أو وكيل سفر — للحسابات الآجلة وعقود الشركات."""

    __tablename__ = "company"

    property_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="SET NULL"), index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name_ar: Mapped[str] = mapped_column(String(250), nullable=False)
    name_en: Mapped[str] = mapped_column(String(250), nullable=False)

    tax_registration_number: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    commercial_register: Mapped[Optional[str]] = mapped_column(String(40))
    contact_person: Mapped[Optional[str]] = mapped_column(String(200))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    address: Mapped[Optional[str]] = mapped_column(String(500))

    #: حد الائتمان للحساب الآجل — لو اتعدّى، النظام يمنع الترحيل
    credit_limit: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    credit_days: Mapped[int] = mapped_column(nullable=False, default=0)
    current_balance: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: عمولة وكيل السفر
    commission_percent: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    is_travel_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contract_from: Mapped[Optional[date]] = mapped_column(Date)
    contract_to: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(String(1000))


class GuestDocument(Base, PKMixin, TimestampMixin):
    """صور المستندات المرفوعة عند الـ check-in (بطاقة/باسبور)."""

    __tablename__ = "guest_document"

    guest_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("guest.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reservation_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    doc_type: Mapped[IdentificationType] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64))
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    #: تاريخ الحذف المقرر — التزام بحماية البيانات الشخصية
    purge_after: Mapped[Optional[datetime]] = mapped_column(TZDateTime, index=True)
