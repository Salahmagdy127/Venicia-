/** الإتاحة والانتظار — بيع أكتر من السعة بحساب، ومين نكلّمه لما حجز يتلغي. */

import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { get, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { addDays, formatRange, parseDate, toISO, weekdayIndex } from "@/lib/format";
import type { InventoryBoard, WaitlistPage } from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import SellingControls, { type Pick } from "@/components/SellingControls";
import Waitlist from "@/components/Waitlist";
import { ErrorState, Loading, cx } from "@/components/ui";
import { IconWarning } from "@/components/Icons";

const HORIZONS = [30, 60, 90] as const;

/** مقاسات الشبكة — نفس منطق شاشة الحجوزات عشان العين تتعوّد على شكل واحد. */
const LABEL_W = 168;
const DAY_W = 46;
const ROW_H = 40;

export default function Inventory() {
  const { t, locale } = useI18n();
  const { can } = useAuth();

  const [tab, setTab] = useState<"board" | "waitlist">("board");
  const [days, setDays] = useState<(typeof HORIZONS)[number]>(30);
  const [start, setStart] = useState(() => toISO(new Date()));
  /** الخانة المختارة — بتملا لوحة الضبط بدل ما الموظف يكتب التواريخ بإيده */
  const [pick, setPick] = useState<Pick>(null);

  const board = useQuery({
    queryKey: ["inventory", start, days],
    queryFn: () => get<InventoryBoard>(`/inventory${qs({ start, days })}`),
    placeholderData: keepPreviousData,
  });

  const waitlist = useQuery({
    queryKey: ["waitlist"],
    queryFn: () => get<WaitlistPage>("/waitlist"),
  });

  const data = board.data;

  /** الخانات مفهرسة بـ «فئة|تاريخ» — الشبكة بتقرأ منها بدل ما تدوّر كل مرة */
  const cellMap = useMemo(() => {
    const map = new Map<string, InventoryBoard["cells"][number]>();
    for (const c of data?.cells ?? []) map.set(`${c.unit_category_id}|${c.stay_date}`, c);
    return map;
  }, [data]);

  const dayList = useMemo(() => {
    const first = parseDate(start);
    return Array.from({ length: days }, (_, i) => addDays(first, i));
  }, [start, days]);

  const s = data?.summary;

  function onCell(categoryId: number, date: string, extend: boolean) {
    const limit = cellMap.get(`${categoryId}|${date}`)?.overbooking_limit ?? 0;
    setPick((prev) => {
      // شيفت على خانة تانية في نفس الفئة = مدى من أول اختيار لهنا
      if (extend && prev && prev.categoryId === categoryId) {
        const from = prev.from < date ? prev.from : date;
        const last = prev.from < date ? date : prev.from;
        return { categoryId, from, to: toISO(addDays(parseDate(last), 1)), limit: prev.limit };
      }
      return { categoryId, from: date, to: toISO(addDays(parseDate(date), 1)), limit };
    });
  }

  return (
    <>
      <PageHeader
        title={t("inv.title")}
        subtitle={data ? formatRange(data.start_date, data.end_date, locale) : "—"}
      >
        {s && (
          <StatStrip
            items={[
              {
                label: t("inv.oversold"),
                value: String(s.oversold_cells),
                tone: s.oversold_cells > 0 ? "bad" : "ink",
              },
              { label: t("inv.soldOut"), value: String(s.sold_out_cells), tone: "warn" },
              { label: t("wl.waitingCount"), value: String(s.waiting_count) },
              {
                label: t("wl.readyCount"),
                value: String(s.ready_count),
                tone: s.ready_count > 0 ? "good" : "ink",
              },
            ]}
          />
        )}

        <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
          {(["board", "waitlist"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={cx(
                "h-9 px-3.5 text-[13px] font-bold border-e border-line-strong last:border-e-0",
                tab === k ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
              )}
            >
              {t(k === "board" ? "inv.tabBoard" : "inv.tabWaitlist")}
              {k === "waitlist" && (waitlist.data?.waiting_count ?? 0) > 0 && (
                <span
                  className={cx(
                    "num ms-1.5 text-[11px]",
                    tab === k ? "opacity-80" : "text-muted",
                  )}
                >
                  {waitlist.data?.waiting_count}
                </span>
              )}
            </button>
          ))}
        </div>
      </PageHeader>

      {tab === "waitlist" ? (
        <Waitlist />
      ) : (
        <div className="flex-1 min-h-0 flex">
          {/* ── الشبكة */}
          <div className="flex-1 min-w-0 flex flex-col">
            <div className="shrink-0 px-5 py-2.5 border-b border-line flex items-center gap-3">
              <label className="flex items-center gap-2 text-[12.5px] text-muted font-bold">
                {t("inv.from")}
                <input
                  type="date"
                  className="num h-8 px-2 rounded-[6px] bg-surface border border-line-strong text-ink outline-none focus:border-accent"
                  value={start}
                  onChange={(e) => e.target.value && setStart(e.target.value)}
                />
              </label>
              <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
                {HORIZONS.map((h) => (
                  <button
                    key={h}
                    onClick={() => setDays(h)}
                    className={cx(
                      "num h-8 px-2.5 text-[12.5px] font-bold border-e border-line-strong last:border-e-0",
                      days === h ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
                    )}
                  >
                    {h}
                  </button>
                ))}
              </div>
              <span className="text-[12px] text-muted">{t("inv.days")}</span>

              <div className="flex-1" />
              <Legend />
            </div>

            {board.isLoading && <Loading />}
            {board.isError && <ErrorState onRetry={() => board.refetch()} />}

            {data && (
              <>
                {s && s.oversold_cells > 0 && (
                  <div className="shrink-0 mx-5 mt-3 rounded-[6px] border border-bad/40 bg-bad/8 px-3.5 py-2 text-[12.5px] text-bad font-bold flex items-center gap-2">
                    <IconWarning size={15} />
                    {t("inv.oversoldWarning")}
                  </div>
                )}

                <div className="flex-1 min-h-0 overflow-auto p-5">
                  <div style={{ width: LABEL_W + dayList.length * DAY_W }}>
                    {/* رأس التواريخ */}
                    <div className="flex sticky top-0 z-10 bg-ground">
                      <div style={{ width: LABEL_W }} className="shrink-0" />
                      {dayList.map((d) => {
                        const weekend = [4, 5].includes(weekdayIndex(d));
                        return (
                          <div
                            key={d.toISOString()}
                            style={{ width: DAY_W }}
                            className={cx(
                              "shrink-0 text-center pb-1.5 border-b border-line",
                              weekend && "bg-surface-2/50",
                            )}
                          >
                            <div className="num text-[13px] font-bold leading-tight">
                              {d.getDate()}
                            </div>
                            <div className="text-[10px] text-muted leading-tight">
                              {(locale === "ar"
                                ? ["ن", "ث", "ر", "خ", "ج", "س", "ح"]
                                : ["M", "T", "W", "T", "F", "S", "S"])[weekdayIndex(d)]}
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {/* صف لكل فئة */}
                    {data.categories.map((cat) => (
                      <div key={cat.id} className="flex items-stretch">
                        <div
                          style={{ width: LABEL_W, height: ROW_H }}
                          className="shrink-0 flex flex-col justify-center pe-3 border-b border-line"
                        >
                          <span className="text-[13px] font-bold truncate">
                            {locale === "ar" ? cat.name_ar : cat.name_en}
                          </span>
                          <span className="num text-[11px] text-muted">
                            {cat.total_units} {t("set.units")}
                          </span>
                        </div>

                        {dayList.map((d) => {
                          const key = `${cat.id}|${toISO(d)}`;
                          const c = cellMap.get(key);
                          const selected =
                            pick?.categoryId === cat.id &&
                            toISO(d) >= pick.from &&
                            toISO(d) < pick.to;
                          return (
                            <Cell
                              key={key}
                              cell={c}
                              selected={!!selected}
                              weekend={[4, 5].includes(weekdayIndex(d))}
                              onClick={(e) => onCell(cat.id, toISO(d), e.shiftKey)}
                            />
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* ── لوحة الضبط */}
          {can("rate.edit") && (
            <SellingControls categories={data?.categories ?? []} pick={pick} />
          )}
        </div>
      )}
    </>
  );
}

/* ─────────────────────────────────────────────────── الخانة */
function Cell({
  cell,
  selected,
  weekend,
  onClick,
}: {
  cell: InventoryBoard["cells"][number] | undefined;
  selected: boolean;
  weekend: boolean;
  onClick: (e: React.MouseEvent) => void;
}) {
  if (!cell) {
    return (
      <div
        style={{ width: DAY_W, height: ROW_H }}
        className={cx("shrink-0 border-b border-line", weekend && "bg-surface-2/50")}
      />
    );
  }

  const oversold = cell.oversold_by > 0;
  const tone = cell.is_closed
    ? "bg-ink/10 text-muted"
    : oversold
      ? "bg-bad/18 text-bad"
      : cell.available === 0
        ? "bg-warn/16 text-warn"
        : cell.available <= 2
          ? "bg-gold-soft text-gold"
          : "text-ink-2";

  return (
    <button
      onClick={onClick}
      title={`${cell.stay_date} · ${cell.sold}/${cell.total}`}
      style={{ width: DAY_W, height: ROW_H }}
      className={cx(
        "shrink-0 border-b border-line relative grid place-items-center",
        weekend && !cell.is_closed && !oversold && cell.available > 2 && "bg-surface-2/50",
        tone,
        selected && "outline outline-2 -outline-offset-2 outline-accent",
      )}
    >
      <span className="num text-[13px] font-bold leading-none">
        {cell.is_closed ? "—" : oversold ? `+${cell.oversold_by}` : cell.available}
      </span>
      {/* شرطة تحت الرقم = اليوم ده عليه حد تجاوز مفعّل */}
      {cell.overbooking_limit > 0 && !cell.is_closed && (
        <span className="absolute bottom-1 w-3 h-[2px] rounded-full bg-accent" />
      )}
      {cell.held > 0 && (
        <span className="absolute top-1 end-1 w-1.5 h-1.5 rounded-full bg-accent" />
      )}
    </button>
  );
}

function Legend() {
  const { t } = useI18n();
  const items: [string, string][] = [
    ["bg-bad/18", t("inv.oversold")],
    ["bg-warn/16", t("inv.soldOut")],
    ["bg-gold-soft", "1–2"],
    ["bg-ink/10", t("inv.closed")],
  ];
  return (
    <div className="flex items-center gap-3">
      {items.map(([bg, label]) => (
        <span key={label} className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className={cx("w-3 h-3 rounded-[3px] border border-line", bg)} />
          {label}
        </span>
      ))}
      <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
        <span className="w-3 h-[2px] rounded-full bg-accent" />
        {t("inv.limit")}
      </span>
    </div>
  );
}
