"""قوائم الحالات الثابتة في النظام — Domain enumerations.

كل قيمة بتتخزن كنص قصير في الداتابيز عشان تفضل مقروءة في التقارير والتدقيق،
وعشان إضافة قيمة جديدة متحتاجش ALTER TYPE في Postgres.
"""

from __future__ import annotations

from enum import StrEnum


# ---------------------------------------------------------------- الوحدات
class UnitKind(StrEnum):
    """نوع الوحدة المؤجَّرة — فينيسيا مش غرف بس."""

    ROOM = "ROOM"                    # غرفة
    CHALET = "CHALET"                # شاليه
    VILLA = "VILLA"                  # فيلا
    SUITE = "SUITE"                  # جناح
    LAKE_TENT = "LAKE_TENT"          # خيمة على البحيرة
    LAKE_LOUNGE = "LAKE_LOUNGE"      # جلسة على البحيرة
    CABANA = "CABANA"                # كابانا


class HousekeepingStatus(StrEnum):
    """حالة نظافة الوحدة — بتتغيّر لايف من تطبيق السوبرفايزر."""

    CLEAN = "CLEAN"                  # نظيفة
    DIRTY = "DIRTY"                  # متسخة
    INSPECTED = "INSPECTED"          # تم الفحص
    CLEANING = "CLEANING"            # جاري التنظيف


class UnitCondition(StrEnum):
    """صلاحية الوحدة للبيع."""

    OPERATIONAL = "OPERATIONAL"      # صالحة
    MAINTENANCE = "MAINTENANCE"      # تحت الصيانة (ممكن تتباع بعد الإصلاح)
    OUT_OF_ORDER = "OUT_OF_ORDER"    # خارج الخدمة — بتتخصم من الإتاحة
    OUT_OF_SERVICE = "OUT_OF_SERVICE"  # موقوفة إدارياً — مش بتتخصم من الإشغال


class OccupancyStatus(StrEnum):
    VACANT = "VACANT"                # فاضية
    OCCUPIED = "OCCUPIED"            # مشغولة


# ---------------------------------------------------------------- الحجوزات
class ReservationStatus(StrEnum):
    INQUIRY = "INQUIRY"              # استعلام
    TENTATIVE = "TENTATIVE"          # مبدئي (تحت انتظار العربون)
    CONFIRMED = "CONFIRMED"          # مؤكد
    CHECKED_IN = "CHECKED_IN"        # نازل
    CHECKED_OUT = "CHECKED_OUT"      # غادر
    CANCELLED = "CANCELLED"          # ملغي
    NO_SHOW = "NO_SHOW"              # لم يحضر
    WAITLIST = "WAITLIST"            # قائمة انتظار


#: الحالات اللي بتحجز إتاحة فعلية (بتخصم من الغرف المتاحة)
BLOCKING_RESERVATION_STATUSES: frozenset[ReservationStatus] = frozenset(
    {
        ReservationStatus.TENTATIVE,
        ReservationStatus.CONFIRMED,
        ReservationStatus.CHECKED_IN,
    }
)


class WaitlistStatus(StrEnum):
    """رحلة الطلب في قايمة الانتظار."""

    WAITING = "WAITING"              # مستنّي مكان يفضى
    OFFERED = "OFFERED"              # اتعرض عليه وبنستنى رده — الوحدة محجوزة مؤقتاً
    CONVERTED = "CONVERTED"          # اتحوّل لحجز فعلي
    EXPIRED = "EXPIRED"              # التواريخ عدّت من غير ما نلاقي مكان
    CANCELLED = "CANCELLED"          # النزيل عدل أو الموظف شطبه


class WaitlistPriority(StrEnum):
    """أولوية الاتصال لما يفضى مكان."""

    NORMAL = "NORMAL"                # عادي
    HIGH = "HIGH"                    # مهم
    VIP = "VIP"                      # نزيل مميز أو متكرر


class BookingSource(StrEnum):
    """مصدر الحجز — ده اللي بيحسب عمولة القنوات وبيثبت قيمة الـ Booking Engine."""

    DIRECT = "DIRECT"                # مباشر (تليفون / حضور)
    WEBSITE = "WEBSITE"              # موقع القرية — عمولة صفر
    WALK_IN = "WALK_IN"              # بدون حجز مسبق
    BOOKING_COM = "BOOKING_COM"
    AGODA = "AGODA"
    EXPEDIA = "EXPEDIA"
    AIRBNB = "AIRBNB"
    TRAVEL_AGENT = "TRAVEL_AGENT"    # شركة سياحة
    CORPORATE = "CORPORATE"          # عقد شركات


