/** عناصر مشتركة في التطبيق الميداني — شيت، ختم، اختيارات، وضغط الصور. */

import { useEffect, useState, type ReactNode } from "react";
import { Check } from "./icons";

// ═════════════════════════════════════════════════════════ الشيت السفلي
export function Sheet({
  open,
  onClose,
  head,
  foot,
  children,
}: {
  open: boolean;
  onClose: () => void;
  head?: ReactNode;
  foot?: ReactNode;
  children: ReactNode;
}) {
  // زرار الرجوع في الأندرويد المفروض يقفل الشيت مش يخرج من التطبيق
  useEffect(() => {
    if (!open) return;
    const onBack = () => onClose();
    window.addEventListener("popstate", onBack);
    history.pushState({ sheet: true }, "");
    return () => {
      window.removeEventListener("popstate", onBack);
      if (history.state?.sheet) history.back();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div className="f-backdrop" onClick={onClose} />
      <div className="f-sheet" role="dialog" aria-modal="true">
        <div className="f-grip" />
        {head ? <div className="f-sheet-head">{head}</div> : null}
        <div className="f-sheet-body">{children}</div>
        {foot ? <div className="f-sheet-foot">{foot}</div> : null}
      </div>
    </>
  );
}

// ═════════════════════════════════════════════════════════ ختم الإنجاز
/** بيظهر لحظة قفل المهمة — الرد الوحيد اللي مبيحتاجش شبكة. */
export function Seal({ text, onDone }: { text: string; onDone: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDone, 1250);
    return () => clearTimeout(timer);
  }, [onDone]);

  return (
    <div className="f-seal">
      <div>
        <svg className="f-seal-ring" viewBox="0 0 100 100" aria-hidden>
          <circle cx="50" cy="50" r="44" />
          <path d="M30 51.5 44 65l26-28" />
        </svg>
        <div className="f-seal-text">{text}</div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════ الاختيارات
export function Toggle({
  label,
  on,
  onChange,
}: {
  label: string;
  on: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div
      className={`f-check${on ? " is-on" : ""}`}
      onClick={() => onChange(!on)}
      role="checkbox"
      aria-checked={on}
      tabIndex={0}
    >
      <span className="f-box">
        <Check size={15} />
      </span>
      <span>{label}</span>
    </div>
  );
}

export function Pills<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { code: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div className="f-pills">
      {options.map((option) => (
        <button
          key={option.code}
          type="button"
          className={`f-pill${option.code === value ? " is-on" : ""}`}
          onClick={() => onChange(option.code)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// ══════════════════════════════════════════════════════════ وميض الغالق
export function Flash() {
  const [on, setOn] = useState(true);
  useEffect(() => {
    const timer = setTimeout(() => setOn(false), 400);
    return () => clearTimeout(timer);
  }, []);
  return on ? <div className="f-flash" /> : null;
}

// ═══════════════════════════════════════════════════════════ ضغط الصور
/**
 * بيصغّر الصورة قبل ما تتخزّن على التليفون.
 *
 * كاميرا تليفون النهاردة بتطلع صورة ٤ ميجا. جولة فيها ٤٠ صورة = ١٦٠
 * ميجا في IndexedDB ورفعها على شبكة قرية سياحية مستحيل. التصغير لـ
 * ١٢٨٠ بكسل بجودة ٧٢٪ بينزّلها لحوالي ٢٠٠ كيلو — وده كفاية تماماً
 * للغرض: إثبات إن الغرفة كانت في حالة معيّنة قبل وبعد.
 */
export async function compress(file: Blob, max = 1280, quality = 0.72): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
    const width = Math.round(bitmap.width * scale);
    const height = Math.round(bitmap.height * scale);

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close?.();

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality),
    );
    return blob ?? file;
  } catch {
    // متصفح قديم أو صورة غريبة — بنرفع الأصل بدل ما نضيّع الصورة
    return file;
  }
}

// ═══════════════════════════════════════════════════════════ الوقت
export function since(iso: string | null): string {
  if (!iso) return "—";
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "دلوقتي";
  if (minutes < 60) return `من ${minutes} دقيقة`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `من ${hours} ساعة`;
  return `من ${Math.floor(hours / 24)} يوم`;
}

export function clock(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function duration(seconds: number): string {
  if (!seconds) return "—";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} د`;
  return `${Math.floor(minutes / 60)} س ${minutes % 60} د`;
}
