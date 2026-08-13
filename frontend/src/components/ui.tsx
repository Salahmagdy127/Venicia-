/** مكوّنات الواجهة المشتركة — مسطّحة بحدود، بدون ظلال. */

import type { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";
import { IconWarning } from "./Icons";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/* ─────────────────────────────────────────────────────── البطاقة */
export function Card({
  children,
  className,
  title,
  action,
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  action?: ReactNode;
  padded?: boolean;
}) {
  return (
    <section
      className={cx(
        "bg-surface border border-line rounded-[8px] flex flex-col min-h-0",
        className,
      )}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 px-5 py-3 border-b border-line shrink-0">
          <h2 className="text-[15px] font-bold">{title}</h2>
          {action}
        </header>
      )}
      <div className={cx("min-h-0 flex-1", padded && "p-5")}>{children}</div>
    </section>
  );
}

/* ─────────────────────────────────────────────────────── الحبّة */
type Tone = "accent" | "gold" | "good" | "bad" | "muted";

const TONE_STYLE: Record<Tone, string> = {
  accent: "bg-accent-soft text-accent",
  gold: "bg-gold-soft text-gold",
  good: "bg-good/12 text-good",
  bad: "bg-bad/12 text-bad",
  muted: "bg-surface-2 text-ink-2",
};

export function Pill({
  children,
  tone = "muted",
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-bold whitespace-nowrap leading-6",
        TONE_STYLE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ─────────────────────────────────────────────────────── الأزرار */
type BtnVariant = "primary" | "secondary" | "ghost" | "danger";

const BTN: Record<BtnVariant, string> = {
  primary: "bg-accent text-accent-ink hover:bg-accent-hover border border-transparent",
  secondary: "bg-transparent text-ink border border-line-strong hover:bg-surface-2",
  ghost: "bg-transparent text-ink-2 border border-transparent hover:bg-surface-2",
  danger: "bg-transparent text-bad border border-bad/40 hover:bg-bad/10",
};

export function Button({
  children,
  variant = "secondary",
  size = "md",
  className,
  ...rest
}: {
  children: ReactNode;
  variant?: BtnVariant;
  size?: "sm" | "md" | "lg";
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const sizes = {
    sm: "h-8 px-3 text-[13px]",
    md: "h-10 px-4 text-[14px]",
    lg: "h-12 px-5 text-[15px]",
  };
  return (
    <button
      {...rest}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-[6px] font-bold transition-colors",
        "disabled:opacity-45 disabled:cursor-not-allowed",
        BTN[variant],
        sizes[size],
        className,
      )}
    >
      {children}
    </button>
  );
}

/* ────────────────────────────────────────────── بلاطة مؤشر (KPI) */
export function StatTile({
  label,
  value,
  suffix,
  change,
  tone = "ink",
}: {
  label: string;
  value: string;
  suffix?: string;
  change?: number | null;
  tone?: "ink" | "gold" | "accent";
}) {
  const color =
    tone === "gold" ? "text-gold" : tone === "accent" ? "text-accent" : "text-ink";
  return (
    <div className="bg-surface border border-line rounded-[8px] px-5 py-4 flex flex-col gap-1">
      <span className="text-[12.5px] text-muted font-bold">{label}</span>
      <span className={cx("num text-[26px] font-bold leading-tight", color)}>
        {value}
        {suffix && <span className="text-[15px] font-bold opacity-70"> {suffix}</span>}
      </span>
      {change !== null && change !== undefined && Number.isFinite(change) && (
        <span
          className={cx(
            "num text-[12.5px] font-bold",
            change >= 0 ? "text-good" : "text-bad",
          )}
        >
          {change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(1)}%
        </span>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────── الحالات الفارغة */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cx(
        "inline-block w-5 h-5 rounded-full border-2 border-line border-t-accent animate-spin",
        className,
      )}
      role="status"
      aria-label="loading"
    />
  );
}

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="h-full w-full flex items-center justify-center gap-3 text-muted py-16">
      <Spinner />
      <span className="text-[14px]">{label ?? t("state.loading")}</span>
    </div>
  );
}

export function EmptyState({ title, hint }: { title?: string; hint?: string }) {
  const { t } = useI18n();
  return (
    <div className="h-full w-full flex flex-col items-center justify-center gap-2 py-16 text-center">
      <span className="text-[15px] font-bold text-ink-2">{title ?? t("state.empty")}</span>
      {hint && <span className="text-[13px] text-muted max-w-[42ch]">{hint}</span>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="h-full w-full flex flex-col items-center justify-center gap-3 py-16 text-center">
      <IconWarning size={22} className="text-bad" />
      <span className="text-[14px] font-bold text-ink">{message ?? t("state.error")}</span>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          {t("action.retry")}
        </Button>
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────── المودال */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = 460,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
      onClick={onClose}
    >
      <div
        className="bg-surface border border-line rounded-[8px] w-full flex flex-col max-h-[88vh]"
        style={{ maxWidth: width }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <header className="px-5 py-3.5 border-b border-line shrink-0">
          <h3 className="text-[15px] font-bold">{title}</h3>
        </header>
        <div className="p-5 overflow-y-auto min-h-0">{children}</div>
        {footer && (
          <footer className="px-5 py-3.5 border-t border-line flex items-center justify-end gap-2 shrink-0">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────── المدخلات */
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5 mb-4">
      <span className="text-[13px] font-bold text-ink-2">{label}</span>
      {children}
      {hint && <span className="text-[12px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "h-10 px-3 rounded-[6px] bg-surface border border-line-strong text-ink " +
  "focus:border-accent outline-none w-full";
