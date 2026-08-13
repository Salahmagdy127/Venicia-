/** قائمة الانتظار — مين مستنّي، ومين بقى فيه له مكان، وتحويله لحجز. */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { addDays, formatDateShort, money, parseDate, toISO } from "@/lib/format";
import type {
  GuestPage,
  RatePlan,
  UnitCategoryOut,
  WaitlistItem,
  WaitlistPage,
  WaitlistPriority,
  WaitlistResult,
} from "@/lib/types";
import { Button, EmptyState, Loading, Modal, Pill, cx, inputClass } from "./ui";
import { IconCheck, IconPlus, IconSearch, IconWarning, IconX } from "./Icons";

const PRIORITIES: WaitlistPriority[] = ["NORMAL", "HIGH", "VIP"];

const PRIORITY_TONE: Record<WaitlistPriority, "muted" | "gold" | "accent"> = {
  NORMAL: "muted",
  HIGH: "gold",
  VIP: "accent",
};

export default function Waitlist() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [adding, setAdding] = useState(false);
  const [offering, setOffering] = useState<WaitlistItem | null>(null);
  const [converting, setConverting] = useState<WaitlistItem | null>(null);
  const [flash, setFlash] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const page = useQuery({
    queryKey: ["waitlist"],
    queryFn: () => get<WaitlistPage>("/waitlist"),
    // العروض بتنتهي بالوقت، فالقايمة بتتحدّث لوحدها كل دقيقة
    refetchInterval: 60_000,
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["waitlist"] });
    qc.invalidateQueries({ queryKey: ["inventory"] });
    qc.invalidateQueries({ queryKey: ["tape-chart"] });
  }

  const act = useMutation({
    mutationFn: ({ id, action, body }: { id: number; action: string; body?: unknown }) =>
      post<WaitlistResult>(`/waitlist/${id}/${action}`, body ?? {}),
    onSuccess: (r) => {
      setFlash({ tone: "good", text: locale === "ar" ? r.message_ar : r.message_en });
      setOffering(null);
      setConverting(null);
      refresh();
    },
    onError: (err) =>
      setFlash({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      }),
  });

  const items = page.data?.items ?? [];
  const canEdit = can("reservation.edit");
  const canCreate = can("reservation.create");

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="shrink-0 px-5 py-3 border-b border-line flex items-center gap-4">
        <p className="text-[12.5px] text-muted max-w-[62ch] leading-relaxed">{t("wl.subtitle")}</p>
        <div className="flex-1" />
        {page.data && (
          <div className="flex items-center gap-4 text-[12.5px]">
            <Count label={t("wl.waitingCount")} value={page.data.waiting_count} />
            <Count label={t("wl.offeredCount")} value={page.data.offered_count} tone="gold" />
            <Count
              label={t("wl.readyCount")}
              value={page.data.ready_count}
              tone={page.data.ready_count > 0 ? "good" : "muted"}
            />
          </div>
        )}
        {canCreate && (
          <Button variant="primary" onClick={() => setAdding(true)}>
            <IconPlus size={16} />
            {t("wl.add")}
          </Button>
        )}
      </div>

      {flash && (
        <div
          className={cx(
            "shrink-0 mx-5 mt-3 rounded-[6px] px-3.5 py-2 text-[12.5px] font-bold border flex items-center gap-2",
            flash.tone === "good"
              ? "border-good/40 bg-good/10 text-good"
              : "border-bad/40 bg-bad/10 text-bad",
          )}
        >
          {flash.tone === "good" ? <IconCheck size={14} /> : <IconWarning size={14} />}
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} aria-label={t("action.close")}>
            <IconX size={14} />
          </button>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-auto">
        {page.isLoading && <Loading />}
        {!page.isLoading && items.length === 0 && (
          <EmptyState title={t("wl.empty")} hint={t("wl.emptyHint")} />
        )}

        {items.length > 0 && (
          <table className="w-full border-collapse text-[13px]">
            <thead className="sticky top-0 bg-surface z-10">
              <tr className="text-muted text-[12px]">
                <Th className="text-start ps-5">{t("wl.priority")}</Th>
                <Th className="text-start">{t("wl.guest")}</Th>
                <Th className="text-start">{t("wl.category")}</Th>
                <Th className="text-start">{t("wl.dates")}</Th>
                <Th className="text-end">{t("wl.quoted")}</Th>
                <Th className="text-start">{t("wl.status")}</Th>
                <Th className="text-end pe-5" />
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="hover:bg-surface-2/50 align-top">
                  <td className="px-3 ps-5 py-3 border-b border-line">
                    <Pill tone={PRIORITY_TONE[e.priority]}>{t(`wl.${e.priority}`)}</Pill>
                  </td>

                  <td className="px-3 py-3 border-b border-line">
                    <div className="font-bold flex items-center gap-1.5">
                      {e.guest_name}
                      {e.is_vip && <span className="text-gold text-[11px]">★</span>}
                    </div>
                    {e.guest_phone && (
                      <div className="num text-[11.5px] text-muted" dir="ltr">
                        {e.guest_phone}
                      </div>
                    )}
                    {e.contact_note && (
                      <div className="text-[11.5px] text-muted mt-0.5">{e.contact_note}</div>
                    )}
                  </td>

                  <td className="px-3 py-3 border-b border-line text-ink-2">
                    {locale === "ar" ? e.category_name_ar : e.category_name_en}
                    <div className="num text-[11.5px] text-muted">
                      {e.adults + e.children} {locale === "ar" ? "فرد" : "pax"}
                    </div>
                  </td>

                  <td className="px-3 py-3 border-b border-line">
                    <span className="num">
                      {formatDateShort(e.arrival_date, locale)} →{" "}
                      {formatDateShort(e.departure_date, locale)}
                    </span>
                    <div className="text-[11.5px] text-muted">
                      <span className="num">{e.nights}</span> {t("tape.nights")}
                      {" · "}
                      {e.flexible_days > 0
                        ? t("wl.flexDays").replace("{n}", String(e.flexible_days))
                        : t("wl.exact")}
                    </div>
                  </td>

                  <td className="num text-end px-3 py-3 border-b border-line font-bold">
                    {money(e.quoted_total, 0)}
                  </td>

                  <td className="px-3 py-3 border-b border-line">
                    <StatusCell entry={e} />
                  </td>

                  <td className="px-3 pe-5 py-3 border-b border-line">
                    <div className="flex items-center justify-end gap-1.5 flex-wrap">
                      {e.status === "WAITING" && e.has_match && canEdit && (
                        <Button size="sm" variant="primary" onClick={() => setOffering(e)}>
                          {t("wl.offerShort")}
                        </Button>
                      )}
                      {(e.status === "OFFERED" || (e.status === "WAITING" && e.has_match)) &&
                        canCreate && (
                          <Button size="sm" onClick={() => setConverting(e)}>
                            {t("wl.convert")}
                          </Button>
                        )}
                      {e.status === "OFFERED" && canEdit && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={act.isPending}
                          onClick={() => act.mutate({ id: e.id, action: "withdraw" })}
                        >
                          {t("wl.withdraw")}
                        </Button>
                      )}
                      {canEdit && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={act.isPending}
                          onClick={() => act.mutate({ id: e.id, action: "cancel" })}
                        >
                          {t("wl.remove")}
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <AddDialog open={adding} onClose={() => setAdding(false)} onDone={refresh} />

      <OfferDialog
        entry={offering}
        pending={act.isPending}
        onClose={() => setOffering(null)}
        onConfirm={(hours) =>
          offering && act.mutate({ id: offering.id, action: "offer", body: { hours } })
        }
      />

      <ConvertDialog
        entry={converting}
        pending={act.isPending}
        onClose={() => setConverting(null)}
        onConfirm={(body) =>
          converting && act.mutate({ id: converting.id, action: "convert", body })
        }
      />
    </div>
  );
}

/* ─────────────────────────────────────────────── خلية الحالة */
function StatusCell({ entry }: { entry: WaitlistItem }) {
  const { t, locale } = useI18n();

  if (entry.status === "OFFERED") {
    return (
      <div className="flex flex-col gap-1">
        <Pill tone="gold">{t("wl.OFFERED")}</Pill>
        {entry.offered_arrival && (
          <span className="num text-[11.5px] text-muted">
            {t("wl.offeredDates")} {formatDateShort(entry.offered_arrival, locale)}
          </span>
        )}
        {entry.offer_expires_at && <Countdown until={entry.offer_expires_at} />}
      </div>
    );
  }

  if (entry.status === "CONVERTED") {
    return (
      <div className="flex flex-col gap-1">
        <Pill tone="good">{t("wl.CONVERTED")}</Pill>
        {entry.converted_reservation_code && (
          <span className="num text-[11.5px] text-muted">{entry.converted_reservation_code}</span>
        )}
      </div>
    );
  }

  if (entry.status !== "WAITING") {
    return <Pill tone="muted">{t(`wl.${entry.status}`)}</Pill>;
  }

  if (!entry.has_match) {
    return (
      <div className="flex flex-col gap-1">
        <Pill tone="muted">{t("wl.WAITING")}</Pill>
        <span className="text-[11.5px] text-muted">{t("wl.waitingOn")}</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <Pill tone="good">
        <IconCheck size={12} />
        {t("wl.ready")}
      </Pill>
      {entry.match_arrival && (
        <span className="num text-[11.5px] text-good">
          {formatDateShort(entry.match_arrival, locale)}
          {!!entry.match_shift_days && (
            <span className="text-muted ms-1">
              {t("wl.shifted").replace("{n}", String(entry.match_shift_days))}
            </span>
          )}
        </span>
      )}
    </div>
  );
}

/** الوقت الباقي على العرض — بيعد لوحده كل نص دقيقة. */
function Countdown({ until }: { until: string }) {
  const { t } = useI18n();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const left = new Date(until).getTime() - now;
  if (left <= 0) return <span className="text-[11.5px] text-bad font-bold">{t("wl.expired")}</span>;

  const hours = Math.floor(left / 3_600_000);
  const minutes = Math.floor((left % 3_600_000) / 60_000);
  return (
    <span className={cx("num text-[11.5px] font-bold", hours < 3 ? "text-warn" : "text-muted")}>
      {t("wl.expiresIn")} {hours}:{`${minutes}`.padStart(2, "0")}
    </span>
  );
}

function Count({
  label,
  value,
  tone = "muted",
}: {
  label: string;
  value: number;
  tone?: "muted" | "gold" | "good";
}) {
  const color = tone === "good" ? "text-good" : tone === "gold" ? "text-gold" : "text-ink";
  return (
    <span className="flex items-center gap-1.5">
      <span className={cx("num text-[15px] font-bold", color)}>{value}</span>
      <span className="text-muted">{label}</span>
    </span>
  );
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}

/* ──────────────────────────────────────────── نافذة العرض */
function OfferDialog({
  entry,
  pending,
  onClose,
  onConfirm,
}: {
  entry: WaitlistItem | null;
  pending: boolean;
  onClose: () => void;
  onConfirm: (hours: number) => void;
}) {
  const { t, locale } = useI18n();
  const [hours, setHours] = useState(24);

  return (
    <Modal
      open={!!entry}
      onClose={onClose}
      title={t("wl.offer")}
      footer={
        <>
          <Button onClick={onClose}>{t("action.cancel")}</Button>
          <Button variant="primary" disabled={pending} onClick={() => onConfirm(hours)}>
            {t("action.confirm")}
          </Button>
        </>
      }
    >
      {entry && (
        <>
          <p className="text-[13px] mb-1">
            <span className="font-bold">{entry.guest_name}</span>
            {entry.guest_phone && (
              <span className="num text-muted ms-2" dir="ltr">
                {entry.guest_phone}
              </span>
            )}
          </p>
          <p className="num text-[13px] text-ink-2 mb-4">
            {formatDateShort(entry.match_arrival ?? entry.arrival_date, locale)} →{" "}
            {formatDateShort(entry.match_departure ?? entry.departure_date, locale)}
          </p>

          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-bold text-ink-2">{t("wl.offerHours")}</span>
            <div className="flex items-center gap-2">
              {[6, 12, 24, 48].map((h) => (
                <button
                  key={h}
                  onClick={() => setHours(h)}
                  className={cx(
                    "num h-9 px-3 rounded-[6px] text-[13px] font-bold border",
                    hours === h
                      ? "bg-accent text-accent-ink border-transparent"
                      : "border-line-strong text-ink-2 hover:bg-surface-2",
                  )}
                >
                  {h}
                </button>
              ))}
            </div>
          </label>

          <p className="text-[12px] text-muted leading-relaxed mt-3">{t("wl.holdNote")}</p>
        </>
      )}
    </Modal>
  );
}

/* ─────────────────────────────────────────── نافذة التحويل */
function ConvertDialog({
  entry,
  pending,
  onClose,
  onConfirm,
}: {
  entry: WaitlistItem | null;
  pending: boolean;
  onClose: () => void;
  onConfirm: (body: { rate_plan_id: number | null; deposit_paid: number }) => void;
}) {
  const { t, locale } = useI18n();
  const [planId, setPlanId] = useState<number | null>(null);
  const [deposit, setDeposit] = useState("");

  const plans = useQuery({
    queryKey: ["rate-plans"],
    queryFn: () => get<RatePlan[]>("/rate-plans"),
    enabled: !!entry,
    staleTime: 10 * 60_000,
  });

  useEffect(() => {
    if (entry) {
      setPlanId(entry.rate_plan_id ?? plans.data?.[0]?.id ?? null);
      setDeposit("");
    }
  }, [entry, plans.data]);

  return (
    <Modal
      open={!!entry}
      onClose={onClose}
      title={t("wl.convert")}
      footer={
        <>
          <Button onClick={onClose}>{t("action.cancel")}</Button>
          <Button
            variant="primary"
            disabled={pending || planId === null}
            onClick={() => onConfirm({ rate_plan_id: planId, deposit_paid: Number(deposit) || 0 })}
          >
            {t("action.confirm")}
          </Button>
        </>
      }
    >
      {entry && (
        <>
          <p className="text-[13px] font-bold mb-1">{entry.guest_name}</p>
          <p className="num text-[13px] text-ink-2 mb-4">
            {formatDateShort(entry.offered_arrival ?? entry.match_arrival ?? entry.arrival_date, locale)}{" "}
            →{" "}
            {formatDateShort(
              entry.offered_departure ?? entry.match_departure ?? entry.departure_date,
              locale,
            )}{" "}
            · {locale === "ar" ? entry.category_name_ar : entry.category_name_en}
          </p>

          <label className="flex flex-col gap-1.5 mb-4">
            <span className="text-[13px] font-bold text-ink-2">{t("set.ratePlans")}</span>
            <select
              className={inputClass}
              value={planId ?? ""}
              onChange={(e) => setPlanId(Number(e.target.value))}
            >
              {(plans.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {locale === "ar" ? p.name_ar : p.name_en}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-bold text-ink-2">{t("book.deposit")}</span>
            <input
              type="number"
              min={0}
              className={cx(inputClass, "num")}
              value={deposit}
              onChange={(e) => setDeposit(e.target.value)}
              placeholder="0"
            />
          </label>
        </>
      )}
    </Modal>
  );
}

/* ────────────────────────────────────── نافذة الطلب الجديد */
function AddDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t, locale } = useI18n();

  const [term, setTerm] = useState("");
  const [guest, setGuest] = useState<{ id: number; name: string } | null>(null);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [arrival, setArrival] = useState(() => toISO(addDays(new Date(), 7)));
  const [departure, setDeparture] = useState(() => toISO(addDays(new Date(), 9)));
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(0);
  const [flex, setFlex] = useState(0);
  const [priority, setPriority] = useState<WaitlistPriority>("NORMAL");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTerm("");
    setGuest(null);
    setNote("");
    setError(null);
    setPriority("NORMAL");
    setFlex(0);
  }, [open]);

  const categories = useQuery({
    queryKey: ["unit-categories"],
    queryFn: () => get<UnitCategoryOut[]>("/unit-categories"),
    enabled: open,
    staleTime: 10 * 60_000,
  });

  useEffect(() => {
    if (categoryId === null && categories.data?.length) setCategoryId(categories.data[0].id);
  }, [categories.data, categoryId]);

  const guests = useQuery({
    queryKey: ["guests", "waitlist-pick", term],
    queryFn: () => get<GuestPage>(`/guests${qs({ search: term, limit: 8 })}`),
    enabled: open && term.trim().length >= 2,
  });

  const nights = Math.max(
    0,
    Math.round((parseDate(departure).getTime() - parseDate(arrival).getTime()) / 86_400_000),
  );

  const create = useMutation({
    mutationFn: () =>
      post<WaitlistItem>("/waitlist", {
        guest_id: guest?.id,
        unit_category_id: categoryId,
        arrival_date: arrival,
        departure_date: departure,
        adults,
        children,
        flexible_days: flex,
        priority,
        contact_note: note.trim() || null,
      }),
    onSuccess: () => {
      onDone();
      onClose();
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const ready = guest !== null && categoryId !== null && nights > 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("wl.add")}
      width={520}
      footer={
        <>
          <Button onClick={onClose}>{t("action.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!ready || create.isPending}
            onClick={() => {
              setError(null);
              create.mutate();
            }}
          >
            {t("action.save")}
          </Button>
        </>
      }
    >
      {/* النزيل */}
      <div className="mb-4">
        <span className="text-[13px] font-bold text-ink-2 block mb-1.5">{t("wl.guest")}</span>
        {guest ? (
          <div className="flex items-center justify-between gap-2 h-10 px-3 rounded-[6px] border border-accent bg-accent-soft">
            <span className="text-[13px] font-bold text-accent">{guest.name}</span>
            <button onClick={() => setGuest(null)} aria-label={t("action.close")}>
              <IconX size={15} className="text-accent" />
            </button>
          </div>
        ) : (
          <>
            <div className="relative">
              <IconSearch
                size={16}
                className="absolute top-1/2 -translate-y-1/2 start-3 text-muted"
              />
              <input
                className={cx(inputClass, "ps-9")}
                placeholder={t("tape.searchPlaceholder")}
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                autoFocus
              />
            </div>
            {guests.data && term.trim().length >= 2 && (
              <div className="mt-1.5 border border-line rounded-[6px] max-h-[168px] overflow-y-auto">
                {guests.data.items.map((g) => (
                  <button
                    key={g.id}
                    onClick={() => setGuest({ id: g.id, name: g.full_name })}
                    className="w-full text-start px-3 py-2 hover:bg-surface-2 border-b border-line last:border-b-0"
                  >
                    <span className="text-[13px] font-bold">{g.full_name}</span>
                    {g.phone && (
                      <span className="num text-[11.5px] text-muted ms-2" dir="ltr">
                        {g.phone}
                      </span>
                    )}
                  </button>
                ))}
                {guests.data.items.length === 0 && (
                  <p className="px-3 py-2 text-[12.5px] text-muted">{t("state.empty")}</p>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* الفئة والتواريخ */}
      <label className="flex flex-col gap-1.5 mb-4">
        <span className="text-[13px] font-bold text-ink-2">{t("wl.category")}</span>
        <select
          className={inputClass}
          value={categoryId ?? ""}
          onChange={(e) => setCategoryId(Number(e.target.value))}
        >
          {(categories.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {locale === "ar" ? c.name_ar : c.name_en}
            </option>
          ))}
        </select>
      </label>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-bold text-ink-2">{t("inv.from")}</span>
          <input
            type="date"
            className={cx(inputClass, "num")}
            value={arrival}
            onChange={(e) => e.target.value && setArrival(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-bold text-ink-2">{t("inv.to")}</span>
          <input
            type="date"
            className={cx(inputClass, "num")}
            value={departure}
            onChange={(e) => e.target.value && setDeparture(e.target.value)}
          />
        </label>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-bold text-ink-2">{t("book.adults")}</span>
          <input
            type="number"
            min={1}
            className={cx(inputClass, "num")}
            value={adults}
            onChange={(e) => setAdults(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-bold text-ink-2">{t("book.children")}</span>
          <input
            type="number"
            min={0}
            className={cx(inputClass, "num")}
            value={children}
            onChange={(e) => setChildren(Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-bold text-ink-2">{t("wl.flex")}</span>
          <select
            className={cx(inputClass, "num")}
            value={flex}
            onChange={(e) => setFlex(Number(e.target.value))}
          >
            {[0, 1, 2, 3, 5, 7].map((n) => (
              <option key={n} value={n}>
                {n === 0 ? t("wl.exact") : `± ${n}`}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mb-4">
        <span className="text-[13px] font-bold text-ink-2 block mb-1.5">{t("wl.priority")}</span>
        <div className="flex items-center gap-2">
          {PRIORITIES.map((p) => (
            <button
              key={p}
              onClick={() => setPriority(p)}
              className={cx(
                "h-9 px-3.5 rounded-[6px] text-[13px] font-bold border",
                priority === p
                  ? "bg-accent text-accent-ink border-transparent"
                  : "border-line-strong text-ink-2 hover:bg-surface-2",
              )}
            >
              {t(`wl.${p}`)}
            </button>
          ))}
        </div>
      </div>

      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-bold text-ink-2">{t("wl.note")}</span>
        <input
          className={inputClass}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={500}
        />
      </label>

      {error && (
        <div className="mt-4 rounded-[6px] border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-[12.5px] text-bad">
          {error}
        </div>
      )}
    </Modal>
  );
}
