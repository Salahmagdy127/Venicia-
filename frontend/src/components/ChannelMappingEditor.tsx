/** ربط الغرف — فئة الوحدة عندنا ← رقم الغرفة على القناة. */

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { ApiError, api, get } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import type { Channel, RatePlan, UnitCategoryOut } from "@/lib/types";
import { Button, Card, cx, inputClass } from "./ui";
import { IconPlus, IconTrash } from "./Icons";

type Row = {
  unit_category_id: number;
  rate_plan_id: number | null;
  external_room_id: string;
  external_rate_id: string | null;
  allocation: number;
  is_active: boolean;
};

export default function ChannelMappingEditor({
  channel,
  onSaved,
}: {
  channel: Channel;
  onSaved: () => void;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();

  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // بصمة الربط الجاي من السيرفر. الاعتماد عليها بدل المصفوفة نفسها مقصود:
  // اللوحة بتعيد الجلب كل نص دقيقة، ومصفوفة جديدة بنفس المحتوى كانت هتمسح
  // اللي الموظف كاتبه. البصمة بتتغيّر بس لما الداتا نفسها تتغيّر.
  const signature = channel.mappings
    .map((m) => `${m.id}:${m.external_room_id}:${m.external_rate_id}:${m.allocation}`)
    .join("|");

  useEffect(() => {
    setRows(
      channel.mappings.map((m) => ({
        unit_category_id: m.unit_category_id,
        rate_plan_id: m.rate_plan_id,
        external_room_id: m.external_room_id,
        external_rate_id: m.external_rate_id,
        allocation: m.allocation,
        is_active: m.is_active,
      })),
    );
    setError(null);
    setSaved(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel.id, signature]);

  const categories = useQuery({
    queryKey: ["unit-categories"],
    queryFn: () => get<UnitCategoryOut[]>("/unit-categories"),
    staleTime: 10 * 60_000,
  });
  const plans = useQuery({
    queryKey: ["rate-plans"],
    queryFn: () => get<RatePlan[]>("/rate-plans"),
    staleTime: 10 * 60_000,
  });

  const save = useMutation({
    mutationFn: () =>
      api<Channel>(`/channels/${channel.id}/mappings`, { method: "PUT", body: rows }),
    onSuccess: () => {
      setSaved(true);
      setError(null);
      onSaved();
    },
    onError: (err) => {
      setSaved(false);
      setError(err instanceof ApiError ? err.text(locale) : t("state.error"));
    },
  });

  const used = new Set(rows.map((r) => `${r.unit_category_id}|${r.rate_plan_id ?? ""}`));
  const free = (categories.data ?? []).filter(
    (c) => !used.has(`${c.id}|${plans.data?.[0]?.id ?? ""}`),
  );
  const canManage = can("channel.manage");

  function update(index: number, patch: Partial<Row>) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
    setSaved(false);
  }

  return (
    <Card title={t("ch.mapping")}>
      <p className="text-[12px] text-muted leading-relaxed mb-4">{t("ch.mappingHint")}</p>

      <div className="flex flex-col gap-3">
        {rows.map((row, index) => {
          const cat = categories.data?.find((c) => c.id === row.unit_category_id);
          return (
            <div key={index} className="border border-line rounded-[6px] p-3 flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-bold truncate">
                  {cat ? (locale === "ar" ? cat.name_ar : cat.name_en) : "—"}
                </span>
                {canManage && (
                  <button
                    onClick={() => {
                      setRows((prev) => prev.filter((_, i) => i !== index));
                      setSaved(false);
                    }}
                    aria-label={t("wl.remove")}
                    className="text-muted hover:text-bad"
                  >
                    <IconTrash size={15} />
                  </button>
                )}
              </div>

              <label className="flex flex-col gap-1">
                <span className="text-[11.5px] font-bold text-muted">{t("ch.roomId")}</span>
                <input
                  className={cx(inputClass, "num h-9 text-[13px]")}
                  value={row.external_room_id}
                  disabled={!canManage}
                  onChange={(e) => update(index, { external_room_id: e.target.value })}
                />
              </label>

              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1">
                  <span className="text-[11.5px] font-bold text-muted">{t("ch.rateId")}</span>
                  <input
                    className={cx(inputClass, "num h-9 text-[13px]")}
                    value={row.external_rate_id ?? ""}
                    disabled={!canManage}
                    onChange={(e) => update(index, { external_rate_id: e.target.value })}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[11.5px] font-bold text-muted">
                    {t("ch.allocation")}
                  </span>
                  <input
                    type="number"
                    min={0}
                    className={cx(inputClass, "num h-9 text-[13px]")}
                    value={row.allocation}
                    disabled={!canManage}
                    onChange={(e) =>
                      update(index, { allocation: Math.max(0, Number(e.target.value) || 0) })
                    }
                  />
                </label>
              </div>
              <span className="text-[11px] text-muted">{t("ch.allocationHint")}</span>
            </div>
          );
        })}

        {rows.length === 0 && (
          <p className="text-[12.5px] text-muted py-2">{t("state.empty")}</p>
        )}
      </div>

      {canManage && (
        <>
          {free.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {free.map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    setRows((prev) => [
                      ...prev,
                      {
                        unit_category_id: c.id,
                        rate_plan_id: plans.data?.[0]?.id ?? null,
                        external_room_id: "",
                        external_rate_id: null,
                        allocation: 0,
                        is_active: true,
                      },
                    ]);
                    setSaved(false);
                  }}
                  className="inline-flex items-center gap-1 h-7 px-2.5 rounded-full border border-line-strong text-[12px] font-bold text-ink-2 hover:bg-surface-2"
                >
                  <IconPlus size={13} />
                  {locale === "ar" ? c.name_ar : c.name_en}
                </button>
              ))}
            </div>
          )}

          <Button
            variant="primary"
            className="w-full mt-4"
            disabled={save.isPending || rows.some((r) => !r.external_room_id.trim())}
            onClick={() => save.mutate()}
          >
            {t("ch.saveMapping")}
          </Button>
        </>
      )}

      {saved && (
        <div className="mt-3 rounded-[6px] border border-good/40 bg-good/10 px-3 py-2 text-[12.5px] text-good">
          {t("ch.resync")} ✓
        </div>
      )}
      {error && (
        <div className="mt-3 rounded-[6px] border border-bad/40 bg-bad/10 px-3 py-2 text-[12.5px] text-bad">
          {error}
        </div>
      )}
    </Card>
  );
}
