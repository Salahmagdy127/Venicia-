/** الصيانة — البلاغات من فتحها لحد ما تتقفل والوحدة ترجع للبيع. */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { get, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatTime, money } from "@/lib/format";
import type { MaintenanceBoard, Ticket, TicketStatus } from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import NewTicket from "@/components/NewTicket";
import TicketDrawer from "@/components/TicketDrawer";
import { Card, ErrorState, Loading, Pill, cx } from "@/components/ui";
import { IconWarning } from "@/components/Icons";

const PRIORITY_TONE: Record<string, "bad" | "gold" | "accent" | "muted"> = {
  URGENT: "bad",
  HIGH: "gold",
  NORMAL: "accent",
  LOW: "muted",
};

const STATUS_TONE: Record<string, "gold" | "accent" | "good" | "muted"> = {
  OPEN: "gold",
  ASSIGNED: "accent",
  IN_PROGRESS: "accent",
  DONE: "good",
  CANCELLED: "muted",
};

const FILTERS: (TicketStatus | "")[] = ["", "OPEN", "ASSIGNED", "IN_PROGRESS", "DONE"];

export default function Maintenance() {
  const { t } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [filter, setFilter] = useState<TicketStatus | "">("");
  const [open, setOpen] = useState<number | null>(null);

  const board = useQuery({
    queryKey: ["maintenance", filter],
    queryFn: () =>
      get<MaintenanceBoard>(`/maintenance${qs({ status: filter || undefined, limit: 100 })}`),
    refetchInterval: 60_000,
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["maintenance"] });
    qc.invalidateQueries({ queryKey: ["housekeeping"] });
    qc.invalidateQueries({ queryKey: ["inventory"] });
  }

  const b = board.data;

  return (
    <>
      <PageHeader title={t("mt.title")} subtitle={t("mt.subtitle")}>
        {b && (
          <StatStrip
            items={[
              { label: t("mt.open"), value: String(b.open), tone: b.open > 0 ? "warn" : "ink" },
              { label: t("mt.inProgress"), value: String(b.in_progress) },
              {
                label: t("mt.overdue"),
                value: String(b.overdue),
                tone: b.overdue > 0 ? "bad" : "good",
              },
              {
                label: t("mt.blockedUnits"),
                value: String(b.blocked_units),
                tone: b.blocked_units > 0 ? "warn" : "ink",
              },
              { label: t("mt.monthCost"), value: money(b.cost_this_month, 0) },
            ]}
          />
        )}
        {can("maintenance.manage") && <NewTicket onCreated={refresh} />}
      </PageHeader>

      <div className="flex-1 min-h-0 overflow-y-auto p-5 flex flex-col gap-4 max-w-[1400px]">
        {board.isLoading && <Loading />}
        {board.isError && <ErrorState onRetry={() => board.refetch()} />}

        {b && b.urgent > 0 && (
          <div className="rounded-[6px] border border-bad/40 bg-bad/10 px-4 py-3 text-[13px] text-bad font-bold flex items-center gap-2">
            <IconWarning size={16} />
            {t("mt.urgentAlert").replace("{n}", String(b.urgent))}
          </div>
        )}

        <Card
          title={t("mt.tickets")}
          padded={false}
          action={
            <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
              {FILTERS.map((x) => (
                <button
                  key={x || "live"}
                  onClick={() => setFilter(x)}
                  className={cx(
                    "h-9 px-3 text-[12.5px] font-bold border-e border-line-strong last:border-e-0",
                    filter === x ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
                  )}
                >
                  {x ? t(`mt.${x}`) : t("mt.live")}
                </button>
              ))}
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead className="sticky top-0 bg-surface">
                <tr className="text-muted text-[12px]">
                  <Th className="text-start ps-5">{t("mt.number")}</Th>
                  <Th className="text-start">{t("mt.what")}</Th>
                  <Th className="text-start">{t("mt.where")}</Th>
                  <Th className="text-start">{t("mt.priority")}</Th>
                  <Th className="text-start">{t("res.status")}</Th>
                  <Th className="text-start">{t("mt.assignedTo")}</Th>
                  <Th className="text-end pe-5">{t("mt.opened")}</Th>
                </tr>
              </thead>
              <tbody>
                {b?.tickets.map((k) => (
                  <TicketRow key={k.id} ticket={k} onOpen={() => setOpen(k.id)} />
                ))}
                {b?.tickets.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-5 py-10 text-center text-[13px] text-muted">
                      {t("mt.allClear")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <p className="text-[12px] text-muted leading-relaxed max-w-[80ch]">{t("mt.note")}</p>
      </div>

      {open !== null && (
        <TicketDrawer
          ticketId={open}
          tickets={b?.tickets ?? []}
          onClose={() => setOpen(null)}
          onChanged={refresh}
        />
      )}
    </>
  );
}

function TicketRow({ ticket, onOpen }: { ticket: Ticket; onOpen: () => void }) {
  const { t } = useI18n();
  return (
    <tr
      onClick={onOpen}
      className={cx(
        "cursor-pointer hover:bg-surface-2/60",
        ticket.is_overdue && "bg-bad/5",
      )}
    >
      <td className="num px-3 ps-5 py-2.5 border-b border-line font-bold">
        {ticket.number}
        {ticket.blocks_unit && (
          <span className="text-[10.5px] text-bad ms-1.5 font-bold">
            {t("mt.blocking")}
          </span>
        )}
      </td>
      <td className="px-3 py-2.5 border-b border-line">
        <div className="truncate max-w-[280px]">{ticket.title}</div>
        <div className="text-[11px] text-muted">{t(`mt.cat.${ticket.category}`)}</div>
      </td>
      <td className="px-3 py-2.5 border-b border-line">
        <span className="num font-bold">{ticket.unit_label ?? "—"}</span>
        {ticket.location && (
          <div className="text-[11px] text-muted truncate max-w-[150px]">{ticket.location}</div>
        )}
      </td>
      <td className="px-3 py-2.5 border-b border-line">
        <Pill tone={PRIORITY_TONE[ticket.priority] ?? "muted"}>
          {t(`mt.pri.${ticket.priority}`)}
        </Pill>
      </td>
      <td className="px-3 py-2.5 border-b border-line">
        <Pill tone={STATUS_TONE[ticket.status] ?? "muted"}>{t(`mt.${ticket.status}`)}</Pill>
        {ticket.is_overdue && (
          <div className="text-[11px] text-bad font-bold mt-0.5">{t("mt.late")}</div>
        )}
      </td>
      <td className="px-3 py-2.5 border-b border-line text-ink-2 truncate max-w-[140px]">
        {ticket.assigned_to_name ?? "—"}
      </td>
      <td className="num text-end px-3 pe-5 py-2.5 border-b border-line text-muted">
        {formatTime(ticket.opened_at)}
      </td>
    </tr>
  );
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}
