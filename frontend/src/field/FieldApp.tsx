/**
 * تطبيق الميدان — الغلاف.
 *
 * ثلاث شاشات وبس: **جولتي**، **الأعطال**، **أنا**. أي حاجة زيادة عن
 * كده بتبقى شغل مكتب، ومكانها الشاشة الكبيرة.
 *
 * الهيدر بيقول تلات حاجات طول الوقت، وكلها مهمة لواحد شغّال في الشمس:
 * فاضل كام مهمة (الحلقة)، الشبكة موجودة ولا لأ، وكام عملية لسه في
 * الطابور مستنية توصل.
 */

import { useEffect, useMemo, useState } from "react";

import "./field.css";
import { FieldProvider, useField } from "./store";
import FieldLogin from "./FieldLogin";
import Round from "./Round";
import TicketSheet from "./TicketSheet";
import { Seal, since } from "./ui";
import { Alert, Broom, Cloud, CloudOff, List, Mark, Sync, User, Wrench } from "./icons";
import type { FieldTicket } from "./types";

/**
 * تركيب التطبيق كـ PWA.
 *
 * الملف ده بيتحمّل بس لما حد يفتح ``/field``، فالإعدادات دي مبتلمسش
 * النظام الكبير: صفحة الحجوزات مش المفروض تتقفل في تبويب لوحدها ولا
 * تتخزّن في كاش عامل خدمة.
 *
 * وعامل الخدمة نطاقه ``/field/`` بس — عشان لو حصلت مشكلة في الكاش
 * متأثرش على شاشات النظام اللي بتتحدّث كل يوم.
 */
function usePwa() {
  useEffect(() => {
    const previousTheme = document
      .querySelector('meta[name="theme-color"]')
      ?.getAttribute("content");

    const manifest = document.createElement("link");
    manifest.rel = "manifest";
    manifest.href = "/field.webmanifest";
    document.head.appendChild(manifest);

    let theme = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (!theme) {
      theme = document.createElement("meta");
      theme.name = "theme-color";
      document.head.appendChild(theme);
    }
    theme.setAttribute("content", "#04161a");

    // الشاشة مبتتكبّرش بالزوم — الأزرار كبيرة أصلاً، والزوم بالغلط
    // وسط الشغل بيضيّع مكان الموظف في القايمة
    const viewport = document.querySelector<HTMLMetaElement>('meta[name="viewport"]');
    const previousViewport = viewport?.getAttribute("content") ?? null;
    viewport?.setAttribute(
      "content",
      "width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover",
    );

    if ("serviceWorker" in navigator && location.protocol === "https:") {
      navigator.serviceWorker.register("/field-sw.js", { scope: "/field" }).catch(() => {
        // مفيش عامل خدمة — التطبيق لسه بيشتغل أوفلاين من IndexedDB،
        // اللي بيضيع بس هو إن الصفحة تفتح من غير شبكة بعد قفلها
      });
    }

    return () => {
      manifest.remove();
      if (previousTheme) theme?.setAttribute("content", previousTheme);
      if (previousViewport) viewport?.setAttribute("content", previousViewport);
    };
  }, []);
}

export default function FieldApp() {
  usePwa();
  return (
    <FieldProvider>
      <Shell />
    </FieldProvider>
  );
}

type Tab = "round" | "tickets" | "me";

