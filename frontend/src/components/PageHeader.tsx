/** شريط عنوان الشاشة — عنوان وسطر توضيحي على الشمال، أدوات على اليمين. */

import type { ReactNode } from "react";
import { TopBarToggles } from "./Layout";
import { cx } from "./ui";

export default function PageHeader({
  title,
  subtitle,
  children,
  className,
}: {
  title: string;
  subtitle?: ReactNode;
  /** أدوات الشاشة — بتتحط قبل زراير اللغة والثيم */
  children?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cx(
        "shrink-0 h-16 px-5 border-b border-line bg-surface flex items-center gap-4",
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="text-[18px] font-bold leading-tight truncate">{title}</h1>
        {subtitle && (
          <div className="text-[12.5px] text-muted leading-tight truncate">{subtitle}</div>
        )}
      </div>
      <div className="flex-1" />
      {children}
      <TopBarToggles />
    </header>
  );
}

/** صف مؤشرات صغير تحت العنوان — رقم + وصف، مفصولين بخط. */
export function StatStrip({
  items,
}: {
  items: { label: string; value: string; tone?: "ink" | "good" | "warn" | "bad" | "accent" }[];
}) {
  const color = {
    ink: "text-ink",
    good: "text-good",
    warn: "text-warn",
    bad: "text-bad",
    accent: "text-accent",
  } as const;
  return (
    <div className="flex items-stretch divide-x divide-line rtl:divide-x-reverse">
      {items.map((it) => (
        <div key={it.label} className="px-4 first:ps-0 last:pe-0 flex flex-col justify-center">
          <span className={cx("num text-[17px] font-bold leading-tight", color[it.tone ?? "ink"])}>
            {it.value}
          </span>
          <span className="text-[11.5px] text-muted leading-tight whitespace-nowrap">
            {it.label}
          </span>
        </div>
      ))}
    </div>
  );
}
