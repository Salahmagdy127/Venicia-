/**
 * جولة الميدان من على المكتب — اللي بيقفل الدايرة.
 *
 * صور «قبل وبعد» بتبقى إجراء بيروقراطي لو محدش بيشوفها. الشاشة دي هي
 * المكان اللي بتتشاف فيه، وبتجاوب على تلات أسئلة السوبرفايزر بيسألها
 * كل يوم:
 *
 *   • الشغل ماشي إزاي دلوقتي؟          (الشريط العلوي)
 *   • مين ورا في جولته؟                 (التجميع بالموظف)
 *   • الأوضة دي اتنضفت فعلاً؟           (الصور والسجل)
 *
 * والسجل بيعرض **وقت الحدث** جنب **وقت وصوله**. الفرق بينهم هو الوقت
 * اللي الموظف كان فيه من غير شبكة — مش تأخير منه.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, get } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { FieldSupervisorBoard, FieldTask, FieldTimelineEntry } from "@/lib/types";
import { StatStrip } from "@/components/PageHeader";
import { Button, EmptyState, ErrorState, Loading, Modal, cx } from "@/components/ui";

const KIND_AR: Record<string, string> = {
  DEPARTURE: "مغادرة",
  ARRIVAL_PREP: "وصول",
  STAYOVER: "إقامة",
  TURNDOWN: "مسائي",
  DEEP: "عميق",
  POST_MAINTENANCE: "بعد صيانة",
  INSPECTION: "فحص",
};

const STATUS_AR: Record<string, string> = {
  PENDING: "في الطابور",
  IN_PROGRESS: "شغّالة",
  DND: "عدم إزعاج",
  BLOCKED: "متعذّرة",
  DONE: "خلصت",
  INSPECTED: "اتفحصت",
  REJECTED: "اترفضت",
  SKIPPED: "اتلغت",
};

const STATUS_TONE: Record<string, string> = {
  PENDING: "text-muted",
  IN_PROGRESS: "text-accent",
  DND: "text-warn",
  BLOCKED: "text-bad",
  DONE: "text-good",
  INSPECTED: "text-good",
  REJECTED: "text-bad",
  SKIPPED: "text-muted",
};

const EVENT_AR: Record<string, string> = {
  CREATED: "اتعملت",
  ASSIGNED: "اتسندت",
  STARTED: "بدأ",
  PAUSED: "وقف",
  RESUMED: "كمّل",
  DND: "عدم إزعاج",
  BLOCKED: "متعذّرة",
  COMPLETED: "خلص",
  INSPECTED: "اتفحصت",
  REJECTED: "اترفضت",
  SKIPPED: "اتلغت",
  PHOTO: "صوّر",
  NOTE: "ملاحظة",
  ISSUE_REPORTED: "بلّغ عن عطل",
  MINIBAR: "جرد ميني بار",
};

function time(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function mins(seconds: number): string {
  return seconds ? `${Math.round(seconds / 60)} د` : "—";
}

export default function FieldRound() {
  const { t } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState<FieldTask | null>(null);

  const board = useQuery({
    queryKey: ["field-supervisor"],
    queryFn: () => get<FieldSupervisorBoard>("/field/supervisor"),
    refetchInterval: 60_000,
  });

  const generate = useMutation({
    mutationFn: () => api("/field/generate", { method: "POST", body: { assign: true } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["field-supervisor"] }),
  });

  const tasks = board.data?.tasks ?? [];

  // التجميع بالموظف — «مين ورا؟» أهم سؤال في نص اليوم
  const byStaff = useMemo(() => {
    const map = new Map<string, FieldTask[]>();
    for (const task of tasks) {
      const key = task.assigned_to_name || "مش موزّعة";
      const list = map.get(key);
      if (list) list.push(task);
      else map.set(key, [task]);
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [tasks]);

  if (board.isLoading) return <Loading />;
  if (board.isError) return <ErrorState onRetry={() => board.refetch()} />;

  const b = board.data!;
  const closed = b.done + b.inspected;

  return (
    <>
      <div className="shrink-0 px-5 py-3 border-b border-line bg-surface flex items-center gap-4 flex-wrap">
        <StatStrip
          items={[
            { label: "المهام", value: String(b.total) },
            { label: "خلصت", value: String(closed), tone: "good" },
            { label: "شغّالة", value: String(b.in_progress), tone: "accent" },
            {
              label: "عدم إزعاج",
              value: String(b.dnd),
              tone: b.dnd > 0 ? "warn" : "ink",
            },
            {
              label: "متعذّرة",
              value: String(b.blocked),
              tone: b.blocked > 0 ? "bad" : "ink",
            },
            {
              label: "محتاجة تدخّل",
              value: String(b.escalated),
              tone: b.escalated > 0 ? "bad" : "ink",
            },
            { label: "صور", value: String(b.photos) },
          ]}
        />
        <div className="ms-auto flex items-center gap-2">
          <span className="text-[12px] text-muted">
            <span className="num">{b.minutes_worked}</span> /{" "}
            <span className="num">{b.minutes_planned}</span> دقيقة
          </span>
          {can("housekeeping.update") && (
            <Button
              onClick={() => generate.mutate()}
              disabled={generate.isPending}
              variant="secondary"
            >
              {generate.isPending ? "…" : "ولّد ووزّع"}
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {!tasks.length && (
          <EmptyState
            title="مفيش مهام النهاردة"
            hint="الجولة بتتبني كل ليلة مع النايت أوديت — أو ولّدها من هنا."
          />
        )}

        <div className="flex flex-col gap-5">
          {byStaff.map(([staff, list]) => {
            const finished = list.filter((x) =>
              ["DONE", "INSPECTED", "SKIPPED"].includes(x.status),
            ).length;
            return (
              <section key={staff}>
                <h2 className="text-[13px] font-bold text-muted mb-2 flex items-center gap-2">
                  {staff}
                  <span className="num text-ink-2">
                    {finished}/{list.length}
                  </span>
                  <span className="flex-1 h-px bg-line" />
                  <span className="num text-[11px]">
                    {list.reduce((sum, x) => sum + x.expected_minutes, 0)} د
                  </span>
                </h2>
                <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(230px,1fr))]">
                  {list.map((task) => (
                    <TaskCard key={task.id} task={task} onOpen={() => setOpen(task)} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </div>

      {open && <TaskModal task={open} onClose={() => setOpen(null)} t={t} />}
    </>
  );
}

function TaskCard({ task, onOpen }: { task: FieldTask; onOpen: () => void }) {
  const shots = task.photos.length;
  return (
    <button
      onClick={onOpen}
      className={cx(
        "text-start border rounded-[8px] p-2.5 bg-surface flex flex-col gap-2 transition-colors hover:bg-surface-2",
        task.status === "IN_PROGRESS" ? "border-accent/50" : "border-line",
        task.dnd_attempts >= 3 && "border-bad/50",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="num text-[15px] font-bold">{task.unit_label}</span>
        <span className="text-[11px] text-muted">{KIND_AR[task.kind] ?? task.kind}</span>
        <span
          className={cx("text-[11px] font-bold ms-auto", STATUS_TONE[task.status])}
        >
          {STATUS_AR[task.status] ?? task.status}
        </span>
      </div>

      <div className="flex items-center gap-1.5 text-[10.5px] text-muted">
        {task.photos_required && (
          <span className="num">
            📷 {task.photo_before_count}+{task.photo_after_count}
          </span>
        )}
        {task.dnd_attempts > 0 && (
          <span className="text-warn font-bold num">عدم إزعاج ×{task.dnd_attempts}</span>
        )}
        {task.working_seconds > 0 && <span className="num">{mins(task.working_seconds)}</span>}
        {task.inspection_score != null && (
          <span className={task.inspection_score >= 3 ? "text-good" : "text-bad"}>
            ★ {task.inspection_score}
          </span>
        )}
      </div>

      {shots > 0 && (
        <div className="flex gap-1">
          {task.photos.slice(0, 4).map((photo) => (
            <img
              key={photo.id}
              src={photo.thumb_url ?? photo.url}
              alt=""
              loading="lazy"
              className="w-11 h-11 object-cover rounded-[4px] border border-line"
            />
          ))}
          {shots > 4 && (
            <span className="w-11 h-11 rounded-[4px] border border-line grid place-items-center text-[11px] num text-muted">
              +{shots - 4}
            </span>
          )}
        </div>
      )}
    </button>
  );
}

function TaskModal({
  task,
  onClose,
  t,
}: {
  task: FieldTask;
  onClose: () => void;
  t: (key: string, fallback?: string) => string;
}) {
  const timeline = useQuery({
    queryKey: ["field-timeline", task.id],
    queryFn: () => get<FieldTimelineEntry[]>(`/field/tasks/${task.id}/timeline`),
  });

  const before = task.photos.filter((p) => p.phase === "BEFORE");
  const after = task.photos.filter((p) => p.phase === "AFTER");

  return (
    <Modal
      open
      onClose={onClose}
      width={820}
      title={`الوحدة ${task.unit_label} · ${KIND_AR[task.kind] ?? task.kind}`}
    >
      <div className="flex items-center gap-3 flex-wrap text-[12.5px] text-muted mb-4">
        <span className={cx("font-bold", STATUS_TONE[task.status])}>
          {STATUS_AR[task.status] ?? task.status}
        </span>
        <span>·</span>
        <span>{task.assigned_to_name ?? "مش موزّعة"}</span>
        <span>·</span>
        <span className="num">
          {time(task.started_at)} → {time(task.completed_at)}
        </span>
        <span>·</span>
        <span className="num">
          {mins(task.working_seconds)} من {task.expected_minutes} د متوقّعة
        </span>
      </div>

      {task.blocked_reason && (
        <div className="mb-4 text-[13px] rounded-[6px] border border-bad/35 bg-bad/8 text-bad px-3 py-2">
          {task.blocked_reason}
        </div>
      )}
      {task.note && (
        <div className="mb-4 text-[13px] rounded-[6px] border border-line bg-surface-2 px-3 py-2">
          {task.note}
        </div>
      )}

      {task.photos_required && (
        <div className="grid grid-cols-2 gap-4 mb-5">
          <PhotoColumn label="قبل" photos={before} />
          <PhotoColumn label="بعد" photos={after} />
        </div>
      )}

      <h3 className="text-[12px] font-bold text-muted mb-2">السجل</h3>
      {timeline.isLoading && <Loading />}
      <div className="flex flex-col">
        {(timeline.data ?? []).map((entry, index) => (
          <div
            key={index}
            className="flex items-baseline gap-3 py-1.5 border-b border-line last:border-0 text-[13px]"
          >
            <span className="num text-muted w-[46px] shrink-0">
              {time(entry.happened_at)}
            </span>
            <span className="font-bold w-[110px] shrink-0">
              {EVENT_AR[entry.kind] ?? entry.kind}
            </span>
            <span className="text-ink-2 flex-1 min-w-0 truncate">
              {entry.note || entry.user_name || ""}
            </span>
            {entry.offline_seconds > 120 && (
              <span
                className="text-[11px] text-warn num shrink-0"
                title={`اتسجّل على التليفون ${time(entry.happened_at)} ووصل ${time(entry.received_at)}`}
              >
                أوفلاين {Math.round(entry.offline_seconds / 60)} د
              </span>
            )}
          </div>
        ))}
        {!timeline.isLoading && !(timeline.data ?? []).length && (
          <span className="text-[13px] text-muted">{t("state.empty", "مفيش حاجة")}</span>
        )}
      </div>
    </Modal>
  );
}

function PhotoColumn({
  label,
  photos,
}: {
  label: string;
  photos: FieldTask["photos"];
}) {
  return (
    <div>
      <h3 className="text-[12px] font-bold text-muted mb-2">
        {label} <span className="num">{photos.length}</span>
      </h3>
      {photos.length ? (
        <div className="grid grid-cols-2 gap-2">
          {photos.map((photo) => (
            <a
              key={photo.id}
              href={photo.url}
              target="_blank"
              rel="noreferrer"
              title={`${time(photo.taken_at)} · ${photo.taken_by_name ?? ""}`}
            >
              <img
                src={photo.thumb_url ?? photo.url}
                alt=""
                loading="lazy"
                className="w-full aspect-square object-cover rounded-[6px] border border-line hover:border-accent transition-colors"
              />
            </a>
          ))}
        </div>
      ) : (
        <div className="text-[12.5px] text-muted rounded-[6px] border border-dashed border-line px-3 py-6 text-center">
          مفيش صور
        </div>
      )}
    </div>
  );
}