function Shell() {
  const field = useField();
  const [tab, setTab] = useState<Tab>("round");
  const [seal, setSeal] = useState<string | null>(null);
  const [ticket, setTicket] = useState<FieldTicket | null>(null);

  // الفني مالوش جولة تنضيف — بيفتح على الأعطال على طول
  useEffect(() => {
    if (field.board && !field.board.can_clean && field.board.can_fix) setTab("tickets");
  }, [field.board]);

  if (!field.ready) {
    return (
      <div className="f-app">
        <div style={{ margin: "auto", opacity: 0.5 }}>
          <Mark size={72} />
        </div>
      </div>
    );
  }

  if (!field.authed) {
    return (
      <div className="f-app">
        <FieldLogin />
      </div>
    );
  }

  const board = field.board;
  const total = board ? board.tasks.length : 0;
  const done = board ? board.done : 0;
  const progress = total ? done / total : 0;
  const queued = field.pending + field.pendingPhotos;
  const openTickets = board?.tickets.filter((t) => t.status !== "DONE").length ?? 0;

  return (
    <div className="f-app">
      <header className="f-head">
        <ProgressRing value={progress} label={`${done}/${total}`} />
        <div className="f-head-text">
          <div className="f-head-name">{board?.user_name_ar ?? "…"}</div>
          <div className="f-head-meta">
            <span>{board?.role_ar}</span>
            {queued > 0 ? (
              <>
                <span>·</span>
                <span style={{ color: "var(--f-dnd)" }}>
                  <span className="f-num">{queued}</span> مستنية
                </span>
              </>
            ) : null}
          </div>
        </div>
        <NetPill
          online={field.online}
          syncing={field.syncing}
          queued={queued}
          onTap={() => void field.flush()}
        />
      </header>

      {!field.online ? (
        <div className="f-banner">
          <CloudOff size={16} />
          مفيش شبكة — شغلك بيتسجّل على التليفون وهيتبعت لوحده
        </div>
      ) : null}

      {field.online && field.stale && queued === 0 ? (
        <div className="f-banner">
          <Alert size={16} />
          آخر تحديث {since(field.lastSync)} — اضغط على علامة الشبكة تحدّث
        </div>
      ) : null}

      {tab === "round" ? (
        <Round onSealed={setSeal} />
      ) : tab === "tickets" ? (
        <Tickets onOpen={setTicket} />
      ) : (
        <Me />
      )}

      <nav className="f-tabs">
        {board?.can_clean !== false ? (
          <button
            className={`f-tab${tab === "round" ? " is-on" : ""}`}
            onClick={() => setTab("round")}
          >
            <Broom size={22} />
            جولتي
            {board && board.remaining > 0 ? (
              <span className="f-tab-badge f-num" style={{ background: "var(--f-accent)", color: "#032723" }}>
                {board.remaining}
              </span>
            ) : null}
          </button>
        ) : null}
        {board?.can_fix ? (
          <button
            className={`f-tab${tab === "tickets" ? " is-on" : ""}`}
            onClick={() => setTab("tickets")}
          >
            <Wrench size={22} />
            الأعطال
            {openTickets ? <span className="f-tab-badge f-num">{openTickets}</span> : null}
          </button>
        ) : null}
        <button
          className={`f-tab${tab === "me" ? " is-on" : ""}`}
          onClick={() => setTab("me")}
        >
          <User size={22} />
          أنا
        </button>
      </nav>

      {ticket ? (
        <TicketSheet
          ticket={ticket}
          onClose={() => setTicket(null)}
          onSealed={setSeal}
        />
      ) : null}

      {seal ? <Seal text={seal} onDone={() => setSeal(null)} /> : null}

      <div className="f-toasts">
        {field.toasts.map((toast) => (
          <div key={toast.id} className={`f-toast is-${toast.tone}`}>
            <div style={{ flex: 1 }}>
              {toast.text}
              {toast.detail ? <div className="f-toast-detail">{toast.detail}</div> : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════ حلقة التقدّم
function ProgressRing({ value, label }: { value: number; label: string }) {
  const radius = 22;
  const circumference = 2 * Math.PI * radius;
  return (
    <div className="f-ring">
      <svg width="52" height="52" viewBox="0 0 52 52">
        <circle className="f-ring-track" cx="26" cy="26" r={radius} />
        <circle
          className="f-ring-fill"
          cx="26"
          cy="26"
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - Math.min(1, Math.max(0, value)))}
        />
      </svg>
      <div className="f-ring-label f-num">{label}</div>
    </div>
  );
}

function NetPill({
  online,
  syncing,
  queued,
  onTap,
}: {
  online: boolean;
  syncing: boolean;
  queued: number;
  onTap: () => void;
}) {
  const state = syncing ? "is-syncing" : online ? "" : "is-off";
  return (
    <button
      className={`f-net ${state}`}
      onClick={onTap}
      style={{ appearance: "none", fontFamily: "inherit", color: "inherit" }}
    >
      <span className="f-net-dot" />
      {syncing ? (
        <span className="f-spin" style={{ display: "grid" }}>
          <Sync size={13} />
        </span>
      ) : online ? (
        <Cloud size={13} />
      ) : (
        <CloudOff size={13} />
      )}
      {queued > 0 ? <span className="f-num">{queued}</span> : null}
    </button>
  );
}

// ═══════════════════════════════════════════════════════ شاشة الأعطال
function Tickets({ onOpen }: { onOpen: (ticket: FieldTicket) => void }) {
  const { board } = useField();
  const tickets = board?.tickets ?? [];

  if (!tickets.length) {
    return (
      <div className="f-scroll">
        <div className="f-empty">
          <div className="f-empty-mark" style={{ color: "var(--f-go)" }}>
            <Wrench size={34} />
          </div>
          <div className="f-empty-title">مفيش أعطال مفتوحة</div>
          <div className="f-empty-text">كل حاجة شغّالة. لو ظهر عطل هيوصلك هنا.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="f-scroll">
      {tickets.map((ticket, index) => (
        <div
          key={ticket.id}
          className={`f-card${ticket.status === "IN_PROGRESS" ? " is-running" : ""}${ticket.is_overdue ? " is-blocked" : ""}`}
          style={{ animationDelay: `${Math.min(index, 10) * 40}ms` }}
          onClick={() => onOpen(ticket)}
        >
          <div className="f-card-top">
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 17, fontWeight: 800, lineHeight: 1.35 }}>
                {ticket.title}
              </div>
              <div className="f-card-sub">
                {ticket.unit_label ? `الوحدة ${ticket.unit_label}` : ticket.location}
                {" · "}
                {since(ticket.opened_at)}
              </div>
            </div>
            {ticket.priority === "URGENT" ? (
              <span className="f-chip is-stop">عاجل</span>
            ) : ticket.is_overdue ? (
              <span className="f-chip is-dnd">متأخرة</span>
            ) : null}
          </div>
          <div className="f-card-foot">
            {ticket.is_mine ? <span className="f-chip is-hot">عليّا</span> : null}
            {ticket.blocks_unit ? <span className="f-chip is-stop">الوحدة مقفولة</span> : null}
            {ticket.status === "IN_PROGRESS" ? (
              <span className="f-chip is-hot">شغّالة</span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════ شاشة أنا
function Me() {
  const field = useField();
  const board = field.board;
  const worked = board?.minutes_worked ?? 0;
  const planned = board?.minutes_planned ?? 0;

  const stats = useMemo(
    () => [
      { label: "مهام خلصت", value: String(board?.done ?? 0) },
      { label: "فاضل", value: String(board?.remaining ?? 0) },
      { label: "دقايق شغل", value: String(worked) },
      { label: "المخطّط", value: String(planned) },
    ],
    [board, planned, worked],
  );

  return (
    <div className="f-scroll">
      <div style={{ textAlign: "center", padding: "20px 0 26px" }}>
        <div style={{ color: "var(--f-accent)", display: "inline-block" }}>
          <Mark size={62} />
        </div>
        <div style={{ fontSize: 21, fontWeight: 800, marginTop: 12 }}>
          {board?.user_name_ar}
        </div>
        <div style={{ fontSize: 13.5, color: "var(--f-ink-3)", marginTop: 3 }}>
          {board?.role_ar} · {field.boot?.property_name_ar}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {stats.map((stat, index) => (
          <div
            key={stat.label}
            className="f-card"
            style={{ marginBottom: 0, animationDelay: `${index * 50}ms`, padding: 16 }}
          >
            <div className="f-num" style={{ fontSize: 27, fontWeight: 800, lineHeight: 1 }}>
              {stat.value}
            </div>
            <div style={{ fontSize: 12, color: "var(--f-ink-3)", marginTop: 6 }}>
              {stat.label}
            </div>
          </div>
        ))}
      </div>

      <div className="f-label">المزامنة</div>
      <div className="f-card" style={{ padding: 16 }}>
        <Row label="الشبكة" value={field.online ? "موجودة" : "مقطوعة"} />
        <Row label="عمليات مستنية" value={String(field.pending)} />
        <Row label="صور مستنية" value={String(field.pendingPhotos)} />
        <Row label="آخر مزامنة" value={since(field.lastSync)} />
      </div>

      <button
        className="f-btn is-primary is-wide"
        style={{ marginTop: 14 }}
        disabled={field.syncing}
        onClick={() => void field.flush()}
      >
        <Sync size={19} /> {field.syncing ? "بيزامن…" : "زامن دلوقتي"}
      </button>

      <button
        className="f-btn is-ghost is-wide"
        style={{ marginTop: 10 }}
        onClick={() => {
          if (field.pending + field.pendingPhotos > 0) {
            field.notify({
              tone: "warn",
              text: "فيه شغل لسه ماوصلش",
              detail: "زامن الأول قبل ما تخرج",
            });
            return;
          }
          field.logout();
        }}
      >
        <List size={18} /> خروج
      </button>

      <div
        style={{
          textAlign: "center",
          fontSize: 11.5,
          color: "var(--f-ink-3)",
          marginTop: 24,
          lineHeight: 1.8,
        }}
      >
        فينيسيا · تطبيق الميدان
        <br />
        شغلك بيتسجّل على التليفون الأول — الشبكة مش شرط.
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "9px 0",
        fontSize: 14,
        borderBottom: "1px solid var(--f-line)",
      }}
    >
      <span style={{ color: "var(--f-ink-3)" }}>{label}</span>
      <span style={{ fontWeight: 700 }}>{value}</span>
    </div>
  );
}
