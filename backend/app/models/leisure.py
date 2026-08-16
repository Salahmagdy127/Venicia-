"""السبا والأنشطة والمناسبات — Spa, activities, venues and events.

الموديول ده بيضيف مصادر الدخل اللي مش إقامة ولا أكل. في قرية على
بحيرة دي مش إضافة صغيرة: الفرح الواحد ممكن يساوي أسبوع إشغال، ورحلة
القارب بتتباع لنزيل موجود أصلاً — يعني إيراد بتكلفة تسويق صفر.

الفكرة المحورية في السبا والأنشطة: **المورد هو اللي بيتحجز، مش
الخدمة.** المساج مش بيتحجز — *المعالجة* هي اللي بتتحجز. القارب مش
بيتحجز مرتين في نفس الساعة مهما كانت أسماء الرحلات مختلفة. عشان كده
كل حجز بيمسك ``resource_id``، والتعارض بيتحسب على المورد.

وفي المناسبات: **المكان بيتقفل بالحالة مش بالنية.** استعلام مبيقفلش
حاجة، ومبدئي بيقفل. الفرق ده هو اللي بيمنع إن قاعة تتباع مرتين لأن
حد قال «إن شاء الله» في التليفون.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    ForeignKey,
    Index,
    String,
    Table,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Quantity, TZDateTime
from app.models.enums import (
    EventItemKind,
    EventKind,
    EventStatus,
    FeedbackChannel,
    FeedbackKind,
    FeedbackStatus,
    ResourceKind,
    ServiceBookingStatus,
    ServiceCategory,
    VenueKind,
)
from app.models.mixins import ActiveMixin, BilingualNameMixin, CodeMixin

#: أي مورد ينفع لأي خدمة. المعالجة بتعمل مساج سويدي وحجر ساخن، والقارب
#: بيعمل رحلة غروب وصيد — فالربط كتير لكتير مش عمود واحد.
service_resource = Table(
    "service_resource",
    Base.metadata,
    Column("service_id", BigIntPK, ForeignKey("service.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "resource_id",
        BigIntPK,
        ForeignKey("service_resource_item.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Service(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """خدمة قابلة للبيع بموعد — مساج، رحلة قارب، كلاس يوجا."""

    __tablename__ = "service"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    category: Mapped[ServiceCategory] = mapped_column(String(12), nullable=False, index=True)

    duration_minutes: Mapped[int] = mapped_column(nullable=False, default=60)
    #: وقت التجهيز بين حجزين — ترتيب الكابينة، رجوع القارب للرصيف.
    #: من غيره الجدول بيبان مظبوط والواقع بيتأخّر عشر دقايق كل مرة.
    buffer_minutes: Mapped[int] = mapped_column(nullable=False, default=15)

    price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    price_child: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: التكلفة المباشرة (زيوت، وقود، أجر مرشد) — عشان الهامش يبان
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    #: أقصى عدد أفراد في الميعاد الواحد. المساج ١، كلاس اليوجا ١٢.
    capacity: Mapped[int] = mapped_column(nullable=False, default=1)
    #: بيحتاج مورد؟ «تأجير دراجة» ممكن يتباع من غير جدول
    requires_resource: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    opens_at: Mapped[Optional[time]] = mapped_column(Time)
    closes_at: Mapped[Optional[time]] = mapped_column(Time)

    description_ar: Mapped[Optional[str]] = mapped_column(String(700))
    description_en: Mapped[Optional[str]] = mapped_column(String(700))
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    resources: Mapped[list["ServiceResourceItem"]] = relationship(
        secondary=service_resource, back_populates="services", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_service_property_category", "property_id", "category", "sort_order"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Service {self.code} {self.name_ar}>"


class ServiceResourceItem(Base, PKMixin, TimestampMixin, CodeMixin, ActiveMixin):
    """المورد اللي بيتحجز — معالجة، كابينة، قارب."""

    __tablename__ = "service_resource_item"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    kind: Mapped[ResourceKind] = mapped_column(String(12), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(150), nullable=False)
    name_en: Mapped[str] = mapped_column(String(150), nullable=False)

    #: كام حجز يشيل في نفس اللحظة. المعالجة ١، القارب ٨ ركاب.
    capacity: Mapped[int] = mapped_column(nullable=False, default=1)
    #: الموظف المرتبط بالمورد لو المورد شخص
    user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    shift_start: Mapped[Optional[time]] = mapped_column(Time)
    shift_end: Mapped[Optional[time]] = mapped_column(Time)
    notes: Mapped[Optional[str]] = mapped_column(String(300))

    services: Mapped[list[Service]] = relationship(
        secondary=service_resource, back_populates="resources", lazy="noload"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Resource {self.code} {self.name_ar}>"


class ServiceBooking(Base, PKMixin, TimestampMixin):
    """موعد محجوز — النزيل، الخدمة، المورد، والوقت."""

    __tablename__ = "service_booking"

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    service_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("service.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    resource_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("service_resource_item.id", ondelete="SET NULL"), index=True
    )

    guest_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    guest_name: Mapped[str] = mapped_column(String(250), nullable=False)
    #: الحساب اللي هيترحّل عليه. فاضي = زائر يومي بيدفع كاش
    folio_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    reservation_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    start_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    status: Mapped[ServiceBookingStatus] = mapped_column(
        String(12), nullable=False, default=ServiceBookingStatus.CONFIRMED, index=True
    )
    adults: Mapped[int] = mapped_column(nullable=False, default=1)
    children: Mapped[int] = mapped_column(nullable=False, default=0)

    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: سطر الحساب اللي اترحّل — بيمنع الترحيل مرتين
    folio_line_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    posted_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)

    notes: Mapped[Optional[str]] = mapped_column(String(500))
    cancelled_reason: Mapped[Optional[str]] = mapped_column(String(300))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    __table_args__ = (
        # الاستعلام اللي بيتنده عند كل محاولة حجز: المورد ده مشغول إمتى؟
        Index("ix_booking_resource_time", "resource_id", "start_at", "end_at"),
        Index("ix_booking_property_date", "property_id", "business_date", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ServiceBooking {self.number} {self.status}>"


# ═══════════════════════════════════════════════════════ المناسبات
class Venue(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """مكان مناسبات — قاعة، حديقة، شاطئ."""

    __tablename__ = "venue"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    kind: Mapped[VenueKind] = mapped_column(String(10), nullable=False)

    capacity_seated: Mapped[int] = mapped_column(nullable=False, default=0)
    capacity_standing: Mapped[int] = mapped_column(nullable=False, default=0)
    area_sqm: Mapped[Optional[int]] = mapped_column()

    day_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    hourly_rate: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: أقل إنفاق مقبول. الفرح اللي مش هيوصله مش بياخد القاعة —
    #: عشان يوم في قاعة الأفراح أغلى بكتير من إيجارها.
    minimum_spend: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    description_ar: Mapped[Optional[str]] = mapped_column(String(700))
    description_en: Mapped[Optional[str]] = mapped_column(String(700))
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Venue {self.code} {self.name_ar}>"


class EventBooking(Base, PKMixin, TimestampMixin):
    """مناسبة — من الاستعلام لحد ما تخلص وتتحاسب."""

    __tablename__ = "event_booking"

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    venue_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("venue.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(250), nullable=False)
    kind: Mapped[EventKind] = mapped_column(String(12), nullable=False, default=EventKind.OTHER)
    status: Mapped[EventStatus] = mapped_column(
        String(12), nullable=False, default=EventStatus.INQUIRY, index=True
    )

    guest_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    company_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    client_name: Mapped[str] = mapped_column(String(250), nullable=False)
    client_phone: Mapped[Optional[str]] = mapped_column(String(40))
    client_email: Mapped[Optional[str]] = mapped_column(String(200))

    start_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    pax: Mapped[int] = mapped_column(nullable=False, default=0)
    package_per_person: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=Decimal("0")
    )

    venue_charge: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    items_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    service_charge: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    deposit_required: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    deposit_paid: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: آخر ميعاد لدفع العربون — بعده الحجز المبدئي بيتفك
    option_until: Mapped[Optional[date]] = mapped_column(Date, index=True)

    folio_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    notes: Mapped[Optional[str]] = mapped_column(String(1500))
    #: ملاحظات التشغيل: شكل الجلوس، وقت الوصول، تعليمات المطبخ
    setup_notes: Mapped[Optional[str]] = mapped_column(String(1500))
    lost_reason: Mapped[Optional[str]] = mapped_column(String(300))
    cancelled_reason: Mapped[Optional[str]] = mapped_column(String(300))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    items: Mapped[list["EventItem"]] = relationship(
        back_populates="event", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # تقويم القاعات: مين حاجز إيه إمتى
        Index("ix_event_venue_date", "venue_id", "event_date", "status"),
        Index("ix_event_property_date", "property_id", "event_date", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Event {self.number} {self.title}>"


class EventItem(Base, PKMixin):
    """بند في ورقة تشغيل المناسبة — Banquet Event Order line."""

    __tablename__ = "event_item"

    event_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("event_booking.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[EventItemKind] = mapped_column(String(14), nullable=False)
    description_ar: Mapped[str] = mapped_column(String(300), nullable=False)
    description_en: Mapped[Optional[str]] = mapped_column(String(300))

    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: بند مش بيتحاسب عليه — مجاملة أو ضمن الباكدج
    is_complimentary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[Optional[str]] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    event: Mapped[EventBooking] = relationship(back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EventItem {self.kind} {self.description_ar}>"


# ═══════════════════════════════════════════════ ملاحظات النزلاء
class GuestFeedback(Base, PKMixin, TimestampMixin):
    """شكوى أو ثناء أو تقييم — بمالك ووقت رد.

    من غير الجدول ده الشكوى بتعيش في واتساب مدير الاستقبال. وده مش
    مجرد ترتيب: **زمن الرد** هو المقياس الوحيد اللي بيفرق بين شكوى
    بتتحل وشكوى بتتحوّل مراجعة بنجمة واحدة على جوجل.
    """

    __tablename__ = "guest_feedback"

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    guest_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    guest_name: Mapped[str] = mapped_column(String(250), nullable=False)
    reservation_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    unit_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    kind: Mapped[FeedbackKind] = mapped_column(String(12), nullable=False, index=True)
    channel: Mapped[FeedbackChannel] = mapped_column(String(14), nullable=False)
    status: Mapped[FeedbackStatus] = mapped_column(
        String(14), nullable=False, default=FeedbackStatus.OPEN, index=True
    )
    #: من ١ لـ ٥. فاضي في الشكاوى اللي مالهاش تقييم
    rating: Mapped[Optional[int]] = mapped_column()
    department: Mapped[Optional[str]] = mapped_column(String(60), index=True)

    subject: Mapped[str] = mapped_column(String(250), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(String(2000))

    received_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    owner_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    resolution: Mapped[Optional[str]] = mapped_column(String(1500))
    #: التعويض اللي اتقدّم (خصم، ليلة مجانية) — بيتقاس مع الوقت
    compensation: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tags: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    __table_args__ = (
        Index("ix_feedback_property_status", "property_id", "status", "received_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Feedback {self.number} {self.kind}>"