# ------------------------------------------------------- الربط بالقنوات
class ChannelMessageKind(StrEnum):
    """نوع الرسالة الطالعة للقناة."""

    AVAILABILITY = "AVAILABILITY"    # عدد الوحدات المتاحة
    RATE = "RATE"                    # السعر
    STOP_SELL = "STOP_SELL"          # قفل أو فتح البيع


class ChannelMessageStatus(StrEnum):
    PENDING = "PENDING"              # في الطابور
    SENT = "SENT"                    # اتبعت واتأكدت
    FAILED = "FAILED"                # فشلت وهتتعاد
    SKIPPED = "SKIPPED"              # الفئة دي مش مربوطة على القناة


class ChannelBookingAction(StrEnum):
    """الحجز الجاي من القناة بيعمل إيه."""

    NEW = "NEW"                      # حجز جديد
    MODIFY = "MODIFY"                # تعديل على حجز قايم
    CANCEL = "CANCEL"                # إلغاء


class ChannelBookingStatus(StrEnum):
    PROCESSED = "PROCESSED"          # اتنفّذ
    DUPLICATE = "DUPLICATE"          # وصل قبل كده — اتجاهل
    REJECTED = "REJECTED"            # مرفوض (مفيش إتاحة أو مفيش ربط)
    FAILED = "FAILED"                # خطأ فني


class MealPlan(StrEnum):
    RO = "RO"    # غرفة فقط — Room Only
    BB = "BB"    # إفطار — Bed & Breakfast
    HB = "HB"    # نصف إقامة — Half Board
    FB = "FB"    # إقامة كاملة — Full Board
    AI = "AI"    # شامل كلياً — All Inclusive


class IdentificationType(StrEnum):
    NATIONAL_ID = "NATIONAL_ID"      # الرقم القومي
    PASSPORT = "PASSPORT"            # جواز السفر
    DRIVING_LICENSE = "DRIVING_LICENSE"
    OTHER = "OTHER"


# ---------------------------------------------------------------- الحسابات
class FolioStatus(StrEnum):
    OPEN = "OPEN"                    # مفتوح
    CLOSED = "CLOSED"                # مقفول
    TRANSFERRED = "TRANSFERRED"      # محوّل


class FolioType(StrEnum):
    GUEST = "GUEST"                  # حساب النزيل
    MASTER = "MASTER"                # حساب رئيسي (مجموعة/شركة)
    EVENT = "EVENT"                  # مناسبة (فرح / مؤتمر)


class ChargeKind(StrEnum):
    """نوع الحركة على حساب النزيل."""

    ROOM = "ROOM"                    # إيجار الوحدة
    FNB = "FNB"                      # مأكولات ومشروبات
    SPA = "SPA"                      # سبا
    ACTIVITY = "ACTIVITY"            # رحلات وأنشطة
    MINIBAR = "MINIBAR"              # ميني بار
    LAUNDRY = "LAUNDRY"              # مغسلة
    TELEPHONE = "TELEPHONE"
    SERVICE_CHARGE = "SERVICE_CHARGE"  # الخدمة 12%
    TAX = "TAX"                      # الضرائب
    CITY_TAX = "CITY_TAX"            # رسوم بلدية
    DISCOUNT = "DISCOUNT"            # خصم
    PAYMENT = "PAYMENT"              # دفعة
    DEPOSIT = "DEPOSIT"              # عربون
    REFUND = "REFUND"                # استرداد
    ADJUSTMENT = "ADJUSTMENT"        # تسوية
    CANCELLATION_FEE = "CANCELLATION_FEE"
    NO_SHOW_FEE = "NO_SHOW_FEE"


#: الحركات اللي بتزوّد المديونية (مدين) مقابل اللي بتقللها (دائن)
CREDIT_CHARGE_KINDS: frozenset[ChargeKind] = frozenset(
    {
        ChargeKind.PAYMENT,
        ChargeKind.DEPOSIT,
        ChargeKind.DISCOUNT,
        ChargeKind.REFUND,
    }
)


class PaymentMethod(StrEnum):
    CASH = "CASH"                    # نقدي
    CARD = "CARD"                    # فيزا / ماستر
    FAWRY = "FAWRY"                  # فوري
    PAYMOB = "PAYMOB"                # باي موب
    INSTAPAY = "INSTAPAY"
    BANK_TRANSFER = "BANK_TRANSFER"  # تحويل بنكي
    CHEQUE = "CHEQUE"                # شيك
    CITY_LEDGER = "CITY_LEDGER"      # آجل على حساب شركة
    OTA_PREPAID = "OTA_PREPAID"      # محصّل من القناة
    COMPLIMENTARY = "COMPLIMENTARY"  # ضيافة


