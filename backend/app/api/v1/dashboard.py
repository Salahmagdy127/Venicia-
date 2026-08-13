"""داشبورد المالك — Owner dashboard.

بيقرا من جداول الملخّص اليومية بس. مفيش تجميع لحظي على الحركات، فالسرعة
ثابتة مهما كبرت البيانات.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentProperty, CurrentUser, DbSession
from app.models.analytics import DailyOutletStatistics, DailyStatistics
from app.models.folio import Folio
from app.models.enums import FolioStatus
from app.models.pos import Outlet
from app.schemas.common import ApiModel

router = APIRouter(prefix="/dashboard", tags=["الداشبورد — Dashboard"])

PERIODS = {"today": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}


class Kpi(ApiModel):
    key: str
    label_ar: str
    label_en: str
    value: Decimal
    unit: str                       # percent | money | count
    change_percent: float | None = None
    is_money: bool = False


class TrendPoint(ApiModel):
    date: date
    revenue: Decimal
    room_revenue: Decimal
    occupancy_percent: Decimal
    adr: Decimal
    revpar: Decimal


class SourceSlice(ApiModel):
    source: str
    label_ar: str
    bookings: int
    revenue: Decimal
    commission: Decimal
    share_percent: float


class OutletSlice(ApiModel):
    outlet_id: int
    name_ar: str
    name_en: str
    net_sales: Decimal
    orders: int
    covers: int
    average_check: Decimal
    cost_of_sales: Decimal
    void_count: int
    void_after_send_count: int
    share_percent: float


class Alert(ApiModel):
    severity: str                   # warning | critical
    message_ar: str
    message_en: str
    value: str | None = None


class CommissionBox(ApiModel):
    """الصندوق اللي بيبيع النظام — العمولة اللي المالك دفعها."""

    total_commission: Decimal
    ota_bookings: int
    direct_bookings: int
    direct_share_percent: float
    #: التوفير لو نص حجوزات القنوات بقت مباشرة
    potential_saving: Decimal


class DashboardOut(ApiModel):
    period: str
    start_date: date
    end_date: date
    kpis: list[Kpi]
    trend: list[TrendPoint]
    by_source: list[SourceSlice]
    by_outlet: list[OutletSlice]
    commission: CommissionBox
    alerts: list[Alert]


SOURCE_LABELS = {
    "BOOKING_COM": "بوكينج", "AGODA": "أجودا", "EXPEDIA": "إكسبيديا",
    "AIRBNB": "إير بي إن بي", "WEBSITE": "الموقع المباشر", "DIRECT": "حجز مباشر",
    "WALK_IN": "حضور بدون حجز", "TRAVEL_AGENT": "وكيل سفر",
    "CORPORATE": "عقد شركات", "POS": "نقاط البيع",
}


def _pct_change(current: Decimal, previous: Decimal) -> float | None:
    if not previous:
        return None
    return round(float((current - previous) / previous * 100), 1)


@router.get("", response_model=DashboardOut, summary="داشبورد المالك")
def get_dashboard(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    period: str = Query(default="month", pattern="^(today|week|month|quarter|year)$"),
    as_of: date | None = Query(default=None, description="آخر يوم — افتراضياً النهاردة"),
) -> DashboardOut:
    end_date = as_of or date.today()
    span = PERIODS[period]
    start_date = end_date - timedelta(days=span - 1)
    prev_start = start_date - timedelta(days=span)
    prev_end = start_date - timedelta(days=1)

    stats = list(
        db.execute(
            select(DailyStatistics)
            .where(
                DailyStatistics.property_id == prop.id,
                DailyStatistics.business_date >= start_date,
                DailyStatistics.business_date <= end_date,
            )
            .order_by(DailyStatistics.business_date)
        ).scalars().all()
    )

    prev = db.execute(
        select(
            func.sum(DailyStatistics.total_revenue),
            func.sum(DailyStatistics.room_revenue),
            func.sum(DailyStatistics.sold_units),
            func.avg(DailyStatistics.occupancy_percent),
            func.avg(DailyStatistics.adr),
            func.avg(DailyStatistics.average_check),
        ).where(
            DailyStatistics.property_id == prop.id,
            DailyStatistics.business_date >= prev_start,
            DailyStatistics.business_date <= prev_end,
        )
    ).one()

    days = len(stats) or 1
    total_revenue = sum((s.total_revenue for s in stats), Decimal("0"))
    room_revenue = sum((s.room_revenue for s in stats), Decimal("0"))
    sold_units = sum(s.sold_units for s in stats)
    available_units = sum(s.total_units - s.out_of_order_units for s in stats) or 1
    occupancy = Decimal(sold_units) / available_units * 100
    adr = room_revenue / sold_units if sold_units else Decimal("0")
    revpar = room_revenue / available_units
    covers = sum(s.covers for s in stats)
    avg_check = (
        sum((s.average_check * s.covers for s in stats), Decimal("0")) / covers
        if covers else Decimal("0")
    )
    commission_total = sum((s.ota_commission_total for s in stats), Decimal("0"))
    ota_bookings = sum(s.ota_bookings for s in stats)
    direct_bookings = sum(s.direct_bookings for s in stats)

    def rnd(value: Decimal) -> Decimal:
        return Decimal(value).quantize(Decimal("0.01"))

    kpis = [
        Kpi(key="occupancy", label_ar="الإشغال", label_en="Occupancy",
            value=rnd(occupancy), unit="percent",
            change_percent=_pct_change(occupancy, Decimal(prev[3] or 0))),
        Kpi(key="adr", label_ar="متوسط سعر الليلة", label_en="ADR",
            value=rnd(adr), unit="money", is_money=True,
            change_percent=_pct_change(adr, Decimal(prev[4] or 0))),
        Kpi(key="revpar", label_ar="إيراد الوحدة المتاحة", label_en="RevPAR",
            value=rnd(revpar), unit="money", is_money=True),
        Kpi(key="revenue", label_ar="إجمالي الإيراد", label_en="Total Revenue",
            value=rnd(total_revenue), unit="money", is_money=True,
            change_percent=_pct_change(total_revenue, Decimal(prev[0] or 0))),
        Kpi(key="avg_check", label_ar="متوسط الفاتورة", label_en="Average Check",
            value=rnd(avg_check), unit="money", is_money=True,
            change_percent=_pct_change(avg_check, Decimal(prev[5] or 0))),
    ]

    trend = [
        TrendPoint(
            date=s.business_date,
            revenue=s.total_revenue,
            room_revenue=s.room_revenue,
            occupancy_percent=s.occupancy_percent,
            adr=s.adr,
            revpar=s.revpar,
        )
        for s in stats
    ]

    # ── توزيع مصادر الحجز ───────────────────────────────────────────
    source_revenue: dict[str, Decimal] = defaultdict(Decimal)
    for s in stats:
        for source, amount in (s.revenue_by_source or {}).items():
            source_revenue[source] += Decimal(str(amount))
    grand = sum(source_revenue.values()) or Decimal("1")

    by_source = sorted(
        (
            SourceSlice(
                source=source,
                label_ar=SOURCE_LABELS.get(source, source),
                bookings=0,
                revenue=rnd(amount),
                commission=Decimal("0"),
                share_percent=round(float(amount / grand * 100), 1),
            )
            for source, amount in source_revenue.items()
        ),
        key=lambda x: x.revenue,
        reverse=True,
    )

    # ── منافذ البيع ─────────────────────────────────────────────────
    outlet_rows = db.execute(
        select(
            DailyOutletStatistics.outlet_id,
            func.sum(DailyOutletStatistics.net_sales),
            func.sum(DailyOutletStatistics.orders_count),
            func.sum(DailyOutletStatistics.covers),
            func.sum(DailyOutletStatistics.cost_of_sales),
            func.sum(DailyOutletStatistics.void_count),
            func.sum(DailyOutletStatistics.void_after_send_count),
        )
        .where(
            DailyOutletStatistics.property_id == prop.id,
            DailyOutletStatistics.business_date >= start_date,
            DailyOutletStatistics.business_date <= end_date,
        )
        .group_by(DailyOutletStatistics.outlet_id)
    ).all()

    outlets = {
        o.id: o
        for o in db.execute(select(Outlet).where(Outlet.property_id == prop.id))
        .scalars().all()
    }
    outlet_total = sum((Decimal(r[1] or 0) for r in outlet_rows), Decimal("0")) or Decimal("1")

    by_outlet = sorted(
        (
            OutletSlice(
                outlet_id=row[0],
                name_ar=outlets[row[0]].name_ar if row[0] in outlets else "—",
                name_en=outlets[row[0]].name_en if row[0] in outlets else "—",
                net_sales=rnd(Decimal(row[1] or 0)),
                orders=int(row[2] or 0),
                covers=int(row[3] or 0),
                average_check=rnd(Decimal(row[1] or 0) / int(row[2])) if row[2] else Decimal("0"),
                cost_of_sales=rnd(Decimal(row[4] or 0)),
                void_count=int(row[5] or 0),
                void_after_send_count=int(row[6] or 0),
                share_percent=round(float(Decimal(row[1] or 0) / outlet_total * 100), 1),
            )
            for row in outlet_rows
        ),
        key=lambda x: x.net_sales,
        reverse=True,
    )

    # ── التنبيهات ───────────────────────────────────────────────────
    alerts: list[Alert] = []

    stale_folios = db.execute(
        select(func.count(Folio.id)).where(
            Folio.property_id == prop.id,
            Folio.status == FolioStatus.OPEN,
            Folio.opened_at < func.date(end_date - timedelta(days=1)),
        )
    ).scalar() or 0

    voids_after_send = sum(o.void_after_send_count for o in by_outlet)
    if voids_after_send:
        alerts.append(
            Alert(
                severity="critical",
                message_ar="أصناف اتلغت بعد ما راحت المطبخ",
                message_en="Items voided after being sent to the kitchen",
                value=str(voids_after_send),
            )
        )

    no_shows = sum(s.no_shows for s in stats)
    if no_shows:
        alerts.append(
            Alert(
                severity="warning",
                message_ar="حجوزات لم يحضر أصحابها في الفترة",
                message_en="No-shows in the period",
                value=str(no_shows),
            )
        )

    if commission_total > 0:
        alerts.append(
            Alert(
                severity="warning",
                message_ar="عمولات قنوات مدفوعة في الفترة",
                message_en="Channel commissions paid in the period",
                value=f"{commission_total:,.0f} ج.م",
            )
        )

    total_bookings = ota_bookings + direct_bookings
    return DashboardOut(
        period=period,
        start_date=start_date,
        end_date=end_date,
        kpis=kpis,
        trend=trend,
        by_source=by_source,
        by_outlet=by_outlet,
        commission=CommissionBox(
            total_commission=rnd(commission_total),
            ota_bookings=ota_bookings,
            direct_bookings=direct_bookings,
            direct_share_percent=(
                round(direct_bookings / total_bookings * 100, 1) if total_bookings else 0.0
            ),
            potential_saving=rnd(commission_total / 2),
        ),
        alerts=alerts,
    )
