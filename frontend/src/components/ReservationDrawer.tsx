/** لوحة تفاصيل الحجز — بتتفتح من شاشة الحجوزات ومن الاستقبال. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate, formatRange, money } from "@/lib/format";
import { OTA_SOURCES, STATUS_COLOR } from "@/lib/status";
import type { ActionResult, Reservation } from "@/lib/types";
import { Button, Loading, ErrorState, cx, inputClass } from "./ui";
import { IconLock, IconX } from "./Icons";
import GuestProfile from "./GuestProfile";

export default function ReservationDrawer({
  reservationId,
  onClose,
}: {
  reservationId: number | null;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [confirm, setConfirm] = useState<"cancel" | "checkout" | null>(null);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [penalty, setPenalty] = useState(true);
  const [banner, setBanner] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const open = reservationId !== null;

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["reservation", reservationId],
    queryFn: () => get<Reservation>(`/reservations/${reservationId}`),
    enabled: open,
  });

  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      post<ActionResult>(`/reservations/${reservationId}/${path}`, body),
    onSuccess: (res) => {
      setBanner({ tone: "good", text: locale === "ar" ? res.message_ar : res.message_en });
      setConfirm(null);
      qc.invalidateQueries({ queryKey: ["reservation", reservationId] });
      qc.invalidateQueries({ queryKey: ["tape-chart"] });
      qc.invalidateQueries({ queryKey: ["front-desk"] });
      qc.invalidateQueries({ queryKey: ["housekeeping"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err) => {
      setBanner({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      });
    },
  });

  if (!open) return null;

  const r = data;
  const balance = Number(r?.balance ?? 0);
  const isOta = r ? OTA_SOURCES.has(r.source) : false;

  const canCheckIn =
    r && (r.status === "CONFIRMED" || r.status === "TENTATIVE") && can("reservation.checkin");
  const canCheckOut = r && r.status === "CHECKED_IN" && can("reservation.checkout");
  const canCancel =
    r &&
    r.status !== "CHECKED_OUT" &&
    r.status !== "CANCELLED" &&
    r.status !== "CHECKED_IN" &&
    can("reservation.cancel");

  return (
    <div className="fixed inset-0 z-50 flex bg-black/45" onClick={onClose}>
      <aside
        className="ms-auto h-full w-full max-w-[460px] bg-surface border-s border-line flex flex-col"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("res.details")}
      >
        {/* ── الرأس */}
        <header className="shrink-0 px-5 py-4 border-b border-line flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="num text-[17px] font-bold">{r?.code ?? "—"}</span>
              {r && (
                <span
                  className="text-[11.5px] font-bold rounded-full px-2 py-0.5 text-white"
                  style={{ background: STATUS_COLOR[r.status] }}
                >
                  {t(`status.${r.status}`)}
                </span>
              )}
              {r?.source && (
                <span
                  className={cx(
                    "text-[11.5px] font-bold rounded-full px-2 py-0.5",
                    isOta ? "bg-gold-soft text-gold" : "bg-surface-2 text-ink-2",
                  )}
                >
                  {t(`source.${r.source}`, r.source)}
                </span>
              )}
            </div>
            <button
              onClick={() => r && setProfileId(r.guest_id)}
              disabled={!r}
              className="text-[14px] text-ink-2 truncate mt-0.5 hover:text-accent hover:underline text-start"
            >
              {r?.guest_name}
            </button>
          </div>
          <button
            onClick={onClose}
            aria-label={t("action.close")}
            className="w-8 h-8 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2 shrink-0"
          >
            <IconX size={18} />
          </button>
        </header>

        {/* ── المحتوى */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {isLoading && <Loading />}
          {isError && <ErrorState onRetry={() => refetch()} />}

          {r && (
            <div className="p-5 flex flex-col gap-5">
              {banner && (
                <div
                  className={cx(
                    "rounded-[6px] px-3.5 py-2.5 text-[13px] border",
                    banner.tone === "good"
                      ? "border-good/40 bg-good/10 text-good"
                      : "border-bad/40 bg-bad/10 text-bad",
                  )}
                >
                  {banner.text}
                </div>
              )}

              <Rows
                rows={[
                  [t("res.stay"), formatRange(r.arrival_date, r.departure_date, locale)],
                  [
                    t("tape.nights"),
                    `${r.nights} ${r.nights === 1 ? t("tape.night") : t("tape.nights")}`,
                  ],
                  [
                    t("res.guests"),
                    `${r.adults} ${t("desk.adults")}${
                      r.children ? ` · ${r.children} ${t("desk.children")}` : ""
                    }`,
                  ],
                  [t("res.phone"), r.guest_phone || "—", "num"],
                ]}
              />

              {/* الوحدات */}
              <section>
                <h3 className="text-[13px] font-bold text-muted mb-2">{t("res.unit")}</h3>
                <div className="flex flex-col gap-1.5">
                  {r.units.map((u) => (
                    <div
                      key={u.id}
                      className="flex items-center justify-between gap-3 border border-line rounded-[6px] px-3 py-2"
                    >
                      <span className="num text-[14px] font-bold">
                        {u.unit_label ?? t("desk.notAssigned")}
                      </span>
                      <span className="text-[12.5px] text-muted num">
                        {formatDate(u.arrival_date, locale)} → {formatDate(u.departure_date, locale)}
                      </span>
                    </div>
                  ))}
                </div>
              </section>

              {/* الحساب */}
              <section>
                <h3 className="text-[13px] font-bold text-muted mb-2">{t("folio.charges")}</h3>
                <div className="border border-line rounded-[6px] divide-y divide-line">
                  <MoneyRow label={t("res.roomTotal")} value={r.room_total} />
                  {Number(r.discount_total) > 0 && (
                    <MoneyRow label={t("res.discount")} value={`-${r.discount_total}`} tone="bad" />
                  )}
                  <MoneyRow label={t("res.service")} value={r.service_charge_total} />
                  <MoneyRow label={t("res.tax")} value={r.tax_total} />
                  <MoneyRow label={t("res.grandTotal")} value={r.grand_total} strong />
                  <MoneyRow label={t("res.paid")} value={r.paid_total} tone="good" />
                  <MoneyRow
                    label={t("res.balance")}
                    value={r.balance}
                    strong
                    tone={balance > 0 ? "bad" : "good"}
                  />
                  {isOta && Number(r.channel_commission_amount) > 0 && (
                    <MoneyRow
                      label={t("res.commission")}
                      value={r.channel_commission_amount}
                      tone="gold"
                    />
                  )}
                </div>
              </section>

              {r.special_requests && (
                <section>
                  <h3 className="text-[13px] font-bold text-muted mb-1.5">{t("res.requests")}</h3>
                  <p className="text-[13.5px] text-ink-2 leading-relaxed">{r.special_requests}</p>
                </section>
              )}

              {/* تأكيد الإجراء */}
              {confirm === "cancel" && (
                <section className="border border-bad/40 rounded-[6px] p-3.5 flex flex-col gap-2.5">
                  <span className="text-[13px] font-bold text-bad">{t("res.cancel")}</span>
                  <input
                    className={inputClass}
                    placeholder={t("res.cancelReason")}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                  <label className="flex items-center gap-2 text-[13px] text-ink-2">
                    <input
                      type="checkbox"
                      checked={penalty}
                      onChange={(e) => setPenalty(e.target.checked)}
                    />
                    {t("res.chargePenalty")}
                  </label>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={act.isPending}
                      onClick={() =>
                        act.mutate({
                          path: "cancel",
                          body: { reason: reason || null, charge_penalty: penalty },
                        })
                      }
                    >
                      {t("action.confirm")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>
                      {t("action.cancel")}
                    </Button>
                  </div>
                </section>
              )}

              {confirm === "checkout" && (
                <section className="border border-warn/40 rounded-[6px] p-3.5 flex flex-col gap-2.5">
                  <span className="text-[13px] font-bold text-warn">
                    {t("res.forceCheckout")} — {money(r.balance)} {t("res.balance")}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={act.isPending}
                      onClick={() => act.mutate({ path: "check-out", body: { force: true } })}
                    >
                      {t("action.confirm")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>
                      {t("action.cancel")}
                    </Button>
                  </div>
                </section>
              )}
            </div>
          )}
        </div>

        {/* ── الإجراءات */}
        {r && (
          <footer className="shrink-0 px-5 py-3.5 border-t border-line flex items-center gap-2">
            {canCheckIn && (
              <Button
                variant="primary"
                disabled={act.isPending}
                onClick={() => act.mutate({ path: "check-in" })}
              >
                {t("desk.checkIn")}
              </Button>
            )}
            {canCheckOut && (
              <Button
                variant="primary"
                disabled={act.isPending}
                onClick={() =>
                  balance > 0
                    ? setConfirm("checkout")
                    : act.mutate({ path: "check-out", body: { force: false } })
                }
              >
                {t("desk.checkOut")}
                {balance > 0 && <IconLock size={13} />}
              </Button>
            )}
            {canCancel && (
              <Button variant="danger" onClick={() => setConfirm("cancel")}>
                {t("res.cancel")}
              </Button>
            )}
            <div className="flex-1" />
            <Button variant="ghost" onClick={onClose}>
              {t("action.close")}
            </Button>
          </footer>
        )}
      </aside>

      <GuestProfile guestId={profileId} onClose={() => setProfileId(null)} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────── مساعدات */
function Rows({ rows }: { rows: (string | undefined)[][] }) {
  return (
    <div className="flex flex-col gap-2">
      {rows.map(([label, value, cls]) => (
        <div key={label} className="flex items-baseline gap-3">
          <span className="text-[13px] text-muted w-[92px] shrink-0">{label}</span>
          <span className={cx("text-[13.5px] font-bold text-ink", cls)}>{value}</span>
        </div>
      ))}
    </div>
  );
}

function MoneyRow({
  label,
  value,
  strong,
  tone,
}: {
  label: string;
  value: string;
  strong?: boolean;
  tone?: "good" | "bad" | "gold";
}) {
  const { locale } = useI18n();
  const color =
    tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : tone === "gold" ? "text-gold" : "";
  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2">
      <span className={cx("text-[13px]", strong ? "font-bold text-ink" : "text-ink-2")}>
        {label}
      </span>
      <span className={cx("num text-[13.5px] font-bold", color, strong && "text-[15px]")}>
        {money(value)} <span className="text-[11px] opacity-60">{locale === "ar" ? "ج.م" : "EGP"}</span>
      </span>
    </div>
  );
}
