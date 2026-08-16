/**
 * شاشة تذكرة الصيانة — للفني.
 *
 * الفني بياخد التذكرة ويقفلها من مكانه. لما يقفلها بتحصل تلات حاجات
 * في نفس اللحظة، من غير ما حد في المكتب يعمل حاجة:
 *   • الوحدة بترجع للبيع لو كانت محجوبة بالبلاغ ده وبس.
 *   • بترجع **متسخة** — لأن الفني كان جوّه، ومحتاجة مرور هاوس كيبينج.
 *   • بتتولّد مهمة «بعد الصيانة» في جولة اليوم.
 */

import { useState } from "react";

import { useField } from "./store";
import { Check, Wrench } from "./icons";
import { Sheet, since } from "./ui";
import type { FieldTicket } from "./types";

const PRIORITY_LABEL: Record<string, string> = {
  URGENT: "عاجل",
  HIGH: "مهم",
  NORMAL: "عادي",
  LOW: "مش مستعجل",
};

export default function TicketSheet({
  ticket,
  onClose,
  onSealed,
}: {
  ticket: FieldTicket;
  onClose: () => void;
  onSealed: (text: string) => void;
}) {
  const { act } = useField();
  const [resolution, setResolution] = useState("");
  const [cost, setCost] = useState("");
  const [busy, setBusy] = useState(false);

  const running = ticket.status === "IN_PROGRESS";

  async function start() {
    setBusy(true);
    try {
      await act("ticket.start", { ticketId: ticket.id });
      onSealed(`${ticket.number} — بدأت`);
      onClose();
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!resolution.trim()) return;
    setBusy(true);
    try {
      await act("ticket.complete", {
        ticketId: ticket.id,
        payload: { resolution: resolution.trim(), cost: cost || "0" },
      });
      onSealed(`${ticket.number} اتقفلت`);
      onClose();
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
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <span className="f-num" style={{ fontSize: 12.5, color: "var(--f-ink-3)" }}>
              {ticket.number}
            </span>
            <span
              className={`f-chip${ticket.priority === "URGENT" ? " is-stop" : ticket.priority === "HIGH" ? " is-dnd" : ""}`}
            >
              {PRIORITY_LABEL[ticket.priority] ?? ticket.priority}
            </span>
            {ticket.blocks_unit ? <span className="f-chip is-stop">الوحدة مقفولة</span> : null}
          </div>
          <div style={{ fontSize: 21, fontWeight: 800, marginTop: 7, lineHeight: 1.35 }}>
            {ticket.title}
          </div>
          <div style={{ fontSize: 13, color: "var(--f-ink-3)", marginTop: 4 }}>
            {ticket.unit_label ? `الوحدة ${ticket.unit_label}` : ticket.location}
            {" · "}
            {since(ticket.opened_at)}
          </div>
        </>
      }
      foot={
        running ? (
          <>
            <button className="f-btn is-ghost" onClick={onClose}>
              بعدين
            </button>
            <button
              className="f-btn is-primary is-live"
              style={{ flex: 1 }}
              disabled={busy || !resolution.trim()}
              onClick={finish}
            >
              <Check size={19} /> قفل التذكرة
            </button>
          </>
        ) : (
          <button
            className="f-btn is-primary is-wide"
            disabled={busy}
            onClick={start}
          >
            <Wrench size={19} /> خدتها وبادئ
          </button>
        )
      }
    >
      {ticket.is_overdue ? (
        <div className="f-error" style={{ marginBottom: 16 }}>
          فات ميعادها — لو مش هتخلص النهاردة بلّغ السوبرفايزر.
        </div>
      ) : null}

      {ticket.description ? (
        <>
          <div className="f-label">اللي اتبلّغ</div>
          <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.75, color: "var(--f-ink-2)" }}>
            {ticket.description}
          </p>
        </>
      ) : null}

      {running ? (
        <>
          <div className="f-label">اتعمل إيه</div>
          <textarea
            className="f-area"
            value={resolution}
            placeholder="غيّرت كباسة التكييف واتجرّبت ربع ساعة…"
            onChange={(e) => setResolution(e.target.value)}
          />
          <div className="f-label">تكلفة القطع (لو فيه)</div>
          <input
            className="f-input f-num"
            inputMode="decimal"
            value={cost}
            placeholder="0.00"
            onChange={(e) => setCost(e.target.value)}
          />
          {ticket.blocks_unit ? (
            <div
              className="f-error"
              style={{
                marginTop: 18,
                color: "var(--f-go)",
                background: "rgba(94,224,140,.08)",
                borderColor: "rgba(94,224,140,.28)",
              }}
            >
              أول ما تقفلها الوحدة هترجع للبيع وهتتحوّل لمهمة تنضيف.
            </div>
          ) : null}
        </>
      ) : (
        <p style={{ color: "var(--f-ink-3)", fontSize: 14, lineHeight: 1.75, marginTop: 18 }}>
          اضغط «خدتها وبادئ» عشان التذكرة تتسجّل باسمك ويبان للكل إن حد
          ماسكها.
        </p>
      )}
    </Sheet>
  );
}
