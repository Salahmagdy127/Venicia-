"""الصيانة والميني بار — Maintenance tickets and minibar catalog.

التذكرة مش مجرد ملاحظة: هي **اللي بتشيل الوحدة من البيع وترجّعها**.
قبل الموديول ده، الوحدة بتبقى «خارج الخدمة» ومحدش عارف ليه ولا مين
بيصلّحها ولا هترجع إمتى — وده بالظبط اللي بيخلّي وحدة تفضل مقفولة
أسبوعين على عطل صيانته ساعة.

الميني بار كتالوج بسيط بيترحّل على حساب النزيل زي أي بند تاني، فبيدخل
الفاتورة والتقارير من غير مسار خاص.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, TZDateTime
from app.models.enums import (
    TicketCategory,
    TicketPriority,
    TicketSource,
    TicketStatus,
)
from app.models.mixins import ActiveMixin, BilingualNameMixin, CodeMixin


class MaintenanceTicket(Base, PKMixin, TimestampMixin):
    """بلاغ عطل — من فتحه لحد ما يتقفل."""

    __tablename__ = "maintenance_ticket"

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    #: ممكن يكون فاضي — فيه أعطال في مناطق عامة مش في وحدة
    unit_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("unit.id", ondelete="SET NULL"), index=True
    )
    #: مكان العطل لو مش وحدة — «حمام السباحة»، «الاستقبال»
    location: Mapped[Optional[str]] = mapped_column(String(120))

    category: Mapped[TicketCategory] = mapped_column(
        String(12), nullable=False, default=TicketCategory.OTHER
    )
    priority: Mapped[TicketPriority] = mapped_column(
        String(8), nullable=False, default=TicketPriority.NORMAL, index=True
    )
    status: Mapped[TicketStatus] = mapped_column(
        String(12), nullable=False, default=TicketStatus.OPEN, index=True
    )
    source: Mapped[TicketSource] = mapped_column(
        String(14), nullable=False, default=TicketSource.STAFF
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000))

    #: التذكرة دي بتشيل الوحدة من البيع؟ ده الفرق بين «الريموت ضايع»
    #: و«التكييف واقف» — الأولى مبتمنعش البيع والتانية بتمنعه
    blocks_unit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: الحالة اللي الوحدة كانت عليها قبل الحجب — عشان ترجعلها بالظبط
    previous_condition: Mapped[Optional[str]] = mapped_column(String(20))

    reported_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    #: لو النزيل هو اللي اشتكى — بيربط الشكوى بإقامته
    folio_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    opened_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    started_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    #: الوعد بالإصلاح — اللي بعده بتبقى متأخرة
    due_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime, index=True)

    resolution: Mapped[Optional[str]] = mapped_column(String(1000))
    cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    cancelled_reason: Mapped[Optional[str]] = mapped_column(String(300))

    __table_args__ = (
        # الاستعلام الرئيسي في الشاشة: المفتوح بالأولوية
        Index("ix_ticket_board", "property_id", "status", "priority"),
        Index("ix_ticket_unit_status", "unit_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Ticket {self.number} {self.status}>"


class MinibarItem(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """صنف في الميني بار — كتالوج صغير بأسعاره."""

    __tablename__ = "minibar_item"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    contains_alcohol: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        Index("ix_minibar_property_active", "property_id", "is_active", "sort_order"),
    )
