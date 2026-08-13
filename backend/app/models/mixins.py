"""أجزاء متكررة في النماذج — Reusable model mixins."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class BilingualNameMixin:
    """اسم عربي وإنجليزي — كل ما يُعرض للمستخدم مخزّن باللغتين."""

    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)

    def display_name(self, locale: str = "ar") -> str:
        return self.name_ar if locale == "ar" else self.name_en


class BilingualDescriptionMixin:
    description_ar: Mapped[Optional[str]] = mapped_column(String(1000))
    description_en: Mapped[Optional[str]] = mapped_column(String(1000))


class ActiveMixin:
    """التعطيل بدل الحذف — الحذف الفعلي ممنوع في نظام محاسبي."""

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1", index=True
    )


class CodeMixin:
    """كود قصير فريد يستخدمه الموظفون في البحث السريع."""

    @declared_attr
    def code(cls) -> Mapped[str]:  # noqa: N805
        return mapped_column(String(32), nullable=False, unique=True, index=True)
