/** داشبورد المالك — بيقرا من الملخّصات اليومية، فالفتح فوري مهما كبرت الداتا. */

import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { get, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { compact, formatRange, money, percent } from "@/lib/format";
import type { DashboardData } from "@/lib/types";
import PageHeader from "@/components/PageHeader";
import { BarList, ComboChart } from "@/components/Chart";
import { Card, ErrorState, Loading, StatTile, cx } from "@/components/ui";
import { IconWarning } from "@/components/Icons";

const PERIODS = ["today", "week", "month", "quarter", "year"] as const;

export default function Dashboard() {
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("month");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["dashboard", period],
    queryFn: () => get<DashboardData>(`/dashboard${qs({ period })}`),
    placeholderData: keepPreviousData,
  });

  const name = locale === "ar" ? user?.full_name_ar : user?.full_name_en;

  return (
    <>
      <PageHeader
        title={`${t("dash.greeting")} ${name ?? ""}`}
        subtitle={data ? formatRange(data.start_date, data.end_date, locale) : "—"}
      >
        <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cx(
                "h-9 px-3 text-[13px] font-bold border-e border-line-strong last:border-e-0",
                period === p ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
              )}
            >
              {t(`dash.period.${p}`)}
            </button>
          ))}
        </div>
      </PageHeader>

      <div className="flex-1 min-h-0 overflow-y-auto p-5">
        {isLoading && <Loading />}
        {isError && <ErrorState onRetry={() => refetch()} />}

        {data && (
          <div className="flex flex-col gap-4 max-w-[1500px]">
            {/* ── المؤشرات */}
            <div className="grid gap-4 grid-cols-2 lg:grid-cols-5">
              {data.kpis.map((k) => (
                <StatTile
                  key={k.key}
                  label={locale === "ar" ? k.label_ar : k.label_en}
                  value={
                    k.unit === "percent"
                      ? percent(k.value)
                      : k.is_money
                        ? money(k.value, 0)
                        : money(k.value, 0)
                  }
                  suffix={k.is_money ? (locale === "ar" ? "ج.م" : "EGP") : undefined}
                  change={k.change_percent}
                  tone={k.key === "revenue" ? "accent" : "ink"}
                />
              ))}
            </div>

            {/* ── الرسم + صندوق العمولة */}
            <div className="grid gap-4 grid-cols-1 xl:grid-cols-3">
              <Card className="xl:col-span-2" title={t("dash.revenueTrend")}>
                <ComboChart
                  barLabel={t("dash.revenue")}
                  lineLabel={t("dash.occupancy")}
                  points={data.trend.map((p) => ({
                    date: p.date,
                    bar: Number(p.revenue),
                    line: Number(p.occupancy_percent),
                  }))}
                />
              </Card>

              <CommissionCard data={data} />
            </div>

            {/* ── المصادر + المنافذ */}
            <div className="grid gap-4 grid-cols-1 xl:grid-cols-3">
              <Card title={t("dash.bySource")}>
                <BarList
                  rows={data.by_source.map((s) => ({
                    key: s.source,
                    label: t(`source.${s.source}`, s.label_ar),
                    value: money(s.revenue, 0),
                    percent: s.share_percent,
                  }))}
                />
              </Card>

              <Card className="xl:col-span-2" title={t("dash.byOutlet")} padded={false}>
                <OutletTable data={data} />
              </Card>
            </div>

            {/* ── التنبيهات */}
            <Card title={t("dash.alerts")}>
              {data.alerts.length === 0 ? (
                <span className="text-[13.5px] text-muted">{t("dash.noAlerts")}</span>
              ) : (
                <ul className="flex flex-col gap-2 m-0 p-0 list-none">
                  {data.alerts.map((a, i) => (
                    <li
                      key={i}
                      className={cx(
                        "flex items-center gap-2.5 rounded-[6px] border px-3.5 py-2.5",
                        a.severity === "critical"
                          ? "border-bad/40 bg-bad/8"
                          : "border-warn/40 bg-warn/8",
                      )}
                    >
                      <IconWarning
                        size={16}
                        className={a.severity === "critical" ? "text-bad" : "text-warn"}
                      />
                      <span className="text-[13.5px] text-ink flex-1">
                        {locale === "ar" ? a.message_ar : a.message_en}
                      </span>
                      {a.value && <span className="num text-[13.5px] font-bold">{a.value}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        )}
      </div>
    </>
  );
}

/* ═══════════════════════════════════ صندوق العمولة — أهم رقم للمالك */
function CommissionCard({ data }: { data: DashboardData }) {
  const { t, locale } = useI18n();
  const c = data.commission;
  const cur = locale === "ar" ? "ج.م" : "EGP";
  const total = c.ota_bookings + c.direct_bookings;

  return (
    <section className="bg-surface border border-gold/45 rounded-[8px] flex flex-col">
      <header className="px-5 py-3 border-b border-line">
        <h2 className="text-[15px] font-bold text-gold">{t("dash.commission")}</h2>
      </header>

      <div className="p-5 flex flex-col gap-4 flex-1">
        <div>
          <div className="text-[12.5px] text-muted font-bold mb-1">{t("dash.commissionPaid")}</div>
          <div className="num text-[38px] font-bold leading-none text-gold">
            {money(c.total_commission, 0)}
            <span className="text-[16px] opacity-70"> {cur}</span>
          </div>
          <p className="text-[12.5px] text-muted mt-1.5 leading-relaxed">
            {t("dash.commissionNote")}
          </p>
        </div>

        <div className="rounded-[6px] bg-gold-soft px-3.5 py-3">
          <div className="text-[12.5px] text-gold font-bold">{t("dash.commissionSaving")}</div>
          <div className="num text-[22px] font-bold text-gold leading-tight">
            {money(c.potential_saving, 0)} <span className="text-[13px] opacity-70">{cur}</span>
          </div>
        </div>

        {/* شريط توزيع القنوات مقابل المباشر */}
        <div className="mt-auto">
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="text-[12.5px] text-muted font-bold">{t("dash.directShare")}</span>
            <span className="num text-[14px] font-bold">{c.direct_share_percent}%</span>
          </div>
          <div className="h-2.5 rounded-full overflow-hidden bg-gold flex" dir="ltr">
            <div
              className="h-full bg-accent"
              style={{ width: `${c.direct_share_percent}%` }}
              title={t("dash.directBookings")}
            />
          </div>
          <div className="flex items-center justify-between mt-1.5 text-[11.5px]">
            <span className="flex items-center gap-1.5 text-ink-2">
              <span className="w-2.5 h-2.5 rounded-[2px] bg-accent" />
              {t("dash.directBookings")} <span className="num">{c.direct_bookings}</span>
            </span>
            <span className="flex items-center gap-1.5 text-ink-2">
              <span className="w-2.5 h-2.5 rounded-[2px] bg-gold" />
              {t("dash.otaBookings")} <span className="num">{c.ota_bookings}</span>
            </span>
          </div>
          <div className="text-[11.5px] text-muted mt-1 num">
            {total} {locale === "ar" ? "حجز في الفترة" : "bookings this period"}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════ جدول منافذ البيع */
function OutletTable({ data }: { data: DashboardData }) {
  const { t, locale } = useI18n();
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-muted text-[12px]">
            <th className="text-start font-bold px-5 py-2.5 border-b border-line">
              {t("dash.outlet")}
            </th>
            <th className="text-end font-bold px-3 py-2.5 border-b border-line">
              {t("dash.netSales")}
            </th>
            <th className="text-end font-bold px-3 py-2.5 border-b border-line">
              {t("dash.orders")}
            </th>
            <th className="text-end font-bold px-3 py-2.5 border-b border-line">
              {t("dash.covers")}
            </th>
            <th className="text-end font-bold px-3 py-2.5 border-b border-line">
              {t("dash.avgCheck")}
            </th>
            <th className="text-end font-bold px-3 py-2.5 border-b border-line">
              {t("dash.margin")}
            </th>
            <th className="text-end font-bold px-5 py-2.5 border-b border-line">
              {t("dash.voids")}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.by_outlet.map((o) => {
            const sales = Number(o.net_sales);
            const margin = sales > 0 ? ((sales - Number(o.cost_of_sales)) / sales) * 100 : 0;
            return (
              <tr key={o.outlet_id} className="hover:bg-surface-2/60">
                <td className="px-5 py-2.5 border-b border-line font-bold">
                  {locale === "ar" ? o.name_ar : o.name_en}
                </td>
                <td className="num text-end px-3 py-2.5 border-b border-line font-bold">
                  {money(o.net_sales, 0)}
                </td>
                <td className="num text-end px-3 py-2.5 border-b border-line text-ink-2">
                  {compact(o.orders)}
                </td>
                <td className="num text-end px-3 py-2.5 border-b border-line text-ink-2">
                  {compact(o.covers)}
                </td>
                <td className="num text-end px-3 py-2.5 border-b border-line">
                  {money(o.average_check)}
                </td>
                <td
                  className={cx(
                    "num text-end px-3 py-2.5 border-b border-line font-bold",
                    margin >= 60 ? "text-good" : margin >= 45 ? "text-ink" : "text-warn",
                  )}
                >
                  {margin.toFixed(1)}%
                </td>
                <td
                  className={cx(
                    "num text-end px-5 py-2.5 border-b border-line font-bold",
                    o.void_after_send_count > 0 ? "text-bad" : "text-muted",
                  )}
                >
                  {o.void_after_send_count}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
