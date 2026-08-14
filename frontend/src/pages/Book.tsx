/** صفحة الحجز المباشر — الصفحة العامة على موقع القرية، بعمولة صفر. */

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import { addDays, formatDate, money, parseDate, toISO } from "@/lib/format";
import type { BookingOut, HoldOut, PublicProperty, SearchOut } from "@/lib/types";
import { Button, Spinner, cx, inputClass } from "@/components/ui";
import { IconCheck, IconGlobe, IconMoon, IconSun, IconWarning, IconWaves } from "@/components/Icons";

type Stage = "search" | "pick" | "details" | "done";

export default function Book() {
  const { t, locale, toggle: toggleLocale } = useI18n();
  const { theme, toggle: toggleTheme } = useTheme();
  const ar = locale === "ar";

  const [stage, setStage] = useState<Stage>("search");
  const [arrival, setArrival] = useState(() => toISO(addDays(new Date(), 7)));
  const [departure, setDeparture] = useState(() => toISO(addDays(new Date(), 10)));
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(0);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [hold, setHold] = useState<HoldOut | null>(null);
  const [booking, setBooking] = useState<BookingOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const property = useQuery({
    queryKey: ["book", "property"],
    queryFn: () => get<PublicProperty>("/book/property"),
    staleTime: 30 * 60_000,
  });

  const results = useQuery({
    queryKey: ["book", "search", submitted, adults, children],
    queryFn: () =>
      get<SearchOut>(
        `/book/search${qs({
          arrival_date: arrival,
          departure_date: departure,
          adults,
          children,
        })}`,
      ),
    enabled: submitted !== null,
    retry: false,
  });

  const takeHold = useMutation({
    mutationFn: (categoryId: number) =>
      post<HoldOut>("/book/hold", {
        unit_category_id: categoryId,
        arrival_date: arrival,
        departure_date: departure,
        adults,
        children,
      }),
    onSuccess: (h) => {
      setHold(h);
      setError(null);
      setStage("details");
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const nights = Math.max(
    0,
    Math.round((parseDate(departure).getTime() - parseDate(arrival).getTime()) / 86_400_000),
  );
  const cur = ar ? "ج.م" : "EGP";

  function runSearch() {
    setError(null);
    setBooking(null);
    setHold(null);
    setSubmitted(`${arrival}|${departure}`);
    setStage("pick");
  }

  const searchError =
    results.error instanceof ApiError ? results.error.text(locale) : null;

  return (
    <div className="min-h-screen bg-ground text-ink">
      {/* ── الترويسة */}
      <header className="border-b border-line bg-surface">
        <div className="max-w-[1100px] mx-auto px-5 h-16 flex items-center gap-3">
          <span className="w-9 h-9 rounded-[8px] bg-accent grid place-items-center shrink-0">
            <IconWaves size={20} className="text-accent-ink" />
          </span>
          <div className="min-w-0">
            <div className="text-[16px] font-bold leading-tight truncate">
              {property.data ? (ar ? property.data.name_ar : property.data.name_en) : "—"}
            </div>
            <div className="text-[11.5px] text-muted truncate">
              {property.data?.city ?? ""}
              {property.data?.phone && (
                <span className="num ms-2" dir="ltr">
                  {property.data.phone}
                </span>
              )}
            </div>
          </div>
          <div className="flex-1" />
          <button
            onClick={toggleLocale}
            className="w-9 h-9 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2"
            aria-label="Switch language"
          >
            <IconGlobe size={18} />
          </button>
          <button
            onClick={toggleTheme}
            className="w-9 h-9 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2"
            aria-label="Switch theme"
          >
            {theme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
          </button>
        </div>
      </header>

      <main className="max-w-[1100px] mx-auto px-5 py-8 flex flex-col gap-6">
        {stage !== "done" && (
          <>
            <div>
              <h1 className="text-[26px] font-bold leading-tight">{t("be.title")}</h1>
              <p className="text-[14px] text-muted mt-1">{t("be.subtitle")}</p>
            </div>

            {/* ── شريط البحث */}
            <section className="bg-surface border border-line rounded-[10px] p-5">
              <div className="grid gap-3 grid-cols-2 md:grid-cols-5">
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12.5px] font-bold text-ink-2">{t("book.arrival")}</span>
                  <input
                    type="date"
                    className={cx(inputClass, "num")}
                    value={arrival}
                    min={toISO(new Date())}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      setArrival(e.target.value);
                      if (e.target.value >= departure) {
                        setDeparture(toISO(addDays(parseDate(e.target.value), 2)));
                      }
                    }}
                  />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12.5px] font-bold text-ink-2">
                    {t("book.departure")}
                  </span>
                  <input
                    type="date"
                    className={cx(inputClass, "num")}
                    value={departure}
                    min={toISO(addDays(parseDate(arrival), 1))}
                    onChange={(e) => e.target.value && setDeparture(e.target.value)}
                  />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12.5px] font-bold text-ink-2">{t("book.adults")}</span>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    className={cx(inputClass, "num")}
                    value={adults}
                    onChange={(e) => setAdults(Math.max(1, Number(e.target.value) || 1))}
                  />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12.5px] font-bold text-ink-2">{t("book.children")}</span>
                  <input
                    type="number"
                    min={0}
                    max={8}
                    className={cx(inputClass, "num")}
                    value={children}
                    onChange={(e) => setChildren(Math.max(0, Number(e.target.value) || 0))}
                  />
                </label>
                <div className="flex flex-col justify-end">
                  <Button variant="primary" size="lg" onClick={runSearch} disabled={nights < 1}>
                    {t("be.search")}
                  </Button>
                </div>
              </div>
              {nights > 0 && (
                <p className="text-[12.5px] text-muted mt-3">
                  <span className="num font-bold">{nights}</span> {t("tape.nights")} ·{" "}
                  {formatDate(arrival, locale)} → {formatDate(departure, locale)}
                </p>
              )}
            </section>
          </>
        )}

        {error && (
          <div className="rounded-[8px] border border-bad/40 bg-bad/10 px-4 py-3 text-[13px] text-bad flex items-center gap-2">
            <IconWarning size={16} />
            {error}
          </div>
        )}

        {/* ── النتائج */}
        {stage === "pick" && (
          <section className="flex flex-col gap-3">
            {results.isFetching && (
              <div className="flex items-center gap-3 text-muted py-10 justify-center">
                <Spinner />
                <span className="text-[14px]">{t("state.loading")}</span>
              </div>
            )}

            {searchError && (
              <div className="rounded-[8px] border border-warn/40 bg-warn/10 px-4 py-3 text-[13px] text-warn">
                {searchError}
              </div>
            )}

            {results.data && results.data.offers.length === 0 && (
              <div className="bg-surface border border-line rounded-[10px] px-5 py-10 text-center">
                <p className="text-[15px] font-bold">{t("be.noRooms")}</p>
                <p className="text-[13px] text-muted mt-1">{t("be.noRoomsHint")}</p>
              </div>
            )}

            {results.data?.offers.map((o) => (
              <article
                key={o.unit_category_id}
                className="bg-surface border border-line rounded-[10px] p-5 flex flex-col md:flex-row gap-5"
              >
                <div className="flex-1 min-w-0">
                  <h2 className="text-[17px] font-bold">{ar ? o.name_ar : o.name_en}</h2>
                  {(ar ? o.description_ar : o.description_en) && (
                    <p className="text-[13px] text-muted mt-1 leading-relaxed">
                      {ar ? o.description_ar : o.description_en}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-[12.5px] text-ink-2">
                    <span>
                      {t("be.upTo")} <span className="num font-bold">{o.max_occupancy}</span>{" "}
                      {ar ? "أفراد" : "guests"}
                    </span>
                    {o.area_sqm && (
                      <span className="num">
                        {o.area_sqm} {ar ? "م²" : "m²"}
                      </span>
                    )}
                    {o.bed_configuration && <span>{o.bed_configuration}</span>}
                  </div>
                  {(ar ? o.amenities_ar : o.amenities_en) && (
                    <p className="text-[12px] text-muted mt-2">
                      {ar ? o.amenities_ar : o.amenities_en}
                    </p>
                  )}
                  {o.left <= 3 && (
                    <p className="text-[12.5px] font-bold text-warn mt-3">
                      {t("be.fewLeft").replace("{n}", String(o.left))}
                    </p>
                  )}
                </div>

                <div className="md:w-[230px] shrink-0 flex flex-col justify-between gap-3 md:border-s md:border-line md:ps-5">
                  <div>
                    <div className="text-[11.5px] text-muted">{t("be.forNights").replace("{n}", String(o.nights))}</div>
                    <div className="num text-[26px] font-bold leading-tight text-accent">
                      {money(o.grand_total, 0)}{" "}
                      <span className="text-[14px] font-bold">{cur}</span>
                    </div>
                    <div className="text-[11.5px] text-muted mt-0.5">
                      {t("be.perNight")}{" "}
                      <span className="num">{money(o.average_nightly_rate, 0)}</span> · {t("be.taxIncluded")}
                    </div>
                  </div>
                  <Button
                    variant="primary"
                    size="lg"
                    disabled={takeHold.isPending}
                    onClick={() => takeHold.mutate(o.unit_category_id)}
                  >
                    {t("be.pick")}
                  </Button>
                </div>
              </article>
            ))}
          </section>
        )}

        {/* ── بيانات الزائر */}
        {stage === "details" && hold && (
          <GuestForm
            hold={hold}
            onDone={(b) => {
              setBooking(b);
              setStage("done");
            }}
            onBack={() => {
              post("/book/release", { token: hold.token }).catch(() => undefined);
              setHold(null);
              setStage("pick");
            }}
          />
        )}

        {/* ── التأكيد */}
        {stage === "done" && booking && (
          <Confirmation
            booking={booking}
            onRestart={() => {
              setBooking(null);
              setHold(null);
              setSubmitted(null);
              setStage("search");
            }}
          />
        )}

        <footer className="text-[11.5px] text-muted text-center pt-4 border-t border-line">
          {property.data && (
            <>
              {t("be.checkIn")} <span className="num">{property.data.check_in_time}</span> ·{" "}
              {t("be.checkOut")} <span className="num">{property.data.check_out_time}</span> ·{" "}
              {t("be.pricesInclude")
                .replace("{s}", String(Number(property.data.service_charge_percent)))
                .replace("{v}", String(Number(property.data.vat_percent)))}
            </>
          )}
        </footer>
      </main>
    </div>
  );
}

