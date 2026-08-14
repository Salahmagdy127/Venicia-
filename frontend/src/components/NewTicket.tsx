/** فتح بلاغ صيانة — الوحدة أو مكان عام، وحجب اختياري. */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { ApiError, get, post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { HousekeepingBoard, Ticket, TicketCategory, TicketPriority } from "@/lib/types";
import { Button, Modal, cx, inputClass } from "./ui";
import { IconPlus } from "./Icons";

const CATEGORIES: TicketCategory[] = [
  "AC",
  "PLUMBING",
  "ELECTRICAL",
  "FURNITURE",
  "APPLIANCE",
  "NETWORK",
  "POOL",
  "GROUNDS",
  "OTHER",
];

const PRIORITIES: TicketPriority[] = ["LOW", "NORMAL", "HIGH", "URGENT"];

export default function NewTicket({ onCreated }: { onCreated: () => void }) {
  const { t, locale } = useI18n();
  const [open, setOpen] = useState(false);

  const [title, setTitle] = useState("");
  const [unitId, setUnitId] = useState<number | "">("");
  const [location, setLocation] = useState("");
  const [category, setCategory] = useState<TicketCategory>("OTHER");
  const [priority, setPriority] = useState<TicketPriority>("NORMAL");
  const [description, setDescription] = useState("");
  const [blocks, setBlocks] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const units = useQuery({
    queryKey: ["housekeeping"],
    queryFn: () => get<HousekeepingBoard>("/housekeeping"),
    enabled: open,
    staleTime: 60_000,
  });

  const create = useMutation({
    mutationFn: () =>
      post<Ticket>("/maintenance", {
        title,
        unit_id: unitId === "" ? null : unitId,
        location: location.trim() || null,
        category,
        priority,
        source: "STAFF",
        description: description.trim() || null,
        blocks_unit: blocks,
      }),
    onSuccess: () => {
      onCreated();
      reset();
      setOpen(false);
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  function reset() {
    setTitle("");
    setUnitId("");
    setLocation("");
    setCategory("OTHER");
    setPriority("NORMAL");
    setDescription("");
    setBlocks(false);
    setError(null);
  }

  const ready = title.trim() && (unitId !== "" || location.trim());

  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        <IconPlus size={16} />
        {t("mt.new")}
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("mt.new")}
        width={520}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t("action.cancel")}</Button>
            <Button
              variant="primary"
              disabled={!ready || create.isPending}
              onClick={() => {
                setError(null);
                create.mutate();
              }}
            >
              {t("mt.openTicket")}
            </Button>
          </>
        }
      >
        <label className="flex flex-col gap-1.5 mb-3">
          <span className="text-[12.5px] font-bold text-ink-2">{t("mt.what")}</span>
          <input
            className={inputClass}
            placeholder={t("mt.titleHint")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-bold text-ink-2">{t("hk.unit")}</span>
            <select
              className={cx(inputClass, "num")}
              value={unitId}
              onChange={(e) => setUnitId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">{t("mt.publicArea")}</option>
              {units.data?.units.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.label} — {u.category_name_ar}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-bold text-ink-2">{t("mt.where")}</span>
            <input
              className={inputClass}
              placeholder={t("mt.locationHint")}
              value={location}
              disabled={unitId !== ""}
              onChange={(e) => setLocation(e.target.value)}
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-bold text-ink-2">{t("mt.category")}</span>
            <select
              className={inputClass}
              value={category}
              onChange={(e) => setCategory(e.target.value as TicketCategory)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {t(`mt.cat.${c}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-bold text-ink-2">{t("mt.priority")}</span>
            <select
              className={inputClass}
              value={priority}
              onChange={(e) => setPriority(e.target.value as TicketPriority)}
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {t(`mt.pri.${p}`)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="flex flex-col gap-1.5 mb-3">
          <span className="text-[12.5px] font-bold text-ink-2">{t("mt.details")}</span>
          <input
            className={inputClass}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        <label
          className={cx(
            "flex items-start gap-2.5 rounded-[6px] border p-3 cursor-pointer",
            blocks ? "border-bad/40 bg-bad/8" : "border-line",
            unitId === "" && "opacity-50 pointer-events-none",
          )}
        >
          <input
            type="checkbox"
            className="mt-0.5"
            checked={blocks}
            disabled={unitId === ""}
            onChange={(e) => setBlocks(e.target.checked)}
          />
          <span className="text-[13px]">
            <span className="font-bold">{t("mt.blockUnit")}</span>
            <span className="block text-[11.5px] text-muted mt-0.5">{t("mt.blockHint")}</span>
          </span>
        </label>

        {error && (
          <div className="mt-3 rounded-[6px] border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-[12.5px] text-bad">
            {error}
          </div>
        )}
      </Modal>
    </>
  );
}
