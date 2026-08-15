/** تفاصيل قيد اليومية — سطوره وعكسه. */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { ApiError, post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate, money } from "@/lib/format";
import type { JournalEntryOut } from "@/lib/types";
import { Button, Modal, Pill, cx, inputClass } from "./ui";

export default function JournalDrawer({
  entry,
  onClose,
  onChanged,
}: {
  entry: JournalEntryOut;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reverse = useMutation({
    mutationFn: () =>
      post<JournalEntryOut>(`/accounting/journal/${entry.id}/reverse`, { reason }),
    onSuccess: onChanged,
    onError: (err) =>
      setError(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  // القيد المرحّل مبيتعدّلش — بيتعكس. والعكس محتاج صلاحية وسبب مكتوب.
  const canReverse = can("gl.post") && entry.status === "POSTED";

  return (
    <Modal open title={`${t("gl.entry")} ${entry.number}`} onClose={onClose} width={780}>
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3 flex-wrap text-[13px]">
          <Pill tone={entry.status === "REVERSED" ? "bad" : "good"}>
            {t(`gl.status.${entry.status}`, entry.status)}
          </Pill>
          <Pill tone="muted">{t(`gl.source.${entry.source}`, entry.source)}</Pill>
          <span className="num text-ink-2">{formatDate(entry.business_date, locale)}</span>
        </div>

        <div className="text-[14px] font-bold">{entry.description_ar}</div>

        {entry.reversal_reason && (
          <div className="rounded-[6px] border border-bad/40 bg-bad/10 px-4 py-2.5 text-[12.5px] text-bad">
            {t("gl.reversedBecause")}: {entry.reversal_reason}
          </div>
        )}

        <div className="rounded-[6px] border border-line overflow-hidden">
          <table className="w-full border-collapse text-[13px]">
            <thead className="bg-surface-2">
              <tr className="text-muted text-[11.5px]">
                <th className="font-bold text-start px-3 py-2">{t("gl.account")}</th>
                <th className="font-bold text-start px-3 py-2">{t("gl.description")}</th>
                <th className="font-bold text-end px-3 py-2">{t("gl.debit")}</th>
                <th className="font-bold text-end px-3 py-2">{t("gl.credit")}</th>
              </tr>
            </thead>
            <tbody>
              {entry.lines.map((line, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="px-3 py-2">
                    <span className="num text-muted text-[11.5px] me-2">
                      {line.account_code}
                    </span>
                    <span className="font-bold">{line.account_name_ar}</span>
                  </td>
                  <td className="px-3 py-2 text-ink-2 text-[12.5px]">{line.description_ar}</td>
                  <td className="num text-end px-3 py-2 font-bold">
                    {Number(line.debit) ? money(line.debit, 2) : ""}
                  </td>
                  <td className="num text-end px-3 py-2 font-bold">
                    {Number(line.credit) ? money(line.credit, 2) : ""}
                  </td>
                </tr>
              ))}
              <tr className="border-t border-line-strong bg-surface-2 font-bold">
                <td className="px-3 py-2.5" colSpan={2}>
                  {t("gl.total")}
                </td>
                <td className="num text-end px-3 py-2.5">{money(entry.total_debit, 2)}</td>
                <td className="num text-end px-3 py-2.5">{money(entry.total_credit, 2)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {error && (
          <div className="rounded-[6px] border border-bad/40 bg-bad/10 px-4 py-2.5 text-[12.5px] text-bad">
            {error}
          </div>
        )}

        {canReverse && (
          <div className="border-t border-line pt-4 flex flex-col gap-2">
            <div className="text-[12.5px] text-muted">{t("gl.reverseHint")}</div>
            <div className="flex items-center gap-2">
              <input
                className={cx(inputClass, "flex-1 h-9 text-[13px]")}
                placeholder={t("gl.reverseReason")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <Button
                variant="danger"
                disabled={!reason.trim() || reverse.isPending}
                onClick={() => reverse.mutate()}
              >
                {t("gl.reverse")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
