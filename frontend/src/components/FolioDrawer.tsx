/** كشف حساب النزيل — الحركات باليوم، والتحصيل والإقفال. */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate, formatTime, money } from "@/lib/format";
import type { Folio, FolioAction, FolioListItem } from "@/lib/types";
import { Button, EmptyState, ErrorState, Loading, Modal, cx, inputClass } from "./ui";
import { IconCheck, IconSearch, IconTrash, IconX } from "./Icons";

const METHODS = ["CASH", "CARD", "INSTAPAY", "BANK_TRANSFER", "CITY_LEDGER"] as const;
const KINDS = ["FNB", "SPA", "ACTIVITY", "MINIBAR", "LAUNDRY", "ADJUSTMENT"] as const;

export default function FolioDrawer({
  folioId,
  onClose,
}: {
  folioId: number | null;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [modal, setModal] = useState<"settle" | "charge" | "split" | "transfer" | null>(null);
  const [voidLine, setVoidLine] = useState<number | null>(null);
  const [banner, setBanner] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  /** وضع التحديد — بيتفعّل لما تدوس «اختار حركات» */
  const [picking, setPicking] = useState(false);
  const [chosen, setChosen] = useState<number[]>([]);

  const open = folioId !== null;

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["folio", folioId],
    queryFn: () => get<Folio>(`/folios/${folioId}`),
    enabled: open,
  });

  const done = (res: FolioAction) => {
    setBanner({ tone: "good", text: locale === "ar" ? res.message_ar : res.message_en });
    setModal(null);
    setVoidLine(null);
    setPicking(false);
    setChosen([]);
    qc.invalidateQueries({ queryKey: ["folio", folioId] });
    qc.invalidateQueries({ queryKey: ["front-desk"] });
    qc.invalidateQueries({ queryKey: ["pos"] });
  };
  const oops = (err: unknown) =>
    setBanner({
      tone: "bad",
      text: err instanceof ApiError ? err.text(locale) : t("state.error"),
    });

  const settle = useMutation({
    mutationFn: (v: { method: string; amount: number; reference?: string }) =>
      post<FolioAction>(`/folios/${folioId}/settle`, v),
    onSuccess: done,
    onError: oops,
  });

  const charge = useMutation({
    mutationFn: (v: {
      charge_kind: string;
      description_ar: string;
      amount: number;
      quantity: number;
    }) => post<FolioAction>(`/folios/${folioId}/charges`, v),
    onSuccess: done,
    onError: oops,
  });

  const voidCharge = useMutation({
    mutationFn: (v: { lineId: number; reason: string }) =>
      post<FolioAction>(`/folios/${folioId}/charges/${v.lineId}/void`, { reason: v.reason }),
    onSuccess: done,
    onError: oops,
  });

  const closeFolio = useMutation({
    mutationFn: () => post<FolioAction>(`/folios/${folioId}/close`),
    onSuccess: (res) => {
      done(res);
      onClose();
    },
    onError: oops,
  });

  const split = useMutation({
    mutationFn: (label: string) =>
      post<FolioAction>(`/folios/${folioId}/split`, {
        line_ids: chosen,
        label: label || null,
      }),
    onSuccess: done,
    onError: oops,
  });

  const transfer = useMutation({
    mutationFn: async (targetFolioId: number) => {
      // الـ API بيحوّل حركة واحدة في المرة — بنعدّي على المحدّد بالترتيب
      let last: FolioAction | null = null;
      for (const lineId of chosen) {
        last = await post<FolioAction>(
          `/folios/${folioId}/charges/${lineId}/transfer`,
          { target_folio_id: targetFolioId },
        );
      }
      return last!;
    },
    onSuccess: (res) =>
      done({
        ...res,
        message_ar: `تم تحويل ${chosen.length} حركة`,
        message_en: `Transferred ${chosen.length} charges`,
      }),
    onError: oops,
  });

  if (!open) return null;

  const f = data;
  const balance = Number(f?.balance ?? 0);
  const cur = locale === "ar" ? "ج.م" : "EGP";
  const isOpen = f?.status === "OPEN";

  const chosenTotal = (f?.days ?? [])
    .flatMap((d) => d.lines)
    .filter((l) => chosen.includes(l.id))
    .reduce((sum, l) => sum + Number(l.total_amount), 0);

  return (
    <div className="fixed inset-0 z-50 flex bg-black/45" onClick={onClose}>
      <aside
        className="ms-auto h-full w-full max-w-[620px] bg-surface border-s border-line flex flex-col"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("folio.title")}
      >
        <header className="shrink-0 px-5 py-4 border-b border-line flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="num text-[17px] font-bold">{f?.unit_label ?? f?.code ?? "—"}</span>
              {f?.is_vip && (
                <span className="text-[11.5px] font-bold rounded-full bg-gold-soft text-gold px-2 py-0.5">
                  VIP
                </span>
              )}
              {f?.is_returning && (
                <span className="text-[11.5px] font-bold rounded-full bg-accent-soft text-accent px-2 py-0.5">
                  {t("folio.returning")} · <span className="num">{f.total_stays}</span>
                </span>
              )}
              <span
                className={cx(
                  "text-[11.5px] font-bold rounded-full px-2 py-0.5",
                  isOpen ? "bg-good/12 text-good" : "bg-surface-2 text-muted",
                )}
              >
                {isOpen ? t("folio.open") : t("folio.closed")}
              </span>
            </div>
            <div className="text-[14px] text-ink-2 truncate mt-0.5">{f?.guest_name}</div>
            {f?.arrival_date && f?.departure_date && (
              <div className="num text-[12px] text-muted mt-0.5">
                {formatDate(f.arrival_date, locale)} → {formatDate(f.departure_date, locale)}
                {f.reservation_code && ` · ${f.reservation_code}`}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label={t("action.close")}
            className="w-8 h-8 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2 shrink-0"
          >
            <IconX size={18} />
          </button>
        </header>

        {/* الرصيد */}
        <div className="shrink-0 px-5 py-3 border-b border-line flex items-center gap-5 bg-surface-2/50">
          <div>
            <div className="text-[11.5px] text-muted font-bold">{t("folio.balance")}</div>
            <div
              className={cx(
                "num text-[26px] font-bold leading-tight",
                balance > 0 ? "text-bad" : "text-good",
              )}
            >
              {money(f?.balance ?? 0)} <span className="text-[13px] opacity-70">{cur}</span>
            </div>
          </div>
          <div className="flex gap-5 ms-auto text-end">
            <Mini label={t("folio.charges")} value={money(f?.charges_total ?? 0, 0)} />
            <Mini label={t("folio.payments")} value={money(f?.payments_total ?? 0, 0)} />
            <Mini label={t("res.tax")} value={money(f?.tax_total ?? 0, 0)} />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          {isLoading && <Loading />}
          {isError && <ErrorState onRetry={() => refetch()} />}

          {banner && (
            <div
              className={cx(
                "m-4 rounded-[6px] px-3.5 py-2.5 text-[13px] border",
                banner.tone === "good"
                  ? "border-good/40 bg-good/10 text-good"
                  : "border-bad/40 bg-bad/10 text-bad",
              )}
            >
              {banner.text}
            </div>
          )}

          {f && f.days.length === 0 && <EmptyState />}

          {f?.days.map((day) => (
            <section key={day.business_date}>
              <header className="sticky top-0 z-10 flex items-center justify-between gap-3 px-5 py-1.5 bg-surface-2 border-y border-line">
                <span className="text-[12.5px] font-bold">
                  {formatDate(day.business_date, locale)}
                </span>
                <span className="num text-[12.5px] font-bold text-ink-2">
                  {money(day.day_total)}
                </span>
              </header>

              <ul className="m-0 p-0 list-none">
                {day.lines.map((l) => {
                  const selectable = !l.is_void && !l.is_transferred;
                  const isChosen = chosen.includes(l.id);
                  return (
                  <li
                    key={l.id}
                    onClick={() => {
                      if (!picking || !selectable) return;
                      setChosen((prev) =>
                        prev.includes(l.id)
                          ? prev.filter((x) => x !== l.id)
                          : [...prev, l.id],
                      );
                    }}
                    className={cx(
                      "flex items-center gap-3 px-5 py-2 border-b border-line",
                      l.is_void && "opacity-45",
                      picking && selectable && "cursor-pointer hover:bg-surface-2",
                      picking && !selectable && "opacity-40",
                      isChosen && "bg-accent-soft",
                    )}
                  >
                    {picking && (
                      <span
                        className={cx(
                          "w-4 h-4 rounded-[3px] border grid place-items-center shrink-0",
                          isChosen
                            ? "bg-accent border-accent text-accent-ink"
                            : "border-line-strong",
                        )}
                      >
                        {isChosen && <IconCheck size={11} />}
                      </span>
                    )}
                    <span className="num text-[11px] text-muted w-10 shrink-0">
                      {formatTime(l.created_at)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div
                        className={cx(
                          "text-[13.5px] leading-snug truncate",
                          l.is_void && "line-through",
                        )}
                      >
                        {locale === "ar" ? l.description_ar : l.description_en || l.description_ar}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-muted">
                        <span>{l.charge_label_ar}</span>
                        {Number(l.quantity) !== 1 && (
                          <span className="num">
                            {Number(l.quantity)} × {money(l.unit_price)}
                          </span>
                        )}
                        {l.pos_order_id && <span>{t("folio.pos")}</span>}
                        {l.is_transferred && <span>{t("folio.transferred")}</span>}
                      </div>
                    </div>
                    <span
                      className={cx(
                        "num text-[13.5px] font-bold shrink-0",
                        l.is_credit ? "text-good" : "text-ink",
                      )}
                    >
                      {l.is_credit ? "-" : ""}
                      {money(l.total_amount)}
                    </span>
                    {isOpen && !picking && !l.is_void && can("folio.void") && (
                      <button
                        onClick={() => setVoidLine(l.id)}
                        aria-label={t("folio.void")}
                        className="w-7 h-7 grid place-items-center rounded-[6px] text-muted hover:text-bad hover:bg-bad/10 shrink-0"
                      >
                        <IconTrash size={14} />
                      </button>
                    )}
                  </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>

        {f && isOpen && !picking && (
          <footer className="shrink-0 px-5 py-3.5 border-t border-line flex items-center gap-2">
            {can("folio.post") && (
              <Button onClick={() => setModal("charge")}>{t("folio.addCharge")}</Button>
            )}
            {can("folio.settle") && (
              <Button variant="primary" onClick={() => setModal("settle")}>
                {t("folio.settle")}
              </Button>
            )}
            {(can("folio.split") || can("folio.transfer")) && (
              <Button variant="ghost" onClick={() => setPicking(true)}>
                {t("folio.select")}
              </Button>
            )}
            <div className="flex-1" />
            {can("folio.settle") && balance <= 0 && (
              <Button
                variant="ghost"
                disabled={closeFolio.isPending}
                onClick={() => closeFolio.mutate()}
              >
                {t("folio.close")}
              </Button>
            )}
          </footer>
        )}

        {/* شريط التحديد — بيبان بدل الإجراءات وقت اختيار الحركات */}
        {f && isOpen && picking && (
          <footer className="shrink-0 px-5 py-3 border-t border-line bg-accent-soft flex items-center gap-2">
            <div className="min-w-0">
              <div className="text-[13px] font-bold text-accent">
                <span className="num">{chosen.length}</span> {t("folio.selected")}
              </div>
              <div className="num text-[11.5px] text-ink-2">
                {t("folio.selectedTotal")}: {money(chosenTotal)} {cur}
              </div>
            </div>
            <div className="flex-1" />
            {can("folio.split") && (
              <Button
                variant="secondary"
                disabled={chosen.length === 0}
                onClick={() => setModal("split")}
              >
                {t("folio.splitTitle")}
              </Button>
            )}
            {can("folio.transfer") && (
              <Button
                variant="primary"
                disabled={chosen.length === 0}
                onClick={() => setModal("transfer")}
              >
                {t("folio.transferTitle")}
              </Button>
            )}
            <Button
              variant="ghost"
              onClick={() => {
                setPicking(false);
                setChosen([]);
              }}
            >
              {t("folio.cancelSelect")}
            </Button>
          </footer>
        )}
      </aside>

      {/* ── التحصيل */}
      <SettleModal
        open={modal === "settle"}
        balance={balance}
        busy={settle.isPending}
        onClose={() => setModal(null)}
        onConfirm={(method, amount, reference) => settle.mutate({ method, amount, reference })}
      />

      {/* ── ترحيل حركة */}
      <ChargeModal
        open={modal === "charge"}
        busy={charge.isPending}
        onClose={() => setModal(null)}
        onConfirm={(v) => charge.mutate(v)}
      />

      {/* ── إلغاء حركة */}
      <VoidModal
        open={voidLine !== null}
        busy={voidCharge.isPending}
        onClose={() => setVoidLine(null)}
        onConfirm={(reason) => voidLine !== null && voidCharge.mutate({ lineId: voidLine, reason })}
      />

      {/* ── تقسيم الفاتورة */}
      <SplitModal
        open={modal === "split"}
        count={chosen.length}
        total={chosenTotal}
        busy={split.isPending}
        onClose={() => setModal(null)}
        onConfirm={(label) => split.mutate(label)}
      />

      {/* ── تحويل لغرفة تانية */}
      <TransferModal
        open={modal === "transfer"}
        count={chosen.length}
        total={chosenTotal}
        excludeFolioId={folioId}
        busy={transfer.isPending}
        onClose={() => setModal(null)}
        onConfirm={(targetId) => transfer.mutate(targetId)}
      />
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-muted">{label}</div>
      <div className="num text-[14px] font-bold">{value}</div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════ النوافذ */
function SettleModal({
  open,
  balance,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  balance: number;
  busy: boolean;
  onClose: () => void;
  onConfirm: (method: string, amount: number, reference?: string) => void;
}) {
  const { t, locale } = useI18n();
  const [method, setMethod] = useState<string>("CASH");
  const [amount, setAmount] = useState(0);
  const [reference, setReference] = useState("");

  useEffect(() => {
    if (open) {
      setMethod("CASH");
      setAmount(Math.max(0, balance));
      setReference("");
    }
  }, [open, balance]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("folio.settleTitle")}
      width={420}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy || amount <= 0}
            onClick={() => onConfirm(method, amount, reference || undefined)}
          >
            {t("folio.settle")}
          </Button>
        </>
      }
    >
      <div className="flex items-baseline justify-between mb-4 pb-3 border-b border-line">
        <span className="text-[13.5px] font-bold">{t("folio.balance")}</span>
        <span className="num text-[22px] font-bold text-bad">
          {money(balance)} <span className="text-[12px] opacity-70">{locale === "ar" ? "ج.م" : "EGP"}</span>
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        {METHODS.map((m) => (
          <button
            key={m}
            onClick={() => setMethod(m)}
            className={cx(
              "h-10 rounded-[6px] border text-[12.5px] font-bold",
              method === m
                ? "bg-accent text-accent-ink border-accent"
                : "border-line-strong text-ink hover:bg-surface-2",
            )}
          >
            {t(`pay.${m}`, m)}
          </button>
        ))}
      </div>

      <label className="flex flex-col gap-1.5 mb-3">
        <span className="text-[13px] font-bold text-ink-2">{t("folio.amount2")}</span>
        <input
          type="number"
          className={`${inputClass} num`}
          value={amount}
          onChange={(e) => setAmount(Number(e.target.value))}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-bold text-ink-2">{t("folio.reference")}</span>
        <input
          className={inputClass}
          value={reference}
          onChange={(e) => setReference(e.target.value)}
        />
      </label>
    </Modal>
  );
}

function ChargeModal({
  open,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: (v: {
    charge_kind: string;
    description_ar: string;
    amount: number;
    quantity: number;
  }) => void;
}) {
  const { t } = useI18n();
  const [kind, setKind] = useState<string>("FNB");
  const [desc, setDesc] = useState("");
  const [amount, setAmount] = useState(0);
  const [qty, setQty] = useState(1);

  useEffect(() => {
    if (open) {
      setKind("FNB");
      setDesc("");
      setAmount(0);
      setQty(1);
    }
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("folio.addCharge")}
      width={420}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy || amount <= 0 || desc.trim().length < 2}
            onClick={() =>
              onConfirm({
                charge_kind: kind,
                description_ar: desc.trim(),
                amount,
                quantity: qty,
              })
            }
          >
            {t("action.save")}
          </Button>
        </>
      }
    >
      <label className="flex flex-col gap-1.5 mb-3">
        <span className="text-[13px] font-bold text-ink-2">{t("folio.chargeKind")}</span>
        <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`kind.${k}`, k)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1.5 mb-3">
        <span className="text-[13px] font-bold text-ink-2">{t("folio.chargeDesc")}</span>
        <input className={inputClass} value={desc} onChange={(e) => setDesc(e.target.value)} />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-bold text-ink-2">{t("folio.price")}</span>
          <input
            type="number"
            className={`${inputClass} num`}
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-bold text-ink-2">{t("folio.qty")}</span>
          <input
            type="number"
            min={1}
            className={`${inputClass} num`}
            value={qty}
            onChange={(e) => setQty(Number(e.target.value))}
          />
        </label>
      </div>
    </Modal>
  );
}

function SplitModal({
  open,
  count,
  total,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  count: number;
  total: number;
  busy: boolean;
  onClose: () => void;
  onConfirm: (label: string) => void;
}) {
  const { t, locale } = useI18n();
  const [label, setLabel] = useState("");
  useEffect(() => {
    if (open) setLabel("");
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("folio.splitTitle")}
      width={420}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button variant="primary" disabled={busy || count === 0} onClick={() => onConfirm(label)}>
            {t("folio.splitDo")}
          </Button>
        </>
      }
    >
      <div className="flex items-baseline justify-between mb-3 pb-3 border-b border-line">
        <span className="text-[13.5px] font-bold">
          <span className="num">{count}</span> {t("folio.selected")}
        </span>
        <span className="num text-[20px] font-bold text-accent">
          {money(total)}{" "}
          <span className="text-[12px] opacity-70">{locale === "ar" ? "ج.م" : "EGP"}</span>
        </span>
      </div>
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-bold text-ink-2">{t("folio.splitLabel")}</span>
        <input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <p className="text-[12px] text-muted mt-3 leading-relaxed">{t("folio.splitHint")}</p>
    </Modal>
  );
}

function TransferModal({
  open,
  count,
  total,
  excludeFolioId,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  count: number;
  total: number;
  excludeFolioId: number | null;
  busy: boolean;
  onClose: () => void;
  onConfirm: (targetFolioId: number) => void;
}) {
  const { t, locale } = useI18n();
  const [term, setTerm] = useState("");
  const [target, setTarget] = useState<number | null>(null);

  useEffect(() => {
    if (open) {
      setTerm("");
      setTarget(null);
    }
  }, [open]);

  const folios = useQuery({
    queryKey: ["folio", "targets", term],
    queryFn: () => get<FolioListItem[]>(`/folios${qs({ search: term, limit: 40 })}`),
    enabled: open,
  });

  const options = (folios.data ?? []).filter((f) => f.id !== excludeFolioId);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("folio.transferTitle")}
      width={440}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy || target === null || count === 0}
            onClick={() => target !== null && onConfirm(target)}
          >
            {t("folio.transferDo")}
          </Button>
        </>
      }
    >
      <div className="flex items-baseline justify-between mb-3 pb-3 border-b border-line">
        <span className="text-[13.5px] font-bold">
          <span className="num">{count}</span> {t("folio.selected")}
        </span>
        <span className="num text-[20px] font-bold text-accent">
          {money(total)}{" "}
          <span className="text-[12px] opacity-70">{locale === "ar" ? "ج.م" : "EGP"}</span>
        </span>
      </div>

      <p className="text-[12.5px] text-muted mb-2">{t("folio.transferHint")}</p>

      <label className="relative flex items-center mb-2">
        <span className="absolute start-0 ps-2.5 text-muted pointer-events-none">
          <IconSearch size={15} />
        </span>
        <input
          className={`${inputClass} ps-8`}
          placeholder={t("folio.searchFolio")}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
      </label>

      <div className="max-h-[240px] overflow-y-auto border border-line rounded-[6px] divide-y divide-line">
        {folios.isLoading && <Loading />}
        {!folios.isLoading && options.length === 0 && <EmptyState />}
        {options.map((f) => (
          <button
            key={f.id}
            onClick={() => setTarget(f.id)}
            className={cx(
              "w-full text-start px-3 py-2 flex items-center gap-2",
              target === f.id ? "bg-accent-soft" : "hover:bg-surface-2",
            )}
          >
            <span className="num text-[13.5px] font-bold w-14 shrink-0">
              {f.unit_label ?? "—"}
            </span>
            <span className="text-[13px] truncate flex-1">{f.guest_name}</span>
            <span className="num text-[12px] text-muted shrink-0">{money(f.balance, 0)}</span>
            {target === f.id && <IconCheck size={14} className="text-accent shrink-0" />}
          </button>
        ))}
      </div>
    </Modal>
  );
}

function VoidModal({
  open,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
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
      title={t("folio.void")}
      width={380}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="danger"
            disabled={busy || reason.trim().length < 2}
            onClick={() => onConfirm(reason.trim())}
          >
            {t("action.confirm")}
          </Button>
        </>
      }
    >
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-bold text-ink-2">{t("folio.voidReason")}</span>
        <input
          className={inputClass}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
      </label>
      <p className="text-[12px] text-muted mt-3 leading-relaxed">
        {t(
          "folio.voidNote",
          "الحركة مش بتتمسح — بيتسجّل قيد عكسي، وده اللي بيخلي الحساب قابل للمراجعة.",
        )}
      </p>
    </Modal>
  );
}