# ---------------------------------------------------------------- نقاط البيع
class OutletType(StrEnum):
    RESTAURANT = "RESTAURANT"        # مطعم
    BAR = "BAR"                      # بار
    CAFE = "CAFE"                    # كافيه
    SPA = "SPA"                      # سبا
    BEACH = "BEACH"                  # الشاطئ / الخيام
    ROOM_SERVICE = "ROOM_SERVICE"    # خدمة الغرف
    SHOP = "SHOP"                    # متجر
    ACTIVITIES = "ACTIVITIES"        # رحلات وأنشطة


class TableStatus(StrEnum):
    FREE = "FREE"                    # فاضية
    OCCUPIED = "OCCUPIED"            # مشغولة
    RESERVED = "RESERVED"            # محجوزة
    BILLED = "BILLED"                # اتطلبت الفاتورة


class PosOrderStatus(StrEnum):
    OPEN = "OPEN"                    # مفتوح
    SENT = "SENT"                    # اتبعت للمطبخ
    SERVED = "SERVED"                # اتقدّم
    SETTLED = "SETTLED"              # اتحاسب
    VOID = "VOID"                    # ملغي


class PosOrderType(StrEnum):
    DINE_IN = "DINE_IN"              # في المكان
    TAKEAWAY = "TAKEAWAY"            # تيك أواي
    ROOM_SERVICE = "ROOM_SERVICE"    # خدمة غرف
    BEACH_SERVICE = "BEACH_SERVICE"  # خدمة الشاطئ / الخيام
    DELIVERY = "DELIVERY"


class KotStatus(StrEnum):
    PENDING = "PENDING"              # في الانتظار
    PRINTED = "PRINTED"              # اتطبع
    PREPARING = "PREPARING"          # بيتحضّر
    READY = "READY"                  # جاهز
    SERVED = "SERVED"                # اتقدّم
    CANCELLED = "CANCELLED"          # ملغي


class SettlementType(StrEnum):
    CASH = "CASH"
    CARD = "CARD"
    ROOM_CHARGE = "ROOM_CHARGE"      # على حساب الغرفة
    CITY_LEDGER = "CITY_LEDGER"
    COMPLIMENTARY = "COMPLIMENTARY"
    STAFF = "STAFF"                  # على الموظفين


class ShiftStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"        # اتطابقت العهدة


# ---------------------------------------------------------------- الفوترة
class InvoiceType(StrEnum):
    INVOICE = "INVOICE"              # فاتورة إلكترونية (B2B)
    RECEIPT = "RECEIPT"              # إيصال إلكتروني (B2C)
    CREDIT_NOTE = "CREDIT_NOTE"      # إشعار خصم
    DEBIT_NOTE = "DEBIT_NOTE"        # إشعار إضافة


class EtaStatus(StrEnum):
    """حالة المستند على منظومة مصلحة الضرائب المصرية."""

    DRAFT = "DRAFT"                  # مسودة
    QUEUED = "QUEUED"                # في الطابور
    SUBMITTED = "SUBMITTED"          # اتبعت
    VALID = "VALID"                  # مقبولة
    INVALID = "INVALID"              # مرفوضة
    REJECTED = "REJECTED"            # مرفوضة من المستلم
    CANCELLED = "CANCELLED"          # ملغاة
    FAILED = "FAILED"                # فشل الإرسال


# ---------------------------------------------------------------- التسعير
class RateRuleType(StrEnum):
    """قواعد التسعير الديناميكي فوق السعر الأساسي."""

    WEEKEND = "WEEKEND"              # ويك إند
    MIDWEEK = "MIDWEEK"              # منتصف الأسبوع
    HOLIDAY = "HOLIDAY"              # أعياد ومواسم
    OCCUPANCY = "OCCUPANCY"          # حسب نسبة الإشغال
    LEAD_TIME = "LEAD_TIME"          # حسب قرب الميعاد
    LENGTH_OF_STAY = "LENGTH_OF_STAY"  # حسب عدد الليالي


class AdjustmentMethod(StrEnum):
    PERCENT = "PERCENT"              # نسبة مئوية
    AMOUNT = "AMOUNT"                # مبلغ ثابت
    OVERRIDE = "OVERRIDE"            # سعر بديل نهائي


# ---------------------------------------------------------------- عام
class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    VOID = "VOID"                    # إلغاء حركة
    DISCOUNT = "DISCOUNT"            # منح خصم
    PRICE_OVERRIDE = "PRICE_OVERRIDE"  # تعديل سعر يدوي
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    NIGHT_AUDIT = "NIGHT_AUDIT"
    EXPORT = "EXPORT"                # تصدير بيانات


class Gender(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNSPECIFIED = "UNSPECIFIED"
