/** رسومات مرسومة بالـ SVG — بدون أي مكتبة، وبتاخد ألوان الثيم. */

import { useI18n } from "@/lib/i18n";
import { compact, formatDateShort, money, parseDate } from "@/lib/format";
import { cx } from "./ui";

const W = 900;
const H = 250;
const PAD = { top: 14, right: 46, bottom: 26, left: 52 };

export type ComboPoint = {
  date: string;
  /** العمود — الإيراد */
  bar: number;
  /** الخط — نسبة الإشغال */
  line: number;
};

/**
 * إيراد يومي كأعمدة + نسبة إشغال كخط فوقيها.
 * الوقت بيمشي من الشمال لليمين في اللغتين — ده المتعارف عليه في الرسوم.
 */
export function ComboChart({ points, barLabel, lineLabel }: {
  points: ComboPoint[];
  barLabel: string;
  lineLabel: string;
}) {
  const { locale } = useI18n();
  if (points.length === 0) return null;

  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const maxBar = Math.max(...points.map((p) => p.bar), 1);
  const niceMax = niceCeil(maxBar);
  const n = points.length;
  const slot = innerW / n;
  const barW = Math.max(2, Math.min(26, slot * 0.62));

  const x = (i: number) => PAD.left + slot * i + slot / 2;
  const yBar = (v: number) => PAD.top + innerH - (v / niceMax) * innerH;
  const yLine = (v: number) => PAD.top + innerH - (Math.min(v, 100) / 100) * innerH;

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${yLine(p.line).toFixed(1)}`)
    .join(" ");

  // عدد تسميات المحور الأفقي بيقل لما الأيام تكتر
  const step = Math.ceil(n / 12);

  return (
    <figure className="m-0" dir="ltr">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-[250px]"
        role="img"
        aria-label={`${barLabel} & ${lineLabel}`}
      >
        {/* شبكة أفقية + محور الإيراد */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const y = PAD.top + innerH - f * innerH;
          return (
            <g key={f}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y}
                y2={y}
                stroke="var(--line)"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 8}
                y={y + 4}
                textAnchor="end"
                fontSize={11}
                fill="var(--muted)"
                fontFamily="var(--font-mono)"
              >
                {compact(niceMax * f)}
              </text>
              <text
                x={W - PAD.right + 8}
                y={y + 4}
                textAnchor="start"
                fontSize={11}
                fill="var(--muted)"
                fontFamily="var(--font-mono)"
              >
                {Math.round(f * 100)}%
              </text>
            </g>
          );
        })}

        {/* الأعمدة */}
        {points.map((p, i) => {
          const y = yBar(p.bar);
          return (
            <rect
              key={p.date}
              x={x(i) - barW / 2}
              y={y}
              width={barW}
              height={Math.max(1, PAD.top + innerH - y)}
              rx={2}
              fill="var(--accent)"
              opacity={0.85}
            >
              <title>
                {`${formatDateShort(p.date, locale)} — ${money(p.bar, 0)} · ${p.line.toFixed(1)}%`}
              </title>
            </rect>
          );
        })}

        {/* خط الإشغال */}
        <path d={linePath} fill="none" stroke="var(--gold)" strokeWidth={2} />
        {points.map((p, i) => (
          <circle key={p.date} cx={x(i)} cy={yLine(p.line)} r={2.2} fill="var(--gold)" />
        ))}

        {/* تواريخ المحور */}
        {points.map((p, i) =>
          i % step === 0 || i === n - 1 ? (
            <text
              key={p.date}
              x={x(i)}
              y={H - 8}
              textAnchor="middle"
              fontSize={10.5}
              fill="var(--muted)"
              fontFamily="var(--font-mono)"
            >
              {parseDate(p.date).getDate()}
            </text>
          ) : null,
        )}
      </svg>

      <figcaption className="flex items-center gap-4 justify-center pt-1">
        <span className="flex items-center gap-1.5 text-[11.5px] text-ink-2">
          <span className="w-3 h-3 rounded-[2px] bg-accent" /> {barLabel}
        </span>
        <span className="flex items-center gap-1.5 text-[11.5px] text-ink-2">
          <span className="w-3.5 h-0.5 bg-gold" /> {lineLabel}
        </span>
      </figcaption>
    </figure>
  );
}

/** قائمة بأعمدة أفقية — للمصادر والمنافذ. */
export function BarList({
  rows,
  tone = "accent",
}: {
  rows: { key: string; label: string; value: string; percent: number; note?: string }[];
  tone?: "accent" | "gold";
}) {
  const max = Math.max(...rows.map((r) => r.percent), 1);
  return (
    <div className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <div key={r.key} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[13px] text-ink truncate">{r.label}</span>
            <span className="num text-[13px] font-bold shrink-0">{r.value}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 rounded-full bg-surface-2 overflow-hidden">
              <div
                className={cx("h-full rounded-full", tone === "gold" ? "bg-gold" : "bg-accent")}
                style={{ width: `${(r.percent / max) * 100}%` }}
              />
            </div>
            <span className="num text-[11.5px] text-muted w-[42px] text-end shrink-0">
              {r.percent.toFixed(1)}%
            </span>
          </div>
          {r.note && <span className="text-[11.5px] text-muted">{r.note}</span>}
        </div>
      ))}
    </div>
  );
}

/** خط صغير بدون محاور — جوّه البلاطات. */
export function Sparkline({ values, color = "var(--accent)" }: { values: number[]; color?: string }) {
  if (values.length < 2) return null;
  const w = 120;
  const h = 28;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const d = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 4) - 2;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-[120px] h-7" aria-hidden="true">
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} />
      <circle
        cx={w}
        cy={h - ((values[values.length - 1] - min) / range) * (h - 4) - 2}
        r={2.4}
        fill={color}
      />
    </svg>
  );
}

/** يقرّب الحد الأعلى لرقم مريح للعين */
function niceCeil(v: number) {
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = v / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}
