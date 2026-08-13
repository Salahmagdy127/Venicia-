/** تقفيل اليوم — معاينة قبل التنفيذ، تنفيذ، وسجل التقفيلات السابقة. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { addDays, formatDate, formatTime, money, toISO } from "@/lib/format";
import type { AuditPreview, AuditWarnings, NightAuditRun } from "@/lib/types";
import { Button, Card, Loading, cx } from "./ui";
import { IconCheck, IconWarning } from "./Icons";

export default function NightAudit() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  // الافتراضي: امبارح — اليوم اللي خلص فعلاً
  const [day, setDay] = useState(() => toISO(addDays(new Date(), -1)));
  const [result, setResult] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const preview = useQuery({
    queryKey: ["night-audit", "preview", day],
    queryFn: () => get<AuditPreview>(`/night-audit/preview${qs({ business_date: day })}`),
  });

  const history = useQuery({
    queryKey: ["night-audit", "history"],
    queryFn: () => get<NightAuditRun[]>("/night-audit?limit=14"),
  });

  const run = useMutation({
    mutationFn: (force: boolean) =>
      post<NightAuditRun>("/night-audit/run", { business_date: day, force }),
    onSuccess: (r) => {
      setResult({
        tone: "good",
        text: `${t("na.done")} — ${t("na.nightsPosted")} ${r.nights_posted} · ${t("na.noShows")} ${r.no_shows_marked}`,
      });
      qc.invalidateQueries({ queryKey: ["night-audit"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err) =>
      setResult({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      }),
  });

  const p = preview.data;
  const canRun = can("nightaudit.run");

  return (
    <div className="grid gap-4 grid-cols-1 xl:grid-cols-3">
      {/* ── المعاينة والتنفيذ */}
      <Card className="xl:col-span-1" title={t("na.title")}>
        <p className="text-[12.5px] text-muted leading-relaxed mb-4">{t("na.subtitle")}</p>

        <label className="flex flex-col gap-1.5 mb-4">
          <span className="text-[12.5px] font-bold text-ink-2">{t("na.businessDate")}</span>
          <input
            type="date"
            className="num h-10 px-3 rounded-[6px] bg-surface border border-line-strong text-ink outline-none focus:border-accent"
            value={day}
            max={toISO(new Date())}
            onChange={(e) => {
              if (e.target.value) setDay(e.target.value);
              setResult(null);
            }}
          />
        </label>

        {preview.isLoading && <Loading />}

        {p && (
          <>
            <div
              className={cx(
                "rounded-[6px] px-3.5 py-2.5 text-[13px] font-bold mb-4 flex items-center gap-2",
                p.already_done
                  ? "bg-good/12 text-good"
                  : "bg-warn/12 text-warn",
              )}
            >
              {p.already_done ? <IconCheck size={15} /> : <IconWarning size={15} />}
              {p.already_done ? t("na.done") : t("na.pending")} ·{" "}
              <span className="num">{formatDate(p.business_date, locale)}</span>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-4">
              <Tile label={t("na.willPost")} value={p.pending_nights} tone="accent" />
              <Tile
                label={t("na.willNoShow")}
                value={p.pending_no_shows}
                tone={p.pending_no_shows > 0 ? "warn" : "ink"}
              />
            </div>

            <Warnings warnings={p.warnings} />

            {p.already_done && (
              <p className="text-[11.5px] text-muted leading-relaxed mt-3">
                {t("na.rerunHint")}
              </p>
            )}

            {result && (
              <div
                className={cx(
                  "mt-4 rounded-[6px] px-3.5 py-2.5 text-[13px] border",
                  result.tone === "good"
                    ? "border-good/40 bg-good/10 text-good"
                    : "border-bad/40 bg-bad/10 text-bad",
                )}
              >
                {result.text}
              </div>
            )}

            {canRun && (
              <Button
                variant={p.already_done ? "secondary" : "primary"}
                className="w-full mt-4"
                size="lg"
                disabled={run.isPending}
                onClick={() => run.mutate(p.already_done)}
              >
                {run.isPending ? "…" : p.already_done ? t("na.rerun") : t("na.run")}
              </Button>
            )}
          </>
        )}
      </Card>

      {/* ── السجل */}
      <Card className="xl:col-span-2" title={t("na.history")} padded={false}>
        {history.isLoading && <Loading />}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-muted text-[12px]">
                <Th className="text-start ps-5">{t("na.businessDate")}</Th>
                <Th className="text-start">{t("res.status")}</Th>
                <Th className="text-end">{t("na.nightsPosted")}</Th>
                <Th className="text-end">{t("na.revenuePosted")}</Th>
                <Th className="text-end">{t("na.noShows")}</Th>
                <Th className="text-end">{t("na.openFolios")}</Th>
                <Th className="text-end pe-5">{t("na.ranAt")}</Th>
              </tr>
            </thead>
            <tbody>
              {history.data?.map((r) => (
                <tr key={r.id} className="hover:bg-surface-2/60">
                  <td className="num px-3 ps-5 py-2.5 border-b border-line font-bold">
                    {formatDate(r.business_date, locale)}
                  </td>
                  <td className="px-3 py-2.5 border-b border-line">
                    <span
                      className={cx(
                        "text-[11.5px] font-bold rounded-full px-2 py-0.5",
                        r.status === "COMPLETED"
                          ? "bg-good/12 text-good"
                          : r.status === "FAILED"
                            ? "bg-bad/12 text-bad"
                            : "bg-surface-2 text-ink-2",
                      )}
                    >
                      {t(`na.${r.status}`, r.status)}
                    </span>
                    <span className="text-[11px] text-muted ms-2">
                      {r.is_automatic ? t("na.auto") : t("na.manual")}
                    </span>
                  </td>
                  <td className="num text-end px-3 py-2.5 border-b border-line">
                    {r.nights_posted}
                  </td>
                  <td className="num text-end px-3 py-2.5 border-b border-line">
                    {money(r.room_revenue_posted, 0)}
                  </td>
                  <td
                    className={cx(
                      "num text-end px-3 py-2.5 border-b border-line",
                      r.no_shows_marked > 0 && "text-warn font-bold",
                    )}
                  >
                    {r.no_shows_marked}
                  </td>
                  <td className="num text-end px-3 py-2.5 border-b border-line text-ink-2">
                    {r.open_folios_remaining}
                  </td>
                  <td className="num text-end px-3 pe-5 py-2.5 border-b border-line text-muted">
                    {formatTime(r.started_at)}
                  </td>
                </tr>
              ))}
              {history.data?.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-5 py-6 text-center text-[13px] text-muted">
                    {t("state.empty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ─────────────────────────────────────────────────── مساعدات */
function Tile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "accent" | "warn" | "ink";
}) {
  const color = tone === "accent" ? "text-accent" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="border border-line rounded-[6px] px-3 py-2.5">
      <div className="text-[11.5px] text-muted font-bold">{label}</div>
      <div className={cx("num text-[24px] font-bold leading-tight", color)}>{value}</div>
    </div>
  );
}

function Warnings({ warnings }: { warnings: AuditWarnings }) {
  const { t } = useI18n();
  const rows: [string, number, boolean][] = [
    [t("na.openFolios"), warnings.open_folios, false],
    [t("na.openOrders"), warnings.open_pos_orders, warnings.open_pos_orders > 0],
    [t("na.openShifts"), warnings.open_shifts, warnings.open_shifts > 0],
    [t("na.noUnit"), warnings.in_house_without_unit, warnings.in_house_without_unit > 0],
    [t("na.overdue"), warnings.overdue_checkouts, warnings.overdue_checkouts > 0],
  ];
  const anyCritical = rows.some(([, , bad]) => bad);

  return (
    <div>
      <div className="text-[12.5px] font-bold text-muted mb-2">
        {anyCritical ? t("na.needsAttention") : t("na.allClear")}
      </div>
      <div className="flex flex-col gap-1">
        {rows.map(([label, value, bad]) => (
          <div
            key={label}
            className={cx(
              "flex items-center justify-between gap-3 px-2.5 py-1.5 rounded-[4px] text-[12.5px]",
              bad ? "bg-warn/10 text-warn font-bold" : "text-ink-2",
            )}
          >
            <span>{label}</span>
            <span className="num font-bold">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}
