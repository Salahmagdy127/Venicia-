/**
 * شاشة المهمة — اللي الهاوس كيبر بيقضي يومه فيها.
 *
 * الشاشة مبنية على **خطوة واحدة ظاهرة في كل لحظة**. مش قايمة خيارات
 * والموظف يختار: التطبيق عارف هو فين، وبيوري الزرار الصح بس.
 *
 *   صوّر قبل  →  ابدأ  →  صوّر بعد  →  خلصت
 *
 * وفي أي لحظة فيه مخرجين: «عدم إزعاج» و«بلاغ عطل». الاتنين دول مش
 * استثناءات نادرة — دول نص شغل اليوم الحقيقي، فمكانهم قدام مش جوّه
 * قايمة.
 */

import { useMemo, useRef, useState } from "react";

import { useField } from "./store";
import type { PhotoPhase, Task } from "./types";
import { Alert, Camera, Check, Clock, Cup, Moon, Lock, X } from "./icons";
import { Flash, Pills, Sheet, Toggle, clock, compress, duration } from "./ui";
import IssueSheet from "./IssueSheet";
import MinibarSheet from "./MinibarSheet";

const KIND_LABEL: Record<string, string> = {
  DEPARTURE: "تنضيف مغادرة",
  ARRIVAL_PREP: "تجهيز وصول",
  STAYOVER: "ترتيب يومي",
  TURNDOWN: "ترتيب مسائي",
  DEEP: "تنضيف عميق",
  POST_MAINTENANCE: "بعد الصيانة",
  INSPECTION: "فحص",
};

type Step = "before" | "start" | "after" | "finish" | "closed";

/** الخطوة الحالية — بتتحسب من حالة المهمة، مش متخزّنة في مكان تاني. */
function stepOf(task: Task): Step {
  if (["DONE", "INSPECTED", "SKIPPED"].includes(task.status)) return "closed";
  if (task.photos_required && task.photo_before_count < 1) return "before";
  if (task.status !== "IN_PROGRESS") return "start";
  if (task.photos_required && task.photo_after_count < 1) return "after";
  return "finish";
}

