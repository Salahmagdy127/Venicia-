"""مهام الميدان — Field tasks, evidence photos and the offline event log.

الموديول ده هو ظهر تطبيق الموبايل. تلات جداول وكل واحد بيجاوب على سؤال:

* ``HousekeepingTask`` — **مين المفروض ينضّف إيه النهاردة؟** المهمة بتتولّد
  من الحجوزات (مغادرة، وصول، إقامة) مش بتتكتب بالإيد، فمفيش وحدة بتفوت.
* ``FieldPhoto`` — **إثبات إن الشغل اتعمل.** صورة قبل وصورة بعد، وبتتخزّن
  ببصمتها فالصورة الواحدة مش بتتعدّ مرتين ولا بتترفع مرتين.
* ``TaskEvent`` — **حصل إيه بالظبط وإمتى؟** سجل بالإضافة فقط، بيتبني من
  التليفون. كل حدث معاه ``client_uuid``، وده المفتاح اللي بيخلّي إعادة
  الإرسال بعد ما الشبكة ترجع **مش** بتكرّر الشغل.

الفكرة اللي كل حاجة هنا مبنية عليها: **الشبكة مش موجودة.** الهاوس كيبر بيمشي
في قرية على بحيرة، جوّه شاليهات بحيطان خرسانة. التليفون بيسجّل محلياً
وبيطلّع لما يلاقي شبكة — ممكن بعد ساعتين. يبقى وقت الحدث الحقيقي هو
اللي التليفون سجّله (``happened_at``)، ووقت وصوله للسيرفر حاجة تانية
خالص (``received_at``). لو خلطناهم، تقرير «الغرفة اتنضفت الساعة كام»
بيبقى بيقيس الشبكة مش الشغل.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin
from app.db.types import BigIntPK, TZDateTime
from app.models.enums import PhotoPhase, TaskEventKind, TaskKind, TaskStatus


class HousekeepingTask(Base, PKMixin, TimestampMixin):
    """مهمة تنضيف وحدة في يوم — الوحدة الأساسية اللي التطبيق بيشتغل عليها."""

    __tablename__ = "housekeeping_task"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    unit_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("unit.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_date: Mapped[date] = mapped_column(nullable=False, index=True)

    kind: Mapped[TaskKind] = mapped_column(String(20), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        String(14), nullable=False, default=TaskStatus.PENDING, index=True
    )
    #: أقل رقم = أول في الجولة. المغادرات الأول لأن فيه نزيل جاي عليها
    priority: Mapped[int] = mapped_column(nullable=False, default=50, index=True)

    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)

    #: الوقت اللي التليفون سجّله — ده وقت الشغل الحقيقي
    started_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    #: الزمن الصافي بالثواني — الوقفات (عدم إزعاج، بريك) متشالة منه
    working_seconds: Mapped[int] = mapped_column(nullable=False, default=0)
    #: الوقت المتوقّع — بيتحسب من نوع المهمة وفئة الوحدة
    expected_minutes: Mapped[int] = mapped_column(nullable=False, default=30)

    #: كام مرة راح لقى «عدم إزعاج». تلاتة يعني لازم الاستقبال يتدخل
    dnd_attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_dnd_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    #: مبتظهرش في الجولة قبل الوقت ده — عشان «عدم إزعاج» ترجع بعد ساعة
    snoozed_until: Mapped[Optional[datetime]] = mapped_column(TZDateTime, index=True)
    blocked_reason: Mapped[Optional[str]] = mapped_column(String(300))

    #: صور قبل وبعد مطلوبة؟ المغادرة أيوه، الإقامة اليومية لأ
    photos_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    photo_before_count: Mapped[int] = mapped_column(nullable=False, default=0)
    photo_after_count: Mapped[int] = mapped_column(nullable=False, default=0)

    linen_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    amenities_restocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    minibar_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: فحص السوبرفايزر
    inspected_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK)
    inspected_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    inspection_score: Mapped[Optional[int]] = mapped_column()   # من 5
    inspection_note: Mapped[Optional[str]] = mapped_column(String(500))

    note: Mapped[Optional[str]] = mapped_column(String(500))
    #: التذكرة اللي اتفتحت من المهمة دي، لو الهاوس كيبر لقى عطل
    ticket_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    __table_args__ = (
        # التوليد اليومي بيعتمد عليه: نفس الوحدة ونفس النوع في نفس اليوم
        # بتتعمل **مرة واحدة**. من غير القيد ده، تشغيل النايت أوديت مرتين
        # بيدّي الهاوس كيبر نفس الغرفة مرتين في القايمة.
        UniqueConstraint("unit_id", "task_date", "kind", name="uq_task_unit_date_kind"),
        # الاستعلام الرئيسي في التليفون: مهامي النهاردة بالترتيب
        Index("ix_task_assignee_date", "assigned_to_user_id", "task_date", "priority"),
        # لوحة السوبرفايزر: كل مهام القرية النهاردة بحالتها
        Index("ix_task_property_date_status", "property_id", "task_date", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task u{self.unit_id} {self.task_date} {self.kind} {self.status}>"


class FieldPhoto(Base, PKMixin):
    """صورة من الميدان — قبل، بعد، أو عطل.

    الملف نفسه على القرص مش في الداتابيز. الصف ده بيمسك **البصمة**
    و**مين صوّر** و**إمتى بالظبط**، وده اللي بيخلّي الصورة دليل.
    """

    __tablename__ = "field_photo"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    task_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("housekeeping_task.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[Optional[int]] = mapped_column(
        BigIntPK, ForeignKey("maintenance_ticket.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    phase: Mapped[PhotoPhase] = mapped_column(String(10), nullable=False)

    #: معرّف التليفون للصورة — بيمنع الرفع المكرّر لما الشبكة تقطع في النص
    client_uuid: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    #: بصمة المحتوى. صورتين متطابقتين = ملف واحد على القرص
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(300), nullable=False)
    thumb_path: Mapped[Optional[str]] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(60), nullable=False, default="image/jpeg")
    byte_size: Mapped[int] = mapped_column(nullable=False, default=0)
    width: Mapped[Optional[int]] = mapped_column()
    height: Mapped[Optional[int]] = mapped_column()

    #: وقت التصوير الحقيقي من التليفون
    taken_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    #: وقت وصولها للسيرفر — الفرق بينهم هو زمن الأوفلاين
    uploaded_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    taken_by_user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(64))
    note: Mapped[Optional[str]] = mapped_column(String(300))

    __table_args__ = (
        Index("ix_photo_task_phase", "task_id", "phase"),
        Index("ix_photo_property_taken", "property_id", "taken_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Photo {self.phase} t{self.task_id}>"


class TaskEvent(Base, PKMixin):
    """حدث واحد من تليفون موظف — إضافة فقط، مبيتعدّلش ولا بيتمسح.

    ده الجدول اللي بيخلّي المزامنة **آمنة التكرار**: التليفون بيبعت نفس
    الحدث كذا مرة لو الرد ضاع، والسيرفر بيلاقي ``client_uuid`` موجود
    فبيرد ``DUPLICATE`` من غير ما ينفّذ حاجة تاني.
    """

    __tablename__ = "task_event"

    property_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    task_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    ticket_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    unit_id: Mapped[Optional[int]] = mapped_column(BigIntPK)

    kind: Mapped[TaskEventKind] = mapped_column(String(20), nullable=False)
    #: مفتاح آمان التكرار — بيتولّد على التليفون قبل ما يحاول يبعت
    client_uuid: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    device_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    #: وقت الحدث زي ما التليفون سجّله — ده الوقت اللي التقارير بتقرا منه
    happened_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    #: وقت وصوله للسيرفر
    received_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    #: الفرق بالثواني — لو كبير يبقى الموظف كان أوفلاين، مش إن السيرفر بطيء
    offline_seconds: Mapped[int] = mapped_column(nullable=False, default=0)

    user_id: Mapped[Optional[int]] = mapped_column(BigIntPK, index=True)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    note: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_event_task_time", "task_id", "happened_at"),
        Index("ix_event_property_time", "property_id", "happened_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Event {self.kind} t{self.task_id}>"
