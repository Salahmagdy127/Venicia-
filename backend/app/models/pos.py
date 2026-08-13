"""نقاط البيع — Outlets, floor plan, menu, orders, KOT and cashier shifts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Index,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Percent, TZDateTime
from app.models.enums import (
    KotStatus,
    OutletType,
    PosOrderStatus,
    PosOrderType,
    SettlementType,
    ShiftStatus,
    TableStatus,
)
from app.models.mixins import (
    ActiveMixin,
    BilingualDescriptionMixin,
    BilingualNameMixin,
    CodeMixin,
)

# صنف واحد ممكن يتباع في أكتر من منفذ بسعر مختلف
menu_item_outlet = Table(
    "menu_item_outlet",
    Base.metadata,
    Column("menu_item_id", BigIntPK, ForeignKey("menu_item.id", ondelete="CASCADE"), primary_key=True),
    Column("outlet_id", BigIntPK, ForeignKey("outlet.id", ondelete="CASCADE"), primary_key=True),
)


class Outlet(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """منفذ بيع: المطعم، البار، الكافيه، السبا، الخيام على البحيرة."""

    __tablename__ = "outlet"

    property_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    outlet_type: Mapped[OutletType] = mapped_column(
        String(20), nullable=False, default=OutletType.RESTAURANT
    )

    #: نسب خاصة بالمنفذ — البار ممكن يفرق عن المطعم
    service_charge_percent: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("12")
    )
    vat_percent: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=Decimal("14"))

    has_floor_plan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allows_room_charge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: مينيو QR للطلب من الغرفة أو الشاطئ
    qr_ordering_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    opens_at: Mapped[Optional[str]] = mapped_column(String(5))
    closes_at: Mapped[Optional[str]] = mapped_column(String(5))
    #: بادئة رقم الأوردر — R للمطعم، B للبار
    order_prefix: Mapped[str] = mapped_column(String(4), nullable=False, default="O")
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        Index("ix_outlet_property_active", "property_id", "is_active", "sort_order"),
    )


class KitchenStation(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """محطة تحضير — المطبخ الساخن، البارد، البار، الحلويات.

    الـ KOT بيتوجّه للمحطة الصح تلقائياً حسب الصنف.
    """

    __tablename__ = "kitchen_station"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    outlet_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("outlet.id", ondelete="CASCADE"), index=True
    )
    printer_name: Mapped[Optional[str]] = mapped_column(String(120))
    #: عرض على شاشة المطبخ بدل الطباعة
    is_display_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PosTable(Base, PKMixin, TimestampMixin, ActiveMixin):
    """طاولة في تصميم الصالة — Floor Plan."""

    __tablename__ = "pos_table"

    outlet_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("outlet.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    zone_ar: Mapped[Optional[str]] = mapped_column(String(80))   # داخلي / تراس / على البحيرة
    zone_en: Mapped[Optional[str]] = mapped_column(String(80))
    seats: Mapped[int] = mapped_column(nullable=False, default=4)
    status: Mapped[TableStatus] = mapped_column(
        String(15), nullable=False, default=TableStatus.FREE, index=True
    )

    #: إحداثيات الرسم على شاشة الـ Floor Plan
    pos_x: Mapped[int] = mapped_column(nullable=False, default=0)
    pos_y: Mapped[int] = mapped_column(nullable=False, default=0)
    width: Mapped[int] = mapped_column(nullable=False, default=80)
    height: Mapped[int] = mapped_column(nullable=False, default=80)
    shape: Mapped[str] = mapped_column(String(15), nullable=False, default="SQUARE")

    __table_args__ = (
        UniqueConstraint("outlet_id", "label", name="uq_pos_table_outlet_label"),
        Index("ix_pos_table_outlet_status", "outlet_id", "status"),
    )


class MenuCategory(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """قسم في المنيو: مقبلات، مشويات، مشروبات ساخنة، كوكتيلات."""

    __tablename__ = "menu_category"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("menu_category.id", ondelete="SET NULL")
    )
    color: Mapped[Optional[str]] = mapped_column(String(9))
    icon: Mapped[Optional[str]] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        Index("ix_menu_category_property_active", "property_id", "is_active", "sort_order"),
    )


class MenuItem(
    Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, BilingualDescriptionMixin, ActiveMixin
):
    """صنف في المنيو."""

    __tablename__ = "menu_item"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("menu_category.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kitchen_station_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("kitchen_station.id", ondelete="SET NULL"), index=True
    )

    price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: تكلفة الوصفة — بيحسبها موديول المخازن في المرحلة 2
    cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    vat_percent: Mapped[Optional[Decimal]] = mapped_column(Percent)

    image_path: Mapped[Optional[str]] = mapped_column(String(500))
    preparation_minutes: Mapped[Optional[int]] = mapped_column()
    calories: Mapped[Optional[int]] = mapped_column()

    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    #: خلص النهاردة — بيختفي من المنيو من غير ما يتشال
    is_out_of_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_vegetarian: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contains_alcohol: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allergens: Mapped[Optional[str]] = mapped_column(String(300))
    #: بيدخل في حساب الخدمة؟ (المياه المعدنية أحياناً بتتعفى)
    is_service_charged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    outlets: Mapped[list[Outlet]] = relationship(secondary=menu_item_outlet, lazy="noload")

    __table_args__ = (
        Index("ix_menu_item_category_active", "category_id", "is_active", "sort_order"),
        Index("ix_menu_item_property_available", "property_id", "is_available"),
    )


class Shift(Base, PKMixin, TimestampMixin):
    """وردية كاشير — تقفيل الدرج ومطابقة العهدة."""

    __tablename__ = "shift"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    outlet_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    user_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    status: Mapped[ShiftStatus] = mapped_column(
        String(15), nullable=False, default=ShiftStatus.OPEN
    )
    opened_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)

    opening_float: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: اللي النظام شايفه
    expected_cash: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    expected_card: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: اللي الكاشير عدّه فعلاً
    counted_cash: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    counted_card: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: الفرق — ده الرقم اللي بيكشف المشاكل
    variance: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    orders_count: Mapped[int] = mapped_column(nullable=False, default=0)
    voids_count: Mapped[int] = mapped_column(nullable=False, default=0)
    discounts_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    reconciled_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    notes: Mapped[Optional[str]] = mapped_column(String(1000))

    __table_args__ = (
        Index("ix_shift_property_date", "property_id", "business_date", "status"),
        Index("ix_shift_user_date", "user_id", "business_date"),
    )


class PosOrder(Base, PKMixin, TimestampMixin):
    """أوردر في نقطة بيع — جدول عالي الحجم."""

    __tablename__ = "pos_order"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    outlet_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("outlet.id", ondelete="RESTRICT"), nullable=False
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)

    order_type: Mapped[PosOrderType] = mapped_column(
        String(20), nullable=False, default=PosOrderType.DINE_IN
    )
    status: Mapped[PosOrderStatus] = mapped_column(
        String(15), nullable=False, default=PosOrderStatus.OPEN
    )

    table_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("pos_table.id", ondelete="SET NULL"), index=True
    )
    covers: Mapped[int] = mapped_column(nullable=False, default=1)  # عدد الأفراد

    # --- الربط بالغرفة (Room Charge) ---
    folio_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    reservation_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    guest_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    unit_label: Mapped[Optional[str]] = mapped_column(String(40))
    #: توقيع النزيل على الفاتورة
    guest_signature_path: Mapped[Optional[str]] = mapped_column(String(500))

    # --- المبالغ ---
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    discount_percent: Mapped[Decimal] = mapped_column(Percent, nullable=False, default=Decimal("0"))
    discount_reason: Mapped[Optional[str]] = mapped_column(String(300))
    #: مين اعتمد الخصم — الخصومات محكومة بصلاحيات
    discount_approved_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    service_charge_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    paid_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    settlement_type: Mapped[Optional[SettlementType]] = mapped_column(String(20))
    shift_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    waiter_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    cashier_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    opened_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    settled_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[Optional[str]] = mapped_column(String(300))
    voided_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    lines: Mapped[list["PosOrderLine"]] = relationship(
        back_populates="order", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # شاشة الكاشير: أوردرات النهاردة المفتوحة
        Index("ix_pos_order_outlet_date_status", "outlet_id", "business_date", "status"),
        # تقارير الإيراد
        Index("ix_pos_order_property_date", "property_id", "business_date"),
        # تقفيل الوردية
        Index("ix_pos_order_shift", "shift_id", "status"),
    )


class PosOrderLine(Base, PKMixin):
    """سطر أوردر — أعلى جدول نمواً في النظام بعد سجل التدقيق.

    أسماء وأسعار الأصناف **متكرّرة هنا عمداً** (denormalised): الفاتورة
    القديمة لازم تفضل زي ما اتطبعت حتى لو الصنف اتغيّر اسمه أو سعره،
    وكمان بيوفّر join على مليون صف في كل تقرير.
    """

    __tablename__ = "pos_order_line"

    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    order_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("pos_order.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    outlet_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)

    menu_item_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    #: لقطة من بيانات الصنف وقت البيع
    item_name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    item_name_en: Mapped[Optional[str]] = mapped_column(String(200))
    kitchen_station_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    quantity: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: تكلفة الوحدة وقت البيع — أساس تقرير الربحية ومقارنة الهالك
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    line_discount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    notes: Mapped[Optional[str]] = mapped_column(String(300))  # بدون بصل، ويل دن
    kot_status: Mapped[KotStatus] = mapped_column(
        String(15), nullable=False, default=KotStatus.PENDING
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)

    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[Optional[str]] = mapped_column(String(300))
    voided_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    #: إلغاء صنف بعد ما راح المطبخ = مؤشر تلاعب، بيتسجّل منفصل
    voided_after_send: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    order: Mapped[PosOrder] = relationship(back_populates="lines", lazy="noload")

    __table_args__ = (
        Index("ix_pos_order_line_order", "order_id", "id"),
        # تقرير الأصناف الأكتر مبيعاً وتحليل الربحية
        Index("ix_pos_order_line_item_date", "menu_item_id", "business_date"),
        Index("ix_pos_order_line_outlet_date", "outlet_id", "business_date"),
        # شاشة المطبخ: كل المطلوب في المحطة دي دلوقتي
        Index("ix_pos_order_line_station_status", "kitchen_station_id", "kot_status"),
    )


class KotTicket(Base, PKMixin):
    """تذكرة مطبخ — طباعة الطلب في المحطة المسؤولة."""

    __tablename__ = "kot_ticket"

    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("pos_order.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    outlet_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    kitchen_station_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[KotStatus] = mapped_column(
        String(15), nullable=False, default=KotStatus.PENDING
    )
    #: تذكرة إضافية على نفس الأوردر (طلب زيادة)
    sequence: Mapped[int] = mapped_column(nullable=False, default=1)
    table_label: Mapped[Optional[str]] = mapped_column(String(20))
    printed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    ready_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    #: زمن التحضير الفعلي بالدقائق — مؤشر أداء المطبخ
    preparation_minutes: Mapped[Optional[int]] = mapped_column()

    __table_args__ = (
        Index("ix_kot_station_status_time", "kitchen_station_id", "status", "created_at"),
        Index("ix_kot_property_date", "property_id", "business_date"),
    )