export default function TaskSheet({
  task,
  onClose,
  onSealed,
}: {
  task: Task;
  onClose: () => void;
  onSealed: (text: string) => void;
}) {
  const { act, capture, localPhotos, boot } = useField();
  const [flash, setFlash] = useState(false);
  const [busy, setBusy] = useState(false);
  const [linen, setLinen] = useState(task.linen_changed);
  const [amenities, setAmenities] = useState(task.amenities_restocked);
  const [note, setNote] = useState(task.note ?? "");
  const [pane, setPane] = useState<"main" | "dnd" | "block" | "issue" | "minibar">("main");
  const [reason, setReason] = useState("LOCKED");
  const [snooze, setSnooze] = useState(60);
  const shutter = useRef<HTMLInputElement | null>(null);
  const phaseRef = useRef<PhotoPhase>("BEFORE");

  const step = stepOf(task);
  const pending = localPhotos[task.id] ?? [];
  const shots = useMemo(
    () => [
      ...task.photos.map((p) => ({
        key: `s${p.id}`,
        url: p.thumb_url ?? p.url,
        phase: p.phase,
        uploaded: true,
      })),
      ...pending.map((p) => ({
        key: p.uuid,
        url: p.url,
        phase: p.phase,
        uploaded: false,
      })),
    ],
    [task.photos, pending],
  );

  const before = shots.filter((s) => s.phase === "BEFORE");
  const after = shots.filter((s) => s.phase === "AFTER");

  function shoot(phase: PhotoPhase) {
    phaseRef.current = phase;
    shutter.current?.click();
  }

  async function onShot(file: File | undefined) {
    if (!file) return;
    setFlash(true);
    setTimeout(() => setFlash(false), 420);
    const small = await compress(file);
    await capture(task.id, phaseRef.current, small);
  }

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  }

  const start = () =>
    run(async () => {
      await act("task.start", { taskId: task.id });
    });

  const finish = () =>
    run(async () => {
      await act("task.complete", {
        taskId: task.id,
        payload: {
          linen_changed: linen,
          amenities_restocked: amenities,
          minibar_checked: task.minibar_checked,
          note: note.trim() || null,
        },
      });
      onSealed(`الوحدة ${task.unit_label} خلصت`);
      onClose();
    });

  const dnd = () =>
    run(async () => {
      await act("task.dnd", {
        taskId: task.id,
        payload: { snooze_minutes: snooze },
      });
      onSealed(`${task.unit_label} — هنعدّي عليها تاني`);
      onClose();
    });

  const blocked = () =>
    run(async () => {
      const label =
        boot?.block_reasons.find((r) => r.code === reason)?.name_ar ?? reason;
      await act("task.block", { taskId: task.id, payload: { reason: label } });
      onClose();
    });

  // ── اللوحات الفرعية ─────────────────────────────────────────────
  if (pane === "issue") {
    return (
      <IssueSheet
        unitId={task.unit_id}
        unitLabel={task.unit_label}
        taskId={task.id}
        onClose={() => setPane("main")}
        onSent={() => {
          onSealed("البلاغ اتسجّل");
          setPane("main");
        }}
      />
    );
  }

  if (pane === "minibar") {
    return (
      <MinibarSheet
        task={task}
        onClose={() => setPane("main")}
        onSent={() => {
          onSealed("جرد الميني بار اترحّل");
          setPane("main");
        }}
      />
    );
  }

  if (pane === "dnd") {
    return (
      <Sheet
        open
        onClose={() => setPane("main")}
        head={
          <>
            <div style={{ fontSize: 19, fontWeight: 800 }}>عدم إزعاج</div>
            <div style={{ fontSize: 13, color: "var(--f-ink-3)", marginTop: 4 }}>
              الوحدة {task.unit_label} · المحاولة رقم {task.dnd_attempts + 1}
            </div>
          </>
        }
        foot={
          <>
            <button className="f-btn is-ghost" onClick={() => setPane("main")}>
              رجوع
            </button>
            <button
              className="f-btn is-dnd"
              style={{ flex: 1 }}
              disabled={busy}
              onClick={dnd}
            >
              <Moon size={19} /> أجّلها
            </button>
          </>
        }
      >
        <p style={{ color: "var(--f-ink-2)", fontSize: 14.5, lineHeight: 1.75, margin: 0 }}>
          المهمة هتفضل في قايمتك وهترجع تظهر بعد المدة اللي تختارها. مش
          هتتشال ومش هتتحسب عليك.
        </p>
        <div className="f-label">نعدّي عليها تاني بعد</div>
        <Pills
          value={String(snooze)}
          onChange={(v) => setSnooze(Number(v))}
          options={[
            { code: "30", label: "نص ساعة" },
            { code: "60", label: "ساعة" },
            { code: "120", label: "ساعتين" },
            { code: "180", label: "٣ ساعات" },
          ]}
        />
        {task.dnd_attempts + 1 >= (boot?.dnd_escalate_after ?? 3) ? (
          <div
            className="f-error"
            style={{ marginTop: 18, color: "var(--f-dnd)", background: "rgba(247,179,63,.1)", borderColor: "rgba(247,179,63,.3)" }}
          >
            دي المحاولة رقم {task.dnd_attempts + 1} — الاستقبال هيتبلّغ عشان
            يتواصل مع النزيل.
          </div>
        ) : null}
      </Sheet>
    );
  }

  if (pane === "block") {
    return (
      <Sheet
        open
        onClose={() => setPane("main")}
        head={<div style={{ fontSize: 19, fontWeight: 800 }}>مش قادر أدخل</div>}
        foot={
          <>
            <button className="f-btn is-ghost" onClick={() => setPane("main")}>
              رجوع
            </button>
            <button
              className="f-btn is-stop"
              style={{ flex: 1 }}
              disabled={busy}
              onClick={blocked}
            >
              سجّل السبب
            </button>
          </>
        }
      >
        <div className="f-label">السبب</div>
        <Pills
          value={reason}
          onChange={setReason}
          options={(boot?.block_reasons ?? []).map((r) => ({
            code: r.code,
            label: r.name_ar,
          }))}
        />
      </Sheet>
    );
  }

  // ── اللوحة الرئيسية ─────────────────────────────────────────────
  const action = {
    before: { label: "صوّر الأوضة قبل ما تبدأ", icon: <Camera size={20} />, run: () => shoot("BEFORE") },
    start: { label: "ابدأ التنضيف", icon: <Check size={20} />, run: start },
    after: { label: "صوّر بعد ما خلصت", icon: <Camera size={20} />, run: () => shoot("AFTER") },
    finish: { label: "خلصت", icon: <Check size={20} />, run: finish },
    closed: { label: "المهمة اتقفلت", icon: <Check size={20} />, run: onClose },
  }[step];

  return (
    <>
      {flash ? <Flash /> : null}
      <input
        ref={shutter}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          void onShot(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      <Sheet
        open
        onClose={onClose}
        head={
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.7px" }}>
                {task.unit_label}
              </div>
              <div style={{ fontSize: 13, color: "var(--f-ink-3)", marginTop: 3 }}>
                {KIND_LABEL[task.kind] ?? task.kind} · {task.category_name_ar}
                {task.zone_ar ? ` · ${task.zone_ar}` : ""}
              </div>
            </div>
            <button
              className="f-btn is-ghost is-sm"
              style={{ minWidth: 42, padding: 0 }}
              onClick={onClose}
              aria-label="إغلاق"
            >
              <X size={18} />
            </button>
          </div>
        }
        foot={
          <>
            <button
              className="f-btn is-dnd is-sm"
              style={{ minWidth: 56, padding: 0 }}
              onClick={() => setPane("dnd")}
              aria-label="عدم إزعاج"
            >
              <Moon size={19} />
            </button>
            <button
              className="f-btn is-stop is-sm"
              style={{ minWidth: 56, padding: 0 }}
              onClick={() => setPane("block")}
              aria-label="مش قادر أدخل"
            >
              <Lock size={19} />
            </button>
            <button
              className={`f-btn is-primary${step === "finish" ? " is-live" : ""}`}
              style={{ flex: 1 }}
              disabled={busy || step === "closed"}
              onClick={action.run}
            >
              {action.icon} {action.label}
            </button>
          </>
        }
      >
        {/* شريط الخطوات — الموظف بيشوف هو فين من غير ما يقرا */}
        <div style={{ display: "flex", gap: 6, marginBottom: 18 }}>
          {(task.photos_required
            ? (["before", "start", "after", "finish"] as const)
            : (["start", "finish"] as const)
          ).map((s, index, all) => {
            const done = all.indexOf(step as never) > index || step === "closed";
            const now = s === step;
            return (
              <div
                key={s}
                style={{
                  flex: 1,
                  height: 5,
                  borderRadius: 999,
                  background: done || now ? "var(--f-accent)" : "var(--f-line-2)",
                  opacity: now ? 1 : done ? 0.75 : 1,
                  transition: "background 420ms var(--f-ease)",
                }}
              />
            );
          })}
        </div>

        {task.is_occupied ? (
          <div
            className="f-error"
            style={{
              marginBottom: 16,
              color: "var(--f-dnd)",
              background: "rgba(247,179,63,.09)",
              borderColor: "rgba(247,179,63,.28)",
            }}
          >
            النزيل لسه مقيم في الوحدة — خد بالك.
          </div>
        ) : null}

        {task.photos_required ? (
          <>
            <div className="f-label">
              صور قبل {before.length ? `(${before.length})` : ""}
            </div>
            <Gallery
              shots={before}
              onAdd={() => shoot("BEFORE")}
              locked={step === "closed"}
            />

            <div className="f-label">
              صور بعد {after.length ? `(${after.length})` : ""}
            </div>
            <Gallery
              shots={after}
              onAdd={() => shoot("AFTER")}
              locked={step === "closed" || step === "before"}
            />
          </>
        ) : null}

        <div className="f-label">اتعمل إيه</div>
        <Toggle label="غيّرت المفارش والفوط" on={linen} onChange={setLinen} />
        <Toggle label="كمّلت المستلزمات" on={amenities} onChange={setAmenities} />

        {task.has_minibar ? (
          <button
            className="f-btn is-ghost is-wide"
            style={{ marginTop: 4 }}
            onClick={() => setPane("minibar")}
          >
            <Cup size={19} />
            {task.minibar_checked ? "الميني بار اتجرد" : "جرد الميني بار"}
          </button>
        ) : null}

        <button
          className="f-btn is-ghost is-wide"
          style={{ marginTop: 10 }}
          onClick={() => setPane("issue")}
        >
          <Alert size={19} /> فيه حاجة بايظة؟ بلّغ
        </button>

        <div className="f-label">ملاحظة</div>
        <textarea
          className="f-area"
          value={note}
          placeholder="أي حاجة المفروض حد يعرفها…"
          onChange={(e) => setNote(e.target.value)}
        />

        {task.started_at ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginTop: 18,
              fontSize: 12.5,
              color: "var(--f-ink-3)",
            }}
          >
            <Clock size={15} />
            بدأت {clock(task.started_at)}
            {task.working_seconds ? ` · ${duration(task.working_seconds)}` : ""}
            {" · "}المتوقّع {task.expected_minutes} د
          </div>
        ) : null}
      </Sheet>
    </>
  );
}

function Gallery({
  shots,
  onAdd,
  locked,
}: {
  shots: { key: string; url: string; uploaded: boolean }[];
  onAdd: () => void;
  locked: boolean;
}) {
  return (
    <div className="f-shots">
      {shots.map((shot, index) => (
        <div
          key={shot.key}
          className={`f-shot${shot.uploaded ? "" : " is-pending"}`}
          style={{ animationDelay: `${index * 45}ms` }}
        >
          <img src={shot.url} alt="" loading="lazy" />
        </div>
      ))}
      {!locked ? (
        <button className="f-shot f-shot-add" onClick={onAdd} type="button">
          <Camera size={22} />
          صوّر
        </button>
      ) : null}
    </div>
  );
}
