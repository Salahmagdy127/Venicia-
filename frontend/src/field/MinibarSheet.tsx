/**
 * جرد الميني بار من التليفون.
 *
 * ده أقصر مسار في التطبيق بين شغل الهاوس كيبر وفلوس القرية: البند
 * بيترحّل على حساب النزيل وهو لسه في الغرفة. المسار القديم — ورقة في
 * الجيب توصل الاستقبال آخر اليوم — كان بيخسّر القرية استهلاك يوم
 * المغادرة كله، لأن النزيل بيكون مشي.
 *
 * وجرد فاضي معلومة برضه: «الميني بار متلمسش» بيتسجّل زي «اتاخد منه
 * حاجتين»، عشان محدش يقول بعدين إن الغرفة ماتجردتش.
 */

import { useMemo, useState } from "react";

import { useField } from "./store";
import { Cup } from "./icons";
import { Sheet } from "./ui";
import type { Task } from "./types";

export default function MinibarSheet({
  task,
  onClose,
  onSent,
}: {
  task: Task;
  onClose: () => void;
  onSent: () => void;
}) {
  const { act, boot } = useField();
  const [counts, setCounts] = useState<Record<number, number>>({});
  const [busy, setBusy] = useState(false);

  const items = boot?.minibar ?? [];
  const total = useMemo(
    () =>
      items.reduce(
        (sum, item) => sum + (counts[item.id] ?? 0) * Number(item.price),
        0,
      ),
    [counts, items],
  );
  const taken = Object.values(counts).filter((n) => n > 0).length;

  function bump(id: number, delta: number) {
    setCounts((current) => {
      const next = Math.max(0, (current[id] ?? 0) + delta);
      return { ...current, [id]: next };
    });
  }

  async function send() {
    setBusy(true);
    try {
      await act("task.minibar", {
        taskId: task.id,
        payload: {
          lines: Object.entries(counts)
            .filter(([, quantity]) => quantity > 0)
            .map(([item_id, quantity]) => ({ item_id: Number(item_id), quantity })),
        },
      });
      onSent();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      open
      onClose={onClose}
      head={
        <>
          <div style={{ fontSize: 19, fontWeight: 800 }}>ميني بار — {task.unit_label}</div>
          <div style={{ fontSize: 13, color: "var(--f-ink-3)", marginTop: 4 }}>
            عدّ اللي ناقص وهيترحّل على حساب النزيل
          </div>
        </>
      }
      foot={
        <>
          <button className="f-btn is-ghost" onClick={onClose}>
            رجوع
          </button>
          <button
            className="f-btn is-primary"
            style={{ flex: 1 }}
            disabled={busy}
            onClick={send}
          >
            <Cup size={19} />
            {taken ? (
              <>
                رحّل <span className="f-num">{total.toFixed(2)}</span> ج
              </>
            ) : (
              "متلمسش"
            )}
          </button>
        </>
      }
    >
      {items.length === 0 ? (
        <div className="f-empty-text">مفيش أصناف ميني بار معرّفة.</div>
      ) : null}

      {items.map((item) => {
        const count = counts[item.id] ?? 0;
        return (
          <div
            key={item.id}
            className={`f-check${count ? " is-on" : ""}`}
            style={{ justifyContent: "space-between" }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14.5, fontWeight: 700 }}>{item.name_ar}</div>
              <div style={{ fontSize: 12, color: "var(--f-ink-3)", fontWeight: 500 }}>
                <span className="f-num">{Number(item.price).toFixed(2)}</span> ج
                {item.contains_alcohol ? " · كحولي" : ""}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button
                className="f-btn is-ghost is-sm"
                style={{ minWidth: 44, padding: 0, fontSize: 20 }}
                onClick={() => bump(item.id, -1)}
                disabled={!count}
                aria-label="أقل"
              >
                −
              </button>
              <span
                className="f-num"
                style={{ minWidth: 22, textAlign: "center", fontSize: 18, fontWeight: 800 }}
              >
                {count}
              </span>
              <button
                className="f-btn is-ghost is-sm"
                style={{ minWidth: 44, padding: 0, fontSize: 20 }}
                onClick={() => bump(item.id, 1)}
                aria-label="أكتر"
              >
                +
              </button>
            </div>
          </div>
        );
      })}
    </Sheet>
  );
}
