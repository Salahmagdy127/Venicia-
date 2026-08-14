"""مزامنة القنوات — Channel manager sync.

المبدأ اللي الموديول كله واقف عليه: **الطابور جوّه المعاملة**.

أي تغيير في الإتاحة بيكتب رسالة في ``channel_message`` في نفس معاملة
الحجز. يعني مستحيل يحصل حجز من غير ما القنوات تعرف، ومستحيل تتبعت
رسالة عن حجز اتلغى في آخر لحظة. البديل الشائع — إن السيرفر «يفتكر»
يبعت بعد ما يخلّص — هو بالظبط اللي بيعمل الحجز المزدوج.

حاجتين تانيين مقصودين:

* **الحمولة بتتبني وقت الإرسال مش وقت الطابور.** لو حصلوا خمس حجوزات
  على نفس اليوم قبل ما الطابور يمشي، القناة بتاخد الرقم الأخير الصح
  مرة واحدة — مش خمس أرقام قديمة بالترتيب.
* **الرسايل المتجاورة بتتلمّ في واحدة.** حجز أربع ليالي بيبقى رسالة
  واحدة على مدى، مش أربع رسايل.

الإرسال الفعلي معزول في ``TRANSPORT`` — دلوقتي محاكاة محلية، ولما
تتوقّع عقود مع القنوات بيتغيّر ملف واحد بس.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.channels import Channel, ChannelBooking, ChannelMapping, ChannelMessage
from app.models.enums import (
    BookingSource,
    ChannelBookingAction,
    ChannelBookingStatus,
    ChannelMessageKind,
    ChannelMessageStatus,
    ReservationStatus,
)
from app.models.guests import Guest
from app.models.reservations import Reservation, ReservationUnit

#: أقصى عدد رسايل بتتبعت في الدفعة الواحدة
FLUSH_BATCH = 200
#: بعد كام محاولة فاشلة نسيب الرسالة ونعلّمها فشل نهائي
MAX_ATTEMPTS = 5
#: أطول مدى في رسالة واحدة — أطول من كده بنقسّم
MAX_SPAN_DAYS = 120


class ChannelError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "channel_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════ الطابور الطالع
def _mapped_channels(
    db: Session, property_id: int, category_id: int | None
) -> list[tuple[Channel, ChannelMapping | None]]:
    """القنوات المتوصّلة اللي عندها ربط للفئة دي.

    شرطين مقصودين:

    * **قناة من غير ربط مبتاخدش رسايل** — مفيش رقم غرفة نكتبه، فالرسالة
      مش هتعني حاجة.
    * **قناة لسه ماتوصّلتش مبتاخدش رسايل** — تجميع فروقات على قناة مقفولة
      بيخلّف طابور بايت. أول ما تتوصّل بتاخد الصورة الكاملة بـ ``resync``،
      وده أأمن من إعادة تشغيل تاريخ من التغييرات.
    """
    channels = list(
        db.execute(
            select(Channel).where(
                Channel.property_id == property_id,
                Channel.is_active.is_(True),
                Channel.is_connected.is_(True),
            )
        ).scalars().all()
    )
    if not channels or category_id is None:
        return [(c, None) for c in channels]

    maps = {
        m.channel_id: m
        for m in db.execute(
            select(ChannelMapping).where(
                ChannelMapping.unit_category_id == category_id,
                ChannelMapping.is_active.is_(True),
                ChannelMapping.channel_id.in_([c.id for c in channels]),
            )
        ).scalars().all()
    }
    return [(c, maps[c.id]) for c in channels if c.id in maps]


def queue(
    db: Session,
    property_id: int,
    *,
    kind: ChannelMessageKind,
    start: date,
    end: date,
    category_id: int | None = None,
    reason: str | None = None,
) -> int:
    """بيحط تغيير في طابور كل قناة مربوطة. بيرجّع عدد الرسايل المتأثرة.

    لو فيه رسالة لسه في الطابور لنفس (القناة × الفئة × النوع) وتواريخها
    ملاصقة أو متداخلة، بنوسّع مداها بدل ما نضيف صف جديد.
    """
    if end <= start:
        return 0

    touched = 0
    now = utcnow()

    for channel, _mapping in _mapped_channels(db, property_id, category_id):
        pending = db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.channel_id == channel.id,
                ChannelMessage.kind == kind,
                ChannelMessage.status == ChannelMessageStatus.PENDING,
                ChannelMessage.unit_category_id.is_(category_id)
                if category_id is None
                else ChannelMessage.unit_category_id == category_id,
                # ملاصقة أو متداخلة — يوم واحد بينهم بيتلم برضه
                ChannelMessage.start_date <= end,
                ChannelMessage.end_date >= start,
            )
            .order_by(ChannelMessage.id)
            .limit(1)
        ).scalar_one_or_none()

        if pending is not None:
            new_start = min(pending.start_date, start)
            new_end = max(pending.end_date, end)
            if (new_end - new_start).days <= MAX_SPAN_DAYS:
                pending.start_date = new_start
                pending.end_date = new_end
                if reason:
                    pending.reason = reason
                touched += 1
                continue

        db.add(
            ChannelMessage(
                channel_id=channel.id,
                property_id=property_id,
                unit_category_id=category_id,
                kind=kind,
                status=ChannelMessageStatus.PENDING,
                start_date=start,
                end_date=end,
                reason=reason,
                created_at=now,
            )
        )
        touched += 1

    if touched:
        db.flush()
    return touched


def queue_availability(
    db: Session, property_id: int, category_id: int, start: date, end: date, reason: str
) -> int:
    return queue(
        db,
        property_id,
        kind=ChannelMessageKind.AVAILABILITY,
        start=start,
        end=end,
        category_id=category_id,
        reason=reason,
    )


def queue_stop_sell(
    db: Session,
    property_id: int,
    category_ids: Sequence[int],
    start: date,
    end: date,
    reason: str,
) -> int:
    total = 0
    for category_id in category_ids:
        total += queue(
            db,
            property_id,
            kind=ChannelMessageKind.STOP_SELL,
            start=start,
            end=end,
            category_id=category_id,
            reason=reason,
        )
    return total


def queue_rates(
    db: Session, property_id: int, category_ids: Sequence[int], start: date, end: date, reason: str
) -> int:
    total = 0
    for category_id in category_ids:
        total += queue(
            db,
            property_id,
            kind=ChannelMessageKind.RATE,
            start=start,
            end=end,
            category_id=category_id,
            reason=reason,
        )
    return total


# ═══════════════════════════════════════════════════════ الإرسال
def _simulated_transport(channel: Channel, message: ChannelMessage, payload: dict) -> dict:
    """ناقل محاكاة — بيقبل كل حاجة ويرجّع تأكيد.

    مكانه هنا مقصود: ده الملف الوحيد اللي بيتغيّر لما تتوقّع عقد مع
    بوكينج أو أجودا. كل اللي فوق — الطابور والتجميع وإعادة المحاولة
    والسجل — شغّال زي ما هو من غير أي تعديل.
    """
    return {
        "accepted": True,
        "channel": channel.source,
        "hotel_id": channel.external_property_id,
        "rows": len(payload.get("days", [])),
        "simulated": True,
    }


#: نقطة تبديل الناقل — بيتغيّر في الاختبارات وعند الربط الحقيقي
TRANSPORT: Callable[[Channel, ChannelMessage, dict], dict] = _simulated_transport


@dataclass(slots=True)
class FlushResult:
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    channels: dict[str, int] = field(default_factory=dict)


def _build_payload(db: Session, message: ChannelMessage, mapping: ChannelMapping | None) -> dict:
    """الحمولة بتتبني من آخر إتاحة دلوقتي — مش من الحالة وقت الطابور."""
    from app.services import availability as av  # محلي: بيكسر دورة الاستيراد

    days: list[dict[str, Any]] = []
    if message.unit_category_id is not None:
        rows = av.get_availability(
            db,
            message.property_id,
            message.start_date,
            message.end_date,
            [message.unit_category_id],
        )
        for row in rows:
            free = row.available
            # التخصيص بيحد اللي القناة تشوفه — بيمنع إنها تاكل كل الوحدات
            if mapping is not None and mapping.allocation > 0:
                free = min(free, mapping.allocation)
            days.append(
                {
                    "date": row.stay_date.isoformat(),
                    "available": free,
                    "closed": row.is_closed,
                }
            )

    return {
        "kind": message.kind,
        "room_id": mapping.external_room_id if mapping else None,
        "rate_id": mapping.external_rate_id if mapping else None,
        "start": message.start_date.isoformat(),
        "end": message.end_date.isoformat(),
        "days": days,
    }


def flush(db: Session, property_id: int, *, limit: int = FLUSH_BATCH) -> FlushResult:
    """بيمشّي الطابور: بيبني الحمولة من آخر حالة وبيبعتها ويسجّل النتيجة."""
    result = FlushResult()

    messages = list(
        db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.property_id == property_id,
                ChannelMessage.status == ChannelMessageStatus.PENDING,
            )
            .order_by(ChannelMessage.id)
            .limit(limit)
        ).scalars().all()
    )
    if not messages:
        return result

    channels = {
        c.id: c
        for c in db.execute(
            select(Channel).where(Channel.id.in_({m.channel_id for m in messages}))
        ).scalars().all()
    }
    mappings = {
        (m.channel_id, m.unit_category_id): m
        for m in db.execute(
            select(ChannelMapping).where(
                ChannelMapping.channel_id.in_(channels.keys()),
                ChannelMapping.is_active.is_(True),
            )
        ).scalars().all()
    }

    now = utcnow()
    for message in messages:
        channel = channels.get(message.channel_id)
        message.attempts += 1

        if channel is None or not channel.is_active or not channel.is_connected:
            # القناة مقفولة أو لسه ماتوصّلتش — الرسالة بتستنى، مش بتضيع
            message.status = ChannelMessageStatus.SKIPPED
            message.error = "القناة مش متوصّلة"
            result.skipped += 1
            continue

        mapping = mappings.get((message.channel_id, message.unit_category_id))
        if mapping is None and message.unit_category_id is not None:
            message.status = ChannelMessageStatus.SKIPPED
            message.error = "الفئة مش مربوطة على القناة"
            result.skipped += 1
            continue

        payload = _build_payload(db, message, mapping)
        try:
            answer = TRANSPORT(channel, message, payload)
            if not answer.get("accepted"):
                raise ChannelError(
                    answer.get("error_ar") or "القناة رفضت الرسالة",
                    answer.get("error_en") or "Channel rejected the message",
                )
            message.status = ChannelMessageStatus.SENT
            message.payload = payload
            message.sent_at = now
            message.error = None
            channel.last_push_at = now
            channel.pushed_count += 1
            result.sent += 1
            result.channels[channel.source] = result.channels.get(channel.source, 0) + 1
        except Exception as exc:  # الفشل بيتسجّل والرسالة بتفضل للمحاولة الجاية
            message.error = str(exc)[:500]
            channel.error_count += 1
            channel.last_error = message.error
            result.failed += 1
            message.status = (
                ChannelMessageStatus.FAILED
                if message.attempts >= MAX_ATTEMPTS
                else ChannelMessageStatus.PENDING
            )

    db.flush()
    return result


def retry_failed(db: Session, property_id: int) -> int:
    """رجّع الرسايل الفاشلة للطابور — بيتنادى من الشاشة بعد إصلاح السبب."""
    rows = db.execute(
        select(ChannelMessage).where(
            ChannelMessage.property_id == property_id,
            ChannelMessage.status.in_(
                [ChannelMessageStatus.FAILED, ChannelMessageStatus.SKIPPED]
            ),
        )
    ).scalars().all()
    for message in rows:
        message.status = ChannelMessageStatus.PENDING
        message.attempts = 0
        message.error = None
    if rows:
        db.flush()
    return len(rows)


def resync(db: Session, property_id: int, days: int = 90) -> int:
    """إعادة بعت الإتاحة كلها من النهاردة — زرار «طابق كل حاجة».

    بيتستخدم بعد انقطاع طويل أو بعد ما ربط جديد يتعمل، وقتها الأمان إنك
    تبعت الصورة الكاملة أهم من إنك توفّر رسايل.
    """
    from app.models.units import UnitCategory  # محلي: مش محتاجينه غير هنا

    today = date.today()
    categories = list(
        db.execute(
            select(UnitCategory.id).where(
                UnitCategory.property_id == property_id, UnitCategory.is_active.is_(True)
            )
        ).scalars().all()
    )
    total = 0
    for category_id in categories:
        total += queue(
            db,
            property_id,
            kind=ChannelMessageKind.AVAILABILITY,
            start=today,
            end=today + timedelta(days=days),
            category_id=category_id,
            reason="مطابقة كاملة",
        )
    return total


# ═══════════════════════════════════════════════════ الحجوزات الداخلة
def _record(
    db: Session,
    *,
    channel: Channel,
    payload: dict,
    action: ChannelBookingAction,
    status: ChannelBookingStatus,
    reservation_id: int | None = None,
    error: str | None = None,
    gross: Decimal = Decimal("0"),
    commission: Decimal = Decimal("0"),
) -> ChannelBooking:
    guest = payload.get("guest") or {}
    row = ChannelBooking(
        channel_id=channel.id,
        property_id=channel.property_id,
        external_reference=str(payload.get("external_reference") or "—")[:80],
        action=action,
        status=status,
        guest_name=" ".join(
            x for x in [guest.get("first_name"), guest.get("last_name")] if x
        )[:200]
        or None,
        guest_phone=(guest.get("phone") or None),
        arrival_date=_as_date(payload.get("arrival_date")),
        departure_date=_as_date(payload.get("departure_date")),
        gross_amount=gross,
        commission_amount=commission,
        reservation_id=reservation_id,
        payload=payload,
        error=error,
        received_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _find_guest(db: Session, property_id: int, guest: dict) -> Guest:
    """النزيل الجاي من قناة: بندوّر بالموبايل الأول، وبنعمل ملف جديد لو مالقيناش."""
    phone = (guest.get("phone") or "").strip()
    if phone:
        found = db.execute(
            select(Guest).where(Guest.property_id == property_id, Guest.phone == phone).limit(1)
        ).scalar_one_or_none()
        if found is not None:
            return found

    row = Guest(
        property_id=property_id,
        first_name=(guest.get("first_name") or "نزيل").strip()[:100],
        last_name=(guest.get("last_name") or "قناة").strip()[:100],
        phone=phone or None,
        email=(guest.get("email") or None),
        nationality=(guest.get("nationality") or "EG"),
    )
    db.add(row)
    db.flush()
    return row


def ingest(db: Session, property_id: int, source: BookingSource, payload: dict) -> ChannelBooking:
    """استقبال حجز من قناة — جديد أو تعديل أو إلغاء.

    كل مسار بيسيب أثر في ``channel_booking``، حتى المرفوض. الرفض مش
    فشل صامت: بيتسجّل بسببه عشان الموظف يشوفه في الشاشة ويتصرّف.
    """
    from app.services import reservations as res_svc  # محلي: بيكسر دورة الاستيراد
    from app.services.availability import AvailabilityError
    from app.services.pricing import PricingError

    channel = db.execute(
        select(Channel).where(Channel.property_id == property_id, Channel.source == source)
    ).scalar_one_or_none()
    if channel is None:
        raise ChannelError("القناة دي مش معرّفة", "Channel is not configured", "not_found")

    reference = str(payload.get("external_reference") or "").strip()
    if not reference:
        raise ChannelError("الحجز جه من غير رقم مرجعي", "Missing external reference", "no_reference")

    try:
        action = ChannelBookingAction(str(payload.get("action") or "NEW").upper())
    except ValueError:
        raise ChannelError("إجراء غير معروف", "Unknown action", "bad_action") from None

    channel.last_pull_at = utcnow()
    channel.pulled_count += 1

    # القنوات بتعيد إرسال نفس الحدث عادي، فبنتجاهل التكرار الحرفي.
    # التواريخ جزء من المفتاح عن قصد: نزيل بيعدّل حجزه مرتين بيبعت
    # ‎MODIFY مرتين بتواريخ مختلفة، والتانية دي حدث حقيقي مش إعادة إرسال.
    incoming_from = _as_date(payload.get("arrival_date"))
    incoming_to = _as_date(payload.get("departure_date"))
    seen = db.execute(
        select(ChannelBooking).where(
            ChannelBooking.channel_id == channel.id,
            ChannelBooking.external_reference == reference,
            ChannelBooking.action == action,
            ChannelBooking.status == ChannelBookingStatus.PROCESSED,
            ChannelBooking.arrival_date.is_(None)
            if incoming_from is None
            else ChannelBooking.arrival_date == incoming_from,
            ChannelBooking.departure_date.is_(None)
            if incoming_to is None
            else ChannelBooking.departure_date == incoming_to,
        ).limit(1)
    ).scalar_one_or_none()
    if seen is not None:
        return _record(
            db,
            channel=channel,
            payload=payload,
            action=action,
            status=ChannelBookingStatus.DUPLICATE,
            reservation_id=seen.reservation_id,
            error="وصل قبل كده",
        )

    existing = db.execute(
        select(Reservation).where(
            Reservation.property_id == property_id,
            Reservation.external_reference == reference,
        ).limit(1)
    ).scalar_one_or_none()

    # ── إلغاء
    if action == ChannelBookingAction.CANCEL:
        if existing is None:
            return _record(
                db, channel=channel, payload=payload, action=action,
                status=ChannelBookingStatus.REJECTED,
                error="مفيش حجز بالرقم ده عندنا",
            )
        if existing.status in (ReservationStatus.CANCELLED, ReservationStatus.CHECKED_OUT):
            return _record(
                db, channel=channel, payload=payload, action=action,
                status=ChannelBookingStatus.DUPLICATE, reservation_id=existing.id,
                error="الحجز متقفل بالفعل",
            )
        # غرامة الإلغاء بتمشي بسياسة القناة مش بسياستنا
        res_svc.cancel(db, existing.id, reason="إلغاء من القناة", charge_penalty=False)
        return _record(
            db, channel=channel, payload=payload, action=action,
            status=ChannelBookingStatus.PROCESSED, reservation_id=existing.id,
        )

    # ── تعديل
    if action == ChannelBookingAction.MODIFY:
        if existing is None:
            return _record(
                db, channel=channel, payload=payload, action=action,
                status=ChannelBookingStatus.REJECTED,
                error="مفيش حجز بالرقم ده عندنا",
            )
        arrival = _as_date(payload.get("arrival_date"))
        departure = _as_date(payload.get("departure_date"))
        line = db.execute(
            select(ReservationUnit).where(ReservationUnit.reservation_id == existing.id).limit(1)
        ).scalar_one_or_none()
        if line is None:
            return _record(
                db, channel=channel, payload=payload, action=action,
                status=ChannelBookingStatus.FAILED, reservation_id=existing.id,
                error="الحجز من غير سطور",
            )
        try:
            res_svc.move_reservation_unit(
                db, line.id, arrival=arrival, departure=departure
            )
        except (res_svc.ReservationError, AvailabilityError, PricingError) as exc:
            # الحجز بيفضل زي ما هو — أأمن من إننا نلغيه ونفشل في إعادة حجزه
            return _record(
                db, channel=channel, payload=payload, action=action,
                status=ChannelBookingStatus.REJECTED, reservation_id=existing.id,
                error=getattr(exc, "message_ar", str(exc))[:500],
            )
        db.refresh(existing)
        return _record(
            db, channel=channel, payload=payload, action=action,
            status=ChannelBookingStatus.PROCESSED, reservation_id=existing.id,
            gross=existing.grand_total, commission=existing.channel_commission_amount,
        )

    # ── حجز جديد
    if existing is not None:
        return _record(
            db, channel=channel, payload=payload, action=action,
            status=ChannelBookingStatus.DUPLICATE, reservation_id=existing.id,
            error="الرقم المرجعي ده متسجّل على حجز قايم",
        )

    room_id = str(payload.get("external_room_id") or "").strip()
    mapping = db.execute(
        select(ChannelMapping).where(
            ChannelMapping.channel_id == channel.id,
            ChannelMapping.external_room_id == room_id,
            ChannelMapping.is_active.is_(True),
        ).limit(1)
    ).scalar_one_or_none()
    if mapping is None:
        return _record(
            db, channel=channel, payload=payload, action=action,
            status=ChannelBookingStatus.REJECTED,
            error=f"الغرفة «{room_id}» مش مربوطة على القناة",
        )

    arrival = _as_date(payload.get("arrival_date"))
    departure = _as_date(payload.get("departure_date"))
    if arrival is None or departure is None or departure <= arrival:
        return _record(
            db, channel=channel, payload=payload, action=action,
            status=ChannelBookingStatus.REJECTED, error="تواريخ غير صحيحة",
        )

    guest = _find_guest(db, property_id, payload.get("guest") or {})

    try:
        reservation = res_svc.create_reservation(
            db,
            property_id=property_id,
            guest_id=guest.id,
            unit_category_id=mapping.unit_category_id,
            rate_plan_id=mapping.rate_plan_id
            or _default_plan(db, property_id),
            arrival=arrival,
            departure=departure,
            adults=int(payload.get("adults") or 2),
            children=int(payload.get("children") or 0),
            source=channel.source,
            external_reference=reference,
            special_requests=payload.get("notes"),
            status=ReservationStatus.CONFIRMED,
        )
    except AvailabilityError as exc:
        # الحالة اللي حد التجاوز موجود عشانها: القناة باعت حجز ومفيش مكان
        return _record(
            db, channel=channel, payload=payload, action=action,
            status=ChannelBookingStatus.REJECTED, error=exc.message_ar[:500],
        )
    except (res_svc.ReservationError, PricingError) as exc:
        return _record(
            db, channel=channel, payload=payload, action=action,
            status=ChannelBookingStatus.REJECTED,
            error=getattr(exc, "message_ar", str(exc))[:500],
        )

    return _record(
        db, channel=channel, payload=payload, action=action,
        status=ChannelBookingStatus.PROCESSED, reservation_id=reservation.id,
        gross=reservation.grand_total, commission=reservation.channel_commission_amount,
    )


def _default_plan(db: Session, property_id: int) -> int:
    from app.models.rates import RatePlan

    plan_id = db.execute(
        select(RatePlan.id)
        .where(RatePlan.property_id == property_id, RatePlan.is_active.is_(True))
        .order_by(RatePlan.sort_order)
        .limit(1)
    ).scalar_one_or_none()
    if plan_id is None:
        raise ChannelError("مفيش خطة أسعار معرّفة", "No rate plan configured", "no_rate_plan")
    return plan_id


# ═══════════════════════════════════════════════════════ الحالة
@dataclass(slots=True)
class ChannelHealth:
    channel: Channel
    pending: int
    failed: int
    sent_today: int
    mapped_categories: int
    bookings_today: int
    rejected_today: int


def health(db: Session, property_id: int) -> list[ChannelHealth]:
    """صحة كل قناة — ده اللي بيتعرض في الشاشة."""
    channels = list(
        db.execute(
            select(Channel)
            .where(Channel.property_id == property_id)
            .order_by(Channel.id)
        ).scalars().all()
    )
    if not channels:
        return []

    ids = [c.id for c in channels]
    since = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)

    def counts(stmt) -> dict[int, int]:
        return {row[0]: int(row[1]) for row in db.execute(stmt).all()}

    pending = counts(
        select(ChannelMessage.channel_id, func.count(ChannelMessage.id))
        .where(
            ChannelMessage.channel_id.in_(ids),
            ChannelMessage.status == ChannelMessageStatus.PENDING,
        )
        .group_by(ChannelMessage.channel_id)
    )
    failed = counts(
        select(ChannelMessage.channel_id, func.count(ChannelMessage.id))
        .where(
            ChannelMessage.channel_id.in_(ids),
            ChannelMessage.status.in_(
                [ChannelMessageStatus.FAILED, ChannelMessageStatus.SKIPPED]
            ),
        )
        .group_by(ChannelMessage.channel_id)
    )
    sent_today = counts(
        select(ChannelMessage.channel_id, func.count(ChannelMessage.id))
        .where(
            ChannelMessage.channel_id.in_(ids),
            ChannelMessage.status == ChannelMessageStatus.SENT,
            ChannelMessage.sent_at >= since,
        )
        .group_by(ChannelMessage.channel_id)
    )
    mapped = counts(
        select(ChannelMapping.channel_id, func.count(ChannelMapping.id))
        .where(ChannelMapping.channel_id.in_(ids), ChannelMapping.is_active.is_(True))
        .group_by(ChannelMapping.channel_id)
    )
    arrived = counts(
        select(ChannelBooking.channel_id, func.count(ChannelBooking.id))
        .where(ChannelBooking.channel_id.in_(ids), ChannelBooking.received_at >= since)
        .group_by(ChannelBooking.channel_id)
    )
    rejected = counts(
        select(ChannelBooking.channel_id, func.count(ChannelBooking.id))
        .where(
            ChannelBooking.channel_id.in_(ids),
            ChannelBooking.received_at >= since,
            ChannelBooking.status.in_(
                [ChannelBookingStatus.REJECTED, ChannelBookingStatus.FAILED]
            ),
        )
        .group_by(ChannelBooking.channel_id)
    )

    return [
        ChannelHealth(
            channel=c,
            pending=pending.get(c.id, 0),
            failed=failed.get(c.id, 0),
            sent_today=sent_today.get(c.id, 0),
            mapped_categories=mapped.get(c.id, 0),
            bookings_today=arrived.get(c.id, 0),
            rejected_today=rejected.get(c.id, 0),
        )
        for c in channels
    ]
