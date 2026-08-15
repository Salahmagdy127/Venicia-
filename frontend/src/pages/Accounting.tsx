/** الحسابات — القوائم المالية ودفتر اليومية وميزان المراجعة. */

import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate, money, toISO } from "@/lib/format";
import type {
  AccountLedger,
  AccountingBoard,
  BalanceSheet,
  FinancialLine,
  IncomeStatement,
  JournalEntryOut,
  JournalSource,
  PostingResult,
  TrialBalance,
} from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import JournalDrawer from "@/components/JournalDrawer";
import { Button, Card, ErrorState, Loading, Pill, cx, inputClass } from "@/components/ui";
import { IconCheck, IconWarning } from "@/components/Icons";

type Tab = "income" | "balance" | "trial" | "journal";

const TABS: Tab[] = ["income", "balance", "trial", "journal"];

const SOURCE_TONE: Record<JournalSource, "good" | "bad" | "gold" | "accent" | "muted"> = {
  MANUAL: "gold",
  ROOM_REVENUE: "good",
  POS_REVENUE: "good",
  PAYMENT: "accent",
  REFUND: "bad",
  PURCHASE: "muted",
  CONSUMPTION: "muted",
  WASTE: "bad",
  PAYROLL: "accent",
  OPENING: "muted",
  CLOSING: "muted",
};

function monthStart(): string {
  const now = new Date();
  return toISO(new Date(now.getFullYear(), now.getMonth(), 1));
}

