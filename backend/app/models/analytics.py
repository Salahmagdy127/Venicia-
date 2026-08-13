"""جداول الملخّص اليومية — Pre-aggregated daily snapshots for instant dashboards.

ده الجزء اللي بيخلي داشبورد المالك يفتح فوراً مهما كبرت البيانات: الأرقام
بتتحسب **مرة واحدة** في الـ Night Audit وتتخزن جاهزة، فالداشبورد بيقرا
365 صف في السنة بدل ما يجمّع ملايين الحركات في كل مرة يتفتح.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Date, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Percent, TZDateTime


class DailyStatistics(Base, PKMixin):
    """ملخّص يوم فندقي كامل للمنشأة — مصدر داشبورد المالك وتقرير النايت أوديت."""

    __tablename__ = "daily_statistics"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)

    # --- الإشغال ---
    total_units: Mapped[int] = mapped_column(nullable=False, default=0)
    out_of_order_units: Mapped[int] = mapped_column(nullable=False, default=0)
    available_units: Mapped[int] = mapped_column(nullable=False, default=0)
    sold_units: Mapped[int] = mapped_column(nullable=False, default=0)
    complimentary_units: Mapped[int] = mapped_column(nullable=False, default=0)
    occupancy_percent: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=Decimal("0"))
    guests_in_house: Mapped[int] = mapped_column(nullable=False, default=0)

    # --- الحركة ---
    arrivals: Mapped[int] = mapped_column(nullable=False, default=0)
    departures: Mapped[int] = mapped_column(nullable=False, default=0)
    walk_ins: Mapped[int] = mapped_column(nullable=False, default=0)
    no_shows: Mapped[int] = mapped_column(nullable=False, default=0)
    cancellations: Mapped[int] = mapped_column(nullable=False, default=0)
    new_bookings: Mapped[int] = mapped_column(nullable=False, default=0)

    # --- الإيراد ---
    room_revenue: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    fnb_revenue: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    spa_revenue: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    activity_revenue: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    other_revenue: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    total_revenue: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    service_charge_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    # --- مؤشرات الأداء الفندقية ---
    #: متوسط سعر الليلة المباعة — Average Daily Rate
    adr: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: إيراد الوحدة المتاحة — Revenue Per Available Room
    revpar: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: إجمالي إيراد الوحدة المتاحة شامل نقاط البيع
    trevpar: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    average_check: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    covers: Mapped[int] = mapped_column(nullable=False, default=0)

    # --- العمولات: الرقم اللي بيثبت قيمة الحجز المباشر ---
    ota_commission_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    direct_bookings: Mapped[int] = mapped_column(nullable=False, default=0)
    ota_bookings: Mapped[int] = mapped_column(nullable=False, default=0)
    #: تفصيل الإيراد لكل مصدر حجز — JSON عشان إضافة قناة متطلبش تعديل جدول
    revenue_by_source: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    # --- المدفوعات ---
    cash_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    card_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    city_ledger_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    computed_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("property_id", "business_date", name="uq_daily_statistics_day"),
        Index("ix_daily_statistics_property_date", "property_id", "business_date"),
    )


class DailyCategoryStatistics(Base, PKMixin):
    """ملخّص يومي لكل فئة وحدة — ربحية كل فئة على حدة."""

    __tablename__ = "daily_category_statistics"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    unit_category_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)

    total_units: Mapped[int] = mapped_column(nullable=False, default=0)
    sold_units: Mapped[int] = mapped_column(nullable=False, default=0)
    occupancy_percent: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=Decimal("0"))
    room_revenue: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    adr: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    revpar: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    __table_args__ = (
        UniqueConstraint(
            "unit_category_id", "business_date", name="uq_daily_category_statistics_day"
        ),
        Index("ix_daily_category_stats_property_date", "property_id", "business_date"),
    )


class DailyOutletStatistics(Base, PKMixin):
    """ملخّص يومي لكل منفذ بيع — ربحية المطعم والبار والسبا كل واحد لوحده."""

    __tablename__ = "daily_outlet_statistics"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    outlet_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)

    orders_count: Mapped[int] = mapped_column(nullable=False, default=0)
    covers: Mapped[int] = mapped_column(nullable=False, default=0)
    gross_sales: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    net_sales: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    service_charge_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    cost_of_sales: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    average_check: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    room_charge_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    # --- مؤشرات الرقابة على التلاعب ---
    void_count: Mapped[int] = mapped_column(nullable=False, default=0)
    void_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: إلغاء بعد إرسال الطلب للمطبخ — أهم مؤشر إنذار
    void_after_send_count: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("outlet_id", "business_date", name="uq_daily_outlet_statistics_day"),
        Index("ix_daily_outlet_stats_property_date", "property_id", "business_date"),
    )


class NightAuditRun(Base, PKMixin, TimestampMixin):
    """تشغيلة النايت أوديت — إقفال اليوم الفندقي.

    بترحّل ليالي اليوم، تعلّم الغياب، تحسب الملخّصات، وتقفل اليوم.
    مصممة إنها **تتعاد بأمان** لو وقعت في النص.
    """

    __tablename__ = "night_audit_run"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    #: PENDING · RUNNING · COMPLETED · FAILED
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="PENDING")

    nights_posted: Mapped[int] = mapped_column(nullable=False, default=0)
    room_revenue_posted: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    no_shows_marked: Mapped[int] = mapped_column(nullable=False, default=0)
    folios_closed: Mapped[int] = mapped_column(nullable=False, default=0)
    open_folios_remaining: Mapped[int] = mapped_column(nullable=False, default=0)
    #: أخطاء ومحاذير محتاجة تدخّل بشري
    warnings: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(String(2000))

    run_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    is_automatic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("property_id", "business_date", name="uq_night_audit_day"),
        Index("ix_night_audit_property_date", "property_id", "business_date"),
    )
