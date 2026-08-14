/** المنيو على موبايل النزيل — الصفحة اللي الـ QR بيوديله. */

import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { get, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import { money } from "@/lib/format";
import type { PublicMenu } from "@/lib/types";
import { Spinner, cx } from "@/components/ui";
import { IconGlobe, IconMoon, IconSun, IconWaves } from "@/components/Icons";

export default function Menu() {
  const { code = "" } = useParams();
  const [params] = useSearchParams();
  const table = params.get("table");

  const { t, locale, toggle: toggleLocale } = useI18n();
  const { theme, toggle: toggleTheme } = useTheme();
  const ar = locale === "ar";

  const [active, setActive] = useState<string | null>(null);

  const menu = useQuery({
    queryKey: ["public-menu", code, table],
    queryFn: () => get<PublicMenu>(`/menu/${code}${qs({ table: table || undefined })}`),
    retry: false,
  });

  const m = menu.data;
  const cur = ar ? "ج.م" : "EGP";

  if (menu.isLoading) {
    return (
      <div className="min-h-screen bg-ground grid place-items-center">
        <Spinner />
      </div>
    );
  }

  if (menu.isError || !m) {
    return (
      <div className="min-h-screen bg-ground grid place-items-center px-6 text-center">
        <div>
          <p className="text-[17px] font-bold text-ink">{t("qr.notFound")}</p>
          <p className="text-[13px] text-muted mt-1">{t("qr.notFoundHint")}</p>
        </div>
      </div>
    );
  }

  const shown = active
    ? m.categories.filter((c) => c.name_ar === active)
    : m.categories;

  return (
    <div className="min-h-screen bg-ground text-ink">
      {/* الترويسة */}
      <header className="bg-surface border-b border-line sticky top-0 z-10">
        <div className="max-w-[640px] mx-auto px-4 h-14 flex items-center gap-3">
          <span className="w-8 h-8 rounded-[7px] bg-accent grid place-items-center shrink-0">
            <IconWaves size={17} className="text-accent-ink" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-bold leading-tight truncate">
              {ar ? m.outlet_name_ar : m.outlet_name_en}
            </div>
            <div className="text-[11px] text-muted truncate">
              {ar ? m.property_name_ar : m.property_name_en}
              {m.table_label && (
                <span className="num ms-2 font-bold text-accent">
                  {t("qr.table")} {m.table_label}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={toggleLocale}
            className="w-8 h-8 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2"
            aria-label="Switch language"
          >
            <IconGlobe size={17} />
          </button>
          <button
            onClick={toggleTheme}
            className="w-8 h-8 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2"
            aria-label="Switch theme"
          >
            {theme === "dark" ? <IconSun size={17} /> : <IconMoon size={17} />}
          </button>
        </div>

        {/* شريط الأقسام */}
        <div className="max-w-[640px] mx-auto px-4 pb-2.5 flex gap-1.5 overflow-x-auto">
          <Chip active={active === null} onClick={() => setActive(null)}>
            {t("qr.all")}
          </Chip>
          {m.categories.map((c) => (
            <Chip
              key={c.name_ar}
              active={active === c.name_ar}
              onClick={() => setActive(c.name_ar)}
            >
              {ar ? c.name_ar : c.name_en}
            </Chip>
          ))}
        </div>
      </header>

      <main className="max-w-[640px] mx-auto px-4 py-5 flex flex-col gap-6">
        {shown.map((category) => (
          <section key={category.name_ar}>
            <h2 className="text-[15px] font-bold text-accent mb-2.5">
              {ar ? category.name_ar : category.name_en}
            </h2>
            <div className="flex flex-col">
              {category.items.map((item, index) => (
                <article
                  key={`${category.name_ar}-${index}`}
                  className={cx(
                    "flex items-start gap-3 py-3",
                    index > 0 && "border-t border-line",
                    item.is_out_of_stock && "opacity-45",
                  )}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[14.5px] font-bold">
                        {ar ? item.name_ar : item.name_en}
                      </span>
                      {item.is_vegetarian && (
                        <span className="text-[10px] font-bold text-good border border-good/40 rounded-full px-1.5 py-px">
                          {t("qr.veg")}
                        </span>
                      )}
                      {item.contains_alcohol && (
                        <span className="text-[10px] font-bold text-warn border border-warn/40 rounded-full px-1.5 py-px">
                          {t("qr.alcohol")}
                        </span>
                      )}
                    </div>
                    {(ar ? item.description_ar : item.description_en) && (
                      <p className="text-[12.5px] text-muted leading-relaxed mt-0.5">
                        {ar ? item.description_ar : item.description_en}
                      </p>
                    )}
                    {item.is_out_of_stock ? (
                      <p className="text-[11.5px] font-bold text-bad mt-1">
                        {t("qr.soldOut")}
                      </p>
                    ) : (
                      item.preparation_minutes && (
                        <p className="text-[11px] text-muted mt-1">
                          <span className="num">{item.preparation_minutes}</span>{" "}
                          {t("qr.minutes")}
                        </p>
                      )
                    )}
                  </div>
                  <div className="num text-[15px] font-bold text-accent shrink-0 pt-0.5">
                    {money(item.price, 0)}
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))}

        <footer className="text-[11.5px] text-muted text-center pt-4 border-t border-line leading-relaxed">
          {t("qr.taxNote")
            .replace("{s}", String(Number(m.service_charge_percent)))
            .replace("{v}", String(Number(m.vat_percent)))}
          <div className="mt-1">
            {t("qr.itemCount").replace("{n}", String(m.item_count))} · {cur}
          </div>
        </footer>
      </main>
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cx(
        "shrink-0 h-8 px-3 rounded-full text-[12.5px] font-bold border transition-colors",
        active
          ? "bg-accent text-accent-ink border-transparent"
          : "border-line-strong text-ink-2 hover:bg-surface-2",
      )}
    >
      {children}
    </button>
  );
}
