/** الإعدادات — فئات الوحدات وخطط الأسعار وحسابك وصلاحياتك. */

import { useQuery } from "@tanstack/react-query";

import { get } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { money } from "@/lib/format";
import type { RatePlan, UnitCategoryOut } from "@/lib/types";
import PageHeader from "@/components/PageHeader";
import { Card, Loading, cx } from "@/components/ui";

export default function Settings() {
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useTheme();
  const { user, maxDiscount } = useAuth();

  const categories = useQuery({
    queryKey: ["unit-categories"],
    queryFn: () => get<UnitCategoryOut[]>("/unit-categories"),
    staleTime: 10 * 60_000,
  });

  const plans = useQuery({
    queryKey: ["rate-plans"],
    queryFn: () => get<RatePlan[]>("/rate-plans"),
    staleTime: 10 * 60_000,
  });

  const cur = locale === "ar" ? "ج.م" : "EGP";
  const totalUnits = categories.data?.reduce((s, c) => s + c.unit_count, 0) ?? 0;

  return (
    <>
      <PageHeader
        title={t("nav.settings")}
        subtitle={`${t("app.tagline")} · ${totalUnits} ${t("set.units")}`}
      />

      <div className="flex-1 min-h-0 overflow-y-auto p-5">
        <div className="grid gap-4 grid-cols-1 xl:grid-cols-3 max-w-[1400px]">
          {/* فئات الوحدات */}
          <Card className="xl:col-span-2" title={t("set.categories")} padded={false}>
            {categories.isLoading && <Loading />}
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="text-muted text-[12px]">
                  <th className="text-start font-bold px-5 py-2.5 border-b border-line">
                    {t("tape.unit")}
                  </th>
                  <th className="text-end font-bold px-3 py-2.5 border-b border-line">
                    {t("set.units")}
                  </th>
                  <th className="text-end font-bold px-3 py-2.5 border-b border-line">
                    {t("set.occupancy")}
                  </th>
                  <th className="text-end font-bold px-5 py-2.5 border-b border-line">
                    {t("set.baseRate")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {categories.data?.map((c) => (
                  <tr key={c.id}>
                    <td className="px-5 py-2.5 border-b border-line">
                      <div className="font-bold">{locale === "ar" ? c.name_ar : c.name_en}</div>
                      <div className="num text-[11.5px] text-muted">{c.code}</div>
                    </td>
                    <td className="num text-end px-3 py-2.5 border-b border-line font-bold">
                      {c.unit_count}
                    </td>
                    <td className="num text-end px-3 py-2.5 border-b border-line text-ink-2">
                      {c.base_occupancy}–{c.max_occupancy}
                    </td>
                    <td className="num text-end px-5 py-2.5 border-b border-line font-bold">
                      {money(c.base_rate, 0)} <span className="text-[11px] opacity-60">{cur}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {/* حسابك */}
          <div className="flex flex-col gap-4">
            <Card title={t("set.account")}>
              <div className="flex flex-col gap-2 text-[13.5px]">
                <Row
                  label={t("login.username")}
                  value={user?.username ?? "—"}
                  mono
                />
                <Row
                  label={t("res.guest")}
                  value={(locale === "ar" ? user?.full_name_ar : user?.full_name_en) ?? "—"}
                />
                <Row
                  label={t("res.status")}
                  value={
                    user?.roles
                      .map((r) => (locale === "ar" ? r.name_ar : r.name_en))
                      .join(" · ") || "—"
                  }
                />
                <Row label={t("set.maxDiscount")} value={`${maxDiscount}%`} mono />
              </div>
            </Card>

            <Card title={t("set.appearance")}>
              <div className="flex flex-col gap-3">
                <Toggle
                  label="العربية / English"
                  options={[
                    { key: "ar", label: "العربية" },
                    { key: "en", label: "English" },
                  ]}
                  value={locale}
                  onChange={(v) => setLocale(v as "ar" | "en")}
                />
                <Toggle
                  label={t("set.appearance")}
                  options={[
                    { key: "light", label: locale === "ar" ? "فاتح" : "Light" },
                    { key: "dark", label: locale === "ar" ? "داكن" : "Dark" },
                  ]}
                  value={theme}
                  onChange={(v) => setTheme(v as "light" | "dark")}
                />
              </div>
            </Card>
          </div>

          {/* خطط الأسعار */}
          <Card className="xl:col-span-2" title={t("set.ratePlans")} padded={false}>
            {plans.isLoading && <Loading />}
            <ul className="m-0 p-0 list-none">
              {plans.data?.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center gap-3 px-5 py-2.5 border-b border-line last:border-b-0"
                >
                  <span className="text-[13.5px] font-bold flex-1 min-w-0 truncate">
                    {locale === "ar" ? p.name_ar : p.name_en}
                  </span>
                  <span className="num text-[11.5px] text-muted">{p.code}</span>
                </li>
              ))}
            </ul>
          </Card>

          {/* الصلاحيات */}
          <Card title={t("set.permissions")}>
            <div className="flex flex-wrap gap-1.5">
              {user?.permissions.map((p) => (
                <span
                  key={p}
                  className="mono text-[11.5px] rounded-full border border-line px-2 py-0.5 text-ink-2"
                >
                  {p}
                </span>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="text-[13px] text-muted w-[100px] shrink-0">{label}</span>
      <span className={cx("font-bold", mono && "num")}>{value}</span>
    </div>
  );
}

function Toggle({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: string; label: string }[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div>
      <div className="text-[12.5px] text-muted font-bold mb-1.5">{label}</div>
      <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden">
        {options.map((o) => (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className={cx(
              "flex-1 h-9 text-[13px] font-bold border-e border-line-strong last:border-e-0",
              value === o.key ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
