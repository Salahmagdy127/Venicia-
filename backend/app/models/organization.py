"""المنشأة وإعداداتها — Property / establishment settings."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import Percent
from app.models.mixins import ActiveMixin, BilingualNameMixin, CodeMixin


class Property(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """القرية / المنشأة. النظام متعدد المنشآت من الأساس عشان يتباع لعملاء تانيين."""

    __tablename__ = "property"

    legal_name: Mapped[Optional[str]] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="EG")
    city: Mapped[Optional[str]] = mapped_column(String(120))
    address: Mapped[Optional[str]] = mapped_column(String(500))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    website: Mapped[Optional[str]] = mapped_column(String(200))

    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Cairo")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EGP")
    default_locale: Mapped[str] = mapped_column(String(5), nullable=False, default="ar")

    # --- الضرائب والرسوم المصرية ---
    tax_registration_number: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    commercial_register: Mapped[Optional[str]] = mapped_column(String(40))
    vat_percent: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=Decimal("14"))
    service_charge_percent: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("12")
    )
    municipality_tax_percent: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("0")
    )
    #: هل الخدمة بتتحسب قبل الضريبة (المعتاد في مصر) ولا بعدها
    service_charge_before_tax: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    # --- منظومة الفاتورة الإلكترونية ---
    eta_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eta_client_id: Mapped[Optional[str]] = mapped_column(String(120))
    eta_branch_code: Mapped[Optional[str]] = mapped_column(String(20))
    eta_activity_code: Mapped[Optional[str]] = mapped_column(String(20))

    # --- تشغيل ---
    #: ساعة الـ Night Audit / بداية اليوم الفندقي
    business_day_start_hour: Mapped[int] = mapped_column(nullable=False, default=6)
    check_in_time: Mapped[str] = mapped_column(String(5), nullable=False, default="14:00")
    check_out_time: Mapped[str] = mapped_column(String(5), nullable=False, default="12:00")
    #: نسبة التجاوز المسموحة في الحجز الزائد
    overbooking_percent: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("0")
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Property {self.code} {self.name_ar}>"
