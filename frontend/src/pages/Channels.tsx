/** الربط بالقنوات — حالة كل قناة، وربط الغرف، والطابور، والحجوزات الواردة. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, patch, post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDateShort, formatTime, money } from "@/lib/format";
import type {
  Channel,
  ChannelBoard,
  ChannelBookingRow,
  ChannelMessage,
  SyncResult,
} from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import ChannelMappingEditor from "@/components/ChannelMappingEditor";
import SimulateBooking from "@/components/SimulateBooking";
import { Button, Card, ErrorState, Loading, Pill, cx } from "@/components/ui";
import { IconCheck, IconWarning } from "@/components/Icons";

export default function Channels() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [selected, setSelected] = useState<number | null>(null);
  const [tab, setTab] = useState<"queue" | "inbound">("queue");
  const [flash, setFlash] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const board = useQuery({
    queryKey: ["channels"],
    queryFn: () => get<ChannelBoard>("/channels"),
    refetchInterval: 30_000,
  });

  const queue = useQuery({
    queryKey: ["channel-messages"],
    queryFn: () => get<ChannelMessage[]>("/channels/messages?limit=60"),
    refetchInterval: 30_000,
  });

  const inbound = useQuery({
    queryKey: ["channel-bookings"],
    queryFn: () => get<ChannelBookingRow[]>("/channels/bookings?limit=50"),
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["channels"] });
    qc.invalidateQueries({ queryKey: ["channel-messages"] });
    qc.invalidateQueries({ queryKey: ["channel-bookings"] });
    qc.invalidateQueries({ queryKey: ["inventory"] });
    qc.invalidateQueries({ queryKey: ["tape-chart"] });
  }

  const action = useMutation({
    mutationFn: (path: string) => post<SyncResult>(path, {}),
    onSuccess: (r) => {
      setFlash({ tone: "good", text: locale === "ar" ? r.message_ar : r.message_en });
      refresh();
    },
    onError: (err) =>
      setFlash({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      }),
  });

  const data = board.data;
  const channels = data?.channels ?? [];
  const active = channels.find((c) => c.id === selected) ?? channels[0] ?? null;
  const canManage = can("channel.manage");

  const rows = tab === "queue" ? queue.data ?? [] : [];
  const visibleQueue = active ? rows.filter((m) => m.channel_id === active.id) : rows;
  const visibleInbound = active
    ? (inbound.data ?? []).filter((b) => b.channel_id === active.id)
    : inbound.data ?? [];

  return (
    <>
      <PageHeader title={t("ch.title")} subtitle={t("ch.subtitle")}>
        {data && (
          <StatStrip
            items={[
              {
                label: t("ch.pending"),
                value: String(data.total_pending),
                tone: data.total_pending > 0 ? "warn" : "ink",
              },
              {
                label: t("ch.failed"),
                value: String(data.total_failed),
                tone: data.total_failed > 0 ? "bad" : "ink",
              },
              {
                label: t("ch.unmapped"),
                value: String(data.unmapped_categories.length),
                tone: data.unmapped_categories.length > 0 ? "warn" : "good",
              },
            ]}
          />
        )}
        {canManage && (
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              disabled={action.isPending}
              onClick={() => action.mutate("/channels/sync")}
            >
              {t("ch.sync")}
            </Button>
            <Button
              disabled={action.isPending}
              onClick={() => action.mutate("/channels/resync")}
            >
              {t("ch.resync")}
            </Button>
            {(data?.total_failed ?? 0) > 0 && (
              <Button
                variant="danger"
                disabled={action.isPending}
                onClick={() => action.mutate("/channels/retry")}
              >
                {t("ch.retry")}
              </Button>
            )}
          </div>
        )}
      </PageHeader>

      <div className="flex-1 min-h-0 overflow-y-auto p-5 flex flex-col gap-4 max-w-[1500px]">
        {board.isLoading && <Loading />}
        {board.isError && <ErrorState onRetry={() => board.refetch()} />}

        {flash && (
          <div
            className={cx(
              "rounded-[6px] px-3.5 py-2.5 text-[13px] font-bold border flex items-center gap-2",
              flash.tone === "good"
                ? "border-good/40 bg-good/10 text-good"
                : "border-bad/40 bg-bad/10 text-bad",
            )}
          >
            {flash.tone === "good" ? <IconCheck size={15} /> : <IconWarning size={15} />}
            {flash.text}
          </div>
        )}

        {/* ── كروت القنوات */}
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
          {channels.map((c) => (
            <ChannelCard
              key={c.id}
              channel={c}
              selected={active?.id === c.id}
              onSelect={() => setSelected(c.id)}
            />
          ))}
        </div>

        {active && (
          <>
            <div className="grid gap-4 grid-cols-1 xl:grid-cols-3">
              <ChannelMappingEditor channel={active} onSaved={refresh} />

              <Card
                className="xl:col-span-2"
                title={
                  <div className="flex items-center gap-3">
                    <span>{locale === "ar" ? active.name_ar : active.name_en}</span>
                    <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
                      {(["queue", "inbound"] as const).map((k) => (
                        <button
                          key={k}
                          onClick={() => setTab(k)}
                          className={cx(
                            "h-7 px-3 text-[12.5px] font-bold border-e border-line-strong last:border-e-0",
                            tab === k
                              ? "bg-accent text-accent-ink"
                              : "text-ink-2 hover:bg-surface-2",
                          )}
                        >
                          {t(k === "queue" ? "ch.queue" : "ch.inbound")}
                        </button>
                      ))}
                    </div>
                  </div>
                }
                action={canManage && tab === "inbound" ? <SimulateBooking channel={active} onDone={refresh} /> : undefined}
                padded={false}
              >
                {tab === "queue" ? (
                  <QueueTable rows={visibleQueue} />
                ) : (
                  <InboundTable rows={visibleInbound} />
                )}
              </Card>
            </div>

            <p className="text-[12px] text-muted leading-relaxed max-w-[80ch]">
              {t("ch.queueNote")}
            </p>
          </>
        )}
      </div>
    </>
  );
}