/* ────────────────────────────────────── بيانات الزائر */
function GuestForm({
  hold,
  onDone,
  onBack,
}: {
  hold: HoldOut;
  onDone: (b: BookingOut) => void;
  onBack: () => void;
}) {
  const { t, locale } = useI18n();
  const ar = locale === "ar";
  const cur = ar ? "ج.م" : "EGP";

  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [payDeposit, setPayDeposit] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [left, setLeft] = useState(() => hold.hold_minutes * 60);

  useEffect(() => {
    const tick = setInterval(() => {
      const seconds = Math.max(
        0,
        Math.round((new Date(hold.expires_at).getTime() - Date.now()) / 1000),
      );
      setLeft(seconds);
    }, 1000);
    return () => clearInterval(tick);
  }, [hold.expires_at]);

  const confirm = useMutation({
    mutationFn: () =>
      post<BookingOut>("/book/confirm", {
        token: hold.token,
        first_name: first,
        last_name: last,
        phone,
        email: email.trim() || null,
        notes: notes.trim() || null,
        deposit_paid: payDeposit ? hold.deposit_required : 0,
      }),
    onSuccess: onDone,
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const ready = first.trim() && last.trim() && phone.trim().length >= 8;
  const minutes = Math.floor(left / 60);
  const seconds = left % 60;

  return (
    <section className="grid gap-5 grid-cols-1 lg:grid-cols-3">
      <div className="lg:col-span-2 bg-surface border border-line rounded-[10px] p-5">
        <div className="flex items-center justify-between gap-3 mb-4">
          <h2 className="text-[17px] font-bold">{t("be.yourDetails")}</h2>
          <span
            className={cx(
              "num text-[13px] font-bold rounded-full px-3 py-1",
              left < 120 ? "bg-bad/12 text-bad" : "bg-surface-2 text-ink-2",
            )}
          >
            {minutes}:{`${seconds}`.padStart(2, "0")}
          </span>
        </div>
        <p className="text-[12.5px] text-muted mb-4">{t("be.holdNote")}</p>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-bold text-ink-2">{t("be.firstName")}</span>
            <input className={inputClass} value={first} onChange={(e) => setFirst(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-bold text-ink-2">{t("be.lastName")}</span>
            <input className={inputClass} value={last} onChange={(e) => setLast(e.target.value)} />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-bold text-ink-2">{t("res.phone")}</span>
            <input
              className={cx(inputClass, "num")}
              dir="ltr"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+2010…"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-bold text-ink-2">{t("be.email")}</span>
            <input
              className={cx(inputClass, "num")}
              dir="ltr"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
        </div>

        <label className="flex flex-col gap-1.5 mb-4">
          <span className="text-[12.5px] font-bold text-ink-2">{t("res.requests")}</span>
          <input className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>

        <label className="flex items-start gap-2.5 mb-4 cursor-pointer">
          <input
            type="checkbox"
            className="mt-1"
            checked={payDeposit}
            onChange={(e) => setPayDeposit(e.target.checked)}
          />
          <span className="text-[13px]">
            {t("be.payDeposit")}{" "}
            <span className="num font-bold">{money(hold.deposit_required, 0)}</span> {cur}
            <span className="block text-[11.5px] text-muted">{t("be.depositHint")}</span>
          </span>
        </label>

        {error && (
          <div className="rounded-[6px] border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-[13px] text-bad mb-4">
            {error}
          </div>
        )}

        <div className="flex items-center gap-2">
          <Button onClick={onBack}>{t("be.back")}</Button>
          <Button
            variant="primary"
            size="lg"
            className="flex-1"
            disabled={!ready || confirm.isPending || left === 0}
            onClick={() => {
              setError(null);
              confirm.mutate();
            }}
          >
            {left === 0 ? t("be.expired") : t("be.confirm")}
          </Button>
        </div>
      </div>

      {/* ملخص */}
      <aside className="bg-surface border border-line rounded-[10px] p-5 h-fit">
        <h3 className="text-[15px] font-bold mb-3">{ar ? hold.name_ar : hold.name_en}</h3>
        <div className="num text-[13px] text-ink-2 mb-4">
          {formatDate(hold.arrival_date, locale)} → {formatDate(hold.departure_date, locale)}
          <div className="text-[12px] text-muted">
            {hold.nights} {t("tape.nights")} · {hold.adults + hold.children}{" "}
            {ar ? "أفراد" : "guests"}
          </div>
        </div>

        <dl className="flex flex-col gap-1.5 text-[13px]">
          <Line label={t("res.roomTotal")} value={money(hold.room_total)} />
          <Line label={t("res.service")} value={money(hold.service_charge_total)} />
          <Line label={t("res.tax")} value={money(hold.tax_total)} />
          <div className="border-t border-line mt-1.5 pt-2 flex items-center justify-between">
            <dt className="font-bold">{t("res.grandTotal")}</dt>
            <dd className="num text-[19px] font-bold text-accent">
              {money(hold.grand_total)} <span className="text-[12px]">{cur}</span>
            </dd>
          </div>
        </dl>
      </aside>
    </section>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-muted">{label}</dt>
      <dd className="num">{value}</dd>
    </div>
  );
}

/* ────────────────────────────────────── التأكيد */
function Confirmation({
  booking,
  onRestart,
}: {
  booking: BookingOut;
  onRestart: () => void;
}) {
  const { t, locale } = useI18n();
  const ar = locale === "ar";
  const cur = ar ? "ج.م" : "EGP";

  return (
    <section className="bg-surface border border-line rounded-[10px] p-8 text-center max-w-[620px] mx-auto">
      <span className="w-14 h-14 rounded-full bg-good/12 text-good grid place-items-center mx-auto mb-4">
        <IconCheck size={28} />
      </span>
      <h2 className="text-[22px] font-bold">{t("be.confirmed")}</h2>
      <p className="text-[13.5px] text-muted mt-1">{t("be.confirmedHint")}</p>

      <div className="num text-[26px] font-bold text-accent my-5">{booking.code}</div>

      <dl className="text-[13.5px] flex flex-col gap-2 text-start border-t border-line pt-4">
        <Line label={t("wl.guest")} value={booking.guest_name} />
        <Line
          label={t("wl.category")}
          value={ar ? booking.category_name_ar : booking.category_name_en}
        />
        <Line
          label={t("res.stay")}
          value={`${formatDate(booking.arrival_date, locale)} → ${formatDate(booking.departure_date, locale)}`}
        />
        <Line label={t("res.grandTotal")} value={`${money(booking.grand_total)} ${cur}`} />
        <Line label={t("res.paid")} value={`${money(booking.paid_total)} ${cur}`} />
        <Line label={t("res.balance")} value={`${money(booking.balance)} ${cur}`} />
      </dl>

      <p className="text-[12.5px] text-muted mt-5">
        {t("be.checkIn")} <span className="num">{booking.check_in_time}</span> ·{" "}
        {t("be.checkOut")} <span className="num">{booking.check_out_time}</span>
      </p>

      <Button className="mt-5" onClick={onRestart}>
        {t("be.another")}
      </Button>
    </section>
  );
}
