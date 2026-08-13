/** شاشة الكاشير — تصميم الصالة + المنيو + الأوردر، كلهم في شاشة واحدة. */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatTime, money } from "@/lib/format";
import type {
  FloorPlan,
  InHouse,
  Menu,
  MenuItem,
  Outlet,
  PosOrder,
  PosTable,
  Shift,
} from "@/lib/types";
import PageHeader from "@/components/PageHeader";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Modal,
  cx,
  inputClass,
} from "@/components/ui";
import { IconPlus, IconSearch, IconSend, IconTrash, IconX } from "@/components/Icons";

const SHIFT_KEY = "venicia.shift";

export default function Pos() {
  const { t, locale } = useI18n();
  const { can, maxDiscount } = useAuth();
  const qc = useQueryClient();

  const [outletId, setOutletId] = useState<number | null>(null);
  const [orderId, setOrderId] = useState<number | null>(null);
  const [shiftId, setShiftId] = useState<number | null>(() => {
    const raw = localStorage.getItem(SHIFT_KEY);
    return raw ? Number(raw) : null;
  });
  const [openTable, setOpenTable] = useState<PosTable | null>(null);
  const [modal, setModal] = useState<"settle" | "discount" | "shift" | null>(null);
  const [voidLine, setVoidLine] = useState<number | null>(null);
  const [toast, setToast] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const say = (tone: "good" | "bad", text: string) => {
    setToast({ tone, text });
    window.setTimeout(() => setToast(null), 3200);
  };
  const fail = (err: unknown) =>
    say("bad", err instanceof ApiError ? err.text(locale) : t("state.error"));

  /* ── البيانات ─────────────────────────────────────────── */
  const outlets = useQuery({
    queryKey: ["pos", "outlets"],
    queryFn: () => get<Outlet[]>("/pos/outlets"),
  });

  useEffect(() => {
    if (outletId === null && outlets.data?.length) setOutletId(outlets.data[0].id);
  }, [outlets.data, outletId]);

  const outlet = outlets.data?.find((o) => o.id === outletId) ?? null;

  const floor = useQuery({
    queryKey: ["pos", "floor", outletId],
    queryFn: () => get<FloorPlan>(`/pos/outlets/${outletId}/floor-plan`),
    enabled: outletId !== null,
    refetchInterval: 20_000,
  });

  const menu = useQuery({
    queryKey: ["pos", "menu", outletId],
    queryFn: () => get<Menu>(`/pos/outlets/${outletId}/menu`),
    enabled: outletId !== null,
    staleTime: 5 * 60_000,
  });

  const order = useQuery({
    queryKey: ["pos", "order", orderId],
    queryFn: () => get<PosOrder>(`/pos/orders/${orderId}`),
    enabled: orderId !== null,
  });

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["pos", "floor"] });
    qc.invalidateQueries({ queryKey: ["pos", "order"] });
  };

  /* ── الإجراءات ────────────────────────────────────────── */
  const createOrder = useMutation({
    mutationFn: (v: { table_id: number; covers: number }) =>
      post<PosOrder>("/pos/orders", {
        outlet_id: outletId,
        table_id: v.table_id,
        covers: v.covers,
        shift_id: shiftId,
      }),
    onSuccess: (o) => {
      setOrderId(o.id);
      setOpenTable(null);
      refreshAll();
    },
    onError: fail,
  });

  const addLine = useMutation({
    mutationFn: (item: MenuItem) =>
      post<PosOrder>(`/pos/orders/${orderId}/lines`, {
        menu_item_id: item.id,
        quantity: 1,
      }),
    onSuccess: (o) => {
      qc.setQueryData(["pos", "order", orderId], o);
      qc.invalidateQueries({ queryKey: ["pos", "floor"] });
    },
    onError: fail,
  });

  const doVoid = useMutation({
    mutationFn: (v: { lineId: number; reason: string }) =>
      post<PosOrder>(`/pos/orders/${orderId}/lines/${v.lineId}/void`, { reason: v.reason }),
    onSuccess: (o) => {
      qc.setQueryData(["pos", "order", orderId], o);
      setVoidLine(null);
      refreshAll();
    },
    onError: fail,
  });

  const send = useMutation({
    mutationFn: () => post<PosOrder>(`/pos/orders/${orderId}/send`),
    onSuccess: (o) => {
      qc.setQueryData(["pos", "order", orderId], o);
      say("good", t("pos.sentToKitchen"));
    },
    onError: fail,
  });

  const discount = useMutation({
    mutationFn: (v: { percent: number; reason: string }) =>
      post<PosOrder>(`/pos/orders/${orderId}/discount`, v),
    onSuccess: (o) => {
      qc.setQueryData(["pos", "order", orderId], o);
      setModal(null);
    },
    onError: fail,
  });

  const settle = useMutation({
    mutationFn: (v: { settlement: string; folio_id?: number | null }) =>
      post<PosOrder>(`/pos/orders/${orderId}/settle`, { ...v, shift_id: shiftId }),
    onSuccess: () => {
      setModal(null);
      setOrderId(null);
      refreshAll();
      say("good", t("pos.settled"));
    },
    onError: fail,
  });

  const openShift = useMutation({
    mutationFn: (opening_float: number) =>
      post<Shift>("/pos/shifts/open", { outlet_id: outletId, opening_float }),
    onSuccess: (s) => {
      setShiftId(s.id);
      localStorage.setItem(SHIFT_KEY, String(s.id));
      setModal(null);
    },
    onError: fail,
  });

  const closeShift = useMutation({
    mutationFn: (v: { counted_cash: number; counted_card: number }) =>
      post<Shift>(`/pos/shifts/${shiftId}/close`, v),
    onSuccess: (s) => {
      setShiftId(null);
      localStorage.removeItem(SHIFT_KEY);
      setModal(null);
      const v = Number(s.variance);
      say(
        Math.abs(v) < 0.01 ? "good" : "bad",
        `${t("pos.variance")}: ${money(s.variance)} ${locale === "ar" ? "ج.م" : "EGP"}`,
      );
    },
    onError: fail,
  });

  const current = order.data ?? null;
  const canSell = can("pos.order");

  return (
    <>
      <PageHeader
        title={t("nav.pos")}
        subtitle={
          floor.data
            ? `${locale === "ar" ? floor.data.name_ar : floor.data.name_en} · ${floor.data.occupied}/${floor.data.total} ${t("pos.occupied")}`
            : "—"
        }
      >
        <select
          value={outletId ?? ""}
          onChange={(e) => {
            setOutletId(Number(e.target.value));
            setOrderId(null);
          }}
          className="h-9 px-2.5 rounded-[6px] bg-surface border border-line-strong text-[13.5px] outline-none focus:border-accent"
          aria-label={t("pos.outlet")}
        >
          {outlets.data?.map((o) => (
            <option key={o.id} value={o.id}>
              {locale === "ar" ? o.name_ar : o.name_en}
            </option>
          ))}
        </select>

        {shiftId === null ? (
          <Button size="sm" onClick={() => setModal("shift")}>
            {t("pos.openShift")}
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setModal("shift")}>
            {t("pos.shift")} <span className="num">#{shiftId}</span>
          </Button>
        )}
      </PageHeader>

      <div className="flex-1 min-h-0 flex gap-4 p-4 overflow-hidden">
        {/* ── تصميم الصالة */}
        <Card
          className="w-[360px] shrink-0"
          title={t("pos.floorPlan")}
          padded={false}
          action={
            floor.data && (
              <span className="num text-[12.5px] text-muted">
                {floor.data.occupied}/{floor.data.total}
              </span>
            )
          }
        >
          {floor.isLoading && <Loading />}
          {floor.isError && <ErrorState onRetry={() => floor.refetch()} />}
          {floor.data && floor.data.tables.length === 0 && <EmptyState />}
          {floor.data && floor.data.tables.length > 0 && (
            <FloorPlanView
              tables={floor.data.tables}
              activeOrderId={orderId}
              onPick={(tbl) => {
                if (tbl.open_order_id) setOrderId(tbl.open_order_id);
                else if (canSell) setOpenTable(tbl);
              }}
            />
          )}
        </Card>

        {/* ── المنيو */}
        <MenuPanel
          menu={menu.data}
          loading={menu.isLoading}
          disabled={!current || current.status === "SETTLED" || !canSell}
          onPick={(item) => addLine.mutate(item)}
        />

        {/* ── الأوردر */}
        <TicketPanel
          order={current}
          outlet={outlet}
          onVoid={(lineId) => setVoidLine(lineId)}
          onSend={() => send.mutate()}
          onDiscount={() => setModal("discount")}
          onSettle={() => setModal("settle")}
          busy={send.isPending || settle.isPending}
        />
      </div>

      {/* ── فتح طاولة */}
      <CoversModal
        table={openTable}
        onClose={() => setOpenTable(null)}
        onConfirm={(covers) =>
          openTable && createOrder.mutate({ table_id: openTable.id, covers })
        }
        busy={createOrder.isPending}
      />

      {/* ── إلغاء صنف */}
      <ReasonModal
        open={voidLine !== null}
        title={t("pos.void")}
        label={t("pos.voidReason")}
        confirmLabel={t("folio.void")}
        danger
        busy={doVoid.isPending}
        onClose={() => setVoidLine(null)}
        onConfirm={(reason) => voidLine !== null && doVoid.mutate({ lineId: voidLine, reason })}
      />

      {/* ── خصم */}
      <DiscountModal
        open={modal === "discount"}
        max={maxDiscount}
        busy={discount.isPending}
        onClose={() => setModal(null)}
        onConfirm={(percent, reason) => discount.mutate({ percent, reason })}
      />

      {/* ── تحصيل */}
      <SettleModal
        open={modal === "settle"}
        order={current}
        allowRoomCharge={!!outlet?.allows_room_charge}
        busy={settle.isPending}
        onClose={() => setModal(null)}
        onConfirm={(settlement, folioId) =>
          settle.mutate({ settlement, folio_id: folioId ?? null })
        }
      />

      {/* ── الوردية */}
      <ShiftModal
        open={modal === "shift"}
        shiftId={shiftId}
        busy={openShift.isPending || closeShift.isPending}
        onClose={() => setModal(null)}
        onOpen={(f) => openShift.mutate(f)}
        onClose_={(cash, card) => closeShift.mutate({ counted_cash: cash, counted_card: card })}
      />

      {toast && (
        <div
          className={cx(
            "fixed bottom-5 left-1/2 -translate-x-1/2 z-50 rounded-[6px] px-4 py-2.5",
            "text-[13.5px] font-bold text-white shadow-lg",
            toast.tone === "good" ? "bg-good" : "bg-bad",
          )}
          role="status"
        >
          {toast.text}
        </div>
      )}
    </>
  );
}