/* ──────────────────────────────────────────── كارت القناة */
function ChannelCard({
  channel,
  selected,
  onSelect,
}: {
  channel: Channel;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const toggle = useMutation({
    mutationFn: (connected: boolean) =>
      patch<Channel>(`/channels/${channel.id}`, { is_connected: connected }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channels"] });
      qc.invalidateQueries({ queryKey: ["channel-messages"] });
    },
  });

  const state = !channel.is_active
    ? { label: t("ch.paused"), tone: "muted" as const }
    : channel.is_connected
      ? { label: t("ch.connected"), tone: "good" as const }
      : { label: t("ch.notConnected"), tone: "gold" as const };

  return (
    <button
      onClick={onSelect}
      className={cx(
        "text-start bg-surface border rounded-[8px] p-4 flex flex-col gap-3 transition-colors",
        selected ? "border-accent" : "border-line hover:border-line-strong",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[15px] font-bold truncate">
            {locale === "ar" ? channel.name_ar : channel.name_en}
          </div>
          <div className="num text-[11.5px] text-muted truncate">
            {channel.external_property_id ?? "—"}
          </div>
        </div>
        <Pill tone={state.tone}>{state.label}</Pill>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <Metric label={t("ch.commission")} value={`${Number(channel.commission_percent)}%`} />
        <Metric
          label={t("ch.pending")}
          value={String(channel.pending)}
          tone={channel.pending > 0 ? "warn" : "ink"}
        />
        <Metric
          label={t("ch.failed")}
          value={String(channel.failed)}
          tone={channel.failed > 0 ? "bad" : "ink"}
        />
      </div>

      <div className="text-[11.5px] text-muted flex flex-col gap-0.5">
        <span>
          {t("ch.mapped")}: <span className="num font-bold">{channel.mapped_categories}</span>
          {" · "}
          {t("ch.sentToday")}: <span className="num font-bold">{channel.sent_today}</span>
        </span>
        <span>
          {t("ch.lastPush")}:{" "}
          <span className="num">
            {channel.last_push_at ? formatTime(channel.last_push_at) : t("ch.never")}
          </span>
          {" · "}
          {t("ch.lastPull")}:{" "}
          <span className="num">
            {channel.last_pull_at ? formatTime(channel.last_pull_at) : t("ch.never")}
          </span>
        </span>
      </div>

      {channel.last_error && (
        <p className="text-[11.5px] text-bad line-clamp-2">{channel.last_error}</p>
      )}

      {can("channel.manage") && (
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            toggle.mutate(!channel.is_connected);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.stopPropagation();
              toggle.mutate(!channel.is_connected);
            }
          }}
          className={cx(
            "h-8 grid place-items-center rounded-[6px] text-[12.5px] font-bold border transition-colors",
            channel.is_connected
              ? "border-line-strong text-ink-2 hover:bg-surface-2"
              : "border-transparent bg-accent text-accent-ink hover:bg-accent-hover",
            toggle.isPending && "opacity-50",
          )}
        >
          {channel.is_connected ? t("ch.disconnect") : t("ch.connect")}
        </span>
      )}
    </button>
  );
}

function Metric({
  label,
  value,
  tone = "ink",
}: {
  label: string;
  value: string;
  tone?: "ink" | "warn" | "bad";
}) {
  const color = tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="border border-line rounded-[6px] py-1.5">
      <div className={cx("num text-[16px] font-bold leading-tight", color)}>{value}</div>
      <div className="text-[10.5px] text-muted leading-tight">{label}</div>
    </div>
  );
}

