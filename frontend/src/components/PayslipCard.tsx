/** قسيمة مرتب — كل عنصر مكتوب لوحده عشان الموظف يفهم رقمه. */

import { useI18n } from "@/lib/i18n";
import { money } from "@/lib/format";
import type { PayslipOut } from "@/lib/types";
import { Modal, cx } from "./ui";

export default function PayslipCard({
  slip,
  onClose,
}: {
  slip: PayslipOut;
  onClose: () => void;
}) {
  const { t } = useI18n();

  const earnings: [string, string][] = [
    [t("hr.basic"), slip.basic_salary],
    [t("hr.allowances"), slip.allowances],
    [t("hr.overtime"), slip.overtime],
    [t("hr.serviceShare"), slip.service_share],
    [t("hr.bonus"), slip.bonus],
  ];

  const deductions: [string, string][] = [
    [t("hr.insuranceEmployee"), slip.insurance_employee],
    [t("hr.tax"), slip.income_tax],
    [t("hr.unpaidLeave"), slip.unpaid_leave],
    [t("hr.advances"), slip.advances],
    [t("hr.penalties"), slip.penalties],
  ];

  return (
    <Modal open title={slip.employee_name_ar} onClose={onClose} width={560}>
      <div className="flex flex-col gap-4">
        <div className="text-[12.5px] text-muted">
          <span className="num">{slip.employee_code}</span> · {slip.job_title_ar}
        </div>

        <Section title={t("hr.earnings")} rows={earnings} total={slip.gross} tone="good" />
        <Section
          title={t("hr.deductions")}
          rows={deductions}
          total={slip.total_deductions}
          tone="bad"
        />

        <div className="rounded-[6px] border border-line-strong bg-surface-2 px-4 py-3 flex items-baseline justify-between">
          <span className="text-[13px] font-bold">{t("hr.net")}</span>
          <span className="num text-[24px] font-bold">{money(slip.net_pay, 2)}</span>
        </div>

        {/* حصة صاحب العمل مش بتتخصم من الموظف — بس بتوضّح التكلفة الحقيقية */}
        <div className="text-[12px] text-muted flex items-center justify-between border-t border-line pt-3">
          <span>{t("hr.insuranceEmployer")}</span>
          <span className="num">{money(slip.insurance_employer, 2)}</span>
        </div>
      </div>
    </Modal>
  );
}

function Section({
  title,
  rows,
  total,
  tone,
}: {
  title: string;
  rows: [string, string][];
  total: string;
  tone: "good" | "bad";
}) {
  const visible = rows.filter(([, value]) => Number(value) !== 0);
  if (visible.length === 0) return null;
  return (
    <div>
      <div className="text-[12px] font-bold text-muted mb-1.5">{title}</div>
      <div className="rounded-[6px] border border-line overflow-hidden">
        {visible.map(([label, value]) => (
          <div
            key={label}
            className="flex items-center justify-between px-4 py-2 text-[13px] border-b border-line last:border-b-0"
          >
            <span className="text-ink-2">{label}</span>
            <span className="num">{money(value, 2)}</span>
          </div>
        ))}
        <div
          className={cx(
            "flex items-center justify-between px-4 py-2.5 text-[13px] font-bold bg-surface-2",
            tone === "good" ? "text-good" : "text-bad",
          )}
        >
          <span>{title}</span>
          <span className="num">{money(total, 2)}</span>
        </div>
      </div>
    </div>
  );
}