/* ═══════════════════════════════════════════════ تصميم الصالة */
function FloorPlanView({
  tables,
  activeOrderId,
  onPick,
}: {
  tables: PosTable[];
  activeOrderId: number | null;
  onPick: (t: PosTable) => void;
}) {
  const { t, locale } = useI18n();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  const bounds = useMemo(() => {
    const w = Math.max(...tables.map((x) => x.pos_x + x.width), 1) + 24;
    const h = Math.max(...tables.map((x) => x.pos_y + x.height), 1) + 24;
    return { w, h };
  }, [tables]);

  // المناطق بتترسم كإطار متقطع ورا الطاولات، فالكاشير يعرف هو فين
  const zones = useMemo(() => {
    const map = new Map<string, { x1: number; y1: number; x2: number; y2: number; name: string }>();
    for (const tbl of tables) {
      const name = (locale === "ar" ? tbl.zone_ar : tbl.zone_en) || "";
      if (!name) continue;
      const box = map.get(name);
      if (!box) {
        map.set(name, {
          x1: tbl.pos_x,
          y1: tbl.pos_y,
          x2: tbl.pos_x + tbl.width,
          y2: tbl.pos_y + tbl.height,
          name,
        });
      } else {
        box.x1 = Math.min(box.x1, tbl.pos_x);
        box.y1 = Math.min(box.y1, tbl.pos_y);
        box.x2 = Math.max(box.x2, tbl.pos_x + tbl.width);
        box.y2 = Math.max(box.y2, tbl.pos_y + tbl.height);
      }
    }
    return [...map.values()];
  }, [tables, locale]);

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const fit = () => setScale(Math.min(1.6, (el.clientWidth - 4) / bounds.w));
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [bounds.w]);

  return (
    <div ref={wrapRef} className="h-full overflow-auto p-2" dir="ltr">
      <div
        className="relative"
        style={{ width: bounds.w * scale, height: bounds.h * scale }}
      >
        <div
          className="absolute top-0 left-0 origin-top-left"
          style={{ width: bounds.w, height: bounds.h, transform: `scale(${scale})` }}
        >
          {zones.map((z) => (
            <div
              key={z.name}
              className="absolute border border-dashed border-line-strong rounded-[8px]"
              style={{
                left: z.x1 - 14,
                top: z.y1 - 20,
                width: z.x2 - z.x1 + 28,
                height: z.y2 - z.y1 + 34,
              }}
            >
              <span
                className="absolute -top-2 left-2 px-1.5 bg-surface text-[10px] font-bold text-muted"
                dir="auto"
              >
                {z.name}
              </span>
            </div>
          ))}

          {tables.map((tbl) => {
            const busy = tbl.open_order_id !== null;
            const active = busy && tbl.open_order_id === activeOrderId;
            return (
              <button
                key={tbl.id}
                onClick={() => onPick(tbl)}
                title={`${t("pos.table")} ${tbl.label} · ${tbl.seats} ${t("pos.seats")}`}
                className={cx(
                  "absolute flex flex-col items-center justify-center gap-0.5 border-2 transition-colors",
                  tbl.shape === "ROUND" ? "rounded-full" : "rounded-[6px]",
                  active
                    ? "bg-accent border-accent text-accent-ink"
                    : busy
                      ? "bg-accent-soft border-accent text-accent"
                      : "bg-surface border-line-strong text-ink-2 hover:border-accent",
                )}
                style={{
                  left: tbl.pos_x,
                  top: tbl.pos_y,
                  width: tbl.width,
                  height: tbl.height,
                }}
              >
                <span className="num text-[13px] font-bold leading-none">{tbl.label}</span>
                {busy ? (
                  <span className="num text-[9.5px] leading-none opacity-90">
                    {money(tbl.open_order_total ?? 0, 0)}
                  </span>
                ) : (
                  <span className="num text-[9.5px] leading-none opacity-70">{tbl.seats}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════ المنيو */
function MenuPanel({
  menu,
  loading,
  disabled,
  onPick,
}: {
  menu: Menu | undefined;
  loading: boolean;
  disabled: boolean;
  onPick: (item: MenuItem) => void;
}) {
  const { t, locale } = useI18n();
  const [cat, setCat] = useState<number | "all">("all");
  const [term, setTerm] = useState("");

  const items = useMemo(() => {
    if (!menu) return [];
    const all = menu.categories.flatMap((c) =>
      c.items.map((i) => ({ ...i, catName: locale === "ar" ? c.name_ar : c.name_en })),
    );
    const q = term.trim().toLowerCase();
    return all.filter(
      (i) =>
        (cat === "all" || i.category_id === cat) &&
        (!q ||
          i.name_ar.toLowerCase().includes(q) ||
          i.name_en.toLowerCase().includes(q) ||
          i.code.toLowerCase().includes(q)),
    );
  }, [menu, cat, term, locale]);

  return (
    <section className="flex-1 min-w-0 bg-surface border border-line rounded-[8px] flex flex-col">
      <header className="shrink-0 px-4 py-3 border-b border-line flex items-center gap-3">
        <h2 className="text-[15px] font-bold shrink-0">{t("pos.menu")}</h2>
        <label className="relative flex items-center flex-1 max-w-[280px]">
          <span className="absolute start-0 ps-2.5 text-muted pointer-events-none">
            <IconSearch size={15} />
          </span>
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder={t("pos.searchItem")}
            className="h-8 w-full ps-8 pe-3 rounded-[6px] bg-surface border border-line-strong text-[13px] outline-none focus:border-accent"
          />
        </label>
        <span className="num text-[12px] text-muted ms-auto">{items.length}</span>
      </header>

      {/* تبويبات الأقسام */}
      <div className="shrink-0 flex gap-1 px-3 py-2 border-b border-line overflow-x-auto">
        <CatTab active={cat === "all"} onClick={() => setCat("all")}>
          {t("pos.all")}
        </CatTab>
        {menu?.categories.map((c) => (
          <CatTab key={c.id} active={cat === c.id} onClick={() => setCat(c.id)}>
            {locale === "ar" ? c.name_ar : c.name_en}
          </CatTab>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        {loading && <Loading />}
        {!loading && items.length === 0 && <EmptyState />}
        <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(152px,1fr))]">
          {items.map((item) => {
            const off = item.is_out_of_stock || !item.is_available;
            return (
              <button
                key={item.id}
                disabled={disabled || off}
                onClick={() => onPick(item)}
                className={cx(
                  "text-start rounded-[6px] border p-2.5 flex flex-col gap-1 min-h-[76px]",
                  "transition-colors",
                  off
                    ? "border-line bg-surface-2/60 opacity-55 cursor-not-allowed"
                    : disabled
                      ? "border-line opacity-55 cursor-not-allowed"
                      : "border-line hover:border-accent hover:bg-accent-soft/50",
                )}
              >
                <span className="text-[13px] font-bold leading-snug">
                  {locale === "ar" ? item.name_ar : item.name_en}
                </span>
                <div className="mt-auto flex items-center justify-between gap-1">
                  <span className="num text-[13px] font-bold text-accent">
                    {money(item.price, 0)}
                  </span>
                  <div className="flex items-center gap-1">
                    {item.is_vegetarian && (
                      <span
                        className="w-2 h-2 rounded-full bg-good"
                        title={t("pos.vegetarian")}
                      />
                    )}
                    {item.contains_alcohol && (
                      <span className="w-2 h-2 rounded-full bg-warn" title={t("pos.alcohol")} />
                    )}
                  </div>
                </div>
                {off && (
                  <span className="text-[10.5px] text-bad font-bold">{t("pos.outOfStock")}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function CatTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cx(
        "shrink-0 h-8 px-3 rounded-full text-[12.5px] font-bold whitespace-nowrap border",
        active
          ? "bg-accent text-accent-ink border-accent"
          : "border-line text-ink-2 hover:bg-surface-2",
      )}
    >
      {children}
    </button>
  );
}

/* ═════════════════════════════════════════════════ ورقة الأوردر */
function TicketPanel({
  order,
  outlet,
  onVoid,
  onSend,
  onDiscount,
  onSettle,
  busy,
}: {
  order: PosOrder | null;
  outlet: Outlet | null;
  onVoid: (lineId: number) => void;
  onSend: () => void;
  onDiscount: () => void;
  onSettle: () => void;
  busy: boolean;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const cur = locale === "ar" ? "ج.م" : "EGP";

  if (!order) {
    return (
      <section className="w-[380px] shrink-0 bg-surface border border-line rounded-[8px] grid place-items-center">
        <EmptyState title={t("pos.noOpenTable")} hint={t("pos.pickTable")} />
      </section>
    );
  }

  const lines = order.lines.filter((l) => !l.is_void);
  const voided = order.lines.filter((l) => l.is_void);
  const hasNew = lines.some((l) => l.kot_status === "NEW");
  const settled = order.status === "SETTLED";

  return (
    <section className="w-[380px] shrink-0 bg-surface border border-line rounded-[8px] flex flex-col">
      <header className="shrink-0 px-4 py-3 border-b border-line">
        <div className="flex items-center gap-2">
          <span className="num text-[15px] font-bold">{order.code}</span>
          {order.table_label && (
            <span className="text-[12px] font-bold rounded-full bg-accent-soft text-accent px-2 py-0.5">
              {t("pos.table")} <span className="num">{order.table_label}</span>
            </span>
          )}
          <span className="num text-[12px] text-muted ms-auto">{formatTime(order.opened_at)}</span>
        </div>
        <div className="text-[12px] text-muted mt-0.5">
          <span className="num">{order.covers}</span> {t("pos.covers")}
          {order.unit_label && (
            <>
              {" · "}
              {t("pos.roomCharge")} <span className="num">{order.unit_label}</span>
            </>
          )}
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {lines.length === 0 && <EmptyState title={t("pos.emptyOrder")} />}
        <ul className="m-0 p-0 list-none">
          {lines.map((l) => (
            <li
              key={l.id}
              className="flex items-start gap-2 px-4 py-2.5 border-b border-line last:border-b-0"
            >
              <span className="num text-[13px] font-bold w-6 shrink-0 pt-0.5">
                {Number(l.quantity)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] leading-snug">
                  {locale === "ar" ? l.item_name_ar : l.item_name_en || l.item_name_ar}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="num text-[11.5px] text-muted">{money(l.unit_price)}</span>
                  <span
                    className={cx(
                      "text-[10.5px] font-bold rounded-full px-1.5",
                      l.kot_status === "NEW"
                        ? "bg-surface-2 text-muted"
                        : "bg-good/12 text-good",
                    )}
                  >
                    {l.kot_status === "NEW" ? t("pos.kotNew") : t("pos.kotSent")}
                  </span>
                </div>
              </div>
              <span className="num text-[13.5px] font-bold shrink-0">{money(l.line_total)}</span>
              {!settled && can("pos.void") && (
                <button
                  onClick={() => onVoid(l.id)}
                  aria-label={t("pos.void")}
                  className="w-7 h-7 grid place-items-center rounded-[6px] text-muted hover:text-bad hover:bg-bad/10 shrink-0"
                >
                  <IconTrash size={15} />
                </button>
              )}
            </li>
          ))}
        </ul>

        {voided.length > 0 && (
          <div className="px-4 py-2 border-t border-line">
            <div className="text-[11.5px] font-bold text-muted mb-1">{t("folio.voided")}</div>
            {voided.map((l) => (
              <div key={l.id} className="flex items-center gap-2 text-[12px] text-muted">
                <span className="num">{Number(l.quantity)}</span>
                <span className="line-through truncate">{l.item_name_ar}</span>
                {l.voided_after_send && (
                  <span className="text-[10px] font-bold text-bad shrink-0">
                    {t("dash.voids")}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* الإجماليات */}
      <div className="shrink-0 border-t border-line px-4 py-3 flex flex-col gap-1">
        <TotalRow label={t("pos.subtotal")} value={order.subtotal} />
        {Number(order.discount_total) > 0 && (
          <TotalRow
            label={`${t("pos.discount")} ${Number(order.discount_percent)}%`}
            value={`-${order.discount_total}`}
            tone="bad"
          />
        )}
        <TotalRow
          label={`${t("pos.service")} ${Number(outlet?.service_charge_percent ?? 0)}%`}
          value={order.service_charge_total}
        />
        <TotalRow
          label={`${t("pos.tax")} ${Number(outlet?.vat_percent ?? 0)}%`}
          value={order.tax_total}
        />
        <div className="flex items-baseline justify-between gap-2 pt-1.5 mt-1 border-t border-line">
          <span className="text-[14px] font-bold">{t("pos.total")}</span>
          <span className="num text-[22px] font-bold text-accent">
            {money(order.grand_total)} <span className="text-[12px] opacity-70">{cur}</span>
          </span>
        </div>
      </div>

      {!settled && (
        <footer className="shrink-0 border-t border-line p-3 grid grid-cols-2 gap-2">
          <Button
            variant="secondary"
            disabled={!hasNew || busy}
            onClick={onSend}
            className="col-span-2"
          >
            <IconSend size={16} />
            {t("pos.sendKitchen")}
          </Button>
          {can("pos.discount") && (
            <Button variant="ghost" onClick={onDiscount} disabled={lines.length === 0}>
              {t("pos.applyDiscount")}
            </Button>
          )}
          <Button
            variant="primary"
            onClick={onSettle}
            disabled={lines.length === 0 || busy}
            className={can("pos.discount") ? "" : "col-span-2"}
          >
            {t("pos.settle")}
          </Button>
        </footer>
      )}
    </section>
  );
}

function TotalRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bad";
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[12.5px] text-ink-2">{label}</span>
      <span className={cx("num text-[13px] font-bold", tone === "bad" && "text-bad")}>
        {money(value)}
      </span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════ النوافذ */
function CoversModal({
  table,
  onClose,
  onConfirm,
  busy,
}: {
  table: PosTable | null;
  onClose: () => void;
  onConfirm: (covers: number) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const [covers, setCovers] = useState(2);

  useEffect(() => {
    if (table) setCovers(Math.min(table.seats, 2) || 1);
  }, [table]);

  return (
    <Modal
      open={table !== null}
      onClose={onClose}
      title={`${t("pos.openTable")} ${table?.label ?? ""}`}
      width={340}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button variant="primary" disabled={busy} onClick={() => onConfirm(covers)}>
            {t("pos.newOrder")}
          </Button>
        </>
      }
    >
      <div className="text-[13px] text-muted mb-3">{t("pos.newOrderCovers")}</div>
      <div className="flex items-center justify-center gap-4">
        <button
          onClick={() => setCovers((c) => Math.max(1, c - 1))}
          className="w-11 h-11 rounded-[6px] border border-line-strong grid place-items-center hover:bg-surface-2"
          aria-label="-"
        >
          <IconX size={16} className="rotate-45" />
        </button>
        <span className="num text-[34px] font-bold w-16 text-center">{covers}</span>
        <button
          onClick={() => setCovers((c) => Math.min(table?.seats ?? 12, c + 1))}
          className="w-11 h-11 rounded-[6px] border border-line-strong grid place-items-center hover:bg-surface-2"
          aria-label="+"
        >
          <IconPlus size={18} />
        </button>
      </div>
      <div className="text-center text-[12px] text-muted mt-2 num">
        {table?.seats} {t("pos.seats")}
      </div>
    </Modal>
  );
}

function ReasonModal({
  open,
  title,
  label,
  confirmLabel,
  danger,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  title: string;
  label: string;
  confirmLabel: string;
  danger?: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) setReason("");
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      width={380}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button
            variant={danger ? "danger" : "primary"}
            disabled={busy || reason.trim().length < 2}
            onClick={() => onConfirm(reason.trim())}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-bold text-ink-2">{label}</span>
        <input
          className={inputClass}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
      </label>
    </Modal>
  );
}

function DiscountModal({
  open,
  max,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  max: number;
  busy: boolean;
  onClose: () => void;
  onConfirm: (percent: number, reason: string) => void;
}) {
  const { t } = useI18n();
  const [percent, setPercent] = useState(10);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) {
      setPercent(Math.min(10, max));
      setReason("");
    }
  }, [open, max]);

  const steps = [5, 10, 15, 20, 25].filter((s) => s <= max);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("pos.applyDiscount")}
      width={380}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy || reason.trim().length < 2 || percent <= 0 || percent > max}
            onClick={() => onConfirm(percent, reason.trim())}
          >
            {t("action.confirm")}
          </Button>
        </>
      }
    >
      <div className="text-[12.5px] text-muted mb-3">
        {t("pos.maxDiscount")}: <span className="num font-bold">{max}%</span>
      </div>
      <div className="flex gap-1.5 mb-4">
        {steps.map((s) => (
          <button
            key={s}
            onClick={() => setPercent(s)}
            className={cx(
              "num h-9 flex-1 rounded-[6px] border text-[13.5px] font-bold",
              percent === s
                ? "bg-accent text-accent-ink border-accent"
                : "border-line-strong text-ink-2 hover:bg-surface-2",
            )}
          >
            {s}%
          </button>
        ))}
      </div>
      <label className="flex flex-col gap-1.5 mb-3">
        <span className="text-[13px] font-bold text-ink-2">{t("pos.discountPercent")}</span>
        <input
          type="number"
          min={0}
          max={max}
          className={`${inputClass} num`}
          value={percent}
          onChange={(e) => setPercent(Number(e.target.value))}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-bold text-ink-2">{t("pos.discountReason")}</span>
        <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
    </Modal>
  );
}

function SettleModal({
  open,
  order,
  allowRoomCharge,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  order: PosOrder | null;
  allowRoomCharge: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: (settlement: string, folioId?: number | null) => void;
}) {
  const { t, locale } = useI18n();
  const [mode, setMode] = useState<string | null>(null);
  const [term, setTerm] = useState("");
  const [folioId, setFolioId] = useState<number | null>(null);

  useEffect(() => {
    if (open) {
      setMode(null);
      setTerm("");
      setFolioId(null);
    }
  }, [open]);

  const inHouse = useQuery({
    queryKey: ["pos", "in-house", term],
    queryFn: () => get<InHouse[]>(`/pos/in-house${qs({ search: term })}`),
    enabled: open && mode === "ROOM_CHARGE",
  });

  const options = [
    { key: "CASH", label: t("pos.cash") },
    { key: "CARD", label: t("pos.card") },
    ...(allowRoomCharge ? [{ key: "ROOM_CHARGE", label: t("pos.roomCharge") }] : []),
    { key: "CITY_LEDGER", label: t("pos.cityLedger") },
  ];

  const ready = mode !== null && (mode !== "ROOM_CHARGE" || folioId !== null);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("pos.settleTitle")}
      width={440}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={!ready || busy}
            onClick={() => mode && onConfirm(mode, folioId)}
          >
            {t("pos.settle")}
          </Button>
        </>
      }
    >
      <div className="flex items-baseline justify-between mb-4 pb-3 border-b border-line">
        <span className="text-[14px] font-bold">{t("pos.total")}</span>
        <span className="num text-[26px] font-bold text-accent">
          {money(order?.grand_total ?? 0)}{" "}
          <span className="text-[13px] opacity-70">{locale === "ar" ? "ج.م" : "EGP"}</span>
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-4">
        {options.map((o) => (
          <button
            key={o.key}
            onClick={() => setMode(o.key)}
            className={cx(
              "h-12 rounded-[6px] border text-[14px] font-bold",
              mode === o.key
                ? "bg-accent text-accent-ink border-accent"
                : "border-line-strong text-ink hover:bg-surface-2",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>

      {mode === "ROOM_CHARGE" && (
        <div className="flex flex-col gap-2">
          <label className="relative flex items-center">
            <span className="absolute start-0 ps-2.5 text-muted pointer-events-none">
              <IconSearch size={15} />
            </span>
            <input
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder={t("pos.searchRoom")}
              className={`${inputClass} ps-8`}
            />
          </label>
          <div className="max-h-[220px] overflow-y-auto border border-line rounded-[6px] divide-y divide-line">
            {inHouse.isLoading && <Loading />}
            {inHouse.data?.length === 0 && <EmptyState />}
            {inHouse.data?.map((h) => (
              <button
                key={h.folio_id}
                onClick={() => setFolioId(h.folio_id)}
                className={cx(
                  "w-full text-start px-3 py-2 flex items-center gap-2",
                  folioId === h.folio_id ? "bg-accent-soft" : "hover:bg-surface-2",
                )}
              >
                <span className="num text-[13.5px] font-bold w-14 shrink-0">
                  {h.unit_label ?? "—"}
                </span>
                <span className="text-[13px] truncate flex-1">{h.guest_name}</span>
                <span className="num text-[12px] text-muted shrink-0">{money(h.balance, 0)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}

function ShiftModal({
  open,
  shiftId,
  busy,
  onClose,
  onOpen,
  onClose_,
}: {
  open: boolean;
  shiftId: number | null;
  busy: boolean;
  onClose: () => void;
  onOpen: (openingFloat: number) => void;
  onClose_: (cash: number, card: number) => void;
}) {
  const { t } = useI18n();
  const [float_, setFloat] = useState(1000);
  const [cash, setCash] = useState(0);
  const [card, setCard] = useState(0);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={shiftId === null ? t("pos.openShift") : t("pos.closeShift")}
      width={380}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => (shiftId === null ? onOpen(float_) : onClose_(cash, card))}
          >
            {t("action.confirm")}
          </Button>
        </>
      }
    >
      {shiftId === null ? (
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-bold text-ink-2">{t("pos.openingFloat")}</span>
          <input
            type="number"
            className={`${inputClass} num`}
            value={float_}
            onChange={(e) => setFloat(Number(e.target.value))}
          />
        </label>
      ) : (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-bold text-ink-2">{t("pos.countedCash")}</span>
            <input
              type="number"
              className={`${inputClass} num`}
              value={cash}
              onChange={(e) => setCash(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-bold text-ink-2">{t("pos.countedCard")}</span>
            <input
              type="number"
              className={`${inputClass} num`}
              value={card}
              onChange={(e) => setCard(Number(e.target.value))}
            />
          </label>
        </div>
      )}
    </Modal>
  );
}
