/**
 * جولة اليوم — القايمة اللي الهاوس كيبر بيمشي بيها.
 *
 * القايمة مرتّبة بالمنطقة مش بالأبجدية: الشغل بيتعمل بالمشي، وأي
 * ترتيب تاني معناه إن الموظف هيلف القرية مرتين. والمهام اللي اتقفلت
 * بتنزل تحت في قسم منفصل — موجودة عشان يثبت إنه عملها، بس مش
 * واخدة مكان في وش الشاشة.
 */

import { useMemo, useState } from "react";

import { useField } from "./store";
import TaskSheet from "./TaskSheet";
import { Broom, Camera, Check, Clock, Moon, Lock } from "./icons";
import { clock } from "./ui";
import type { Task } from "./types";

const KIND_SHORT: Record<string, string> = {
  DEPARTURE: "مغادرة",
  ARRIVAL_PREP: "وصول",
  STAYOVER: "إقامة",
  TURNDOWN: "مسائي",
  DEEP: "عميق",
  POST_MAINTENANCE: "بعد صيانة",
  INSPECTION: "فحص",
};

const CLOSED = new Set(["DONE", "INSPECTED", "SKIPPED"]);

export default function Round({ onSealed }: { onSealed: (text: string) => void }) {
  const { board } = useField();
  const [open, setOpen] = useState<number | null>(null);

  const { zones, closed } = useMemo(() => {
    const tasks = board?.tasks ?? [];
    const live = tasks.filter((t) => !CLOSED.has(t.status));
    const groups = new Map<string, Task[]>();
    for (const task of live) {
      const zone = task.zone_ar || "بدون منطقة";
      const list = groups.get(zone) ?? [];
      list.push(task);
      groups.set(zone, list);
    }
    return {
      zones: [...groups.entries()],
      closed: tasks.filter((t) => CLOSED.has(t.status)),
    };
  }, [board]);

  const active = board?.tasks.find((t) => t.id === open) ?? null;

  if (!board) {
    return (
      <div className="f-scroll">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="f-skeleton" style={{ animationDelay: `${i * 90}ms` }} />
        ))}
      </div>
    );
  }

  if (!board.tasks.length) {
    return (
      <div className="f-scroll">
        <div className="f-empty">
          <div className="f-empty-mark" style={{ color: "var(--f-accent)" }}>
            <Broom size={34} />
          </div>
          <div className="f-empty-title">مفيش مهام النهاردة</div>
          <div className="f-empty-text">
            الجولة بتتبني كل ليلة. لو المفروض عندك شغل، كلّم السوبرفايزر.
          </div>
        </div>
      </div>
    );
  }

  if (!zones.length) {
    return (
      <>
        <div className="f-scroll">
          <div className="f-empty">
            <div className="f-empty-mark" style={{ color: "var(--f-go)" }}>
              <Check size={38} />
            </div>
            <div className="f-empty-title">خلصت جولتك</div>
            <div className="f-empty-text">
              <span className="f-num">{board.done}</span> مهمة النهاردة. شغل نضيف.
            </div>
          </div>
          <div className="f-zone">اللي خلص</div>
          {closed.map((task, index) => (
            <Card
              key={task.id}
              task={task}
              index={index}
              onOpen={() => setOpen(task.id)}
            />
          ))}
        </div>
        {active ? (
          <TaskSheet task={active} onClose={() => setOpen(null)} onSealed={onSealed} />
        ) : null}
      </>
    );
  }

  let counter = 0;
  return (
    <>
      <div className="f-scroll">
        {zones.map(([zone, tasks]) => (
          <div key={zone}>
            <div className="f-zone">
              {zone}
              <span className="f-num" style={{ letterSpacing: 0 }}>
                {tasks.length}
              </span>
            </div>
            {tasks.map((task) => (
              <Card
                key={task.id}
                task={task}
                index={counter++}
                onOpen={() => setOpen(task.id)}
              />
            ))}
          </div>
        ))}

        {closed.length ? (
          <>
            <div className="f-zone">
              اللي خلص
              <span className="f-num" style={{ letterSpacing: 0 }}>
                {closed.length}
              </span>
            </div>
            {closed.map((task) => (
              <Card
                key={task.id}
                task={task}
                index={counter++}
                onOpen={() => setOpen(task.id)}
              />
            ))}
          </>
        ) : null}
      </div>

      {active ? (
        <TaskSheet task={active} onClose={() => setOpen(null)} onSealed={onSealed} />
      ) : null}
    </>
  );
}

function Card({
  task,
  index,
  onOpen,
}: {
  task: Task;
  index: number;
  onOpen: () => void;
}) {
  const state =
    task.status === "IN_PROGRESS"
      ? "is-running"
      : task.status === "DND"
        ? "is-dnd"
        : task.status === "BLOCKED"
          ? "is-blocked"
          : CLOSED.has(task.status)
            ? "is-done"
            : "";

  // خطوات الصور — ثلاث شرط: قبل، شغل، بعد
  const steps = task.photos_required
    ? [
        task.photo_before_count > 0,
        task.status === "IN_PROGRESS" || CLOSED.has(task.status),
        task.photo_after_count > 0,
      ]
    : [task.status === "IN_PROGRESS" || CLOSED.has(task.status), CLOSED.has(task.status)];

  return (
    <div
      className={`f-card ${state}`}
      style={{ animationDelay: `${Math.min(index, 12) * 38}ms` }}
      onClick={onOpen}
      role="button"
      tabIndex={0}
    >
      <div className="f-card-top">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="f-unit">{task.unit_label}</div>
          <div className="f-card-sub">
            {KIND_SHORT[task.kind] ?? task.kind} · {task.category_name_ar}
          </div>
        </div>

        {task.status === "DND" ? (
          <span className="f-chip is-dnd">
            <Moon size={12} /> عدم إزعاج ×{task.dnd_attempts}
          </span>
        ) : task.status === "BLOCKED" ? (
          <span className="f-chip is-stop">
            <Lock size={12} /> {task.blocked_reason ?? "مقفولة"}
          </span>
        ) : task.status === "IN_PROGRESS" ? (
          <span className="f-chip is-hot">شغّالة</span>
        ) : task.status === "REJECTED" ? (
          <span className="f-chip is-stop">اترفضت — أعد</span>
        ) : CLOSED.has(task.status) ? (
          <span className="f-chip is-go">
            <Check size={12} /> {clock(task.completed_at)}
          </span>
        ) : (
          <span className="f-chip">
            <Clock size={12} /> {task.expected_minutes} د
          </span>
        )}
      </div>

      <div className="f-card-foot">
        <div className="f-steps">
          {steps.map((on, i) => (
            <span key={i} className={`f-step${on ? " is-on" : ""}`} />
          ))}
        </div>
        {task.photos_required ? (
          <span className="f-chip" style={{ borderStyle: "dashed" }}>
            <Camera size={12} />{" "}
            <span className="f-num">
              {task.photo_before_count + task.photo_after_count}
            </span>
          </span>
        ) : null}
        {task.is_occupied ? <span className="f-chip is-dnd">نزيل جوّه</span> : null}
        {task.has_minibar && !task.minibar_checked && !CLOSED.has(task.status) ? (
          <span className="f-chip">ميني بار</span>
        ) : null}
      </div>
    </div>
  );
}
