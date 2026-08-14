"""الربط بالقنوات — Channel manager.

المشكلة اللي الموديول ده بيحلّها اسمها **الحجز المزدوج**: نفس الشاليه
بيتباع على بوكينج وأجودا في نفس الدقيقة لأن كل قناة شايفة إتاحة قديمة.
الحل مش «نبعت كل شوية» — الحل إن أي تغيير في الإتاحة يدخل **طابور**
مضمون، والطابور بيتبعت بالترتيب ومحدش بينساه.

تلات جداول:

* ``channel``          — القناة نفسها وحالتها وعمولتها
* ``channel_mapping``  — فئة الوحدة عندنا ← رقم الغرفة على القناة
* ``channel_message``  — طابور الرسايل الطالعة (إتاحة / سعر / قفل بيع)
* ``channel_booking``  — سجل كل حجز داخل من القناة، حتى المرفوض

الجدولين الأخرانيين append-only: بيسجّلوا اللي حصل بالظبط، فلو العميل
قال «الحجز ده وصلني على بوكينج ومظهرش عندك» فيه رد بالورق.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Percent, TZDateTime
from app.models.enums import (
    BookingSource,
    ChannelBookingAction,
    ChannelBookingStatus,
    ChannelMessageKind,
    ChannelMessageStatus,
)


class Channel(Base, PKMixin, TimestampMixin):
    """قناة بيع خارجية — بوكينج، أجودا، إكسبيديا، إير بي إن بي."""

    __tablename__ = "channel"

    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="CASCADE"), nullable=False
    )
    #: نفس قيم مصدر الحجز — القناة هي المصدر، مفيش تصنيفين لنفس الحاجة
    source: Mapped[BookingSource] = mapped_column(String(20), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(80), nullable=False)
    name_en: Mapped[str] = mapped_column(String(80), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: الاعتماد اتقبل من القناة — من غيره الطابور بيتجمّع من غير ما يتبعت
    is_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    commission_percent: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("0")
    )

    #: معرّف المنشأة على القناة (hotel id)
    external_property_id: Mapped[Optional[str]] = mapped_column(String(80))
    #: بيانات الاعتماد — بتتخزن مشفّرة في التنفيذ الحقيقي
    credentials: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    # --- حالة المزامنة ---
    last_push_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    last_pull_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    pushed_count: Mapped[int] = mapped_column(nullable=False, default=0)
    pulled_count: Mapped[int] = mapped_column(nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(500))

    mappings: Mapped[list["ChannelMapping"]] = relationship(
        back_populates="channel", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("property_id", "source", name="uq_channel_source"),
        Index("ix_channel_property_active", "property_id", "is_active"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Channel {self.source}>"


class ChannelMapping(Base, PKMixin, TimestampMixin):
    """ربط فئة الوحدة وخطة السعر عندنا برقمها على القناة.

    ده الجزء اللي بيتنسى فيقع كل حاجة: من غير ربط، الرسالة الطالعة
    مش عارفة تكتب رقم إيه، والحجز الداخل مش عارف ينزل على فئة إيه.
    """

    __tablename__ = "channel_mapping"

    channel_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("channel.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    unit_category_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("unit_category.id", ondelete="CASCADE"), nullable=False
    )
    rate_plan_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("rate_plan.id", ondelete="SET NULL")
    )

    #: رقم الغرفة على القناة
    external_room_id: Mapped[str] = mapped_column(String(80), nullable=False)
    #: رقم خطة السعر على القناة
    external_rate_id: Mapped[Optional[str]] = mapped_column(String(80))
    #: عدد الوحدات المسموح بيعها على القناة دي — صفر يعني كل المتاح
    allocation: Mapped[int] = mapped_column(nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    channel: Mapped[Channel] = relationship(back_populates="mappings", lazy="noload")

    __table_args__ = (
        UniqueConstraint(
            "channel_id", "unit_category_id", "rate_plan_id", name="uq_channel_mapping"
        ),
        Index("ix_channel_mapping_category", "unit_category_id"),
    )


class ChannelMessage(Base, PKMixin):
    """رسالة طالعة للقناة — طابور مضمون التسليم.

    كل تغيير في الإتاحة بيدخل هنا في نفس معاملة الحجز. يعني لو الحجز
    نجح، الرسالة موجودة أكيد؛ ولو الحجز فشل، مفيش رسالة كاذبة.
    """

    __tablename__ = "channel_message"

    channel_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("channel.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    unit_category_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    kind: Mapped[ChannelMessageKind] = mapped_column(String(14), nullable=False)
    status: Mapped[ChannelMessageStatus] = mapped_column(
        String(10), nullable=False, default=ChannelMessageStatus.PENDING
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: اللي هيتبعت فعلاً — بيتبني وقت الإرسال من آخر إتاحة، مش وقت الطابور
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    #: سبب الرسالة بالعربي — بيظهر في الشاشة
    reason: Mapped[Optional[str]] = mapped_column(String(120))

    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    error: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        # الاستعلام الوحيد المهم: «هات اللي لسه في الطابور بالترتيب»
        Index("ix_channel_message_queue", "property_id", "status", "id"),
        Index("ix_channel_message_channel", "channel_id", "status"),
    )


class ChannelBooking(Base, PKMixin):
    """سجل كل حجز وصل من قناة — بما فيه المرفوض.

    append-only بالكامل. ده اللي بيخلي سؤال «الحجز ده راح فين؟» له
    إجابة بدل تخمين.
    """

    __tablename__ = "channel_booking"

    channel_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("channel.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)

    #: رقم الحجز على القناة — ده مفتاح منع التكرار
    external_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[ChannelBookingAction] = mapped_column(String(8), nullable=False)
    status: Mapped[ChannelBookingStatus] = mapped_column(String(10), nullable=False)

    guest_name: Mapped[Optional[str]] = mapped_column(String(200))
    guest_phone: Mapped[Optional[str]] = mapped_column(String(30))
    arrival_date: Mapped[Optional[date]] = mapped_column(Date)
    departure_date: Mapped[Optional[date]] = mapped_column(Date)
    gross_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    commission_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    reservation_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    #: الحمولة الأصلية زي ما وصلت — لو حصل خلاف مع القناة
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)

    __table_args__ = (
        # لا يوجد قيد فريد هنا عن قصد: الجدول ده سجل وصول، والمفروض يسجّل
        # حتى المحاولة المكررة عشان تبان في الشاشة. منع التكرار الفعلي
        # بيحصل في الخدمة قبل ما نلمس الحجز نفسه.
        Index("ix_channel_booking_reference", "channel_id", "external_reference"),
        Index("ix_channel_booking_property", "property_id", "received_at"),
    )
