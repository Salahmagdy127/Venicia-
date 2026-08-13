/** حجز جديد — التسعيرة ليلة بليلة، والنزيل، والعربون، في شاشة واحدة. */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { addDays, formatDate, money, parseDate, toISO, weekdayName } from "@/lib/format";
import type { Guest, GuestPage, Quote, RatePlan, UnitCategoryOut } from "@/lib/types";
import { Button, Loading, cx, inputClass } from "./ui";
import { IconCheck, IconSearch, IconX } from "./Icons";

const SOURCES = ["DIRECT", "WALK_IN", "WEBSITE", "TRAVEL_AGENT", "CORPORATE"] as const;
const ID_TYPES = ["NATIONAL_ID", "PASSPORT", "DRIVING_LICENSE"] as const;

export default function NewReservation({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (reservationId: number) => void;
}) {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const cur = locale === "ar" ? "ج.م" : "EGP";

  /* ── الإقامة ─────────────────────────────────────────── */
  const [arrival, setArrival] = useState(() => toISO(new Date()));
  const [departure, setDeparture] = useState(() => toISO(addDays(new Date(), 2)));
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [ratePlanId, setRatePlanId] = useState<number | null>(null);
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(0);
  const [source, setSource] = useState<string>("DIRECT");
  const [notes, setNotes] = useState("");
  const [deposit, setDeposit] = useState(0);

  /* ── النزيل ──────────────────────────────────────────── */
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [term, setTerm] = useState("");
  const [guest, setGuest] = useState<Guest | null>(null);
  const [draft, setDraft] = useState({
    first_name: "",
    last_name: "",
    phone: "",
    id_type: "NATIONAL_ID" as string,
    id_number: "",
    nationality: "EG",
    city: "",
    whatsapp_opt_in: true,
  });

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setGuest(null);
    setTerm("");
    setMode("existing");
    setNotes("");
    setDeposit(0);
  }, [open]);

  /* ── المراجع ─────────────────────────────────────────── */
  const categories = useQuery({
    queryKey: ["unit-categories"],
    queryFn: () => get<UnitCategoryOut[]>("/unit-categories"),
    enabled: open,
    staleTime: 10 * 60_000,
  });
  const plans = useQuery({
    queryKey: ["rate-plans"],
    queryFn: () => get<RatePlan[]>("/rate-plans"),
    enabled: open,
    staleTime: 10 * 60_000,
  });

  useEffect(() => {
    if (categoryId === null && categories.data?.length) setCategoryId(categories.data[0].id);
  }, [categories.data, categoryId]);
  useEffect(() => {
    if (ratePlanId === null && plans.data?.length) setRatePlanId(plans.data[0].id);
  }, [plans.data, ratePlanId]);

  /* ── التسعيرة ────────────────────────────────────────── */
  const nights = useMemo(() => {
    const a = parseDate(arrival).getTime();
    const d = parseDate(departure).getTime();
    return Math.round((d - a) / 86_400_000);
  }, [arrival, departure]);

  const canQuote = categoryId !== null && ratePlanId !== null && nights > 0;

  const quote = useQuery({
    queryKey: ["quote", categoryId, ratePlanId, arrival, departure, adults, children],
    queryFn: () =>
      get<Quote>(
        `/quote${qs({
          unit_category_id: categoryId,
          rate_plan_id: ratePlanId,
          arrival_date: arrival,
          departure_date: departure,
          adults,
          children,
        })}`,
      ),
    enabled: open && canQuote,
  });

  /* ── بحث النزلاء ─────────────────────────────────────── */
  const guests = useQuery({
    queryKey: ["guests", "pick", term],
    queryFn: () => get<GuestPage>(`/guests${qs({ search: term, limit: 8 })}`),
    enabled: open && mode === "existing" && term.trim().length >= 2,
  });

  /* ── الحفظ ───────────────────────────────────────────── */
  const create = useMutation({
    mutationFn: async () => {
      let guestId = guest?.id;
      if (mode === "new") {
        const created = await post<Guest>("/guests", {
          ...draft,
          phone: draft.phone || null,
          id_number: draft.id_number || null,
          city: draft.city || null,
        });
        guestId = created.id;
      }
      if (!guestId) throw new Error("no guest");

      return post<{ id: number; code: string }>("/reservations", {
        guest_id: guestId,
        unit_category_id: categoryId,
        rate_plan_id: ratePlanId,
        arrival_date: arrival,
        departure_date: departure,
        adults,
        children,
        source,
        special_requests: notes || null,
        deposit_paid: deposit,
      });
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["tape-chart"] });
      qc.invalidateQueries({ queryKey: ["front-desk"] });
      qc.invalidateQueries({ queryKey: ["guests"] });
      onCreated(res.id);
      onClose();
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  if (!open) return null;

  const q = quote.data;
  const guestReady =
    mode === "existing"
      ? guest !== null
      : draft.first_name.trim().length > 1 && draft.last_name.trim().length > 1;
  const ready = canQuote && !!q?.is_available && guestReady && !create.isPending;

  return (
    <div className="fixed inset-0 z-50 bg-black/45 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-surface border border-line rounded-[8px] w-full max-w-[1000px] max-h-[92vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <header className="shrink-0 px-5 py-3.5 border-b border-line flex items-center">
          <h2 className="text-[16px] font-bold">{t("book.new")}</h2>
          <button
            onClick={onClose}
            aria-label={t("action.close")}
            className="ms-auto w-8 h-8 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2"
          >
            <IconX size={18} />
          </button>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto grid grid-cols-1 lg:grid-cols-2">
          {/* ═══════════════════ يمين: الإقامة والتسعيرة */}
          <section className="p-5 border-b lg:border-b-0 lg:border-e border-line flex flex-col gap-4">
            <h3 className="text-[13px] font-bold text-muted">{t("book.stay")}</h3>

            <div className="grid grid-cols-2 gap-3">
              <Field label={t("book.arrival")}>
                <input
                  type="date"
                  className={`${inputClass} num`}
                  value={arrival}
                  onChange={(e) => {
                    setArrival(e.target.value);
                    if (e.target.value >= departure) {
                      setDeparture(toISO(addDays(parseDate(e.target.value), 1)));
                    }
                  }}
                />
              </Field>
              <Field label={t("book.departure")}>
                <input
                  type="date"
                  className={`${inputClass} num`}
                  value={departure}
                  min={toISO(addDays(parseDate(arrival), 1))}
                  onChange={(e) => setDeparture(e.target.value)}
                />
              </Field>
            </div>

            <Field label={t("book.category")}>
              <select
                className={inputClass}
                value={categoryId ?? ""}
                onChange={(e) => setCategoryId(Number(e.target.value))}
              >
                {categories.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {locale === "ar" ? c.name_ar : c.name_en} · {c.unit_count} {t("set.units")}
                  </option>
                ))}
              </select>
            </Field>

            <Field label={t("book.ratePlan")}>
              <select
                className={inputClass}
                value={ratePlanId ?? ""}
                onChange={(e) => setRatePlanId(Number(e.target.value))}
              >
                {plans.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {locale === "ar" ? p.name_ar : p.name_en}
                  </option>
                ))}
              </select>
            </Field>

            <div className="grid grid-cols-3 gap-3">
              <Field label={t("book.adults")}>
                <input
                  type="number"
                  min={1}
                  className={`${inputClass} num`}
                  value={adults}
                  onChange={(e) => setAdults(Math.max(1, Number(e.target.value)))}
                />
              </Field>
              <Field label={t("book.children")}>
                <input
                  type="number"
                  min={0}
                  className={`${inputClass} num`}
                  value={children}
                  onChange={(e) => setChildren(Math.max(0, Number(e.target.value)))}
                />
              </Field>
              <Field label={t("book.source")}>
                <select
                  className={inputClass}
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {t(`source.${s}`, s)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            {/* ── التسعيرة ليلة بليلة */}
            <div className="mt-1">
              <div className="flex items-baseline justify-between mb-2">
                <h3 className="text-[13px] font-bold text-muted">{t("book.perNight")}</h3>
                {q && (
                  <span
                    className={cx(
                      "text-[12px] font-bold rounded-full px-2 py-0.5",
                      q.is_available ? "bg-good/12 text-good" : "bg-bad/12 text-bad",
                    )}
                  >
                    <span className="num">{q.available}</span> {t("book.available")}
                  </span>
                )}
              </div>

              {quote.isLoading && <Loading />}
              {quote.isError && (
                <div className="text-[13px] text-bad">{t("book.notAvailable")}</div>
              )}

              {q && (
                <div className="border border-line rounded-[6px] divide-y divide-line max-h-[190px] overflow-y-auto">
                  {q.nights_detail.map((n) => {
                    const d = parseDate(n.stay_date);
                    const raised = Number(n.rate) > Number(n.published_rate);
                    return (
                      <div key={n.stay_date} className="flex items-center gap-2 px-3 py-1.5">
                        <span className="num text-[12px] text-muted w-[86px] shrink-0">
                          {formatDate(n.stay_date, locale)}
                        </span>
                        <span className="text-[11.5px] text-muted w-[42px] shrink-0">
                          {weekdayName(d, locale)}
                        </span>
                        <div className="flex-1 flex flex-wrap gap-1 min-w-0">
                          {n.applied_rules.map((r) => (
                            <span
                              key={r}
                              className="text-[10px] font-bold rounded-full bg-surface-2 text-ink-2 px-1.5 leading-4"
                            >
                              {t(`book.rule.${r}`, r)}
                            </span>
                          ))}
                        </div>
                        {raised && (
                          <span className="num text-[11px] text-muted line-through shrink-0">
                            {money(n.published_rate, 0)}
                          </span>
                        )}
                        <span
                          className={cx(
                            "num text-[13px] font-bold shrink-0 w-[64px] text-end",
                            raised && "text-gold",
                          )}
                        >
                          {money(n.rate, 0)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>

          {/* ═══════════════════ شمال: النزيل والملخّص */}
          <section className="p-5 flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <h3 className="text-[13px] font-bold text-muted">{t("book.guest")}</h3>
              <div className="ms-auto flex items-center rounded-[6px] border border-line-strong overflow-hidden">
                <Tab active={mode === "existing"} onClick={() => setMode("existing")}>
                  {t("book.existingGuest")}
                </Tab>
                <Tab active={mode === "new"} onClick={() => setMode("new")}>
                  {t("book.newGuest")}
                </Tab>
              </div>
            </div>

            {mode === "existing" ? (
              <div className="flex flex-col gap-2">
                {guest ? (
                  <div className="flex items-center gap-2 border border-accent rounded-[6px] px-3 py-2.5 bg-accent-soft">
                    <IconCheck size={16} className="text-accent shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-bold truncate">{guest.full_name}</div>
                      <div className="num text-[11.5px] text-muted">
                        {guest.phone ?? "—"} · {guest.total_stays} {t("guest.stays")}
                      </div>
                    </div>
                    <button
                      onClick={() => setGuest(null)}
                      className="text-[12px] text-accent font-bold shrink-0"
                    >
                      {t("action.cancel")}
                    </button>
                  </div>
                ) : (
                  <>
                    <label className="relative flex items-center">
                      <span className="absolute start-0 ps-2.5 text-muted pointer-events-none">
                        <IconSearch size={15} />
                      </span>
                      <input
                        className={`${inputClass} ps-8`}
                        placeholder={t("book.searchGuest")}
                        value={term}
                        onChange={(e) => setTerm(e.target.value)}
                      />
                    </label>
                    {term.trim().length >= 2 && (
                      <div className="border border-line rounded-[6px] divide-y divide-line max-h-[180px] overflow-y-auto">
                        {guests.isLoading && <Loading />}
                        {guests.data?.items.length === 0 && (
                          <div className="px-3 py-3 text-[13px] text-muted">
                            {t("state.empty")}
                          </div>
                        )}
                        {guests.data?.items.map((g) => (
                          <button
                            key={g.id}
                            onClick={() => setGuest(g)}
                            className="w-full text-start px-3 py-2 hover:bg-surface-2 flex items-center gap-2"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="text-[13px] font-bold truncate">{g.full_name}</div>
                              <div className="num text-[11.5px] text-muted">{g.phone ?? "—"}</div>
                            </div>
                            {g.total_stays > 1 && (
                              <span className="text-[10.5px] font-bold rounded-full bg-accent-soft text-accent px-1.5 shrink-0">
                                {t("folio.returning")}
                              </span>
                            )}
                            {g.is_vip && (
                              <span className="text-[10.5px] font-bold rounded-full bg-gold-soft text-gold px-1.5 shrink-0">
                                VIP
                              </span>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                <Field label={t("book.firstName")}>
                  <input
                    className={inputClass}
                    value={draft.first_name}
                    onChange={(e) => setDraft({ ...draft, first_name: e.target.value })}
                  />
                </Field>
                <Field label={t("book.lastName")}>
                  <input
                    className={inputClass}
                    value={draft.last_name}
                    onChange={(e) => setDraft({ ...draft, last_name: e.target.value })}
                  />
                </Field>
                <Field label={t("guest.phone")}>
                  <input
                    className={`${inputClass} num`}
                    value={draft.phone}
                    onChange={(e) => setDraft({ ...draft, phone: e.target.value })}
                  />
                </Field>
                <Field label={t("book.idType")}>
                  <select
                    className={inputClass}
                    value={draft.id_type}
                    onChange={(e) => setDraft({ ...draft, id_type: e.target.value })}
                  >
                    {ID_TYPES.map((k) => (
                      <option key={k} value={k}>
                        {t(`id.${k}`, k)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={t("book.idNumber")}>
                  <input
                    className={`${inputClass} num`}
                    value={draft.id_number}
                    onChange={(e) => setDraft({ ...draft, id_number: e.target.value })}
                  />
                </Field>
                <Field label={t("guest.city")}>
                  <input
                    className={inputClass}
                    value={draft.city}
                    onChange={(e) => setDraft({ ...draft, city: e.target.value })}
                  />
                </Field>
              </div>
            )}

            <Field label={t("book.notes")}>
              <input
                className={inputClass}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </Field>

            {/* ── الملخّص المالي */}
            <div className="mt-auto border border-line rounded-[6px] divide-y divide-line">
              <Row label={t("res.roomTotal")} value={money(q?.room_total ?? 0)} />
              {Number(q?.extras_total ?? 0) > 0 && (
                <Row label={t("res.guests")} value={money(q?.extras_total ?? 0)} />
              )}
              <Row label={t("res.service")} value={money(q?.service_charge_total ?? 0)} />
              <Row label={t("res.tax")} value={money(q?.tax_total ?? 0)} />
              <div className="flex items-baseline justify-between px-3 py-2.5">
                <span className="text-[14px] font-bold">{t("res.grandTotal")}</span>
                <span className="num text-[22px] font-bold text-accent">
                  {money(q?.grand_total ?? 0)}{" "}
                  <span className="text-[12px] opacity-70">{cur}</span>
                </span>
              </div>
              <div className="flex items-center justify-between px-3 py-2 text-[12px] text-muted">
                <span>
                  <span className="num">{nights}</span>{" "}
                  {nights === 1 ? t("tape.night") : t("tape.nights")} ·{" "}
                  {t("book.avgNight")}
                </span>
                <span className="num font-bold">{money(q?.average_nightly_rate ?? 0, 0)}</span>
              </div>
            </div>

            <Field label={`${t("book.deposit")} — ${t("book.depositHint")}`}>
              <input
                type="number"
                min={0}
                className={`${inputClass} num`}
                value={deposit}
                onChange={(e) => setDeposit(Math.max(0, Number(e.target.value)))}
              />
            </Field>

            {error && (
              <div className="rounded-[6px] border border-bad/40 bg-bad/10 text-bad text-[13px] px-3.5 py-2.5">
                {error}
              </div>
            )}

            <p className="text-[11.5px] text-muted leading-relaxed">
              {t("book.unassignedNote")}
            </p>
          </section>
        </div>

        <footer className="shrink-0 px-5 py-3.5 border-t border-line flex items-center gap-2">
          <span className="text-[12.5px] text-muted">
            {!guestReady && t("book.pickGuest")}
            {guestReady && q && !q.is_available && t("book.notAvailable")}
          </span>
          <div className="flex-1" />
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button variant="primary" disabled={!ready} onClick={() => create.mutate()}>
            {create.isPending ? "…" : t("book.confirm")}
          </Button>
        </footer>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────── مساعدات */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[12.5px] font-bold text-ink-2">{label}</span>
      {children}
    </label>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5">
      <span className="text-[12.5px] text-ink-2">{label}</span>
      <span className="num text-[13px] font-bold">{value}</span>
    </div>
  );
}

function Tab({
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
        "h-8 px-2.5 text-[12px] font-bold border-e border-line-strong last:border-e-0",
        active ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
      )}
    >
      {children}
    </button>
  );
}
