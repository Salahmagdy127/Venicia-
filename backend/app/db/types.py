"""أنواع بيانات محايدة تشتغل على SQLite و PostgreSQL بنفس السلوك.

Portable column types: identical semantics on SQLite (demo) and PostgreSQL
(production), so switching engines never rewrites a model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, TypeDecorator

# مفاتيح 64-بت للجداول اللي بتوصل للملايين. SQLite بيحتاج INTEGER عشان
# الترقيم التلقائي يشتغل، وPostgres بياخد BIGINT.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class UtcDateTime(TypeDecorator):
    """تاريخ ووقت بالـ UTC دايماً — على المحركين.

    SQLite مش بيخزّن المنطقة الزمنية، فلو سِبناه على راحته الوقت بيترجع
    «مجرّد» والواجهة بتفسّره على إنه توقيت محلي — يعني ساعات غلط في كشف
    الحساب وشاشة الكاشير. عشان كده بنحوّل أي وقت لـ UTC قبل التخزين،
    وبنلزق المنطقة الزمنية تاني وقت القراءة. على PostgreSQL الأعمدة
    ``timestamptz`` بترجع أصلاً بمنطقة زمنية، فالنوع ده بيبقى بلا أثر.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# التوقيت دايماً UTC ومعاه المنطقة الزمنية.
TZDateTime = UtcDateTime()

MONEY_SCALE = Decimal("0.0001")
RATE_SCALE = Decimal("0.0001")


class Money(TypeDecorator):
    """قيمة نقدية بدقة عشرية — Exact decimal money.

    لا تُستخدم ``float`` أبداً في الفلوس. الأرقام بترجع Decimal مضبوطة على
    4 خانات عشرية على المحركين.
    """

    impl = Numeric(18, 4)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return value.quantize(MONEY_SCALE)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(str(value)).quantize(MONEY_SCALE)


QUANTITY_SCALE = Decimal("0.001")


class Quantity(TypeDecorator):
    """كمية مخزنية بدقة عشرية.

    تلات خانات مش أربعة: أدق حاجة بتتصرف في مطبخ هي الجرام والمللي،
    وكلاهما بيتكتب بتلات خانات لو الوحدة كيلو أو لتر. الزيادة عن كده
    بتخزّن ضوضاء الحساب من غير أي فايدة.
    """

    impl = Numeric(16, 3)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return value.quantize(QUANTITY_SCALE)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(str(value)).quantize(QUANTITY_SCALE)


class Percent(TypeDecorator):
    """نسبة مئوية (مثال: 14.0000 يعني 14%)."""

    impl = Numeric(9, 4)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return value.quantize(RATE_SCALE)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(str(value)).quantize(RATE_SCALE)
