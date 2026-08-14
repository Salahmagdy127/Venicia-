/** الفاتورة الإلكترونية — المستندات وحالتها في منظومة الضرائب. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate, formatTime, money } from "@/lib/format";
import type { InvoiceDetail, InvoiceListItem, InvoiceStats, QueueResult } from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import InvoiceDocument from "@/components/InvoiceDocument";
import { Button, Card, ErrorState, Loading, Pill, cx, inputClass } from "@/components/ui";
import { IconCheck, IconWarning } from "@/components/Icons";

const ETA_TONE: Record<string, "good" | "gold" | "bad" | "muted"> = {
  VALID: "good",
  QUEUED: "gold",
  SUBMITTED: "gold",
  FAILED: "bad",
  REJECTED: "bad",
  INVALID: "bad",
  DRAFT: "muted",
  CANCELLED: "muted",
};

const TYPES = ["", "INVOICE", "RECEIPT", "CREDIT_NOTE"] as const;

export default function Invoices() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [type, setType] = useState<string>("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [flash, setFlash] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const stats = useQuery({
    queryKey: ["invoice-stats"],
    queryFn: () => get<InvoiceStats>("/invoices/stats"),
    refetchInterval: 60_000,
  });

  const list = useQuery({
    queryKey: ["invoices", type, search],
    queryFn: () =>
      get<InvoiceListItem[]>(
        `/invoices${qs({ invoice_type: type || undefined, search: search || undefined, limit: 80 })}`,
      ),
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["invoices"] });
    qc.invalidateQueries({ queryKey: ["invoice-stats"] });
  }

  const queue = useMutation({
    mutationFn: (path: string) => post<QueueResult>(path, {}),
    onSuccess: (r) => {
      setFlash({ tone: "good", text: locale === "ar" ? r.message_ar : r.message_en });
      refresh();
    },
    onError: (err) =>
      setFlash({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      }),
  });

  const s = stats.data;
  const canIssue = can("invoice.issue");

  return (
    <>
      <PageHeader title={t("einv.title")} subtitle={t("einv.subtitle")}>
        {s && (
          <StatStrip
            items={[
              { label: t("einv.accepted"), value: String(s.accepted), tone: "good" },
              {
                label: t("einv.queued"),
                value: String(s.pending + s.failed),
                tone: s.pending + s.failed > 0 ? "warn" : "ink",
              },
              {
                label: t("einv.rejected"),
                value: String(s.rejected),
                tone: s.rejected > 0 ? "bad" : "ink",
              },
              { label: t("einv.todayTax"), value: money(s.today_tax, 0) },
            ]}
          />
        )}
        {canIssue && (
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              disabled={queue.isPending || !s?.eta_enabled}
              onClick={() => queue.mutate("/invoices/submit")}
            >
              {t("einv.submit")}
            </Button>
            {(s?.rejected ?? 0) > 0 && (
              <Button
                variant="danger"
                disabled={queue.isPending}
                onClick={() => queue.mutate("/invoices/retry")}
              >
                {t("einv.retry")}
              </Button>
            )}
          </div>
        )}
      </PageHeader>

      <div className="flex-1 min-h-0 overflow-y-auto p-5 flex flex-col gap-4 max-w-[1400px]">
        {s && !s.eta_enabled && (
          <div className="rounded-[6px] border border-warn/40 bg-warn/10 px-4 py-3 text-[13px] text-warn flex items-center gap-2">
            <IconWarning size={16} />
            {t("einv.etaOff")}
          </div>
        )}

        {flash && (
          <div
            className={cx(
              "rounded-[6px] px-4 py-3 text-[13px] font-bold border flex items-center gap-2",
              flash.tone === "good"
                ? "border-good/40 bg-good/10 text-good"
                : "border-bad/40 bg-bad/10 text-bad",
            )}
          >
            {flash.tone === "good" ? <IconCheck size={15} /> : <IconWarning size={15} />}
            {flash.text}
          </div>
        )}

        <Card
          title={t("einv.documents")}
          padded={false}
          action={
            <div className="flex items-center gap-2">
              <input
                className={cx(inputClass, "h-9 w-[200px] text-[13px]")}
                placeholder={t("einv.searchHint")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
                {TYPES.map((x) => (
                  <button
                    key={x || "all"}
                    onClick={() => setType(x)}
                    className={cx(
                      "h-9 px-3 text-[12.5px] font-bold border-e border-line-strong last:border-e-0",
                      type === x ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
                    )}
                  >
                    {x ? t(`einv.${x}`) : t("einv.all")}
                  </button>
                ))}
              </div>
            </div>
          }
        >
          {list.isLoading && <Loading />}
          {list.isError && <ErrorState onRetry={() => list.refetch()} />}

          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead className="sticky top-0 bg-surface">
                <tr className="text-muted text-[12px]">
                  <Th className="text-start ps-5">{t("einv.number")}</Th>
                  <Th className="text-start">{t("einv.type")}</Th>
                  <Th className="text-start">{t("einv.customer")}</Th>
                  <Th className="text-start">{t("rep.date")}</Th>
                  <Th className="text-end">{t("res.tax")}</Th>
                  <Th className="text-end">{t("res.grandTotal")}</Th>
                  <Th className="text-start pe-5">{t("einv.etaStatus")}</Th>
                </tr>
              </thead>
              <tbody>
                {list.data?.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => setOpen(r.id)}
                    className={cx(
                      "cursor-pointer hover:bg-surface-2/60",
                      r.is_cancelled && "opacity-60",
                    )}
                  >
                    <td className="num px-3 ps-5 py-2.5 border-b border-line font-bold">
                      {r.number}
                      {r.is_cancelled && (
                        <span className="text-[11px] text-bad ms-2">{t("einv.cancelled")}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 border-b border-line text-ink-2">
                      {t(`einv.${r.invoice_type}`)}
                    </td>
                    <td className="px-3 py-2.5 border-b border-line truncate max-w-[220px]">
                      {r.customer_name}
                    </td>
                    <td className="num px-3 py-2.5 border-b border-line text-muted">
                      {formatDate(r.business_date, locale)}
                      <span className="text-[11px] ms-1.5">{formatTime(r.issued_at)}</span>
                    </td>
                    <td className="num text-end px-3 py-2.5 border-b border-line text-ink-2">
                      {money(r.tax_total, 0)}
                    </td>
                    <td
                      className={cx(
                        "num text-end px-3 py-2.5 border-b border-line font-bold",
                        Number(r.grand_total) < 0 && "text-bad",
                      )}
                    >
                      {money(r.grand_total, 0)}
                    </td>
                    <td className="px-3 pe-5 py-2.5 border-b border-line">
                      <Pill tone={ETA_TONE[r.eta_status] ?? "muted"}>
                        {t(`einv.eta.${r.eta_status}`, r.eta_status)}
                      </Pill>
                      {r.eta_error_message && (
                        <div className="text-[11px] text-bad mt-0.5 truncate max-w-[200px]">
                          {r.eta_error_message}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {list.data?.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-5 py-8 text-center text-[13px] text-muted">
                      {t("state.empty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <p className="text-[12px] text-muted leading-relaxed max-w-[80ch]">{t("einv.note")}</p>
      </div>

      {open !== null && (
        <InvoiceDocument
          invoiceId={open}
          onClose={() => setOpen(null)}
          onChanged={refresh}
        />
      )}
    </>
  );
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}

export type { InvoiceDetail };
