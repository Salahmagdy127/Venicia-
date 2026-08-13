"""نماذج الاستجابة المشتركة — Shared response schemas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Bilingual(ApiModel):
    ar: str
    en: str


class Message(ApiModel):
    """رسالة للمستخدم باللغتين — الواجهة بتختار حسب لغة العرض."""

    ar: str
    en: str


class PageMeta(ApiModel):
    next_cursor: str | None = None
    has_more: bool = False


class Paged(ApiModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class DayCell(ApiModel):
    """عمود يوم في شاشة الحجوزات."""

    date: date
    weekday: int
    weekday_ar: str
    weekday_en: str
    day: int
    month_ar: str
    is_weekend: bool
    is_today: bool


WEEKDAYS_AR = ["اثنين", "ثلاثاء", "أربعاء", "خميس", "جمعة", "سبت", "أحد"]
WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_AR = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]


def build_day(value: date, today: date) -> DayCell:
    weekday = value.weekday()
    return DayCell(
        date=value,
        weekday=weekday,
        weekday_ar=WEEKDAYS_AR[weekday],
        weekday_en=WEEKDAYS_EN[weekday],
        day=value.day,
        month_ar=MONTHS_AR[value.month - 1],
        is_weekend=weekday in (4, 5),  # الجمعة والسبت
        is_today=value == today,
    )


class Money(ApiModel):
    amount: Decimal = Field(default=Decimal("0"))
    currency: str = "EGP"
