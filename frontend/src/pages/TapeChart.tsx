/** شاشة الحجوزات — الشبكة الكاملة بالسحب والإفلات على كل وحدات القرية. */

import { useMemo, useRef, useState, type DragEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { addDays, formatRange, parseDate, toISO } from "@/lib/format";
import { HK_COLOR, OTA_SOURCES, SOURCE_SHORT, STATUS_COLOR } from "@/lib/status";
import type { ActionResult, Bar, TapeChartData } from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import ReservationDrawer from "@/components/ReservationDrawer";
import NewReservation from "@/components/NewReservation";
import { Button, ErrorState, Loading, cx } from "@/components/ui";
import {
  IconChevronLeft,
  IconChevronRight,
  IconLock,
  IconPlus,
  IconSearch,
} from "@/components/Icons";

/* أبعاد الشبكة — مضبوطة عشان 78 وحدة تبان من غير ما الصف يبقى مزنوق */
const LABEL_W = 178;
const DAY_W = 88;
const ROW_H = 34;
const GROUP_H = 32;
const HEAD_H = 52;

export default function TapeChart() {
  const { t, locale, dir } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [start, setStart] = useState(() => toISO(new Date()));
  const [span, setSpan] = useState(14);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [booking, setBooking] = useState(false);
  const [toast, setToast] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  /** الشريط اللي بيتسحب دلوقتي + في أنهي يوم منه أمسك المستخدم */
  const dragging = useRef<{ bar: Bar; grabDay: number } | null>(null);
  const [dropTarget, setDropTarget] = useState<number | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["tape-chart", start, span],
    queryFn: () => get<TapeChartData>(`/tape-chart${qs({ start, days: span })}`),
    placeholderData: keepPreviousData,
  });

  const move = useMutation({
    mutationFn: (v: {
      lineId: number;
      unit_id?: number | null;
      arrival_date?: string;
      departure_date?: string;
    }) =>
      post<ActionResult>(`/reservations/lines/${v.lineId}/move`, {
        unit_id: v.unit_id,
        arrival_date: v.arrival_date,
        departure_date: v.departure_date,
      }),
    onSuccess: (res) => {
      setToast({ tone: "good", text: locale === "ar" ? res.message_ar : res.message_en });
      qc.invalidateQueries({ queryKey: ["tape-chart"] });
      qc.invalidateQueries({ queryKey: ["front-desk"] });
    },
    onError: (err) =>
      setToast({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      }),
  });

  const assign = useMutation({
    mutationFn: (v: { lineId: number; unit_id: number }) =>
      post<ActionResult>(`/reservations/lines/${v.lineId}/assign`, { unit_id: v.unit_id }),
    onSuccess: (res) => {
      setToast({ tone: "good", text: locale === "ar" ? res.message_ar : res.message_en });
      qc.invalidateQueries({ queryKey: ["tape-chart"] });
    },
    onError: (err) =>
      setToast({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      }),
  });

  const canMove = can("reservation.edit");
  const canAssign = can("reservation.assign_unit");

  /* شرائط كل وحدة — بنجهّزها مرة واحدة بدل ما ندوّر جوّه كل صف */
  const barsByUnit = useMemo(() => {
    const map = new Map<number, Bar[]>();
    for (const bar of data?.bars ?? []) {
      if (bar.unit_id === null) continue;
      const list = map.get(bar.unit_id);
      if (list) list.push(bar);
      else map.set(bar.unit_id, [bar]);
    }
    return map;
  }, [data?.bars]);

  /* الإتاحة: فئة+يوم → عدد المتاح */
  const availability = useMemo(() => {
    const map = new Map<string, { available: number; closed: boolean }>();
    for (const a of data?.availability ?? []) {
      map.set(`${a.unit_category_id}|${a.date}`, {
        available: a.available,
        closed: a.is_closed,
      });
    }
    return map;
  }, [data?.availability]);

  const term = search.trim().toLowerCase();
  const matches = (bar: Bar) =>
    !term ||
    bar.code.toLowerCase().includes(term) ||
    bar.guest_name.toLowerCase().includes(term);

  /* ── السحب والإفلات ─────────────────────────────────────── */
  function onDragStart(e: DragEvent<HTMLDivElement>, bar: Bar, fromStrip = false) {
    if (!canMove && !fromStrip) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const offset = dir === "rtl" ? rect.right - e.clientX : e.clientX - rect.left;
    const grabDay = fromStrip
      ? 0
      : Math.max(0, Math.min(bar.span - 1, Math.floor(offset / DAY_W)));
    dragging.current = { bar, grabDay };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(bar.id));
  }

  function onDrop(e: DragEvent<HTMLDivElement>, unitId: number) {
    e.preventDefault();
    setDropTarget(null);
    const drag = dragging.current;
    dragging.current = null;
    if (!drag || !data) return;

    const { bar, grabDay } = drag;

    // حجز لم يُخصص → بيتخصص للوحدة بنفس تواريخه
    if (bar.unit_id === null) {
      if (canAssign) assign.mutate({ lineId: bar.id, unit_id: unitId });
      return;
    }
    if (!canMove) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const offset = dir === "rtl" ? rect.right - e.clientX : e.clientX - rect.left;
    const dropDay = Math.max(0, Math.min(span - 1, Math.floor(offset / DAY_W)));

    // الفرق بالأيام محسوب من موضع الشريط الظاهر، فبيفضل صح حتى لو الشريط مقصوص
    const delta = dropDay - grabDay - bar.start_index;
    if (delta === 0 && bar.unit_id === unitId) return;

    const arrival = addDays(parseDate(bar.arrival_date), delta);
    const departure = addDays(parseDate(bar.departure_date), delta);
    move.mutate({
      lineId: bar.id,
      unit_id: unitId,
      arrival_date: toISO(arrival),
      departure_date: toISO(departure),
    });
  }

  /* ── التنقّل في التواريخ ─────────────────────────────────── */
  const shift = (n: number) => setStart(toISO(addDays(parseDate(start), n)));
  const Prev = dir === "rtl" ? IconChevronRight : IconChevronLeft;
  const Next = dir === "rtl" ? IconChevronLeft : IconChevronRight;

  const s = data?.summary;
  const gridWidth = LABEL_W + span * DAY_W;

  return (
    <>
      <PageHeader
        title={t("nav.tapechart")}
        subtitle={
          data ? formatRange(data.start_date, addDays(parseDate(data.end_date), -1), locale) : "—"
        }
      >
        {s && (
          <StatStrip
            items={[
              {
                label: t("tape.occupancy"),
                value: `${s.occupancy_percent}%`,
                tone: s.occupancy_percent >= 85 ? "good" : s.occupancy_percent < 50 ? "warn" : "ink",
              },
              { label: t("tape.arrivals"), value: String(s.arrivals_today), tone: "accent" },
              { label: t("tape.departures"), value: String(s.departures_today) },
              { label: t("tape.inhouse"), value: `${s.in_house}/${s.total_units - s.out_of_order}` },
            ]}
          />
        )}
      </PageHeader>

      {/* ── شريط الأدوات */}
      <div className="shrink-0 px-5 py-2.5 border-b border-line bg-surface flex items-center gap-2 flex-wrap">
        <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
          <button
            onClick={() => shift(-7)}
            title={t("tape.prev")}
            aria-label={t("tape.prev")}
            className="w-9 h-9 grid place-items-center text-ink-2 hover:bg-surface-2"
          >
            <Prev size={17} />
          </button>
          <input
            type="date"
            value={start}
            onChange={(e) => e.target.value && setStart(e.target.value)}
            className="num h-9 px-2 bg-transparent border-x border-line-strong text-[13px] outline-none"
          />
          <button
            onClick={() => shift(7)}
            title={t("tape.next")}
            aria-label={t("tape.next")}
            className="w-9 h-9 grid place-items-center text-ink-2 hover:bg-surface-2"
          >
            <Next size={17} />
          </button>
        </div>

        <Button size="sm" onClick={() => setStart(toISO(new Date()))}>
          {t("action.today")}
        </Button>

        {can("reservation.create") && (
          <Button size="sm" variant="primary" onClick={() => setBooking(true)}>
            <IconPlus size={16} />
            {t("book.new")}
          </Button>
        )}

        <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
          {[7, 14, 30].map((n) => (
            <button
              key={n}
              onClick={() => setSpan(n)}
              className={cx(
                "num h-9 px-3 text-[13px] font-bold border-e border-line-strong last:border-e-0",
                span === n ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
              )}
            >
              {n}
            </button>
          ))}
        </div>

        <label className="relative flex items-center">
          <span className="absolute start-0 ps-2.5 text-muted pointer-events-none">
            <IconSearch size={16} />
          </span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("tape.searchPlaceholder")}
            className="h-9 w-[260px] ps-8 pe-3 rounded-[6px] bg-surface border border-line-strong text-[13px] outline-none focus:border-accent"
          />
        </label>

        <div className="flex-1" />
        <Legend />
        {isFetching && <span className="text-[12px] text-muted">…</span>}
      </div>

      {/* ── حجوزات لم تُخصص */}
      {data && data.unassigned.length > 0 && (
        <div className="shrink-0 px-5 py-2 border-b border-line bg-gold-soft flex items-center gap-3 overflow-x-auto">
          <span className="text-[12.5px] font-bold text-gold whitespace-nowrap shrink-0">
            {t("tape.unassigned")} · <span className="num">{data.unassigned.length}</span>
          </span>
          <span className="text-[11.5px] text-gold/80 whitespace-nowrap shrink-0">
            {t("tape.unassignedHint")}
          </span>
          <div className="flex items-center gap-1.5">
            {data.unassigned.map((bar) => (
              <div
                key={bar.id}
                draggable={canAssign}
                onDragStart={(e) => onDragStart(e, bar, true)}
                onDragEnd={() => setDropTarget(null)}
                className={cx(
                  "shrink-0 flex items-center gap-2 rounded-[4px] border px-2.5 h-7 bg-surface",
                  "text-[12px] whitespace-nowrap",
                  canAssign ? "cursor-grab active:cursor-grabbing" : "",
                )}
                style={{ borderColor: STATUS_COLOR[bar.status] }}
                title={`${bar.code} · ${bar.guest_name}`}
              >
                <span className="num font-bold">{bar.code}</span>
                <span className="text-ink-2 max-w-[120px] truncate">{bar.guest_name}</span>
                <span className="text-muted text-[11px]">
                  <span className="num">{bar.nights}</span> {t("tape.nights")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── الشبكة */}
      <div className="flex-1 min-h-0 overflow-auto bg-ground">
        {isLoading && <Loading />}
        {isError && <ErrorState onRetry={() => refetch()} />}

        {data && (
          <div style={{ width: gridWidth }} className="relative">
            {/* رأس الأيام */}
            <div
              className="sticky top-0 z-30 flex bg-surface border-b border-line"
              style={{ height: HEAD_H }}
            >
              <div
                className="sticky z-10 bg-surface border-e border-line flex items-end px-3 pb-1.5"
                style={{ width: LABEL_W, insetInlineStart: 0 }}
              >
                <span className="text-[12px] font-bold text-muted">{t("tape.unit")}</span>
              </div>
              {data.days.map((d) => (
                <div
                  key={d.date}
                  className={cx(
                    "shrink-0 flex flex-col items-center justify-center border-e border-line",
                    d.is_weekend && "bg-surface-2",
                    d.is_today && "bg-accent-soft",
                  )}
                  style={{ width: DAY_W }}
                >
                  <span
                    className={cx(
                      "text-[11.5px] leading-tight",
                      d.is_today ? "text-accent font-bold" : "text-muted",
                    )}
                  >
                    {locale === "ar" ? d.weekday_ar : d.weekday_en}
                  </span>
                  <span
                    className={cx(
                      "num text-[15px] font-bold leading-tight",
                      d.is_today && "text-accent",
                    )}
                  >
                    {d.day}
                  </span>
                  <span className="text-[10.5px] text-muted leading-tight">
                    {locale === "ar" ? d.month_ar : d.date.slice(5, 7)}
                  </span>
                </div>
              ))}
            </div>

            {/* المجموعات */}
            {data.categories.map((cat) => (
              <div key={cat.id}>
                {/* صف الفئة — الاسم والإتاحة اليومية */}
                <div
                  className="flex bg-surface-3 border-b border-line"
                  style={{ height: GROUP_H }}
                >
                  <div
                    className="sticky z-20 bg-surface-3 border-e border-line flex items-center gap-2 px-3"
                    style={{ width: LABEL_W, insetInlineStart: 0 }}
                  >
                    <span className="text-[13px] font-bold truncate">
                      {locale === "ar" ? cat.name_ar : cat.name_en}
                    </span>
                    <span className="num text-[11.5px] text-ink-2 ms-auto shrink-0">
                      {cat.sold_today}/{cat.unit_count}
                    </span>
                  </div>
                  {data.days.map((d) => {
                    const cell = availability.get(`${cat.id}|${d.date}`);
                    const free = cell?.available ?? 0;
                    return (
                      <div
                        key={d.date}
                        className={cx(
                          "shrink-0 grid place-items-center border-e border-line",
                          d.is_weekend && "bg-surface-2/60",
                        )}
                        style={{ width: DAY_W }}
                        title={
                          cell?.closed
                            ? t("tape.full")
                            : `${free} ${t("tape.free")}`
                        }
                      >
                        <span
                          className={cx(
                            "num text-[12px] font-bold px-1.5 rounded-full leading-5",
                            cell?.closed || free <= 0
                              ? "bg-bad/15 text-bad"
                              : free <= 2
                                ? "bg-warn/15 text-warn"
                                : "text-ink-2",
                          )}
                        >
                          {free}
                        </span>
                      </div>
                    );
                  })}
                </div>

                {/* الوحدات */}
                {cat.units.map((unit) => {
                  const bars = barsByUnit.get(unit.id) ?? [];
                  const isTarget = dropTarget === unit.id;
                  return (
                    <div
                      key={unit.id}
                      className="flex border-b border-line bg-surface"
                      style={{ height: ROW_H }}
                    >
                      {/* اسم الوحدة */}
                      <div
                        className={cx(
                          "sticky z-20 bg-surface border-e border-line flex items-center gap-2 px-3",
                          !unit.is_sellable && "opacity-60",
                        )}
                        style={{ width: LABEL_W, insetInlineStart: 0 }}
                      >
                        <span
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ background: HK_COLOR[unit.housekeeping_status] }}
                          title={t(`hk.${unit.housekeeping_status}`, unit.housekeeping_status)}
                        />
                        <span
                          className={cx(
                            "num text-[13px] font-bold",
                            !unit.is_sellable && "line-through text-muted",
                          )}
                        >
                          {unit.label}
                        </span>
                        <span className="text-[11px] text-muted truncate ms-auto">
                          {locale === "ar" ? unit.zone_ar : unit.zone_en}
                        </span>
                        {!unit.is_sellable && (
                          <IconLock size={12} className="text-muted shrink-0" />
                        )}
                      </div>

                      {/* المسار */}
                      <div
                        className={cx("relative flex-1", !unit.is_sellable && "hatched")}
                        style={
                          isTarget
                            ? { boxShadow: "inset 0 0 0 2px var(--accent)" }
                            : undefined
                        }
                        onDragOver={(e) => {
                          if (!unit.is_sellable) return;
                          e.preventDefault();
                          e.dataTransfer.dropEffect = "move";
                          if (dropTarget !== unit.id) setDropTarget(unit.id);
                        }}
                        onDragLeave={() => setDropTarget((v) => (v === unit.id ? null : v))}
                        onDrop={(e) => onDrop(e, unit.id)}
                      >
                        {/* خلفية الأيام */}
                        <div className="absolute inset-0 flex pointer-events-none">
                          {data.days.map((d) => (
                            <div
                              key={d.date}
                              className={cx(
                                "shrink-0 border-e border-line",
                                d.is_weekend && "bg-surface-2/45",
                                d.is_today && "bg-accent-soft/45",
                              )}
                              style={{ width: DAY_W }}
                            />
                          ))}
                        </div>

                        {/* الشرائط */}
                        {bars.map((bar) => (
                          <BarView
                            key={bar.id}
                            bar={bar}
                            rangeStart={data.start_date}
                            rangeEnd={data.end_date}
                            dim={!!term && !matches(bar)}
                            draggable={canMove}
                            onDragStart={(e) => onDragStart(e, bar)}
                            onDragEnd={() => setDropTarget(null)}
                            onClick={() => setSelected(bar.reservation_id)}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── رسالة النتيجة */}
      {toast && (
        <div
          className={cx(
            "fixed bottom-5 left-1/2 -translate-x-1/2 z-50",
            "rounded-[6px] px-4 py-2.5 text-[13.5px] font-bold border shadow-lg",
            toast.tone === "good"
              ? "bg-good text-white border-good"
              : "bg-bad text-white border-bad",
          )}
          role="status"
          onClick={() => setToast(null)}
        >
          {toast.text}
        </div>
      )}

      <NewReservation
        open={booking}
        onClose={() => setBooking(false)}
        onCreated={(id) => {
          setSelected(id);
          setToast({ tone: "good", text: t("book.created") });
        }}
      />

      <ReservationDrawer reservationId={selected} onClose={() => setSelected(null)} />
    </>
  );
}

/* ═══════════════════════════════════════════════════ الشريط الواحد */
function BarView({
  bar,
  rangeStart,
  rangeEnd,
  dim,
  draggable,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  bar: Bar;
  rangeStart: string;
  rangeEnd: string;
  dim: boolean;
  draggable: boolean;
  onDragStart: (e: DragEvent<HTMLDivElement>) => void;
  onDragEnd: () => void;
  onClick: () => void;
}) {
  const { t } = useI18n();

  // الوصول والمغادرة بينزلوا نص خانة، فالحجزين المتتاليين مبيلزقوش في بعض
  const clipStart = bar.arrival_date < rangeStart;
  const clipEnd = bar.departure_date > rangeEnd;
  const lead = clipStart ? 0 : DAY_W * 0.3;
  const tail = clipEnd ? 0 : DAY_W * 0.3;
  const width = bar.span * DAY_W - lead - tail;

  const balance = Number(bar.balance);
  const isOta = OTA_SOURCES.has(bar.source);
  const wide = width > 150;

  return (
    <div
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      title={`${bar.code} · ${bar.guest_name} · ${bar.nights} ${t("tape.nights")}`}
      className={cx(
        "absolute flex items-center gap-1.5 px-2 rounded-[4px] text-white overflow-hidden",
        "border border-black/10",
        draggable && "cursor-grab active:cursor-grabbing",
        dim && "opacity-25",
        clipStart && "rounded-s-none",
        clipEnd && "rounded-e-none",
      )}
      style={{
        insetInlineStart: bar.start_index * DAY_W + lead,
        width,
        top: 3,
        height: ROW_H - 7,
        background: STATUS_COLOR[bar.status],
      }}
    >
      {bar.is_vip && <span className="text-[11px] leading-none shrink-0">★</span>}
      <span className="text-[12px] font-bold truncate flex-1 min-w-0">{bar.guest_name}</span>
      {wide && (
        <span className="num text-[10.5px] opacity-75 shrink-0">{bar.code.slice(-6)}</span>
      )}
      {width > 100 && (
        <span
          className={cx(
            "text-[9.5px] font-bold rounded-sm px-1 leading-4 shrink-0",
            isOta ? "bg-white/30" : "bg-black/20",
          )}
        >
          {SOURCE_SHORT[bar.source] ?? bar.source.slice(0, 2)}
        </span>
      )}
      {balance > 0 && (
        <span
          className="w-1.5 h-1.5 rounded-full bg-white shrink-0"
          title={`${t("tape.balanceDue")} — ${balance.toFixed(2)}`}
        />
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════ الدليل */
function Legend() {
  const { t } = useI18n();
  const items = [
    ["CONFIRMED", STATUS_COLOR.CONFIRMED],
    ["CHECKED_IN", STATUS_COLOR.CHECKED_IN],
    ["TENTATIVE", STATUS_COLOR.TENTATIVE],
    ["CHECKED_OUT", STATUS_COLOR.CHECKED_OUT],
  ] as const;
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {items.map(([code, color]) => (
        <span key={code} className="flex items-center gap-1.5 text-[11.5px] text-ink-2">
          <span className="w-3 h-3 rounded-[3px]" style={{ background: color }} />
          {t(`status.${code}`)}
        </span>
      ))}
      <span className="flex items-center gap-1.5 text-[11.5px] text-ink-2">
        <span className="w-3 h-3 rounded-[3px] hatched border border-line" />
        {t("tape.ooo")}
      </span>
    </div>
  );
}
