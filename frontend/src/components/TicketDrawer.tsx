/** تفاصيل البلاغ وتحريكه — إسناد، بدء، قفل، شطب. */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { ApiError, get, post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatTime, money } from "@/lib/format";
import type { Technician, Ticket } from "@/lib/types";
import { Button, Modal, Pill, cx, inputClass } from "./ui";

export default function TicketDrawer({
  ticketId,
  tickets,
  onClose,
  onChanged,
}: {
  ticketId: number;
  tickets: Ticket[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();

  const [current, setCurrent] = useState<Ticket | null>(
    tickets.find((x) => x.id === ticketId) ?? null,
  );
  const [tech, setTech] = useState<number | "">("");
  const [resolution, setResolution] = useState("");
  const [cost, setCost] = useState("0");
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"none" | "close" | "cancel">("none");
  const [error, setError] = useState<string | null>(null);

  const technicians = useQuery({
    queryKey: ["technicians"],
    queryFn: () => get<Technician[]>("/maintenance/technicians"),
    staleTime: 10 * 60_000,
  });

  const act = useMutation({
    mutationFn: (input: { path: string; body?: unknown }) =>
      post<Ticket>(`/maintenance/${ticketId}/${input.path}`, input.body ?? {}),
    onSuccess: (updated) => {
      setCurrent(updated);
      setMode("none");
      setError(null);
      onChanged();
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const k = current;
  if (!k) return null;

  const live = ["OPEN", "ASSIGNED", "IN_PROGRESS"].includes(k.status);
  const canManage = can("maintenance.manage");

  return (
    <Modal open onClose={onClose} title={k.number} width={560}>
      <div className="flex flex-col gap-4">
        <div>
          <h3 className="text-[17px] font-bold">{k.title}</h3>
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <Pill tone={k.status === "DONE" ? "good" : live ? "accent" : "muted"}>
              {t(`mt.${k.status}`)}
            </Pill>
            <Pill tone={k.priority === "URGENT" ? "bad" : k.priority === "HIGH" ? "gold" : "muted"}>
              {t(`mt.pri.${k.priority}`)}
            </Pill>
            <Pill tone="muted">{t(`mt.cat.${k.category}`)}</Pill>
            {k.blocks_unit && <Pill tone="bad">{t("mt.blocking")}</Pill>}
            {k.is_overdue && <Pill tone="bad">{t("mt.late")}</Pill>}
          </div>
        </div>

        {k.description && (
          <p className="text-[13px] text-ink-2 leading-relaxed border-s-2 border-line ps-3">
            {k.description}
          </p>
        )}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12.5px]">
          <Row label={t("mt.where")} value={k.unit_label ?? k.location ?? "—"} />
          <Row label={t("mt.reportedBy")} value={k.reported_by_name ?? "—"} />
          <Row label={t("mt.source")} value={t(`mt.src.${k.source}`)} />
          <Row label={t("mt.assignedTo")} value={k.assigned_to_name ?? "—"} />
          <Row label={t("mt.opened")} value={formatTime(k.opened_at)} />
          <Row label={t("mt.due")} value={k.due_at ? formatTime(k.due_at) : "—"} />
          {k.started_at && <Row label={t("mt.started")} value={formatTime(k.started_at)} />}
          {k.completed_at && <Row label={t("mt.closed")} value={formatTime(k.completed_at)} />}
        </dl>

        {k.resolution && (
          <div className="rounded-[6px] border border-good/40 bg-good/8 px-3.5 py-2.5">
            <div className="text-[11.5px] font-bold text-good mb-1">{t("mt.resolution")}</div>
            <p className="text-[13px]">{k.resolution}</p>
            {Number(k.cost) > 0 && (
              <p className="num text-[12px] text-muted mt-1">
                {t("mt.cost")}: {money(k.cost)}
              </p>
            )}
          </div>
        )}

        {k.cancelled_reason && (
          <div className="rounded-[6px] border border-line bg-surface-2 px-3.5 py-2.5 text-[12.5px] text-muted">
            {t("mt.cancelReason")}: {k.cancelled_reason}
          </div>
        )}

        {error && (
          <div className="rounded-[6px] border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-[12.5px] text-bad">
            {error}
          </div>
        )}

        {/* الإجراءات */}
        {live && canManage && mode === "none" && (
          <div className="border-t border-line pt-4 flex flex-col gap-3">
            <div className="flex items-end gap-2">
              <label className="flex flex-col gap-1.5 flex-1">
                <span className="text-[12px] font-bold text-muted">{t("mt.assignTo")}</span>
                <select
                  className={inputClass}
                  value={tech || k.assigned_to_user_id || ""}
                  onChange={(e) => setTech(e.target.value ? Number(e.target.value) : "")}
                >
                  <option value="">—</option>
                  {technicians.data?.map((x) => (
                    <option key={x.id} value={x.id}>
                      {locale === "ar" ? x.name_ar : x.name_en} — {x.role_ar}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                disabled={!tech || act.isPending}
                onClick={() => act.mutate({ path: "assign", body: { user_id: tech } })}
              >
                {t("mt.assign")}
              </Button>
            </div>

            <div className="flex items-center gap-2">
              {k.status === "ASSIGNED" && (
                <Button
                  variant="primary"
                  disabled={act.isPending}
                  onClick={() => act.mutate({ path: "start" })}
                >
                  {t("mt.start")}
                </Button>
              )}
              <Button
                variant="primary"
                className="flex-1"
                disabled={act.isPending}
                onClick={() => setMode("close")}
              >
                {t("mt.close")}
              </Button>
              <Button variant="danger" onClick={() => setMode("cancel")}>
                {t("mt.cancelTicket")}
              </Button>
            </div>
          </div>
        )}

        {mode === "close" && (
          <div className="border-t border-line pt-4 flex flex-col gap-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-bold text-ink-2">{t("mt.resolution")}</span>
              <input
                className={inputClass}
                placeholder={t("mt.resolutionHint")}
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-bold text-ink-2">{t("mt.cost")}</span>
              <input
                type="number"
                min={0}
                className={cx(inputClass, "num")}
                value={cost}
                onChange={(e) => setCost(e.target.value)}
              />
            </label>
            {k.blocks_unit && (
              <p className="text-[11.5px] text-good">{t("mt.willUnblock")}</p>
            )}
            <div className="flex items-center gap-2 mt-1">
              <Button onClick={() => setMode("none")}>{t("action.cancel")}</Button>
              <Button
                variant="primary"
                className="flex-1"
                disabled={!resolution.trim() || act.isPending}
                onClick={() =>
                  act.mutate({
                    path: "complete",
                    body: { resolution, cost: Number(cost) || 0 },
                  })
                }
              >
                {t("mt.close")}
              </Button>
            </div>
          </div>
        )}

        {mode === "cancel" && (
          <div className="border-t border-line pt-4 flex flex-col gap-2">
            <input
              className={inputClass}
              placeholder={t("mt.cancelReason")}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <div className="flex items-center gap-2">
              <Button onClick={() => setMode("none")}>{t("action.cancel")}</Button>
              <Button
                variant="danger"
                className="flex-1"
                disabled={!reason.trim() || act.isPending}
                onClick={() => act.mutate({ path: "cancel", body: { reason } })}
              >
                {t("mt.cancelTicket")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted text-[11.5px]">{label}</dt>
      <dd className="num font-bold">{value}</dd>
    </div>
  );
}
