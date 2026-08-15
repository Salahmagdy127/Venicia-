/** استلام على أمر شراء — كامل أو جزئي، بسعر المورد الفعلي. */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { ApiError, post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { money } from "@/lib/format";
import type { PurchaseOut } from "@/lib/types";
import { Button, Modal, cx, inputClass } from "./ui";

export default function ReceivePurchase({
  order,
  onClose,
  onDone,
}: {
  order: PurchaseOut;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t, locale } = useI18n();

  // الافتراضي: استلام المتبقي كامل — ده اللي بيحصل في أغلب الحالات
  const [rows, setRows] = useState(() =>
    order.lines.map((l) => ({
      line_id: l.id,
      quantity: Number(l.outstanding),
      actual_cost: Number(l.unit_cost),
    })),
  );
  const [invoice, setInvoice] = useState("");
  const [error, setError] = useState<string | null>(null);

  const receive = useMutation({
    mutationFn: () =>
      post<PurchaseOut>(`/stock/purchases/${order.id}/receive`, {
        lines: rows
          .filter((r) => r.quantity > 0)
          .map((r) => ({
            line_id: r.line_id,
            quantity: r.quantity,
            actual_cost: r.actual_cost,
          })),
        supplier_invoice_number: invoice.trim() || null,
      }),
    onSuccess: onDone,
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const total = rows.reduce((sum, r) => sum + r.quantity * r.actual_cost, 0);
  const ready = rows.some((r) => r.quantity > 0);

  function update(lineId: number, patch: Partial<(typeof rows)[number]>) {
    setRows((prev) => prev.map((r) => (r.line_id === lineId ? { ...r, ...patch } : r)));
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`${t("st.receive")} — ${order.number}`}
      width={640}
      footer={
        <>
          <Button onClick={onClose}>{t("action.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!ready || receive.isPending}
            onClick={() => {
              setError(null);
              receive.mutate();
            }}
          >
            {t("st.confirmReceive")}
          </Button>
        </>
      }
    >
      <p className="text-[12.5px] text-muted leading-relaxed mb-4">{t("st.receiveHint")}</p>

      <label className="flex flex-col gap-1.5 mb-4">
        <span className="text-[12.5px] font-bold text-ink-2">{t("st.supplierInvoice")}</span>
        <input
          className={cx(inputClass, "num")}
          dir="ltr"
          value={invoice}
          onChange={(e) => setInvoice(e.target.value)}
          placeholder="INV-…"
        />
      </label>

      <div className="border border-line rounded-[6px] overflow-hidden">
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr className="text-muted text-[11.5px] bg-surface-2">
              <th className="text-start font-bold px-3 py-2">{t("st.item")}</th>
              <th className="text-end font-bold px-2 py-2">{t("st.ordered")}</th>
              <th className="text-end font-bold px-2 py-2">{t("st.outstanding")}</th>
              <th className="text-end font-bold px-2 py-2 w-[92px]">{t("st.receiveQty")}</th>
              <th className="text-end font-bold px-3 py-2 w-[92px]">{t("st.actualCost")}</th>
            </tr>
          </thead>
          <tbody>
            {order.lines.map((line) => {
              const row = rows.find((r) => r.line_id === line.id)!;
              const done = Number(line.outstanding) === 0;
              return (
                <tr key={line.id} className={cx(done && "opacity-45")}>
                  <td className="px-3 py-2 border-t border-line">
                    {line.item_name_ar}
                    <span className="text-[11px] text-muted ms-1">
                      {t(`st.unit.${line.unit}`, line.unit)}
                    </span>
                  </td>
                  <td className="num text-end px-2 py-2 border-t border-line text-muted">
                    {Number(line.quantity_ordered).toFixed(2)}
                  </td>
                  <td className="num text-end px-2 py-2 border-t border-line font-bold">
                    {Number(line.outstanding).toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 border-t border-line">
                    <input
                      type="number"
                      min={0}
                      max={Number(line.outstanding)}
                      step="0.001"
                      disabled={done}
                      className={cx(inputClass, "num h-8 text-[12.5px] text-end")}
                      value={row.quantity}
                      onChange={(e) =>
                        update(line.id, {
                          quantity: Math.max(
                            0,
                            Math.min(Number(line.outstanding), Number(e.target.value) || 0),
                          ),
                        })
                      }
                    />
                  </td>
                  <td className="px-3 py-1.5 border-t border-line">
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      disabled={done}
                      className={cx(inputClass, "num h-8 text-[12.5px] text-end")}
                      value={row.actual_cost}
                      onChange={(e) =>
                        update(line.id, { actual_cost: Math.max(0, Number(e.target.value) || 0) })
                      }
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-4 pt-3 border-t border-line">
        <span className="text-[13px] font-bold">{t("st.receiveValue")}</span>
        <span className="num text-[19px] font-bold text-accent">
          {money(total)} <span className="text-[12px]">{locale === "ar" ? "ج.م" : "EGP"}</span>
        </span>
      </div>

      <p className="text-[11.5px] text-muted mt-2">{t("st.costNote")}</p>

      {error && (
        <div className="mt-3 rounded-[6px] border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-[12.5px] text-bad">
          {error}
        </div>
      )}
    </Modal>
  );
}
