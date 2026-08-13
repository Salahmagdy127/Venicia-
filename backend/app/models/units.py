"""فئات الوحدات والوحدات وحالتها — Unit categories, units, housekeeping state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, TZDateTime
from app.models.enums import HousekeepingStatus, UnitCondition, UnitKind
from app.models.mixins import (
    ActiveMixin,
    BilingualDescriptionMixin,
    BilingualNameMixin,
    CodeMixin,
)


class UnitCategory(
    Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, BilingualDescriptionMixin, ActiveMixin
):
    """فئة الوحدة — فينيسيا عندها 6 فئات بأسعار مختلفة."""

    __tablename__ = "unit_category"

    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[UnitKind] = mapped_column(String(20), nullable=False, default=UnitKind.ROOM)

    base_occupancy: Mapped[int] = mapped_column(nullable=False, default=2)
    max_occupancy: Mapped[int] = mapped_column(nullable=False, default=4)
    max_adults: Mapped[int] = mapped_column(nullable=False, default=4)
    max_children: Mapped[int] = mapped_column(nullable=False, default=2)

    #: السعر الاسترشادي — التسعير الفعلي بيجي من تقويم الأسعار
    base_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: سعر الفرد الإضافي فوق الإشغال الأساسي
    extra_adult_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    extra_child_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    area_sqm: Mapped[Optional[int]] = mapped_column()
    bed_configuration: Mapped[Optional[str]] = mapped_column(String(120))
    amenities_ar: Mapped[Optional[str]] = mapped_column(String(1000))
    amenities_en: Mapped[Optional[str]] = mapped_column(String(1000))

    #: ترتيب العرض في شاشة الـ Tape Chart
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0, index=True)

    units: Mapped[list["Unit"]] = relationship(
        back_populates="category", lazy="noload", order_by="Unit.sort_order"
    )

    __table_args__ = (
        Index("ix_unit_category_property_active", "property_id", "is_active", "sort_order"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UnitCategory {self.code} {self.name_ar}>"


class Unit(Base, PKMixin, TimestampMixin, CodeMixin, ActiveMixin):
    """وحدة قابلة للبيع: غرفة، شاليه، خيمة على البحيرة، جلسة."""

    __tablename__ = "unit"

    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("unit_category.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    #: الاسم المعروض (غالباً رقم الوحدة) — منفصل عن الكود عشان الترقيم الداخلي
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    zone_ar: Mapped[Optional[str]] = mapped_column(String(120))   # المنطقة: على البحيرة / الحديقة
    zone_en: Mapped[Optional[str]] = mapped_column(String(120))
    building: Mapped[Optional[str]] = mapped_column(String(60))
    floor: Mapped[Optional[str]] = mapped_column(String(20))

    housekeeping_status: Mapped[HousekeepingStatus] = mapped_column(
        String(20), nullable=False, default=HousekeepingStatus.CLEAN, index=True
    )
    condition: Mapped[UnitCondition] = mapped_column(
        String(20), nullable=False, default=UnitCondition.OPERATIONAL, index=True
    )
    #: من/إلى تعطيل الوحدة — بيتخصم من الإتاحة في الفترة دي
    blocked_from: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    blocked_until: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    block_reason: Mapped[Optional[str]] = mapped_column(String(300))

    has_minibar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_smoking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_accessible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: ترتيب الصفوف في شاشة الـ Tape Chart
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    category: Mapped[UnitCategory] = relationship(back_populates="units", lazy="joined")

    __table_args__ = (
        UniqueConstraint("property_id", "label", name="uq_unit_property_label"),
        # الفهرس اللي بتقرا منه شاشة الـ Tape Chart كل مرة
        Index("ix_unit_property_category_sort", "property_id", "category_id", "sort_order"),
        # شاشة الهاوس كيبينج: "وريني كل المتسخ في القرية"
        Index("ix_unit_property_hk", "property_id", "housekeeping_status"),
    )

    @property
    def is_sellable(self) -> bool:
        """هل الوحدة تتعد في الإتاحة؟"""
        return self.is_active and self.condition == UnitCondition.OPERATIONAL

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Unit {self.label}>"


class UnitStatusLog(Base, PKMixin):
    """سجل تغيّر حالة الوحدة — بينمو بسرعة، إضافة فقط.

    بيجاوب على: "الغرفة دي اتنضفت الساعة كام ومين اللي نضّفها؟"
    """

    __tablename__ = "unit_status_log"

    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    unit_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)

    from_housekeeping: Mapped[Optional[HousekeepingStatus]] = mapped_column(String(20))
    to_housekeeping: Mapped[Optional[HousekeepingStatus]] = mapped_column(String(20))
    from_condition: Mapped[Optional[UnitCondition]] = mapped_column(String(20))
    to_condition: Mapped[Optional[UnitCondition]] = mapped_column(String(20))

    changed_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    #: مصدر التغيير: تطبيق السوبرفايزر / الريسبشن / تلقائي بعد الـ check-out
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="SYSTEM")
    note: Mapped[Optional[str]] = mapped_column(String(300))

    __table_args__ = (
        Index("ix_unit_status_log_unit_time", "unit_id", "created_at"),
        Index("ix_unit_status_log_property_time", "property_id", "created_at"),
    )
