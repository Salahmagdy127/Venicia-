/** التقارير — اليومية التفصيلية والمصادر والمنافذ، من نفس الملخّصات اليومية. */

import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { get, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatDate, formatRange, money, parseDate, weekdayName } from "@/lib/format";
import type { DashboardData } from "@/lib/types";
import PageHeader from "@/components/PageHeader";
import NightAudit from "@/components/NightAudit";
import { Card, ErrorState, Loading, cx } from "@/components/ui";

const PERIODS = ["week", "month", "quarter", "year"] as const;

export default function Reports() {
  const { t, locale } = useI18n();
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("month");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["dashboard", period],
    queryFn: () => get<DashboardData>(`/dashboard${qs({ period })}`),
    placeholderData: keepPreviousData,
  });

  const cur = locale === "ar" ? "ج.م" : "EGP";

  const totals = data?.trend.reduce(
    (acc, p) => ({
      revenue: acc.revenue + Number(p.revenue),
      room: acc.room + Number(p.room_revenue),
    }),
    { revenue: 0, room: 0 },
  ) ?? { revenue: 0, room: 0 };

  return (
    <>
      <PageHeader
        title={t("rep.title")}
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
          <div className="flex flex-col gap-4 max-w-[1400px]">
            {/* التقفيل اليومي — أول حاجة لأنه إجراء بيتعمل كل يوم */}
            <NightAudit />

            <Card title={t("rep.daily")} padded={false}>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[13px]">
                  <thead className="sticky top-0 bg-surface">
                    <tr className="text-muted text-[12px]">
                      <th className="text-start font-bold px-5 py-2.5 border-b border-line">
                        {t("rep.date")}
                      </th>
                      <th className="text-end font-bold px-3 py-2.5 border-b border-line">
                        {t("dash.occupancy")}
                      </th>
                      <th className="text-end font-bold px-3 py-2.5 border-b border-line">ADR</th>
                      <th className="text-end font-bold px-3 py-2.5 border-b border-line">
                        RevPAR
                      </th>
                      <th className="text-end font-bold px-3 py-2.5 border-b border-line">
                        {t("rep.roomRevenue")}
                      </th>
                      <th className="text-end font-bold px-3 py-2.5 border-b border-line">
                        {t("rep.otherRevenue")}
                      </th>
                      <th className="text-end font-bold px-5 py-2.5 border-b border-line">
                        {t("rep.total")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trend.map((p) => {
                      const d = parseDate(p.date);
                      const weekend = [4, 5].includes((d.getDay() + 6) % 7);
                      const other = Number(p.revenue) - Number(p.room_revenue);
                      const occ = Number(p.occupancy_percent);
                      return (
                        <tr key={p.date} className={cx(weekend && "bg-surface-2/45")}>
                          <td className="px-5 py-2 border-b border-line">
                            <span className="num font-bold">{formatDate(p.date, locale)}</span>
                            <span className="text-[11.5px] text-muted ms-2">
                              {weekdayName(d, locale)}
                            </span>
                          </td>
                          <td
                            className={cx(
                              "num text-end px-3 py-2 border-b border-line font-bold",
                              occ >= 90 ? "text-good" : occ < 50 ? "text-warn" : "",
                            )}
                          >
                            {occ.toFixed(1)}%
                          </td>
                          <td className="num text-end px-3 py-2 border-b border-line">
                            {money(p.adr, 0)}
                          </td>
                          <td className="num text-end px-3 py-2 border-b border-line">
                            {money(p.revpar, 0)}
                          </td>
                          <td className="num text-end px-3 py-2 border-b border-line">
                            {money(p.room_revenue, 0)}
                          </td>
                          <td className="num text-end px-3 py-2 border-b border-line text-ink-2">
                            {money(other, 0)}
                          </td>
                          <td className="num text-end px-5 py-2 border-b border-line font-bold">
                            {money(p.revenue, 0)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="bg-surface-2">
                      <td className="px-5 py-2.5 font-bold">{t("rep.total")}</td>
                      <td />
                      <td />
                      <td />
                      <td className="num text-end px-3 py-2.5 font-bold">
                        {money(totals.room, 0)}
                      </td>
                      <td className="num text-end px-3 py-2.5 font-bold">
                        {money(totals.revenue - totals.room, 0)}
                      </td>
                      <td className="num text-end px-5 py-2.5 font-bold text-accent">
                        {money(totals.revenue, 0)} <span className="text-[11px]">{cur}</span>
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </Card>

            <div className="grid gap-4 grid-cols-1 xl:grid-cols-2">
              <Card title={t("dash.bySource")} padded={false}>
                <table className="w-full border-collapse text-[13px]">
                  <tbody>
                    {data.by_source.map((s) => (
                      <tr key={s.source}>
                        <td className="px-5 py-2 border-b border-line">
                          {t(`source.${s.source}`, s.label_ar)}
                        </td>
                        <td className="num text-end px-3 py-2 border-b border-line font-bold">
                          {money(s.revenue, 0)}
                        </td>
                        <td className="num text-end px-5 py-2 border-b border-line text-muted w-[70px]">
                          {s.share_percent}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>

              <Card title={t("dash.byOutlet")} padded={false}>
                <table className="w-full border-collapse text-[13px]">
                  <tbody>
                    {data.by_outlet.map((o) => (
                      <tr key={o.outlet_id}>
                        <td className="px-5 py-2 border-b border-line">
                          {locale === "ar" ? o.name_ar : o.name_en}
                        </td>
                        <td className="num text-end px-3 py-2 border-b border-line text-muted">
                          {o.orders}
                        </td>
                        <td className="num text-end px-3 py-2 border-b border-line font-bold">
                          {money(o.net_sales, 0)}
                        </td>
                        <td className="num text-end px-5 py-2 border-b border-line text-muted w-[70px]">
                          {o.share_percent}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
