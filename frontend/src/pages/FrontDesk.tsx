/** الاستقبال — وصول ومغادرة اليوم والحسابات المفتوحة في شاشة واحدة. */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { get, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatDate, formatTime, money } from "@/lib/format";
import { OTA_SOURCES, STATUS_COLOR } from "@/lib/status";
import type { FolioListItem, ReservationListItem } from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import ReservationDrawer from "@/components/ReservationDrawer";
import FolioDrawer from "@/components/FolioDrawer";
import NewReservation from "@/components/NewReservation";
import { Button, EmptyState, ErrorState, Loading, cx } from "@/components/ui";
import { IconPlus, IconSearch } from "@/components/Icons";
import { useAuth } from "@/lib/auth";

export default function FrontDesk() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const [term, setTerm] = useState("");
  const [reservationId, setReservationId] = useState<number | null>(null);
  const [folioId, setFolioId] = useState<number | null>(null);
  const [booking, setBooking] = useState(false);

  const arrivals = useQuery({
    queryKey: ["front-desk", "arrivals"],
    queryFn: () => get<ReservationListItem[]>("/reservations/arrivals"),
  });
  const departures = useQuery({
    queryKey: ["front-desk", "departures"],
    queryFn: () => get<ReservationListItem[]>("/reservations/departures"),
  });
  const folios = useQuery({
    queryKey: ["front-desk", "folios", term],
    queryFn: () => get<FolioListItem[]>(`/folios${qs({ search: term })}`),
  });

  const match = (r: ReservationListItem) =>
    !term ||
    r.code.toLowerCase().includes(term.toLowerCase()) ||
    r.guest_name.toLowerCase().includes(term.toLowerCase());

  const arrivalList = (arrivals.data ?? []).filter(match);
  const departureList = (departures.data ?? []).filter(match);
  const dueTotal = (folios.data ?? []).reduce((sum, f) => sum + Number(f.balance), 0);

  return (
    <>
      <PageHeader title={t("nav.frontdesk")} subtitle={formatDate(new Date(), locale)}>
        <StatStrip
          items={[
            { label: t("desk.arrivals"), value: String(arrivalList.length), tone: "accent" },
            { label: t("desk.departures"), value: String(departureList.length) },
            { label: t("desk.openFolios"), value: String(folios.data?.length ?? 0) },
            { label: t("folio.balance"), value: money(dueTotal, 0), tone: dueTotal > 0 ? "bad" : "good" },
          ]}
        />
        <label className="relative flex items-center">
          <span className="absolute start-0 ps-2.5 text-muted pointer-events-none">
            <IconSearch size={16} />
          </span>
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder={t("desk.searchPlaceholder")}
            className="h-9 w-[240px] ps-8 pe-3 rounded-[6px] bg-surface border border-line-strong text-[13px] outline-none focus:border-accent"
          />
        </label>
        {can("reservation.create") && (
          <Button size="sm" variant="primary" onClick={() => setBooking(true)}>
            <IconPlus size={16} />
            {t("book.new")}
          </Button>
        )}
      </PageHeader>

      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-3 gap-4 p-4 overflow-hidden">
        <Column
          title={t("desk.arrivals")}
          count={arrivalList.length}
          loading={arrivals.isLoading}
          error={arrivals.isError}
          onRetry={() => arrivals.refetch()}
          empty={t("desk.noArrivals")}
        >
          {arrivalList.map((r) => (
            <ReservationRow key={r.id} r={r} onClick={() => setReservationId(r.id)} />
          ))}
        </Column>

        <Column
          title={t("desk.departures")}
          count={departureList.length}
          loading={departures.isLoading}
          error={departures.isError}
          onRetry={() => departures.refetch()}
          empty={t("desk.noDepartures")}
        >
          {departureList.map((r) => (
            <ReservationRow key={r.id} r={r} onClick={() => setReservationId(r.id)} />
          ))}
        </Column>

        <Column
          title={t("desk.openFolios")}
          count={folios.data?.length ?? 0}
          loading={folios.isLoading}
          error={folios.isError}
          onRetry={() => folios.refetch()}
        >
          {folios.data?.map((f) => {
            const balance = Number(f.balance);
            return (
              <button
                key={f.id}
                onClick={() => setFolioId(f.id)}
                className="w-full text-start px-4 py-2.5 border-b border-line hover:bg-surface-2 flex items-center gap-3"
              >
                <span className="num text-[14px] font-bold w-14 shrink-0">
                  {f.unit_label ?? "—"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] truncate">{f.guest_name}</div>
                  <div className="num text-[11.5px] text-muted">
                    {f.code} · {formatTime(f.opened_at)}
                  </div>
                </div>
                <span
                  className={cx(
                    "num text-[13.5px] font-bold shrink-0",
                    balance > 0 ? "text-bad" : "text-good",
                  )}
                >
                  {money(f.balance)}
                </span>
              </button>
            );
          })}
        </Column>
      </div>

      <NewReservation
        open={booking}
        onClose={() => setBooking(false)}
        onCreated={(id) => setReservationId(id)}
      />
      <ReservationDrawer
        reservationId={reservationId}
        onClose={() => setReservationId(null)}
      />
      <FolioDrawer folioId={folioId} onClose={() => setFolioId(null)} />
    </>
  );
}

/* ══════════════════════════════════════════════════════ العمود */
function Column({
  title,
  count,
  loading,
  error,
  onRetry,
  empty,
  children,
}: {
  title: string;
  count: number;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  empty?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-surface border border-line rounded-[8px] flex flex-col min-h-0">
      <header className="shrink-0 flex items-center justify-between gap-3 px-4 py-3 border-b border-line">
        <h2 className="text-[15px] font-bold">{title}</h2>
        <span className="num text-[13px] font-bold text-muted">{count}</span>
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading && <Loading />}
        {error && <ErrorState onRetry={onRetry} />}
        {!loading && !error && count === 0 && <EmptyState title={empty} />}
        {children}
      </div>
    </section>
  );
}

function ReservationRow({ r, onClick }: { r: ReservationListItem; onClick: () => void }) {
  const { t, locale } = useI18n();
  const balance = Number(r.balance);
  const isOta = OTA_SOURCES.has(r.source);

  return (
    <button
      onClick={onClick}
      className="w-full text-start px-4 py-2.5 border-b border-line hover:bg-surface-2 flex items-center gap-3"
    >
      <span
        className="w-1 h-9 rounded-full shrink-0"
        style={{ background: STATUS_COLOR[r.status] }}
      />
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-bold truncate">{r.guest_name}</div>
        <div className="flex items-center gap-2 text-[11.5px] text-muted">
          <span className="num">{r.code}</span>
          <span className="num">
            {r.nights} {t("desk.nights")}
          </span>
          <span className="num">
            {r.adults}
            {r.children > 0 && `+${r.children}`}
          </span>
        </div>
      </div>
      <div className="text-end shrink-0">
        <div className="num text-[13px] font-bold">{money(r.grand_total, 0)}</div>
        {balance > 0 && (
          <div className="num text-[11.5px] text-bad font-bold">{money(balance, 0)}</div>
        )}
      </div>
      <span
        className={cx(
          "text-[10.5px] font-bold rounded-full px-1.5 py-0.5 shrink-0",
          isOta ? "bg-gold-soft text-gold" : "bg-surface-2 text-ink-2",
        )}
      >
        {t(`source.${r.source}`, r.source)}
      </span>
      <span className="text-[11px] text-muted shrink-0 hidden 2xl:inline">
        {formatDate(r.arrival_date, locale)}
      </span>
    </button>
  );
}