export default function Accounting() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [tab, setTab] = useState<Tab>("income");
  const [since, setSince] = useState(monthStart());
  const [until, setUntil] = useState(toISO(new Date()));
  const [openEntry, setOpenEntry] = useState<JournalEntryOut | null>(null);
  const [openAccount, setOpenAccount] = useState<number | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const board = useQuery({
    queryKey: ["gl-board"],
    queryFn: () => get<AccountingBoard>("/accounting"),
  });

  const income = useQuery({
    queryKey: ["gl-income", since, until],
    queryFn: () => get<IncomeStatement>(`/accounting/income-statement${qs({ since, until })}`),
    enabled: tab === "income",
  });

  const sheet = useQuery({
    queryKey: ["gl-balance", until],
    queryFn: () => get<BalanceSheet>(`/accounting/balance-sheet${qs({ as_of: until })}`),
    enabled: tab === "balance",
  });

  const trial = useQuery({
    queryKey: ["gl-trial"],
    queryFn: () => get<TrialBalance>("/accounting/trial-balance"),
    enabled: tab === "trial",
  });

  const journal = useQuery({
    queryKey: ["gl-journal"],
    queryFn: () => get<JournalEntryOut[]>("/accounting/journal?limit=60"),
    enabled: tab === "journal",
  });

  const ledger = useQuery({
    queryKey: ["gl-ledger", openAccount],
    queryFn: () => get<AccountLedger>(`/accounting/ledger/${openAccount}?limit=120`),
    enabled: openAccount !== null,
  });

  function refresh() {
    for (const key of ["gl-board", "gl-income", "gl-balance", "gl-trial", "gl-journal"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  }

  const postDay = useMutation({
    mutationFn: (day: string) =>
      post<PostingResult>("/accounting/post-day", { business_date: day }),
    onSuccess: (r) => {
      setFlash(
        r.posted > 0
          ? t("gl.postedFlash").replace("{n}", String(r.posted)).replace("{d}", r.business_date)
          : t("gl.nothingToPost").replace("{d}", r.business_date),
      );
      refresh();
    },
    onError: (err) => setFlash(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const b = board.data;
  const canPost = can("gl.post");

  /** مجاميع ميزان المراجعة لكل نوع حساب — بتخلّي الجدول مقروء */
  const trialGroups = useMemo(() => {
    if (!trial.data) return [];
    const order: TrialBalance["rows"][number]["account_type"][] = [
      "ASSET",
      "LIABILITY",
      "EQUITY",
      "REVENUE",
      "EXPENSE",
    ];
    return order
      .map((type) => ({
        type,
        rows: trial.data.rows.filter((r) => r.account_type === type),
      }))
      .filter((g) => g.rows.length > 0);
  }, [trial.data]);

  return (
    <>
      <PageHeader title={t("gl.title")} subtitle={t("gl.subtitle")}>
        {b && (
          <StatStrip
            items={[
              { label: t("gl.monthRevenue"), value: money(b.month_revenue, 0), tone: "good" },
              { label: t("gl.monthProfit"), value: money(b.month_profit, 0), tone: "accent" },
              { label: t("gl.margin"), value: `${Number(b.margin_percent).toFixed(1)}%` },
              { label: t("gl.cash"), value: money(b.cash_on_hand, 0) },
              { label: t("gl.bank"), value: money(b.bank, 0) },
            ]}
          />
        )}
      </PageHeader>

      <div className="flex-1 min-h-0 overflow-y-auto p-5 flex flex-col gap-4 max-w-[1500px]">
        {board.isLoading && <Loading />}
        {board.isError && <ErrorState onRetry={() => board.refetch()} />}

        {flash && (
          <div className="rounded-[6px] border border-good/40 bg-good/10 px-4 py-3 text-[13px] text-good">
            {flash}
          </div>
        )}

        {/* حالة الدفتر — أول حاجة المحاسب بيبصّ عليها */}
        {b && (
          <div
            className={cx(
              "rounded-[6px] border px-4 py-3 text-[13px] flex items-center gap-2",
              b.is_balanced
                ? "border-good/40 bg-good/10 text-good"
                : "border-bad/40 bg-bad/10 text-bad",
            )}
          >
            {b.is_balanced ? <IconCheck size={16} /> : <IconWarning size={16} />}
            {b.is_balanced ? t("gl.balanced") : t("gl.unbalanced")}
          </div>
        )}

        {/* الأيام اللي فيها حركة ومترحّلتش */}
        {b && b.unposted_days.length > 0 && (
          <Card title={t("gl.unposted")}>
            <div className="text-[12.5px] text-ink-2 mb-3">{t("gl.unpostedHint")}</div>
            <div className="flex flex-wrap gap-2">
              {b.unposted_days.map((day) => (
                <button
                  key={day}
                  disabled={!canPost || postDay.isPending}
                  onClick={() => postDay.mutate(day)}
                  className={cx(
                    "num h-8 px-3 rounded-[6px] border border-warn/50 bg-warn/10 text-warn",
                    "text-[12.5px] font-bold",
                    canPost ? "hover:bg-warn/20" : "opacity-60 cursor-default",
                  )}
                >
                  {day}
                </button>
              ))}
            </div>
          </Card>
        )}

        {/* أرصدة الحسابات الرئيسية */}
        {b && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <Balance label={t("gl.guestLedger")} value={b.guest_ledger} />
            <Balance label={t("gl.cityLedger")} value={b.city_ledger} />
            <Balance label={t("gl.inventory")} value={b.inventory_value} />
            <Balance label={t("gl.suppliers")} value={b.suppliers_due} tone="warn" />
            <Balance label={t("gl.vatDue")} value={b.vat_payable} tone="warn" />
            <Balance label={t("gl.servicePayable")} value={b.service_payable} tone="warn" />
          </div>
        )}

        {/* التبويبات */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden w-fit">
            {TABS.map((x) => (
              <button
                key={x}
                onClick={() => setTab(x)}
                className={cx(
                  "h-9 px-4 text-[13px] font-bold border-e border-line-strong last:border-e-0",
                  tab === x ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
                )}
              >
                {t(`gl.tab.${x}`)}
              </button>
            ))}
          </div>

          {(tab === "income" || tab === "balance") && (
            <div className="flex items-center gap-2 text-[12.5px]">
              {tab === "income" && (
                <>
                  <span className="text-muted">{t("gl.from")}</span>
                  <input
                    type="date"
                    className={cx(inputClass, "h-9 w-[150px] text-[13px] num")}
                    value={since}
                    onChange={(e) => setSince(e.target.value)}
                  />
                </>
              )}
              <span className="text-muted">{tab === "income" ? t("gl.to") : t("gl.asOf")}</span>
              <input
                type="date"
                className={cx(inputClass, "h-9 w-[150px] text-[13px] num")}
                value={until}
                onChange={(e) => setUntil(e.target.value)}
              />
            </div>
          )}
        </div>

        {/* ── قائمة الدخل */}
        {tab === "income" && (
          <>
            {income.isLoading && <Loading />}
            {income.isError && <ErrorState onRetry={() => income.refetch()} />}
            {income.data && (
              <div className="grid lg:grid-cols-2 gap-4">
                <Card title={t("gl.revenue")} padded={false}>
                  <StatementTable
                    lines={income.data.revenue}
                    total={income.data.total_revenue}
                    totalLabel={t("gl.totalRevenue")}
                    tone="good"
                  />
                </Card>
                <Card title={t("gl.expenses")} padded={false}>
                  <StatementTable
                    lines={income.data.expenses}
                    total={income.data.total_expenses}
                    totalLabel={t("gl.totalExpenses")}
                    tone="bad"
                  />
                </Card>
                <Card className="lg:col-span-2">
                  <div className="flex items-baseline justify-between gap-4 flex-wrap">
                    <div>
                      <div className="text-[13px] text-muted">{t("gl.netProfit")}</div>
                      <div className="num text-[30px] font-bold text-accent leading-tight">
                        {money(income.data.net_profit, 0)}
                      </div>
                    </div>
                    <div className="text-end">
                      <div className="text-[13px] text-muted">{t("gl.margin")}</div>
                      <div className="num text-[22px] font-bold">
                        {Number(income.data.margin_percent).toFixed(1)}%
                      </div>
                    </div>
                  </div>
                </Card>
              </div>
            )}
          </>
        )}

        {/* ── المركز المالي */}
        {tab === "balance" && (
          <>
            {sheet.isLoading && <Loading />}
            {sheet.isError && <ErrorState onRetry={() => sheet.refetch()} />}
            {sheet.data && (
              <>
                <div
                  className={cx(
                    "rounded-[6px] border px-4 py-2.5 text-[12.5px] flex items-center gap-2",
                    sheet.data.is_balanced
                      ? "border-good/40 bg-good/10 text-good"
                      : "border-bad/40 bg-bad/10 text-bad",
                  )}
                >
                  {sheet.data.is_balanced ? <IconCheck size={15} /> : <IconWarning size={15} />}
                  {sheet.data.is_balanced
                    ? t("gl.sheetBalanced")
                    : t("gl.sheetOff").replace("{n}", money(sheet.data.difference, 2))}
                </div>
                <div className="grid lg:grid-cols-2 gap-4">
                  <Card title={t("gl.assets")} padded={false}>
                    <StatementTable
                      lines={sheet.data.assets}
                      total={sheet.data.total_assets}
                      totalLabel={t("gl.totalAssets")}
                    />
                  </Card>
                  <div className="flex flex-col gap-4">
                    <Card title={t("gl.liabilities")} padded={false}>
                      <StatementTable
                        lines={sheet.data.liabilities}
                        total={sheet.data.total_liabilities}
                        totalLabel={t("gl.totalLiabilities")}
                      />
                    </Card>
                    <Card title={t("gl.equity")} padded={false}>
                      <StatementTable
                        lines={[
                          ...sheet.data.equity,
                          {
                            code: "—",
                            name_ar: t("gl.periodProfit"),
                            name_en: "Profit for the period",
                            amount: sheet.data.retained_profit,
                          },
                        ]}
                        total={String(
                          Number(sheet.data.total_equity) + Number(sheet.data.retained_profit),
                        )}
                        totalLabel={t("gl.totalEquity")}
                      />
                    </Card>
                  </div>
                </div>
              </>
            )}
          </>
        )}

        {/* ── ميزان المراجعة */}
        {tab === "trial" && (
          <>
            {trial.isLoading && <Loading />}
            {trial.isError && <ErrorState onRetry={() => trial.refetch()} />}
            {trial.data && (
              <Card
                title={t("gl.tab.trial")}
                padded={false}
                action={
                  <Pill tone={trial.data.is_balanced ? "good" : "bad"}>
                    {trial.data.is_balanced
                      ? t("gl.balancedShort")
                      : money(trial.data.difference, 2)}
                  </Pill>
                }
              >
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-[13px]">
                    <thead className="sticky top-0 bg-surface">
                      <tr className="text-muted text-[12px]">
                        <Th className="text-start ps-5">{t("gl.account")}</Th>
                        <Th className="text-end">{t("gl.debit")}</Th>
                        <Th className="text-end">{t("gl.credit")}</Th>
                        <Th className="text-end pe-5">{t("gl.balance")}</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {trialGroups.map((group) => (
                        <Fragment key={group.type}>
                          <tr className="bg-surface-2">
                            <td
                              colSpan={4}
                              className="px-3 ps-5 py-1.5 text-[11.5px] font-bold text-muted border-b border-line"
                            >
                              {t(`gl.type.${group.type}`)}
                            </td>
                          </tr>
                          {group.rows.map((row) => (
                            <tr
                              key={row.account_id}
                              onClick={() => setOpenAccount(row.account_id)}
                              className="hover:bg-surface-2/50 cursor-pointer"
                            >
                              <td className="px-3 ps-5 py-2.5 border-b border-line">
                                <span className="num text-muted text-[11.5px] me-2">
                                  {row.code}
                                </span>
                                <span className="font-bold">
                                  {locale === "ar" ? row.name_ar : row.name_en}
                                </span>
                              </td>
                              <td className="num text-end px-3 py-2.5 border-b border-line">
                                {Number(row.debit) ? money(row.debit, 0) : "—"}
                              </td>
                              <td className="num text-end px-3 py-2.5 border-b border-line">
                                {Number(row.credit) ? money(row.credit, 0) : "—"}
                              </td>
                              <td className="num text-end px-3 pe-5 py-2.5 border-b border-line font-bold">
                                {money(row.balance, 0)}
                              </td>
                            </tr>
                          ))}
                        </Fragment>
                      ))}
                      <tr className="bg-surface-2 font-bold">
                        <td className="px-3 ps-5 py-3">{t("gl.total")}</td>
                        <td className="num text-end px-3 py-3">
                          {money(trial.data.total_debit, 0)}
                        </td>
                        <td className="num text-end px-3 py-3">
                          {money(trial.data.total_credit, 0)}
                        </td>
                        <td className="px-3 pe-5 py-3" />
                      </tr>
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </>
        )}

        {/* ── دفتر اليومية */}
        {tab === "journal" && (
          <>
            {journal.isLoading && <Loading />}
            {journal.isError && <ErrorState onRetry={() => journal.refetch()} />}
            {journal.data && (
              <Card title={t("gl.tab.journal")} padded={false}>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-[13px]">
                    <thead className="sticky top-0 bg-surface">
                      <tr className="text-muted text-[12px]">
                        <Th className="text-start ps-5">{t("gl.number")}</Th>
                        <Th className="text-start">{t("gl.date")}</Th>
                        <Th className="text-start">{t("gl.source")}</Th>
                        <Th className="text-start">{t("gl.description")}</Th>
                        <Th className="text-end pe-5">{t("gl.amount")}</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {journal.data.map((entry) => (
                        <tr
                          key={entry.id}
                          onClick={() => setOpenEntry(entry)}
                          className={cx(
                            "hover:bg-surface-2/50 cursor-pointer",
                            entry.status === "REVERSED" && "opacity-55",
                          )}
                        >
                          <td className="num px-3 ps-5 py-2.5 border-b border-line font-bold">
                            {entry.number}
                          </td>
                          <td className="num px-3 py-2.5 border-b border-line text-ink-2">
                            {formatDate(entry.business_date, locale)}
                          </td>
                          <td className="px-3 py-2.5 border-b border-line">
                            <Pill tone={SOURCE_TONE[entry.source]}>
                              {t(`gl.source.${entry.source}`, entry.source)}
                            </Pill>
                          </td>
                          <td className="px-3 py-2.5 border-b border-line text-ink-2">
                            {entry.description_ar}
                            {entry.status === "REVERSED" && (
                              <span className="text-[11px] text-bad font-bold ms-2">
                                {t("gl.reversed")}
                              </span>
                            )}
                          </td>
                          <td className="num text-end px-3 pe-5 py-2.5 border-b border-line font-bold">
                            {money(entry.total_debit, 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </>
        )}
      </div>

      {openEntry && (
        <JournalDrawer
          entry={openEntry}
          onClose={() => setOpenEntry(null)}
          onChanged={() => {
            setOpenEntry(null);
            refresh();
          }}
        />
      )}

      {openAccount !== null && ledger.data && (
        <LedgerModal ledger={ledger.data} onClose={() => setOpenAccount(null)} />
      )}
    </>
  );
}

function Balance({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "warn";
}) {
  return (
    <div className="rounded-[6px] border border-line bg-surface px-4 py-3">
      <div className="text-[11.5px] text-muted truncate">{label}</div>
      <div
        className={cx(
          "num text-[17px] font-bold leading-tight mt-0.5",
          tone === "warn" && Number(value) > 0 ? "text-warn" : "",
        )}
      >
        {money(value, 0)}
      </div>
    </div>
  );
}

function StatementTable({
  lines,
  total,
  totalLabel,
  tone,
}: {
  lines: FinancialLine[];
  total: string;
  totalLabel: string;
  tone?: "good" | "bad";
}) {
  const { locale } = useI18n();
  const max = Math.max(...lines.map((l) => Math.abs(Number(l.amount))), 1);
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <tbody>
          {lines.map((line) => (
            <tr key={line.code} className="hover:bg-surface-2/50">
              <td className="px-3 ps-5 py-2.5 border-b border-line w-[55%]">
                <span className="num text-muted text-[11.5px] me-2">{line.code}</span>
                {locale === "ar" ? line.name_ar : line.name_en}
              </td>
              <td className="px-3 py-2.5 border-b border-line">
                {/* شريط نسبي — بيخلّي البند الكبير يبان من غير قراية أرقام */}
                <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
                  <div
                    className={cx(
                      "h-full rounded-full",
                      tone === "bad" ? "bg-bad/60" : tone === "good" ? "bg-good/60" : "bg-accent/50",
                    )}
                    style={{ width: `${(Math.abs(Number(line.amount)) / max) * 100}%` }}
                  />
                </div>
              </td>
              <td className="num text-end px-3 pe-5 py-2.5 border-b border-line font-bold whitespace-nowrap">
                {money(line.amount, 0)}
              </td>
            </tr>
          ))}
          <tr className="bg-surface-2 font-bold">
            <td className="px-3 ps-5 py-3" colSpan={2}>
              {totalLabel}
            </td>
            <td className="num text-end px-3 pe-5 py-3 whitespace-nowrap">{money(total, 0)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function LedgerModal({ ledger, onClose }: { ledger: AccountLedger; onClose: () => void }) {
  const { t, locale } = useI18n();
  return (
    <div
      className="fixed inset-0 z-50 bg-black/45 flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="bg-surface rounded-[8px] border border-line-strong w-full max-w-[900px] max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-line flex items-baseline gap-3">
          <span className="num text-[12px] text-muted">{ledger.account.code}</span>
          <h2 className="text-[16px] font-bold">
            {locale === "ar" ? ledger.account.name_ar : ledger.account.name_en}
          </h2>
          <div className="flex-1" />
          <span className="num text-[17px] font-bold">{money(ledger.account.balance, 2)}</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          <table className="w-full border-collapse text-[12.5px]">
            <thead className="sticky top-0 bg-surface">
              <tr className="text-muted text-[11.5px]">
                <Th className="text-start ps-5">{t("gl.date")}</Th>
                <Th className="text-start">{t("gl.number")}</Th>
                <Th className="text-start">{t("gl.description")}</Th>
                <Th className="text-end">{t("gl.debit")}</Th>
                <Th className="text-end">{t("gl.credit")}</Th>
                <Th className="text-end pe-5">{t("gl.running")}</Th>
              </tr>
            </thead>
            <tbody>
              {ledger.rows.map((row, i) => (
                <tr key={`${row.entry_id}-${i}`} className="hover:bg-surface-2/50">
                  <td className="num px-3 ps-5 py-2 border-b border-line whitespace-nowrap">
                    {formatDate(row.business_date, locale)}
                  </td>
                  <td className="num px-3 py-2 border-b border-line text-muted">
                    {row.entry_number}
                  </td>
                  <td className="px-3 py-2 border-b border-line text-ink-2">
                    {row.description_ar}
                  </td>
                  <td className="num text-end px-3 py-2 border-b border-line">
                    {Number(row.debit) ? money(row.debit, 0) : "—"}
                  </td>
                  <td className="num text-end px-3 py-2 border-b border-line">
                    {Number(row.credit) ? money(row.credit, 0) : "—"}
                  </td>
                  <td className="num text-end px-3 pe-5 py-2 border-b border-line font-bold">
                    {money(row.running_balance, 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-5 py-3 border-t border-line flex justify-end">
          <Button variant="ghost" onClick={onClose}>
            {t("action.close")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}
