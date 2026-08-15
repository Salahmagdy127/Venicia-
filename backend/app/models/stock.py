"""المخازن والوصفات والمشتريات — Inventory, recipes and purchasing.

المبدأ اللي الموديول واقف عليه: **الحركات هي الحقيقة، والرصيد نسخة محسوبة.**

``stock_movement`` جدول append-only: كل استلام وصرف وهالك وتسوية بيتسجّل
فيه ومبيتعدّلش أبداً. ``stock_level`` رصيد مخزّن عشان السرعة، وممكن
يتبني من الصفر من الحركات في أي وقت. يعني لو الرصيد اختلف، فيه مصدر
واحد صحيح نرجعله — مش تخمين.

والقيمة اللي بتفرق فعلاً: **الوصفة**. لما الكاشير يبيع سمكة مشوية،
النظام بيعرف إنها 250 جرام سمك و30 مللي زيت، وبيخصمهم. آخر الشهر
بتقارن اللي المفروض اتصرف باللي اتصرف فعلاً — والفرق ده اسمه هالك أو
سرقة، وده الرقم اللي المالك بيدفع عشانه.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, Money, Quantity, TZDateTime
from app.models.enums import (
    MovementKind,
    PurchaseStatus,
    StockUnit,
    WarehouseKind,
)
from app.models.mixins import ActiveMixin, BilingualNameMixin, CodeMixin


class Supplier(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """مورد."""

    __tablename__ = "supplier"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(150))
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    tax_number: Mapped[Optional[str]] = mapped_column(String(40))
    #: مهلة السداد بالأيام — صفر يعني كاش
    payment_terms_days: Mapped[int] = mapped_column(nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("property_id", "code", name="uq_supplier_code"),
    )


class Warehouse(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """مخزن — رئيسي، مطبخ، بار."""

    __tablename__ = "warehouse"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    kind: Mapped[WarehouseKind] = mapped_column(
        String(14), nullable=False, default=WarehouseKind.MAIN
    )
    #: المنفذ اللي بيصرف منه — لو المخزن تابع لمطعم أو بار
    outlet_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("property_id", "code", name="uq_warehouse_code"),
    )


class StockItem(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """صنف مخزني — مادة خام مش صنف منيو."""

    __tablename__ = "stock_item"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    #: تصنيف للتقارير: لحوم · خضار · مشروبات · مستهلكات
    category_ar: Mapped[str] = mapped_column(String(60), nullable=False, default="عام")
    category_en: Mapped[str] = mapped_column(String(60), nullable=False, default="General")
    unit: Mapped[StockUnit] = mapped_column(String(8), nullable=False, default=StockUnit.PIECE)

    #: متوسط التكلفة المرجّح — بيتحدّث مع كل استلام
    average_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    last_purchase_cost: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=Decimal("0")
    )
    #: تحت الرقم ده بيبقى في تنبيه إعادة الطلب
    reorder_level: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=Decimal("0"))
    #: الكمية اللي بتتطلب عادةً
    reorder_quantity: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0")
    )
    preferred_supplier_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    #: الصنف ده بيتراقب بالجرد اليومي — للأصناف غالية التمن
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("property_id", "code", name="uq_stock_item_code"),
        Index("ix_stock_item_category", "property_id", "category_ar"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StockItem {self.code}>"


class StockLevel(Base, PKMixin, TimestampMixin):
    """رصيد صنف في مخزن — نسخة محسوبة من الحركات عشان السرعة."""

    __tablename__ = "stock_level"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("warehouse.id", ondelete="CASCADE"), nullable=False
    )
    stock_item_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("stock_item.id", ondelete="CASCADE"), nullable=False
    )

    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=Decimal("0"))
    #: قيمة الرصيد بمتوسط التكلفة وقت كل حركة
    value: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    last_movement_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    last_counted_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)

    __table_args__ = (
        UniqueConstraint("warehouse_id", "stock_item_id", name="uq_stock_level"),
        Index("ix_stock_level_item", "property_id", "stock_item_id"),
    )


class StockMovement(Base, PKMixin):
    """حركة مخزنية — append-only، مصدر الحقيقة الوحيد للرصيد."""

    __tablename__ = "stock_movement"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    stock_item_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    kind: Mapped[MovementKind] = mapped_column(String(14), nullable=False)

    #: موجبة دايماً — الاتجاه بيتحدد من ``kind``
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    total_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    #: الرصيد بعد الحركة — بيخلّي كشف الحركة مقروء من غير حساب
    balance_after: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0")
    )

    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    # --- المرجع ---
    purchase_order_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    pos_order_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    #: الحركة المقابلة في التحويل بين المخازن
    counterpart_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    __table_args__ = (
        # كشف حركة الصنف — أهم استعلام في الموديول
        Index("ix_movement_item", "stock_item_id", "warehouse_id", "id"),
        Index("ix_movement_date", "property_id", "business_date"),
        Index("ix_movement_kind", "property_id", "kind", "business_date"),
    )


class Recipe(Base, PKMixin, TimestampMixin):
    """وصفة صنف المنيو — من غيرها المخزن مبيعرفش يخصم إيه."""

    __tablename__ = "recipe"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    menu_item_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("menu_item.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    #: المخزن اللي بيتخصم منه — عادةً مخزن المطبخ
    warehouse_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    #: الوصفة بتطلع كام طبق — عشان وصفات الشوربة والصوصات
    yield_portions: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("1")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    lines: Mapped[list["RecipeLine"]] = relationship(
        back_populates="recipe", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def cost(self) -> Decimal:
        """تكلفة الطبق الواحد من مكوّناته."""
        total = sum((line.line_cost for line in self.lines), Decimal("0"))
        portions = self.yield_portions or Decimal("1")
        return total / portions if portions else Decimal("0")


class RecipeLine(Base, PKMixin):
    """مكوّن في وصفة."""

    __tablename__ = "recipe_line"

    recipe_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False
    )
    stock_item_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: نسبة الفاقد في التجهيز — تقشير وتنضيف السمك مثلاً
    waste_percent: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0")
    )
    #: لقطة من متوسط التكلفة وقت الحفظ — للعرض السريع
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    recipe: Mapped[Recipe] = relationship(back_populates="lines", lazy="noload")

    @property
    def gross_quantity(self) -> Decimal:
        """الكمية اللي بتتصرف فعلاً بعد الفاقد."""
        return self.quantity * (Decimal("1") + self.waste_percent / 100)

    @property
    def line_cost(self) -> Decimal:
        return self.gross_quantity * self.unit_cost

    __table_args__ = (Index("ix_recipe_line_recipe", "recipe_id"),)


class PurchaseOrder(Base, PKMixin, TimestampMixin):
    """أمر شراء."""

    __tablename__ = "purchase_order"

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    supplier_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    status: Mapped[PurchaseStatus] = mapped_column(
        String(10), nullable=False, default=PurchaseStatus.DRAFT, index=True
    )

    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[Optional[date]] = mapped_column(Date)
    received_date: Mapped[Optional[date]] = mapped_column(Date)

    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))

    #: رقم فاتورة المورد — بيربط الاستلام بمستنده
    supplier_invoice_number: Mapped[Optional[str]] = mapped_column(String(60))
    notes: Mapped[Optional[str]] = mapped_column(String(500))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    cancelled_reason: Mapped[Optional[str]] = mapped_column(String(300))

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="order", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_po_board", "property_id", "status", "order_date"),
    )


class PurchaseOrderLine(Base, PKMixin):
    """سطر في أمر شراء — بيتتبّع المطلوب والمستلم."""

    __tablename__ = "purchase_order_line"

    purchase_order_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("purchase_order.id", ondelete="CASCADE"), nullable=False
    )
    stock_item_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, index=True)
    quantity_ordered: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: بيزيد مع كل استلام جزئي
    quantity_received: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0")
    )
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    notes: Mapped[Optional[str]] = mapped_column(String(200))

    order: Mapped[PurchaseOrder] = relationship(back_populates="lines", lazy="noload")

    @property
    def outstanding(self) -> Decimal:
        return max(Decimal("0"), self.quantity_ordered - self.quantity_received)

    __table_args__ = (Index("ix_po_line_order", "purchase_order_id"),)
