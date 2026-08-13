"""التسعير الموسمي والديناميكي — Rate plans, seasons, rules and the rate calendar."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Percent
from app.models.enums import AdjustmentMethod, MealPlan, RateRuleType
from app.models.mixins import (
    ActiveMixin,
    BilingualDescriptionMixin,
    BilingualNameMixin,
    CodeMixin,
)


class CancellationPolicy(
    Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, BilingualDescriptionMixin, ActiveMixin
):
    """سياسة الإلغاء وعدم الحضور."""

    __tablename__ = "cancellation_policy"

    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: الإلغاء المجاني حتى كام ساعة قبل الوصول
    free_cancellation_hours: Mapped[int] = mapped_column(nullable=False, default=48)
    #: الغرامة بعد انتهاء فترة الإلغاء المجاني
    penalty_method: Mapped[AdjustmentMethod] = mapped_column(
        String(20), nullable=False, default=AdjustmentMethod.PERCENT
    )
    penalty_value: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("100"))
    #: غرامة عدم الحضور — عادةً أول ليلة
    no_show_nights: Mapped[int] = mapped_column(nullable=False, default=1)
    #: نسبة العربون المطلوبة لتأكيد الحجز
    deposit_percent: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=Decimal("0"))
    deposit_due_hours: Mapped[int] = mapped_column(nullable=False, default=24)
    is_refundable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RatePlan(
    Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, BilingualDescriptionMixin, ActiveMixin
):
    """خطة سعر: سعر عام، مقيم مصري، شركات، عرض غير قابل للاسترداد..."""

    __tablename__ = "rate_plan"

    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    meal_plan: Mapped[MealPlan] = mapped_column(String(5), nullable=False, default=MealPlan.BB)
    cancellation_policy_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("cancellation_policy.id", ondelete="SET NULL")
    )

    min_stay: Mapped[int] = mapped_column(nullable=False, default=1)
    max_stay: Mapped[Optional[int]] = mapped_column()
    #: أقل مهلة حجز قبل الوصول (بالأيام)
    min_lead_days: Mapped[int] = mapped_column(nullable=False, default=0)
    #: متاح على الموقع المباشر؟ (Booking Engine بعمولة صفر)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    #: متاح للتوزيع على قنوات الـ OTA؟
    is_channel_distributed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    cancellation_policy: Mapped[Optional[CancellationPolicy]] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_rate_plan_property_active", "property_id", "is_active", "sort_order"),
    )


class Season(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """موسم: صيف، شتاء، رمضان، عيد الفطر، عيد الأضحى، رأس السنة."""

    __tablename__ = "season"

    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: الأعلى أولوية بيكسب لما المواسم تتداخل
    priority: Mapped[int] = mapped_column(nullable=False, default=0)
    is_peak: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    color: Mapped[Optional[str]] = mapped_column(String(9))  # لون العرض في التقويم

    __table_args__ = (
        Index("ix_season_property_range", "property_id", "start_date", "end_date"),
    )


class RateRule(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """قاعدة تسعير ديناميكي فوق السعر الأساسي.

    مثال: ويك إند +25% · إشغال فوق 85% +15% · إقامة 7 ليالي -10%
    """

    __tablename__ = "rate_rule"

    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rule_type: Mapped[RateRuleType] = mapped_column(String(20), nullable=False, index=True)
    method: Mapped[AdjustmentMethod] = mapped_column(
        String(20), nullable=False, default=AdjustmentMethod.PERCENT
    )
    value: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    #: نطاق التطبيق — فاضي يعني على الكل
    unit_category_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("unit_category.id", ondelete="CASCADE")
    )
    rate_plan_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("rate_plan.id", ondelete="CASCADE")
    )
    season_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("season.id", ondelete="CASCADE")
    )

    #: أيام الأسبوع اللي القاعدة تنطبق عليها — "0123456" (الاتنين=0)
    weekdays: Mapped[Optional[str]] = mapped_column(String(7))
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)

    #: شروط رقمية (نسبة إشغال / عدد ليالي / مهلة حجز)
    threshold_min: Mapped[Optional[Decimal]] = mapped_column(Money)
    threshold_max: Mapped[Optional[Decimal]] = mapped_column(Money)

    #: الأقل رقماً بيتطبق الأول
    priority: Mapped[int] = mapped_column(nullable=False, default=100)

    __table_args__ = (
        Index("ix_rate_rule_property_type", "property_id", "rule_type", "is_active", "priority"),
    )


class RateCalendarEntry(Base, PKMixin, TimestampMixin):
    """السعر النهائي المنشور لكل (يوم × فئة × خطة سعر).

    قراءة السعر بتبقى **بحث بالفهرس** مش حساب لحظي، وده اللي بيخلي شاشة
    الحجز وتقويم الأسعار بيفتحوا فوراً.
    """

    __tablename__ = "rate_calendar"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    unit_category_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("unit_category.id", ondelete="CASCADE"), nullable=False
    )
    rate_plan_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("rate_plan.id", ondelete="CASCADE"), nullable=False
    )
    stay_date: Mapped[date] = mapped_column(Date, nullable=False)

    rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    extra_adult_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    extra_child_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    min_stay: Mapped[int] = mapped_column(nullable=False, default=1)
    max_stay: Mapped[Optional[int]] = mapped_column()
    #: إغلاق البيع في اليوم ده
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closed_to_arrival: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closed_to_departure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: حصة مخصصة للقنوات — للتحكم في الـ overbooking
    channel_allotment: Mapped[Optional[int]] = mapped_column()

    __table_args__ = (
        UniqueConstraint(
            "unit_category_id", "rate_plan_id", "stay_date", name="uq_rate_calendar_slot"
        ),
        # الاستعلام الفعلي: أسعار مدى تواريخ لفئة وخطة
        Index(
            "ix_rate_calendar_lookup",
            "property_id",
            "stay_date",
            "unit_category_id",
            "rate_plan_id",
        ),
    )
