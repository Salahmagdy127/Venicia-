/** ضبط البيع — حد التجاوز وقفل البيع على مدى تواريخ وفئات محددة. */

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { addDays, parseDate, toISO } from "@/lib/format";
import type { ControlResult, InventoryCategory } from "@/lib/types";
import { Button, cx } from "./ui";
import { IconCheck, IconLock, IconWarning } from "./Icons";

/** الاختيار جاي من الشبكة كاملاً — بما فيه الحد الحالي، عشان اللوحة متسألش عنه. */
export type Pick = {
  categoryId: number;
  from: string;
  to: string;
  limit: number;
} | null;

export default function SellingControls({
  categories,
  pick,
}: {
  categories: InventoryCategory[];
  pick: Pick;
}) {
  const { t, locale } = useI18n();
  const qc = useQueryClient();

  const [from, setFrom] = useState(() => toISO(new Date()));
  const [to, setTo] = useState(() => toISO(addDays(new Date(), 1)));
  const [chosen, setChosen] = useState<number[]>([]);
  const [limit, setLimit] = useState<number | "">("");
  const [result, setResult] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  // الضغط على خانة في الشبكة بيملا اللوحة — أسرع من كتابة التواريخ بالإيد.
  // الاعتماد على `pick` لوحده مقصود: تحديث البيانات في الخلفية مايمسحش
  // اللي الموظف كتبه، لأن `pick` مبيتغيّرش غير بضغطة منه.
  useEffect(() => {
    if (!pick) return;
    setFrom(pick.from);
    setTo(pick.to);
    setChosen([pick.categoryId]);
    setLimit(pick.limit);
    setResult(null);
  }, [pick]);

  const nights = Math.max(0, Math.round((parseDate(to).getTime() - parseDate(from).getTime()) / 86_400_000));

  const apply = useMutation({
    mutationFn: (body: { overbooking_limit?: number; is_closed?: boolean }) =>
      api<ControlResult>("/inventory", {
        method: "PATCH",
        body: {
          start_date: from,
          end_date: to,
          category_ids: chosen,
          ...body,
        },
      }),
    onSuccess: (r) => {
      setResult({ tone: "good", text: locale === "ar" ? r.message_ar : r.message_en });
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["waitlist"] });
      qc.invalidateQueries({ queryKey: ["tape-chart"] });
    },
    onError: (err) =>
      setResult({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      }),
  });

  const selected = categories.filter((c) => chosen.includes(c.id));
  // الحد مايصحّش يعدّي أصغر فئة في الاختيار — بنمنعه قبل ما السيرفر يرفضه
  const ceiling = selected.length
    ? Math.min(...selected.map((c) => c.total_units))
    : Math.min(...categories.map((c) => c.total_units), 10);
  const maxLimit = Math.min(10, ceiling);
  const busy = apply.isPending;
  const validRange = nights > 0;

  return (
    <aside className="w-[280px] shrink-0 border-s border-line bg-surface flex flex-col overflow-y-auto">
      <header className="px-4 py-3 border-b border-line shrink-0">
        <h2 className="text-[14px] font-bold">{t("inv.controls")}</h2>
      </header>

      <div className="p-4 flex flex-col gap-4">
        {/* المدى */}
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-[11.5px] font-bold text-muted">{t("inv.from")}</span>
            <input
              type="date"
              value={from}
              onChange={(e) => e.target.value && setFrom(e.target.value)}
              className="num h-9 px-2 rounded-[6px] bg-surface border border-line-strong text-ink text-[13px] outline-none focus:border-accent"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11.5px] font-bold text-muted">{t("inv.to")}</span>
            <input
              type="date"
              value={to}
              onChange={(e) => e.target.value && setTo(e.target.value)}
              className="num h-9 px-2 rounded-[6px] bg-surface border border-line-strong text-ink text-[13px] outline-none focus:border-accent"
            />
          </label>
        </div>
        <p className="text-[11.5px] text-muted -mt-2">
          <span className="num font-bold">{nights}</span> {t("inv.days")}
        </p>

        {/* الفئات */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11.5px] font-bold text-muted">{t("inv.categories")}</span>
            <button
              onClick={() => setChosen([])}
              className="text-[11.5px] font-bold text-accent hover:underline"
            >
              {t("inv.allCategories")}
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {categories.map((c) => {
              const on = chosen.includes(c.id);
              return (
                <button
                  key={c.id}
                  onClick={() =>
                    setChosen((prev) =>
                      prev.includes(c.id) ? prev.filter((x) => x !== c.id) : [...prev, c.id],
                    )
                  }
                  className={cx(
                    "px-2.5 h-7 rounded-full text-[12px] font-bold border transition-colors",
                    on
                      ? "bg-accent text-accent-ink border-transparent"
                      : "border-line-strong text-ink-2 hover:bg-surface-2",
                  )}
                >
                  {locale === "ar" ? c.name_ar : c.name_en}
                </button>
              );
            })}
          </div>
          {chosen.length === 0 && (
            <p className="text-[11px] text-muted mt-1.5">{t("inv.allCategories")}</p>
          )}
        </div>

        {/* حد التجاوز */}
        <div className="border-t border-line pt-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-[11.5px] font-bold text-muted">{t("inv.setLimit")}</span>
            <div className="flex items-center gap-1.5">
              {Array.from({ length: maxLimit + 1 }, (_, n) => n).map((n) => (
                <button
                  key={n}
                  onClick={() => setLimit(n)}
                  className={cx(
                    "num w-8 h-8 rounded-[6px] text-[13px] font-bold border",
                    limit === n
                      ? "bg-accent text-accent-ink border-transparent"
                      : "border-line-strong text-ink-2 hover:bg-surface-2",
                  )}
                >
                  {n}
                </button>
              ))}
            </div>
          </label>
          <p className="text-[11px] text-muted leading-relaxed mt-2">{t("inv.limitHint")}</p>
          <Button
            variant="primary"
            className="w-full mt-3"
            disabled={busy || limit === "" || !validRange}
            onClick={() => apply.mutate({ overbooking_limit: Number(limit) })}
          >
            {t("inv.apply")}
          </Button>
        </div>

        {/* قفل وفتح البيع */}
        <div className="border-t border-line pt-4 flex flex-col gap-2">
          <Button
            variant="danger"
            disabled={busy || !validRange}
            onClick={() => apply.mutate({ is_closed: true })}
          >
            <IconLock size={14} />
            {t("inv.stopSell")}
          </Button>
          <Button
            variant="secondary"
            disabled={busy || !validRange}
            onClick={() => apply.mutate({ is_closed: false })}
          >
            {t("inv.openSell")}
          </Button>
        </div>

        {result && (
          <div
            className={cx(
              "rounded-[6px] px-3 py-2.5 text-[12.5px] border flex items-start gap-2",
              result.tone === "good"
                ? "border-good/40 bg-good/10 text-good"
                : "border-bad/40 bg-bad/10 text-bad",
            )}
          >
            {result.tone === "good" ? (
              <IconCheck size={14} className="mt-0.5 shrink-0" />
            ) : (
              <IconWarning size={14} className="mt-0.5 shrink-0" />
            )}
            <span>{result.text}</span>
          </div>
        )}
      </div>
    </aside>
  );
}
