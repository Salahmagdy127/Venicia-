"""الحجوزات والإتاحة — Reservations, per-night pricing and the availability counter.

قلب النظام. الحاجة المهمة هنا إن الإتاحة **مش** بتتحسب بمسح الحجوزات؛ فيه
جدول عدّادات ``availability_calendar`` بيتحدّث في نفس معاملة الحجز، فالسؤال
"في غرف فاضية؟" بيبقى قراءة صف واحد بالفهرس مهما كان حجم الحجوزات.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Percent, TZDateTime
from app.models.enums import BookingSource, MealPlan, ReservationStatus


# ------------------------------------------------------------ عدّاد الإتاحة
class AvailabilityCalendar(Base, PKMixin):
    """عدّاد الإتاحة اليومي لكل فئة وحدة.

    صف واحد لكل (فئة × يوم). الحجم ثابت وصغير: 6 فئات × 365 يوم = 2190 صف
    في السنة — يعني الإتاحة بتفضل فورية سواء عندك ألف حجز أو عشرة ملايين.

    ``available = total_units - out_of_order - sold - held + overbooking_limit``
    """

    __tablename__ = "availability_calendar"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    unit_category_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("unit_category.id", ondelete="CASCADE"), nullable=False
    )
    stay_date: Mapped[date] = mapped_column(Date, nullable=False)

    #: إجمالي الوحدات الصالحة في الفئة
    total_units: Mapped[int] = mapped_column(nullable=False, default=0)
    #: خارج الخدمة (صيانة / تعطيل)
    out_of_order: Mapped[int] = mapped_column(nullable=False, default=0)
    #: مباعة فعلياً (حجوزات مؤكدة أو نازلة)
    sold_units: Mapped[int] = mapped_column(nullable=False, default=0)
    #: محجوزة مؤقتاً (سلة الحجز الإلكتروني قبل الدفع)
    held_units: Mapped[int] = mapped_column(nullable=False, default=0)
    #: مسموح تجاوزه فوق السعة — Overbooking control
    overbooking_limit: Mapped[int] = mapped_column(nullable=False, default=0)
    #: إغلاق البيع نهائياً في اليوم ده
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("unit_category_id", "stay_date", name="uq_availability_slot"),
        # الاستعلام الوحيد المهم: إتاحة مدى تواريخ في منشأة
        Index("ix_availability_property_date", "property_id", "stay_date"),
        CheckConstraint("sold_units >= 0", name="sold_units_non_negative"),
        CheckConstraint("held_units >= 0", name="held_units_non_negative"),
    )

    @property
    def available_units(self) -> int:
        if self.is_closed:
            return 0
        return max(
            0,
            self.total_units
            - self.out_of_order
            - self.sold_units
            - self.held_units
            + self.overbooking_limit,
        )


# --------------------------------------------------------------- الحجز
class Reservation(Base, PKMixin, TimestampMixin):
    """رأس الحجز — ممكن يشمل أكتر من وحدة."""

    __tablename__ = "reservation"

    #: رقم الحجز المعروض للنزيل — VNC-2026-000123
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[ReservationStatus] = mapped_column(
        String(20), nullable=False, default=ReservationStatus.TENTATIVE
    )
    source: Mapped[BookingSource] = mapped_column(
        String(20), nullable=False, default=BookingSource.DIRECT
    )
    #: رقم الحجز على القناة الخارجية (بوكينج/أجودا) — للمطابقة ومنع التعارض
    external_reference: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    channel_commission_percent: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("0")
    )
    #: العمولة المحسوبة — ده الرقم اللي بيثبت للمالك قيمة الحجز المباشر
    channel_commission_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=Decimal("0")
    )

    guest_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("guest.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("company.id", ondelete="SET NULL"), index=True
    )

    arrival_date: Mapped[date] = mapped_column(Date, nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(nullable=False, default=1)
    adults: Mapped[int] = mapped_column(nullable=False, default=2)
    children: Mapped[int] = mapped_column(nullable=False, default=0)
    infants: Mapped[int] = mapped_column(nullable=False, default=0)

    # --- المبالغ (محسوبة ومخزّنة عشان القوائم متعملش تجميع لحظي) ---
    room_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    extras_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    service_charge_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    deposit_required: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    deposit_paid: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    paid_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    balance: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    # --- التشغيل ---
    expected_arrival_time: Mapped[Optional[str]] = mapped_column(String(5))
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    checked_out_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(500))
    #: تثبيت مهلة الحجز المؤقت — بعدها الإتاحة بترجع تلقائياً
    hold_expires_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime, index=True)

    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    group_name: Mapped[Optional[str]] = mapped_column(String(200))
    #: مناسبة (فرح / مؤتمر) — المكان بيتباع للعرسان
    event_name: Mapped[Optional[str]] = mapped_column(String(200))

    special_requests: Mapped[Optional[str]] = mapped_column(String(1000))
    internal_notes: Mapped[Optional[str]] = mapped_column(String(1000))

    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    checked_in_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    checked_out_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    units: Mapped[list["ReservationUnit"]] = relationship(
        back_populates="reservation", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # قوائم الوصول والمغادرة اليومية — أكتر شاشتين بيفتحهم الريسبشن
        Index("ix_reservation_property_arrival", "property_id", "arrival_date", "status"),
        Index("ix_reservation_property_departure", "property_id", "departure_date", "status"),
        # لوحة "الحجوزات النشطة" وشاشة الـ Tape Chart
        Index("ix_reservation_property_status", "property_id", "status", "arrival_date"),
        # تاريخ النزيل
        Index("ix_reservation_guest", "guest_id", "arrival_date"),
        # تحليل مصادر الحجز وعمولات القنوات
        Index("ix_reservation_source_date", "property_id", "source", "arrival_date"),
        CheckConstraint("departure_date > arrival_date", name="valid_stay_range"),
        CheckConstraint("nights > 0", name="positive_nights"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Reservation {self.code} {self.status}>"


class ReservationUnit(Base, PKMixin, TimestampMixin):
    """سطر وحدة داخل الحجز — الحجز الواحد ممكن يشمل 3 شاليهات."""

    __tablename__ = "reservation_unit"

    reservation_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("reservation.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)

    unit_category_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("unit_category.id", ondelete="RESTRICT"), nullable=False
    )
    #: الوحدة المحددة — بتفضل فاضية لحد ما الريسبشن يخصص، أو بالسحب في الـ Tape Chart
    unit_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("unit.id", ondelete="SET NULL")
    )
    rate_plan_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("rate_plan.id", ondelete="RESTRICT"), nullable=False
    )
    meal_plan: Mapped[MealPlan] = mapped_column(String(5), nullable=False, default=MealPlan.BB)

    arrival_date: Mapped[date] = mapped_column(Date, nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(nullable=False, default=1)
    adults: Mapped[int] = mapped_column(nullable=False, default=2)
    children: Mapped[int] = mapped_column(nullable=False, default=0)

    #: اسم النزيل في الوحدة دي لو مختلف عن صاحب الحجز
    occupant_name: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[ReservationStatus] = mapped_column(
        String(20), nullable=False, default=ReservationStatus.TENTATIVE
    )

    room_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    reservation: Mapped[Reservation] = relationship(back_populates="units", lazy="noload")
    nights_detail: Mapped[list["ReservationNight"]] = relationship(
        back_populates="reservation_unit", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # قلب شاشة الـ Tape Chart: "كل الوحدات المشغولة في المدى ده"
        Index(
            "ix_reservation_unit_occupancy",
            "property_id",
            "arrival_date",
            "departure_date",
            "status",
        ),
        Index("ix_reservation_unit_unit", "unit_id", "arrival_date"),
        Index("ix_reservation_unit_reservation", "reservation_id"),
        Index("ix_reservation_unit_category_date", "unit_category_id", "arrival_date"),
    )


class ReservationNight(Base, PKMixin):
    """سعر كل ليلة على حدة.

    ده اللي بيخلي التسعير الموسمي حقيقي، وبيدي ADR و RevPAR أرقام مضبوطة
    بدل ما تقسّم الإجمالي على عدد الليالي. جدول بينمو للملايين، فمفيهوش
    علاقات ثقيلة ولا أعمدة زيادة.
    """

    __tablename__ = "reservation_night"

    reservation_unit_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("reservation_unit.id", ondelete="CASCADE"), nullable=False
    )
    reservation_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    unit_category_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)

    stay_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: السعر المنشور قبل أي تعديل
    published_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: السعر المطبّق فعلاً
    rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    extra_person_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: مين عدّل السعر يدوياً — يتربط بسجل التدقيق
    is_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    override_reason: Mapped[Optional[str]] = mapped_column(String(300))
    #: هل الليلة دي اترحّلت على حساب النزيل؟ (بيعملها الـ Night Audit)
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    reservation_unit: Mapped[ReservationUnit] = relationship(
        back_populates="nights_detail", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint("reservation_unit_id", "stay_date", name="uq_reservation_night"),
        # تقارير الإيراد اليومي و ADR/RevPAR
        Index("ix_reservation_night_property_date", "property_id", "stay_date"),
        Index("ix_reservation_night_category_date", "unit_category_id", "stay_date"),
        # ترحيل ليالي اليوم في الـ Night Audit
        Index("ix_reservation_night_posting", "property_id", "stay_date", "is_posted"),
    )
