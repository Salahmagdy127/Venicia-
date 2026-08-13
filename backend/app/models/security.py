"""المستخدمون والصلاحيات وسجل التدقيق — Users, roles, permissions, audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    String,
    Table,
    Column,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, TZDateTime
from app.models.enums import AuditAction
from app.models.mixins import ActiveMixin, BilingualNameMixin, CodeMixin

# ------------------------------------------------------------------ الربط
user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", BigIntPK, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", BigIntPK, ForeignKey("role.id", ondelete="CASCADE"), primary_key=True),
)

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", BigIntPK, ForeignKey("role.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        BigIntPK,
        ForeignKey("permission.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# ------------------------------------------------------------- الصلاحيات
class Permission(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin):
    """صلاحية ذرّية، مثال: ``reservation.create`` أو ``pos.discount.approve``."""

    __tablename__ = "permission"

    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    roles: Mapped[list["Role"]] = relationship(
        secondary=role_permission, back_populates="permissions", lazy="selectin"
    )


class Role(Base, PKMixin, TimestampMixin, CodeMixin, BilingualNameMixin, ActiveMixin):
    """دور وظيفي: ريسبشن، كاشير، شيف، مدير مطعم، محاسب، مالك."""

    __tablename__ = "role"

    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: أقصى نسبة خصم يقدر صاحب الدور يمنحها من غير موافقة أعلى
    max_discount_percent: Mapped[int] = mapped_column(nullable=False, default=0)

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permission, back_populates="roles", lazy="selectin"
    )
    users: Mapped[list["User"]] = relationship(
        secondary=user_role, back_populates="roles", lazy="noload"
    )


class User(Base, PKMixin, TimestampMixin, ActiveMixin):
    """مستخدم النظام."""

    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    full_name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name_en: Mapped[str] = mapped_column(String(200), nullable=False)

    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    #: PIN قصير لتسجيل الدخول السريع على شاشة الكاشير
    pos_pin_hash: Mapped[Optional[str]] = mapped_column(String(255))

    property_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("property.id", ondelete="SET NULL"), index=True
    )
    preferred_locale: Mapped[str] = mapped_column(String(5), nullable=False, default="ar")
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_login_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    failed_login_count: Mapped[int] = mapped_column(nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(TZDateTime)

    roles: Mapped[list[Role]] = relationship(
        secondary=user_role, back_populates="users", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_app_user_property_active", "property_id", "is_active"),
    )

    @property
    def permission_codes(self) -> set[str]:
        if self.is_superuser:
            return {"*"}
        return {p.code for role in self.roles if role.is_active for p in role.permissions}

    def has_permission(self, code: str) -> bool:
        codes = self.permission_codes
        if "*" in codes:
            return True
        if code in codes:
            return True
        # صلاحية بالنجمة على مستوى الموديول: ``pos.*``
        module = code.split(".", 1)[0]
        return f"{module}.*" in codes

    def display_name(self, locale: str = "ar") -> str:
        return self.full_name_ar if locale == "ar" else self.full_name_en

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username}>"


# ------------------------------------------------------------ سجل التدقيق
class AuditLog(Base, PKMixin):
    """مين عدّل إيه وامتى — ضروري ضد التلاعب.

    ده أسرع جدول نمواً في النظام (ملايين الصفوف سنوياً)، فمتصمم كجدول
    **إضافة فقط** بدون علاقات ORM ثقيلة، وبفهارس مركّبة تخدم أنماط
    البحث الفعلية بس. في Postgres بيتقسّم شهرياً بالتاريخ.
    """

    __tablename__ = "audit_log"

    # التوقيت أول عمود في كل فهرس لأن كل البحث بيبدأ بمدى زمني.
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)

    user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(60))
    property_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)

    action: Mapped[AuditAction] = mapped_column(String(30), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    #: وصف مقروء جاهز للعرض بدون joins
    summary_ar: Mapped[Optional[str]] = mapped_column(String(500))
    summary_en: Mapped[Optional[str]] = mapped_column(String(500))

    #: الفروق قبل/بعد. JSON عادي عشان يشتغل على SQLite و Postgres.
    changes: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(300))

    __table_args__ = (
        # "إيه اللي حصل على الحجز ده؟" — أكتر بحث بيتعمل
        Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),
        # "الموظف ده عمل إيه النهاردة؟"
        Index("ix_audit_user_time", "user_id", "created_at"),
        # "كل الخصومات اللي اتعملت الشهر ده" — تتبّع التلاعب
        Index("ix_audit_action_time", "action", "created_at"),
    )


class LoginAttempt(Base, PKMixin):
    """محاولات الدخول — منفصلة عن سجل التدقيق عشان متكبّرهوش."""

    __tablename__ = "login_attempt"

    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    reason: Mapped[Optional[str]] = mapped_column(String(120))

    __table_args__ = (
        Index("ix_login_attempt_user_time", "username", "created_at"),
    )
