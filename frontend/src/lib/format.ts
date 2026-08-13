/** التنسيق — الأرقام إنجليزية دايماً، والتواريخ حسب لغة العرض. */

import type { Locale } from "./i18n";

const AR_MONTHS = [
  "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
  "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
];
const EN_MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const AR_DAYS = ["اثنين", "ثلاثاء", "أربعاء", "خميس", "جمعة", "سبت", "أحد"];
const EN_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** ISO weekday: الاثنين = 0 */
export function weekdayIndex(d: Date) {
  return (d.getDay() + 6) % 7;
}

export function parseDate(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function toISO(d: Date): string {
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function addDays(d: Date, n: number): Date {
  const copy = new Date(d);
  copy.setDate(copy.getDate() + n);
  return copy;
}

export function weekdayName(d: Date, locale: Locale) {
  return (locale === "ar" ? AR_DAYS : EN_DAYS)[weekdayIndex(d)];
}

export function monthName(monthIndex: number, locale: Locale) {
  return (locale === "ar" ? AR_MONTHS : EN_MONTHS)[monthIndex];
}

/** 12 أغسطس 2026 · 12 Aug 2026 — الأرقام إنجليزية في اللغتين */
export function formatDate(value: string | Date, locale: Locale) {
  const d = typeof value === "string" ? parseDate(value.slice(0, 10)) : value;
  return `${d.getDate()} ${monthName(d.getMonth(), locale)} ${d.getFullYear()}`;
}

export function formatDateShort(value: string | Date, locale: Locale) {
  const d = typeof value === "string" ? parseDate(value.slice(0, 10)) : value;
  return `${d.getDate()} ${monthName(d.getMonth(), locale)}`;
}

export function formatRange(from: string | Date, to: string | Date, locale: Locale) {
  const a = typeof from === "string" ? parseDate(from.slice(0, 10)) : from;
  const b = typeof to === "string" ? parseDate(to.slice(0, 10)) : to;
  if (a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear()) {
    return `${a.getDate()} – ${b.getDate()} ${monthName(a.getMonth(), locale)} ${a.getFullYear()}`;
  }
  return `${formatDateShort(a, locale)} – ${formatDate(b, locale)}`;
}

export function formatTime(value: string) {
  const d = new Date(value);
  const h = `${d.getHours()}`.padStart(2, "0");
  const m = `${d.getMinutes()}`.padStart(2, "0");
  return `${h}:${m}`;
}

const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** 1,234.56 — دايماً بأرقام إنجليزية */
export function money(value: number | string | null | undefined, decimals = 2): string {
  const n = typeof value === "string" ? Number(value) : (value ?? 0);
  if (!Number.isFinite(n)) return "0.00";
  return decimals === 0 ? nf0.format(n) : nf2.format(n);
}

/** 1.2M · 384K · 950 — للأرقام الكبيرة في الداشبورد */
export function compact(value: number | string | null | undefined): string {
  const n = typeof value === "string" ? Number(value) : (value ?? 0);
  if (!Number.isFinite(n)) return "0";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}K`;
  return nf0.format(n);
}

export function percent(value: number | string | null | undefined, decimals = 1): string {
  const n = typeof value === "string" ? Number(value) : (value ?? 0);
  if (!Number.isFinite(n)) return "0%";
  return `${n.toFixed(decimals)}%`;
}

export const CURRENCY = { ar: "ج.م", en: "EGP" } as const;

export function currency(locale: Locale) {
  return CURRENCY[locale];
}
