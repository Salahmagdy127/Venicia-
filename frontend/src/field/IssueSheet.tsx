/**
 * بلاغ عطل من التليفون.
 *
 * البلاغ ده بيدخل **نفس** طابور الصيانة اللي الاستقبال بيشتغل عليه —
 * مش دفتر جانبي ولا واتساب. ولو الهاوس كيبر قال إن العطل بيمنع
 * البيع، الوحدة بتتشال من الإتاحة أول ما البلاغ يوصل، من غير ما حد
 * يفتح شاشة.
 *
 * وعشان كده «بيمنع البيع؟» مكتوبة بلغة الشغل مش بلغة النظام: «الوحدة
 * تتباع كده؟». الهاوس كيبر مش لازم يعرف يعني إيه إتاحة عشان ياخد
 * القرار الصح.
 */

import { useState } from "react";

import { useField } from "./store";
import { Alert } from "./icons";
import { Pills, Sheet } from "./ui";

export default function IssueSheet({
  unitId,
  unitLabel,
  taskId,
  onClose,
  onSent,
}: {
  unitId: number | null;
  unitLabel: string | null;
  taskId?: number;
  onClose: () => void;
  onSent: () => void;
}) {
  const { act, boot } = useField();
  const [category, setCategory] = useState("AC");
  const [priority, setPriority] = useState("NORMAL");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [blocks, setBlocks] = useState(false);
  const [busy, setBusy] = useState(false);

  async function send() {
    if (!title.trim()) return;
    setBusy(true);
    try {
      await act("issue.open", {
        taskId,
        payload: {
          unit_id: unitId,
          title: title.trim(),
          description: description.trim() || null,
          category,
          priority,
          blocks_unit: blocks,
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
          <div style={{ fontSize: 19, fontWeight: 800 }}>بلاغ عطل</div>
          <div style={{ fontSize: 13, color: "var(--f-ink-3)", marginTop: 4 }}>
            {unitLabel ? `الوحدة ${unitLabel}` : "منطقة عامة"}
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
            disabled={busy || !title.trim()}
            onClick={send}
          >
            <Alert size={19} /> ابعت البلاغ
          </button>
        </>
      }
    >
      <div className="f-label">إيه اللي بايظ</div>
      <Pills
        value={category}
        onChange={setCategory}
        options={(boot?.ticket_categories ?? []).map((c) => ({
          code: c.code,
          label: c.name_ar,
        }))}
      />

      <div className="f-label">العنوان</div>
      <input
        className="f-input"
        value={title}
        placeholder="التكييف مش بيبرّد"
        onChange={(e) => setTitle(e.target.value)}
      />

      <div className="f-label">تفاصيل (اختياري)</div>
      <textarea
        className="f-area"
        value={description}
        placeholder="الريموت شغّال بس الهوا طالع سخن…"
        onChange={(e) => setDescription(e.target.value)}
      />

      <div className="f-label">إيه استعجاله</div>
      <Pills
        value={priority}
        onChange={setPriority}
        options={(boot?.ticket_priorities ?? []).map((p) => ({
          code: p.code,
          label: p.name_ar,
        }))}
      />

      <div
        className={`f-check${blocks ? " is-on" : ""}`}
        style={{ marginTop: 18 }}
        onClick={() => setBlocks(!blocks)}
        role="checkbox"
        aria-checked={blocks}
        tabIndex={0}
      >
        <span className="f-box">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M20 6 9 17l-5-5" />
          </svg>
        </span>
        <span>
          الوحدة دي متنفعش تتباع كده
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--f-ink-3)", marginTop: 3 }}>
            هتتقفل قدام الحجز لحد ما الفني يخلّص
          </div>
        </span>
      </div>
    </Sheet>
  );
}
