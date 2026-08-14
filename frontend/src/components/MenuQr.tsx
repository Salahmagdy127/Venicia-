/** أكواد QR للمنيو — جاهزة للطباعة واللصق على الطاولات. */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { get } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Outlet, PosTable } from "@/lib/types";
import { Button, Card, cx, inputClass } from "./ui";

//: عنوان السيرفر زي ما المتصفح شايفه — الكود بيشاور على نفس المكان،
//: فعلى الشبكة المحلية بيشتغل من غير أي ضبط.
const ORIGIN = window.location.origin;

export default function MenuQr({ outlets }: { outlets: Outlet[] }) {
  const { t, locale } = useI18n();
  const [outletId, setOutletId] = useState<number | "">(outlets[0]?.id ?? "");
  const [tableLabel, setTableLabel] = useState("");

  const outlet = outlets.find((o) => o.id === outletId);

  const tables = useQuery({
    queryKey: ["pos", "floor-plan", outletId],
    queryFn: () => get<{ tables: PosTable[] }>(`/pos/outlets/${outletId}/floor-plan`),
    enabled: typeof outletId === "number" && Boolean(outlet?.has_floor_plan),
  });

  if (!outlet) return null;

  const target =
    `${ORIGIN}/menu/${outlet.code}` + (tableLabel ? `?table=${encodeURIComponent(tableLabel)}` : "");
  const qrSrc =
    `/api/v1/menu/${outlet.code}/qr.svg?base_url=${encodeURIComponent(ORIGIN)}` +
    (tableLabel ? `&table=${encodeURIComponent(tableLabel)}` : "");

  return (
    <Card title={t("qr.title")}>
      <p className="text-[12.5px] text-muted leading-relaxed mb-4">{t("qr.hint")}</p>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-bold text-ink-2">{t("pos.outlet")}</span>
          <select
            className={inputClass}
            value={outletId}
            onChange={(e) => {
              setOutletId(Number(e.target.value));
              setTableLabel("");
            }}
          >
            {outlets.map((o) => (
              <option key={o.id} value={o.id}>
                {locale === "ar" ? o.name_ar : o.name_en}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-bold text-ink-2">{t("qr.forTable")}</span>
          <select
            className={cx(inputClass, "num")}
            value={tableLabel}
            onChange={(e) => setTableLabel(e.target.value)}
          >
            <option value="">{t("qr.wholeOutlet")}</option>
            {tables.data?.tables.map((x) => (
              <option key={x.id} value={x.label}>
                {x.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* الكود نفسه — بيتطبع من المتصفح مباشرة */}
      <div className="flex flex-col items-center gap-3 border border-line rounded-[8px] p-5 bg-white">
        <img
          src={qrSrc}
          alt={t("qr.title")}
          width={200}
          height={200}
          className="w-[200px] h-[200px]"
        />
        <div className="text-center">
          <div className="text-[14px] font-bold text-[#111]">
            {locale === "ar" ? outlet.name_ar : outlet.name_en}
          </div>
          {tableLabel && (
            <div className="num text-[13px] text-[#555]">
              {t("qr.table")} {tableLabel}
            </div>
          )}
          <div className="text-[11px] text-[#777] mt-1">{t("qr.scanMe")}</div>
        </div>
      </div>

      <p className="num text-[11px] text-muted mt-3 break-all text-center" dir="ltr">
        {target}
      </p>

      <div className="flex items-center gap-2 mt-4">
        <Button className="flex-1" onClick={() => window.open(target, "_blank")}>
          {t("qr.preview")}
        </Button>
        <Button variant="primary" className="flex-1" onClick={() => window.print()}>
          {t("qr.print")}
        </Button>
      </div>
    </Card>
  );
}
