/** شؤون العاملين — الموظفون ومسيّر المرتبات. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { money } from "@/lib/format";
import type { PayrollDetail, PayrollRunOut, StaffBoard } from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import PayslipCard from "@/components/PayslipCard";
import { Button, Card, ErrorState, Loading, Pill, cx, inputClass } from "@/components/ui";

type Tab = "people" | "payroll";

const STATUS_TONE: Record<string, "good" | "gold" | "bad" | "muted"> = {
  ACTIVE: "good",
  PROBATION: "gold",
  SUSPENDED: "bad",
  TERMINATED: "muted",
};

const RUN_TONE: Record<string, "muted" | "gold" | "good" | "accent"> = {
  DRAFT: "muted",
  APPROVED: "accent",
  PAID: "good",
  CANCELLED: "muted",
};

export default function Staff() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [tab, setTab] = useState<Tab>("people");
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState<number | "">("");
  const [openRun, setOpenRun] = useState<number | null>(null);
  const [openSlip, setOpenSlip] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const board = useQuery({
    queryKey: ["staff", search, department],
    queryFn: () =>
      get<StaffBoard>(
        `/hr${qs({ search: search || undefined, department_id: department || undefined })}`,
      ),
  });

  const runs = useQuery({
    queryKey: ["payroll-runs"],
    queryFn: () => get<PayrollRunOut[]>("/hr/payroll"),
    enabled: tab === "payroll",
  });

  const detail = useQuery({
    queryKey: ["payroll-detail", openRun],
    queryFn: () => get<PayrollDetail>(`/hr/payroll/${openRun}`),
    enabled: openRun !== null,
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["staff"] });
    qc.invalidateQueries({ queryKey: ["payroll-runs"] });
    qc.invalidateQueries({ queryKey: ["payroll-detail"] });
  }

  const build = useMutation({
    mutationFn: () => {
      const now = new Date();
      return post<PayrollDetail>("/hr/payroll/build", {
        year: now.getFullYear(),
        month: now.getMonth() + 1,
      });
    },
    onSuccess: (r) => {
      setFlash(t("hr.builtFlash").replace("{n}", String(r.headcount)).replace("{m}", r.label));
      setOpenRun(r.id);
      refresh();
    },
    onError: (err) => setFlash(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const approve = useMutation({
    mutationFn: (id: number) => post<PayrollRunOut>(`/hr/payroll/${id}/approve`, {}),
    onSuccess: (r) => {
      setFlash(t("hr.approvedFlash").replace("{m}", r.label));
      refresh();
    },
    onError: (err) => setFlash(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const pay = useMutation({
    mutationFn: (id: number) => post<PayrollRunOut>(`/hr/payroll/${id}/pay`, {}),
    onSuccess: (r) => {
      setFlash(t("hr.paidFlash").replace("{m}", r.label));
      refresh();
    },
    onError: (err) => setFlash(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const b = board.data;
  const d = detail.data;
  const canRun = can("payroll.run");
  const canApprove = can("payroll.approve");
  const slip = d?.payslips.find((s) => s.employee_code === openSlip) ?? null;

  return (
    <>
      <PageHeader title={t("hr.title")} subtitle={t("hr.subtitle")}>
        {b && (
          <StatStrip
            items={[
              { label: t("hr.headcount"), value: String(b.headcount) },
              { label: t("hr.monthlyCost"), value: money(b.monthly_payroll_cost, 0) },
              { label: t("hr.departments"), value: String(b.departments.length) },
            ]}
          />
        )}
        {canRun && tab === "payroll" && (
          <Button disabled={build.isPending} onClick={() => build.mutate()}>
            {t("hr.buildRun")}
          </Button>
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

        <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden w-fit">
          {(["people", "payroll"] as Tab[]).map((x) => (
            <button
              key={x}
              onClick={() => setTab(x)}
              className={cx(
                "h-9 px-4 text-[13px] font-bold border-e border-line-strong last:border-e-0",
                tab === x ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
              )}
            >
              {t(`hr.tab.${x}`)}
            </button>
          ))}
        </div>

        {/* ── العاملون */}
        {tab === "people" && b && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
              {b.departments.map((dept) => (
                <button
                  key={dept.id}
                  onClick={() => setDepartment(department === dept.id ? "" : dept.id)}
                  className={cx(
                    "rounded-[6px] border px-3 py-2.5 text-start transition-colors",
                    department === dept.id
                      ? "border-accent bg-accent/10"
                      : "border-line bg-surface hover:bg-surface-2",
                  )}
                >
                  <div className="text-[11.5px] text-muted truncate">
                    {locale === "ar" ? dept.name_ar : dept.name_en}
                  </div>
                  <div className="num text-[19px] font-bold leading-tight">{dept.headcount}</div>
                </button>
              ))}
            </div>

            <Card
              title={t("hr.tab.people")}
              padded={false}
              action={
                <input
                  className={cx(inputClass, "h-9 w-[200px] text-[13px]")}
                  placeholder={t("hr.searchHint")}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              }
            >
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[13px]">
                  <thead className="sticky top-0 bg-surface">
                    <tr className="text-muted text-[12px]">
                      <Th className="text-start ps-5">{t("hr.employee")}</Th>
                      <Th className="text-start">{t("hr.department")}</Th>
                      <Th className="text-start">{t("hr.status")}</Th>
                      <Th className="text-end">{t("hr.basic")}</Th>
                      <Th className="text-end">{t("hr.allowances")}</Th>
                      <Th className="text-end">{t("hr.gross")}</Th>
                      <Th className="text-end pe-5">{t("hr.points")}</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {b.employees.map((e) => (
                      <tr key={e.id} className="hover:bg-surface-2/50">
                        <td className="px-3 ps-5 py-2.5 border-b border-line">
                          <div className="font-bold">
                            {locale === "ar" ? e.name_ar : e.name_en}
                          </div>
                          <div className="text-[11.5px] text-muted">
                            <span className="num">{e.code}</span> ·{" "}
                            {locale === "ar" ? e.job_title_ar : e.job_title_en}
                          </div>
                        </td>
                        <td className="px-3 py-2.5 border-b border-line text-ink-2">
                          {e.department_name_ar}
                        </td>
                        <td className="px-3 py-2.5 border-b border-line">
                          <Pill tone={STATUS_TONE[e.status] ?? "muted"}>
                            {t(`hr.status.${e.status}`, e.status)}
                          </Pill>
                        </td>
                        <td className="num text-end px-3 py-2.5 border-b border-line">
                          {money(e.basic_salary, 0)}
                        </td>
                        <td className="num text-end px-3 py-2.5 border-b border-line text-ink-2">
                          {money(e.allowances, 0)}
                        </td>
                        <td className="num text-end px-3 py-2.5 border-b border-line font-bold">
                          {money(e.gross_salary, 0)}
                        </td>
                        <td className="num text-end px-3 pe-5 py-2.5 border-b border-line text-muted">
                          {Number(e.service_points)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}

        {/* ── المرتبات */}
        {tab === "payroll" && (
          <>
            {runs.isLoading && <Loading />}
            {runs.data && runs.data.length === 0 && (
              <Card>
                <div className="text-[13px] text-muted py-6 text-center">{t("hr.noRuns")}</div>
              </Card>
            )}
            {runs.data && runs.data.length > 0 && (
              <Card title={t("hr.runs")} padded={false}>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-[13px]">
                    <thead className="sticky top-0 bg-surface">
                      <tr className="text-muted text-[12px]">
                        <Th className="text-start ps-5">{t("hr.period")}</Th>
                        <Th className="text-start">{t("hr.status")}</Th>
                        <Th className="text-end">{t("hr.headcount")}</Th>
                        <Th className="text-end">{t("hr.servicePool")}</Th>
                        <Th className="text-end">{t("hr.totalGross")}</Th>
                        <Th className="text-end">{t("hr.totalNet")}</Th>
                        <Th className="text-end pe-5">{t("hr.employerCost")}</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.data.map((r) => (
                        <tr
                          key={r.id}
                          onClick={() => setOpenRun(openRun === r.id ? null : r.id)}
                          className={cx(
                            "hover:bg-surface-2/50 cursor-pointer",
                            openRun === r.id && "bg-accent/5",
                          )}
                        >
                          <td className="num px-3 ps-5 py-2.5 border-b border-line font-bold">
                            {r.label}
                            <span className="text-[11px] text-muted ms-2">{r.number}</span>
                          </td>
                          <td className="px-3 py-2.5 border-b border-line">
                            <Pill tone={RUN_TONE[r.status] ?? "muted"}>
                              {t(`hr.run.${r.status}`, r.status)}
                            </Pill>
                          </td>
                          <td className="num text-end px-3 py-2.5 border-b border-line">
                            {r.headcount}
                          </td>
                          <td className="num text-end px-3 py-2.5 border-b border-line text-accent">
                            {money(r.service_pool, 0)}
                          </td>
                          <td className="num text-end px-3 py-2.5 border-b border-line">
                            {money(r.total_gross, 0)}
                          </td>
                          <td className="num text-end px-3 py-2.5 border-b border-line font-bold">
                            {money(r.total_net, 0)}
                          </td>
                          <td className="num text-end px-3 pe-5 py-2.5 border-b border-line">
                            {money(r.total_cost, 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            {detail.isLoading && <Loading />}
            {d && (
              <>
                <Card
                  title={`${t("hr.runDetail")} — ${d.label}`}
                  action={
                    <div className="flex items-center gap-2">
                      {canApprove && d.status === "DRAFT" && (
                        <Button
                          disabled={approve.isPending}
                          onClick={() => approve.mutate(d.id)}
                        >
                          {t("hr.approve")}
                        </Button>
                      )}
                      {canApprove && d.status === "APPROVED" && (
                        <Button disabled={pay.isPending} onClick={() => pay.mutate(d.id)}>
                          {t("hr.pay")}
                        </Button>
                      )}
                    </div>
                  }
                >
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 text-[13px]">
                    <Figure label={t("hr.totalGross")} value={money(d.total_gross, 0)} />
                    <Figure
                      label={t("hr.servicePool")}
                      value={money(d.service_pool, 0)}
                      tone="accent"
                    />
                    <Figure
                      label={t("hr.insurance")}
                      value={money(
                        Number(d.total_insurance_employee) + Number(d.total_insurance_employer),
                        0,
                      )}
                    />
                    <Figure label={t("hr.tax")} value={money(d.total_tax, 0)} />
                    <Figure label={t("hr.totalNet")} value={money(d.total_net, 0)} tone="good" />
                    <Figure
                      label={t("hr.employerCost")}
                      value={money(d.total_cost, 0)}
                      tone="warn"
                    />
                  </div>

                  {d.journal_entry_id && (
                    <div className="mt-4 text-[12.5px] text-muted">
                      {t("hr.postedToLedger")}
                    </div>
                  )}
                </Card>

                <Card title={t("hr.byDepartment")} padded={false}>
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-[13px]">
                      <tbody>
                        {d.by_department.map((row) => {
                          const max = Math.max(
                            ...d.by_department.map((x) => Number(x.employer_cost)),
                            1,
                          );
                          return (
                            <tr key={row.department_id} className="hover:bg-surface-2/50">
                              <td className="px-3 ps-5 py-2.5 border-b border-line font-bold w-[26%]">
                                {row.name_ar}
                                <span className="text-[11.5px] text-muted font-normal ms-2 num">
                                  {row.headcount}
                                </span>
                              </td>
                              <td className="px-3 py-2.5 border-b border-line">
                                <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
                                  <div
                                    className="h-full rounded-full bg-accent/50"
                                    style={{
                                      width: `${(Number(row.employer_cost) / max) * 100}%`,
                                    }}
                                  />
                                </div>
                              </td>
                              <td className="num text-end px-3 pe-5 py-2.5 border-b border-line font-bold whitespace-nowrap">
                                {money(row.employer_cost, 0)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </Card>

                <Card title={t("hr.payslips")} padded={false}>
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-[13px]">
                      <thead className="sticky top-0 bg-surface">
                        <tr className="text-muted text-[12px]">
                          <Th className="text-start ps-5">{t("hr.employee")}</Th>
                          <Th className="text-end">{t("hr.basic")}</Th>
                          <Th className="text-end">{t("hr.serviceShare")}</Th>
                          <Th className="text-end">{t("hr.gross")}</Th>
                          <Th className="text-end">{t("hr.insurance")}</Th>
                          <Th className="text-end">{t("hr.tax")}</Th>
                          <Th className="text-end pe-5">{t("hr.net")}</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.payslips.map((s) => (
                          <tr
                            key={s.employee_id}
                            onClick={() => setOpenSlip(s.employee_code)}
                            className="hover:bg-surface-2/50 cursor-pointer"
                          >
                            <td className="px-3 ps-5 py-2.5 border-b border-line">
                              <div className="font-bold">{s.employee_name_ar}</div>
                              <div className="text-[11.5px] text-muted">{s.job_title_ar}</div>
                            </td>
                            <td className="num text-end px-3 py-2.5 border-b border-line">
                              {money(s.basic_salary, 0)}
                            </td>
                            <td className="num text-end px-3 py-2.5 border-b border-line text-accent">
                              {money(s.service_share, 0)}
                            </td>
                            <td className="num text-end px-3 py-2.5 border-b border-line">
                              {money(s.gross, 0)}
                            </td>
                            <td className="num text-end px-3 py-2.5 border-b border-line text-muted">
                              {money(s.insurance_employee, 0)}
                            </td>
                            <td className="num text-end px-3 py-2.5 border-b border-line text-muted">
                              {money(s.income_tax, 0)}
                            </td>
                            <td className="num text-end px-3 pe-5 py-2.5 border-b border-line font-bold">
                              {money(s.net_pay, 0)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </>
            )}
          </>
        )}
      </div>

      {slip && <PayslipCard slip={slip} onClose={() => setOpenSlip(null)} />}
    </>
  );
}

function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "warn" | "accent";
}) {
  const color = {
    good: "text-good",
    warn: "text-warn",
    accent: "text-accent",
  } as const;
  return (
    <div>
      <div className="text-[11.5px] text-muted">{label}</div>
      <div className={cx("num text-[18px] font-bold leading-tight", tone && color[tone])}>
        {value}
      </div>
    </div>
  );
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}