/* ─────────────────────────────────────────── جدول الطابور */
const MSG_TONE: Record<string, "good" | "gold" | "bad" | "muted"> = {
  SENT: "good",
  PENDING: "gold",
  FAILED: "bad",
  SKIPPED: "muted",
};

function QueueTable({ rows }: { rows: ChannelMessage[] }) {
  const { t, locale } = useI18n();
  if (rows.length === 0) {
    return <p className="px-5 py-8 text-center text-[13px] text-muted">{t("ch.emptyQueue")}</p>;
  }
  return (
    <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 bg-surface">
          <tr className="text-muted text-[12px]">
            <Th className="text-start ps-5">{t("ch.kind")}</Th>
            <Th className="text-start">{t("wl.category")}</Th>
            <Th className="text-start">{t("ch.range")}</Th>
            <Th className="text-start">{t("ch.reason")}</Th>
            <Th className="text-start">{t("res.status")}</Th>
            <Th className="text-end pe-5">{t("na.ranAt")}</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.id} className="hover:bg-surface-2/50">
              <td className="px-3 ps-5 py-2 border-b border-line font-bold">
                {t(`ch.${m.kind}`)}
              </td>
              <td className="px-3 py-2 border-b border-line text-ink-2">
                {m.category_name_ar ?? "—"}
              </td>
              <td className="num px-3 py-2 border-b border-line">
                {formatDateShort(m.start_date, locale)} → {formatDateShort(m.end_date, locale)}
              </td>
              <td className="px-3 py-2 border-b border-line text-muted">{m.reason ?? "—"}</td>
              <td className="px-3 py-2 border-b border-line">
                <Pill tone={MSG_TONE[m.status] ?? "muted"}>{t(`ch.${m.status}`)}</Pill>
                {m.error && <div className="text-[11px] text-bad mt-0.5">{m.error}</div>}
              </td>
              <td className="num text-end px-3 pe-5 py-2 border-b border-line text-muted">
                {m.sent_at ? formatTime(m.sent_at) : formatTime(m.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ────────────────────────────────────── جدول الحجوزات الواردة */
const BOOKING_TONE: Record<string, "good" | "gold" | "bad" | "muted"> = {
  PROCESSED: "good",
  DUPLICATE: "muted",
  REJECTED: "bad",
  FAILED: "bad",
};

function InboundTable({ rows }: { rows: ChannelBookingRow[] }) {
  const { t, locale } = useI18n();
  if (rows.length === 0) {
    return <p className="px-5 py-8 text-center text-[13px] text-muted">{t("ch.emptyInbound")}</p>;
  }
  return (
    <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 bg-surface">
          <tr className="text-muted text-[12px]">
            <Th className="text-start ps-5">{t("ch.reference")}</Th>
            <Th className="text-start">{t("wl.guest")}</Th>
            <Th className="text-start">{t("wl.dates")}</Th>
            <Th className="text-end">{t("res.grandTotal")}</Th>
            <Th className="text-start">{t("ch.result")}</Th>
            <Th className="text-end pe-5">{t("na.ranAt")}</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={b.id} className="hover:bg-surface-2/50 align-top">
              <td className="px-3 ps-5 py-2.5 border-b border-line">
                <div className="num font-bold">{b.external_reference}</div>
                <div className="text-[11px] text-muted">{t(`ch.${b.action}`)}</div>
              </td>
              <td className="px-3 py-2.5 border-b border-line">
                {b.guest_name ?? "—"}
                {b.guest_phone && (
                  <div className="num text-[11px] text-muted" dir="ltr">
                    {b.guest_phone}
                  </div>
                )}
              </td>
              <td className="num px-3 py-2.5 border-b border-line">
                {b.arrival_date
                  ? `${formatDateShort(b.arrival_date, locale)} → ${
                      b.departure_date ? formatDateShort(b.departure_date, locale) : "—"
                    }`
                  : "—"}
              </td>
              <td className="num text-end px-3 py-2.5 border-b border-line">
                {Number(b.gross_amount) > 0 ? money(b.gross_amount, 0) : "—"}
                {Number(b.commission_amount) > 0 && (
                  <div className="text-[11px] text-warn">
                    −{money(b.commission_amount, 0)}
                  </div>
                )}
              </td>
              <td className="px-3 py-2.5 border-b border-line">
                <Pill tone={BOOKING_TONE[b.status] ?? "muted"}>{t(`ch.${b.status}`)}</Pill>
                {b.reservation_code && (
                  <div className="num text-[11px] text-muted mt-0.5">{b.reservation_code}</div>
                )}
                {b.error && <div className="text-[11px] text-bad mt-0.5">{b.error}</div>}
              </td>
              <td className="num text-end px-3 pe-5 py-2.5 border-b border-line text-muted">
                {formatTime(b.received_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}
