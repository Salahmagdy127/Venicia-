/** المستند الضريبي بالكامل — بشكل الفاتورة المطبوعة. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate, formatTime, money } from "@/lib/format";
import type { InvoiceDetail } from "@/lib/types";
import { Button, Loading, Modal, Pill, cx, inputClass } from "./ui";

export default function InvoiceDocument({
  invoiceId,
  onClose,
  onChanged,
}: {
  invoiceId: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [reason, setReason] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doc = useQuery({
    queryKey: ["invoice", invoiceId],
    queryFn: () => get<InvoiceDetail>(`/invoices/${invoiceId}`),
  });

  const cancel = useMutation({
    mutationFn: () => post<InvoiceDetail>(`/invoices/${invoiceId}/cancel`, { reason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      onChanged();
      setAsking(false);
      setReason("");
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const d = doc.data;
  const cur = locale === "ar" ? "ج.م" : "EGP";

  return (
    <Modal open onClose={onClose} title={d?.number ?? t("einv.title")} width={680}>
      {doc.isLoading && <Loading />}

      {d && (
        <div className="flex flex-col gap-5">
          {/* الترويسة */}
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="num text-[20px] font-bold">{d.number}</div>
              <div className="text-[12.5px] text-muted">
                {t(`einv.${d.invoice_type}`)} ·{" "}
                <span className="num">{formatDate(d.business_date, locale)}</span>{" "}
                <span className="num">{formatTime(d.issued_at)}</span>
              </div>
            </div>
            <div className="text-end">
              <Pill tone={d.eta_status === "VALID" ? "good" : d.eta_status === "QUEUED" ? "gold" : "bad"}>
                {t(`einv.eta.${d.eta_status}`, d.eta_status)}
              </Pill>
              {d.is_cancelled && (
                <div className="text-[11.5px] text-bad mt-1">{t("einv.cancelled")}</div>
              )}
            </div>
          </div>

          {d.is_cancelled && d.cancellation_reason && (
            <div className="rounded-[6px] border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-[12.5px] text-bad">
              {t("einv.cancelReason")}: {d.cancellation_reason}
            </div>
          )}

          {/* المستلم */}
          <section className="border border-line rounded-[6px] p-3.5">
            <div className="text-[11.5px] font-bold text-muted mb-1.5">{t("einv.customer")}</div>
            <div className="text-[14px] font-bold">{d.customer_name}</div>
            <div className="num text-[12px] text-muted mt-0.5">
              {d.customer_tax_number
                ? `${t("einv.taxNumber")}: ${d.customer_tax_number}`
                : d.customer_national_id
                  ? `${t("einv.nationalId")}: ${d.customer_national_id}`
                  : "—"}
            </div>
          </section>

          {/* السطور */}
          <div className="overflow-x-auto border border-line rounded-[6px]">
            <table className="w-full border-collapse text-[12.5px]">
              <thead>
                <tr className="text-muted text-[11.5px] bg-surface-2">
                  <th className="text-start font-bold px-3 py-2">{t("einv.description")}</th>
                  <th className="text-end font-bold px-2 py-2">{t("pos.qty")}</th>
                  <th className="text-end font-bold px-2 py-2">{t("einv.unitPrice")}</th>
                  <th className="text-end font-bold px-2 py-2">{t("res.service")}</th>
                  <th className="text-end font-bold px-2 py-2">{t("res.tax")}</th>
                  <th className="text-end font-bold px-3 py-2">{t("rep.total")}</th>
                </tr>
              </thead>
              <tbody>
                {d.lines.map((l) => (
                  <tr key={l.line_number}>
                    <td className="px-3 py-2 border-t border-line">{l.description_ar}</td>
                    <td className="num text-end px-2 py-2 border-t border-line">
                      {Number(l.quantity)}
                    </td>
                    <td className="num text-end px-2 py-2 border-t border-line">
                      {money(l.unit_price)}
                    </td>
                    <td className="num text-end px-2 py-2 border-t border-line text-muted">
                      {money(l.service_charge_amount)}
                    </td>
                    <td className="num text-end px-2 py-2 border-t border-line text-muted">
                      {money(l.tax_amount)}
                    </td>
                    <td className="num text-end px-3 py-2 border-t border-line font-bold">
                      {money(l.total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* الإجماليات */}
          <dl className="flex flex-col gap-1.5 text-[13px]">
            <Row label={t("einv.subtotal")} value={money(d.subtotal)} />
            {Number(d.discount_total) !== 0 && (
              <Row label={t("res.discount")} value={money(d.discount_total)} />
            )}
            <Row label={t("res.service")} value={money(d.service_charge_total)} />
            <Row label={t("res.tax")} value={money(d.tax_total)} />
            <div className="border-t border-line mt-1 pt-2 flex items-center justify-between">
              <dt className="font-bold">{t("res.grandTotal")}</dt>
              <dd
                className={cx(
                  "num text-[20px] font-bold",
                  Number(d.grand_total) < 0 ? "text-bad" : "text-accent",
                )}
              >
                {money(d.grand_total)} <span className="text-[12px]">{cur}</span>
              </dd>
            </div>
          </dl>

          {/* المنظومة */}
          <section className="border border-line rounded-[6px] p-3.5 text-[12px] flex flex-col gap-1">
            <Small label={t("einv.internalId")} value={d.eta_internal_id ?? "—"} />
            <Small label={t("einv.etaUuid")} value={d.eta_uuid ?? "—"} />
            <Small
              label={t("einv.submitted")}
              value={d.eta_submitted_at ? formatTime(d.eta_submitted_at) : "—"}
            />
            <Small
              label={t("einv.acceptedAt")}
              value={d.eta_accepted_at ? formatTime(d.eta_accepted_at) : "—"}
            />
            {d.eta_retry_count > 0 && (
              <Small label={t("ch.attempts")} value={String(d.eta_retry_count)} />
            )}
            {d.eta_error_message && (
              <p className="text-[11.5px] text-bad mt-1">{d.eta_error_message}</p>
            )}
            {d.qr_payload && (
              <p className="num text-[10.5px] text-muted mt-1.5 break-all" dir="ltr">
                {d.qr_payload}
              </p>
            )}
          </section>

          {/* الإلغاء */}
          {!d.is_cancelled && d.invoice_type !== "CREDIT_NOTE" && can("invoice.cancel") && (
            <div className="border-t border-line pt-4">
              {!asking ? (
                <Button variant="danger" onClick={() => setAsking(true)}>
                  {t("einv.issueCreditNote")}
                </Button>
              ) : (
                <div className="flex flex-col gap-2">
                  <p className="text-[12px] text-muted">{t("einv.creditNoteHint")}</p>
                  <input
                    className={inputClass}
                    placeholder={t("einv.cancelReason")}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                  {error && <p className="text-[12.5px] text-bad">{error}</p>}
                  <div className="flex items-center gap-2">
                    <Button onClick={() => setAsking(false)}>{t("action.cancel")}</Button>
                    <Button
                      variant="danger"
                      disabled={!reason.trim() || cancel.isPending}
                      onClick={() => {
                        setError(null);
                        cancel.mutate();
                      }}
                    >
                      {t("einv.issueCreditNote")}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-muted">{label}</dt>
      <dd className="num">{value}</dd>
    </div>
  );
}

function Small({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted shrink-0">{label}</span>
      <span className="num truncate" dir="ltr">
        {value}
      </span>
    </div>
  );
}
