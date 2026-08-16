/**
 * السبا والأنشطة والمناسبات.
 *
 * تبويبتان لأن ديّه شغلانتين مختلفتين بيعملهم ناس مختلفة:
 *
 * **يوم السبا** بيتقرا زي جدول قطارات: كل مورد صف، والوقت عرضي. ده
 * اللي بيخلّي «فاضل ميعاد امتى» سؤال بينحل بالعين مش بالبحث.
 *
 * **المناسبات** بتتقرا زي خط مبيعات: استعلام ← مبدئي ← مؤكد. القيمة
 * المؤكدة منفصلة عن قيمة الاحتمالات عن قصد، لأن جمعهم في رقم واحد هو
 * أسرع طريقة لتوقّع إيراد مش موجود.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, get } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { formatDate, money } from "@/lib/format";
import type {
  EventOut,
  EventsBoard,
  LeisureBoard,
  LeisureBooking,
  LeisureService,
  LeisureSlot,
} from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import { Button, EmptyState, ErrorState, Loading, Modal, cx } from "@/components/ui";
import { IconLotus, IconEvent, IconPlus } from "@/components/Icons";

const CATEGORY_AR: Record<string, string> = {
  SPA: "سبا",
  FITNESS: "لياقة",
  ACTIVITY: "أنشطة",
  EXCURSION: "رحلات",
  KIDS: "أطفال",
  RENTAL: "تأجير",
};

const STATUS_AR: Record<string, string> = {
  REQUESTED: "طلب",
  CONFIRMED: "مؤكد",
  CHECKED_IN: "حاضر",
  COMPLETED: "خلص",
  NO_SHOW: "محضرش",
  CANCELLED: "ملغي",
};

const STATUS_TONE: Record<string, string> = {
  REQUESTED: "text-muted",
  CONFIRMED: "text-accent",
  CHECKED_IN: "text-warn",
  COMPLETED: "text-good",
  NO_SHOW: "text-bad",
  CANCELLED: "text-muted line-through",
};

const EVENT_STATUS_AR: Record<string, string> = {
  INQUIRY: "استعلام",
  TENTATIVE: "مبدئي",
  CONFIRMED: "مؤكد",
  RUNNING: "جاري",
  COMPLETED: "خلصت",
  CANCELLED: "ملغية",
  LOST: "ضاعت",
};

const EVENT_TONE: Record<string, string> = {
  INQUIRY: "border-line text-muted",
  TENTATIVE: "border-warn/45 text-warn",
  CONFIRMED: "border-good/45 text-good",
  RUNNING: "border-accent/45 text-accent",
  COMPLETED: "border-line text-ink-2",
  CANCELLED: "border-line text-muted",
  LOST: "border-bad/45 text-bad",
};

const EVENT_KIND_AR: Record<string, string> = {
  WEDDING: "فرح",
  ENGAGEMENT: "خطوبة",
  BIRTHDAY: "عيد ميلاد",
  CORPORATE: "شركة",
  CONFERENCE: "مؤتمر",
  OTHER: "أخرى",
};

const ITEM_KIND_AR: Record<string, string> = {
  VENUE: "المكان",
  FNB: "أكل وشرب",
  EQUIPMENT: "معدات",
  DECOR: "تنسيق",
  STAFF: "عمالة",
  ACCOMMODATION: "إقامة",
  OTHER: "أخرى",
};

function hhmm(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Leisure() {
  const { locale } = useI18n();
  const { can } = useAuth();
  const [tab, setTab] = useState<"spa" | "events">("spa");
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10));

  return (
    <>
      <PageHeader title="السبا والمناسبات" subtitle={formatDate(day, locale)}>
        {tab === "spa" && (
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="num h-9 px-3 rounded-[6px] border border-line bg-surface text-[13px]"
          />
        )}
      </PageHeader>

      <div className="shrink-0 px-5 border-b border-line bg-surface flex items-center gap-1">
        {(
          [
            ["spa", "يوم السبا والأنشطة", IconLotus],
            ["events", "المناسبات", IconEvent],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cx(
              "h-10 px-4 text-[13.5px] font-bold border-b-2 -mb-px flex items-center gap-2 transition-colors",
              tab === key
                ? "border-accent text-accent"
                : "border-transparent text-muted hover:text-ink-2",
            )}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>

      {tab === "spa" ? (
        <SpaDay day={day} canBook={can("leisure.book")} />
      ) : (
        <Events canManage={can("leisure.manage")} />
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════ يوم السبا
function SpaDay({ day, canBook }: { day: string; canBook: boolean }) {
  const qc = useQueryClient();
  const [booking, setBooking] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const board = useQuery({
    queryKey: ["leisure-board", day],
    queryFn: () => get<LeisureBoard>(`/leisure/board?date=${day}`),
  });

  const act = useMutation({
    mutationFn: (v: { id: number; action: string; body?: unknown }) =>
      api(`/leisure/bookings/${v.id}/${v.action}`, { method: "POST", body: v.body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leisure-board"] }),
    onError: (err) => setToast(err instanceof ApiError ? err.messageAr : "حصل خطأ"),
  });

  const rows = board.data?.rows ?? [];

  // التجميع بالمورد — الجدول بيتقرا زي جدول قطارات: صف لكل معالج/مركب
  const byResource = useMemo(() => {
    const map = new Map<string, LeisureBooking[]>();
    for (const row of rows) {
      const key = row.resource_name || "بدون مورد";
      const list = map.get(key);
      if (list) list.push(row);
      else map.set(key, [row]);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0], "ar"));
  }, [rows]);

  if (board.isLoading) return <Loading />;
  if (board.isError) return <ErrorState onRetry={() => board.refetch()} />;
  const b = board.data!;

  return (
    <>
      <div className="shrink-0 px-5 py-3 border-b border-line bg-surface flex items-center gap-4 flex-wrap">
        <StatStrip
          items={[
            { label: "مواعيد", value: String(b.bookings) },
            { label: "أفراد", value: String(b.guests) },
            { label: "حاضرين", value: String(b.checked_in), tone: "warn" },
            { label: "خلصوا", value: String(b.completed), tone: "good" },
            { label: "محضروش", value: String(b.no_shows), tone: b.no_shows ? "bad" : "ink" },
            { label: "الإيراد", value: money(b.revenue), tone: "accent" },
            { label: "اترحّل", value: money(b.posted) },
          ]}
        />
        {canBook && (
          <Button className="ms-auto" onClick={() => setBooking(true)}>
            <IconPlus size={16} /> موعد جديد
          </Button>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {!rows.length && (
          <EmptyState
            title="مفيش مواعيد في اليوم ده"
            hint="اختار يوم تاني أو احجز موعد جديد."
          />
        )}

        <div className="flex flex-col gap-5">
          {byResource.map(([resource, list]) => {
            const minutes = list
              .filter((x) => x.status !== "CANCELLED")
              .reduce(
                (sum, x) =>
                  sum +
                  (new Date(x.end_at).getTime() - new Date(x.start_at).getTime()) / 60000,
                0,
              );
            return (
              <section key={resource}>
                <h2 className="text-[13px] font-bold text-muted mb-2 flex items-center gap-2">
                  {resource}
                  <span className="flex-1 h-px bg-line" />
                  <span className="num text-[11.5px]">{Math.round(minutes)} د مشغولة</span>
                </h2>
                <div className="flex flex-col gap-1.5">
                  {list
                    .slice()
                    .sort((a, c) => a.start_at.localeCompare(c.start_at))
                    .map((row) => (
                      <BookingRow
                        key={row.id}
                        row={row}
                        canBook={canBook}
                        busy={act.isPending}
                        onAct={(action, body) =>
                          act.mutate({ id: row.id, action, body })
                        }
                      />
                    ))}
                </div>
              </section>
            );
          })}
        </div>
      </div>

      {booking && (
        <NewBooking
          day={day}
          onClose={() => setBooking(false)}
          onDone={() => {
            setBooking(false);
            qc.invalidateQueries({ queryKey: ["leisure-board"] });
          }}
        />
      )}

      {toast && (
        <div
          className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 rounded-[6px] bg-bad text-white px-4 py-2.5 text-[13.5px] font-bold"
          role="status"
          onClick={() => setToast(null)}
        >
          {toast}
        </div>
      )}
    </>
  );
}

function BookingRow({
  row,
  canBook,
  busy,
  onAct,
}: {
  row: LeisureBooking;
  canBook: boolean;
  busy: boolean;
  onAct: (action: string, body?: unknown) => void;
}) {
  const closed = ["COMPLETED", "CANCELLED", "NO_SHOW"].includes(row.status);
  return (
    <div
      className={cx(
        "border rounded-[8px] px-3 py-2.5 bg-surface flex items-center gap-3 flex-wrap",
        row.status === "CHECKED_IN" ? "border-warn/45" : "border-line",
        row.status === "CANCELLED" && "opacity-55",
      )}
    >
      <span className="num text-[14px] font-bold w-[92px] shrink-0">
        {hhmm(row.start_at)} – {hhmm(row.end_at)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-bold truncate">{row.guest_name}</div>
        <div className="text-[12px] text-muted truncate">
          {row.service_name_ar} · {CATEGORY_AR[row.category] ?? row.category}
          {row.adults + row.children > 1 && (
            <>
              {" · "}
              <span className="num">{row.adults + row.children}</span> فرد
            </>
          )}
        </div>
      </div>

      <span className="num text-[13.5px] font-bold">{money(row.total)}</span>
      {row.is_posted ? (
        <span className="text-[10.5px] font-bold rounded-full px-2 py-0.5 bg-good/15 text-good">
          اترحّل
        </span>
      ) : row.folio_id ? (
        <span className="text-[10.5px] font-bold rounded-full px-2 py-0.5 bg-accent-soft text-accent">
          على الغرفة
        </span>
      ) : (
        <span className="text-[10.5px] font-bold rounded-full px-2 py-0.5 bg-surface-2 text-muted">
          كاش
        </span>
      )}

      <span className={cx("text-[12px] font-bold w-[52px] text-center", STATUS_TONE[row.status])}>
        {STATUS_AR[row.status] ?? row.status}
      </span>

      {canBook && !closed && (
        <div className="flex items-center gap-1.5">
          {row.status !== "CHECKED_IN" && (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAct("check-in")}>
              حضر
            </Button>
          )}
          <Button size="sm" disabled={busy} onClick={() => onAct("complete")}>
            خلص
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => onAct("no-show", undefined)}
            title="لم يحضر"
          >
            ×
          </Button>
        </div>
      )}
    </div>
  );
}

function NewBooking({
  day,
  onClose,
  onDone,
}: {
  day: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [serviceId, setServiceId] = useState<number | null>(null);
  const [slot, setSlot] = useState<LeisureSlot | null>(null);
  const [guest, setGuest] = useState("");
  const [adults, setAdults] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const services = useQuery({
    queryKey: ["leisure-services"],
    queryFn: () => get<LeisureService[]>("/services"),
  });

  const slots = useQuery({
    queryKey: ["leisure-slots", serviceId, day],
    queryFn: () => get<LeisureSlot[]>(`/services/${serviceId}/slots?date=${day}`),
    enabled: serviceId != null,
  });

  const create = useMutation({
    mutationFn: () =>
      api("/leisure/bookings", {
        method: "POST",
        body: {
          service_id: serviceId,
          start_at: slot!.start_at,
          resource_id: slot!.resource_id,
          guest_name: guest.trim(),
          adults,
        },
      }),
    onSuccess: onDone,
    onError: (err) => setError(err instanceof ApiError ? err.messageAr : "حصل خطأ"),
  });

  const service = services.data?.find((s) => s.id === serviceId);

  return (
    <Modal
      open
      onClose={onClose}
      width={560}
      title="موعد جديد"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            إلغاء
          </Button>
          <Button
            disabled={!serviceId || !slot || !guest.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            احجز
          </Button>
        </>
      }
    >
      <label className="text-[12px] font-bold text-muted block mb-1.5">الخدمة</label>
      <select
        className="w-full h-10 px-3 rounded-[6px] border border-line bg-surface text-[13.5px] mb-4"
        value={serviceId ?? ""}
        onChange={(e) => {
          setServiceId(Number(e.target.value) || null);
          setSlot(null);
        }}
      >
        <option value="">— اختار —</option>
        {(services.data ?? []).map((s) => (
          <option key={s.id} value={s.id}>
            {CATEGORY_AR[s.category] ?? s.category} · {s.name_ar} — {money(s.price)} ج
          </option>
        ))}
      </select>

      {service && (
        <div className="text-[12px] text-muted mb-3">
          <span className="num">{service.duration_minutes}</span> دقيقة ·{" "}
          <span className="num">{service.buffer_minutes}</span> دقيقة تجهيز · السعة{" "}
          <span className="num">{service.capacity}</span>
        </div>
      )}

      {serviceId && (
        <>
          <label className="text-[12px] font-bold text-muted block mb-1.5">
            المواعيد الفاضية
          </label>
          {slots.isLoading && <Loading />}
          {slots.data && !slots.data.length && (
            <div className="text-[13px] text-muted mb-4">
              مفيش مواعيد فاضية في اليوم ده.
            </div>
          )}
          <div className="flex flex-wrap gap-1.5 mb-4 max-h-[190px] overflow-y-auto">
            {(slots.data ?? []).map((s) => (
              <button
                key={`${s.resource_id}-${s.start_at}`}
                onClick={() => setSlot(s)}
                title={s.resource_name}
                className={cx(
                  "num h-8 px-2.5 rounded-[6px] border text-[12.5px] font-bold",
                  slot?.start_at === s.start_at && slot?.resource_id === s.resource_id
                    ? "bg-accent text-accent-ink border-accent"
                    : "border-line text-ink-2 hover:bg-surface-2",
                )}
              >
                {hhmm(s.start_at)}
              </button>
            ))}
          </div>
          {slot && (
            <div className="text-[12px] text-accent mb-4">مع {slot.resource_name}</div>
          )}
        </>
      )}

      <label className="text-[12px] font-bold text-muted block mb-1.5">اسم النزيل</label>
      <input
        className="w-full h-10 px-3 rounded-[6px] border border-line bg-surface text-[13.5px] mb-4"
        value={guest}
        onChange={(e) => setGuest(e.target.value)}
        placeholder="الاسم زي ما هو في الحجز"
      />

      <label className="text-[12px] font-bold text-muted block mb-1.5">عدد الأفراد</label>
      <input
        type="number"
        min={1}
        max={service?.capacity ?? 1}
        className="num w-24 h-10 px-3 rounded-[6px] border border-line bg-surface text-[13.5px]"
        value={adults}
        onChange={(e) => setAdults(Math.max(1, Number(e.target.value)))}
      />

      {error && (
        <div className="mt-4 text-[13px] rounded-[6px] border border-bad/35 bg-bad/8 text-bad px-3 py-2">
          {error}
        </div>
      )}
    </Modal>
  );
}

// ═══════════════════════════════════════════════════════ المناسبات
function Events({ canManage }: { canManage: boolean }) {
  const { locale } = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = useState<EventOut | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const board = useQuery({
    queryKey: ["events"],
    queryFn: () => get<EventsBoard>("/events?days=400"),
  });

  const move = useMutation({
    mutationFn: (v: { id: number; status: string; reason?: string }) =>
      api<EventOut>(`/events/${v.id}/status`, {
        method: "PATCH",
        body: { status: v.status, reason: v.reason },
      }),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["events"] });
      setOpen(updated);
    },
    onError: (err) => setToast(err instanceof ApiError ? err.messageAr : "حصل خطأ"),
  });

  const deposit = useMutation({
    mutationFn: (v: { id: number; amount: string }) =>
      api<EventOut>(`/events/${v.id}/deposit`, {
        method: "POST",
        body: { amount: v.amount },
      }),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["events"] });
      setOpen(updated);
    },
    onError: (err) => setToast(err instanceof ApiError ? err.messageAr : "حصل خطأ"),
  });

  if (board.isLoading) return <Loading />;
  if (board.isError) return <ErrorState onRetry={() => board.refetch()} />;
  const b = board.data!;

  const groups: [string, EventOut[]][] = [
    ["مؤكدة وجارية", b.events.filter((e) => ["CONFIRMED", "RUNNING"].includes(e.status))],
    ["مبدئية — مستنية عربون", b.events.filter((e) => e.status === "TENTATIVE")],
    ["استعلامات", b.events.filter((e) => e.status === "INQUIRY")],
    ["خلصت", b.events.filter((e) => e.status === "COMPLETED")],
    ["ضاعت أو اتلغت", b.events.filter((e) => ["LOST", "CANCELLED"].includes(e.status))],
  ];

  return (
    <>
      <div className="shrink-0 px-5 py-3 border-b border-line bg-surface flex items-center gap-4 flex-wrap">
        <StatStrip
          items={[
            { label: "مؤكدة", value: String(b.confirmed), tone: "good" },
            { label: "قيمة المؤكد", value: money(b.confirmed_value), tone: "good" },
            { label: "مبدئية", value: String(b.tentative), tone: "warn" },
            { label: "استعلامات", value: String(b.inquiries) },
            { label: "قيمة الاحتمالات", value: money(b.pipeline_value), tone: "warn" },
            { label: "عرابين مستحقة", value: money(b.deposits_due), tone: b.deposits_due !== "0.0000" ? "bad" : "ink" },
            { label: "نسبة التحويل", value: `${b.win_rate_percent}%`, tone: "accent" },
            { label: "ضاعت", value: String(b.lost), tone: b.lost ? "bad" : "ink" },
          ]}
        />
      </div>

      {b.options_expiring > 0 && (
        <div className="shrink-0 px-5 py-2 border-b border-warn/30 bg-warn/8 text-warn text-[12.5px] font-bold">
          <span className="num">{b.options_expiring}</span> حجز مبدئي مهلة عربونه بتخلص خلال أسبوع — المكان هيرجع للبيع لوحده.
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {!b.events.length && (
          <EmptyState title="مفيش مناسبات" hint="سجّل استعلام جديد لما ييجي." />
        )}
        <div className="flex flex-col gap-5">
          {groups
            .filter(([, list]) => list.length)
            .map(([label, list]) => (
              <section key={label}>
                <h2 className="text-[13px] font-bold text-muted mb-2 flex items-center gap-2">
                  {label}
                  <span className="num text-ink-2">{list.length}</span>
                  <span className="flex-1 h-px bg-line" />
                </h2>
                <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
                  {list.map((event) => (
                    <button
                      key={event.id}
                      onClick={() => setOpen(event)}
                      className={cx(
                        "text-start border rounded-[8px] p-3 bg-surface hover:bg-surface-2 transition-colors",
                        EVENT_TONE[event.status]?.split(" ")[0] ?? "border-line",
                      )}
                    >
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="num text-[11px] text-muted">{event.number}</span>
                        <span
                          className={cx(
                            "text-[10.5px] font-bold rounded-full px-2 py-0.5 border",
                            EVENT_TONE[event.status],
                          )}
                        >
                          {EVENT_STATUS_AR[event.status] ?? event.status}
                        </span>
                        <span className="text-[10.5px] text-muted ms-auto">
                          {EVENT_KIND_AR[event.kind] ?? event.kind}
                        </span>
                      </div>
                      <div className="text-[14.5px] font-bold truncate">{event.title}</div>
                      <div className="text-[12px] text-muted truncate mt-0.5">
                        {event.venue_name_ar} · {formatDate(event.event_date, locale)}
                      </div>
                      <div className="flex items-baseline gap-3 mt-2">
                        <span className="num text-[15px] font-bold">
                          {money(event.grand_total)}
                        </span>
                        <span className="num text-[11.5px] text-muted">
                          {event.pax} فرد
                        </span>
                        {Number(event.deposit_outstanding) > 0 &&
                          ["TENTATIVE", "CONFIRMED"].includes(event.status) && (
                            <span className="num text-[11px] text-bad font-bold ms-auto">
                              عربون {money(event.deposit_outstanding)}
                            </span>
                          )}
                      </div>
                    </button>
                  ))}
                </div>
              </section>
            ))}
        </div>
      </div>

      {open && (
        <EventSheet
          event={open}
          canManage={canManage}
          busy={move.isPending || deposit.isPending}
          onClose={() => setOpen(null)}
          onStatus={(status, reason) => move.mutate({ id: open.id, status, reason })}
          onDeposit={(amount) => deposit.mutate({ id: open.id, amount })}
        />
      )}

      {toast && (
        <div
          className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 rounded-[6px] bg-bad text-white px-4 py-2.5 text-[13.5px] font-bold"
          role="status"
          onClick={() => setToast(null)}
        >
          {toast}
        </div>
      )}
    </>
  );
}

function EventSheet({
  event,
  canManage,
  busy,
  onClose,
  onStatus,
  onDeposit,
}: {
  event: EventOut;
  canManage: boolean;
  busy: boolean;
  onClose: () => void;
  onStatus: (status: string, reason?: string) => void;
  onDeposit: (amount: string) => void;
}) {
  const { locale } = useI18n();
  const [reason, setReason] = useState("");

  // الخطوة الجاية بتتحدد من الحالة الحالية — الشاشة مبتعرضش زرار
  // بيرجّع المناسبة لورا، ولا زرار على مناسبة اتقفلت خلاص
  const TRANSITIONS: Record<string, [string, string][]> = {
    INQUIRY: [["TENTATIVE", "احجز مبدئي"]],
    TENTATIVE: [
      ["CONFIRMED", "أكّد"],
      ["LOST", "ضاعت"],
    ],
    CONFIRMED: [
      ["COMPLETED", "خلصت"],
      ["CANCELLED", "الغي"],
    ],
    RUNNING: [["COMPLETED", "خلصت"]],
  };
  const next = TRANSITIONS[event.status] ?? [];

  const needsReason = (status: string) => ["LOST", "CANCELLED"].includes(status);

  return (
    <Modal
      open
      onClose={onClose}
      width={720}
      title={`${event.number} · ${event.title}`}
    >
      <div className="flex items-center gap-3 flex-wrap text-[12.5px] text-muted mb-4">
        <span
          className={cx(
            "text-[11px] font-bold rounded-full px-2 py-0.5 border",
            EVENT_TONE[event.status],
          )}
        >
          {EVENT_STATUS_AR[event.status] ?? event.status}
        </span>
        <span>{event.venue_name_ar}</span>
        <span>·</span>
        <span>{formatDate(event.event_date, locale)}</span>
        <span>·</span>
        <span className="num">
          {hhmm(event.start_at)} – {hhmm(event.end_at)}
        </span>
        <span>·</span>
        <span className="num">{event.pax} فرد</span>
      </div>

      <div className="text-[13px] mb-4">
        <span className="text-muted">العميل: </span>
        <span className="font-bold">{event.client_name}</span>
        {event.client_phone && (
          <span className="num text-muted"> · {event.client_phone}</span>
        )}
      </div>

      {event.option_until && (
        <div className="mb-4 text-[12.5px] rounded-[6px] border border-warn/35 bg-warn/8 text-warn px-3 py-2">
          حجز مبدئي — مهلة العربون لحد {formatDate(event.option_until, locale)}، وبعدها
          المكان بيرجع للبيع لوحده.
        </div>
      )}
      {event.lost_reason && (
        <div className="mb-4 text-[12.5px] rounded-[6px] border border-bad/35 bg-bad/8 text-bad px-3 py-2">
          ضاعت: {event.lost_reason}
        </div>
      )}

      <h3 className="text-[12px] font-bold text-muted mb-2">ورقة التشغيل</h3>
      <div className="border border-line rounded-[8px] overflow-hidden mb-4">
        <table className="w-full text-[13px]">
          <tbody>
            <tr className="border-b border-line">
              <td className="px-3 py-2 text-muted">إيجار المكان</td>
              <td className="px-3 py-2 num text-end font-bold">
                {money(event.venue_charge)}
              </td>
            </tr>
            {Number(event.package_per_person) > 0 && (
              <tr className="border-b border-line">
                <td className="px-3 py-2 text-muted">
                  باكدج × <span className="num">{event.pax}</span> فرد ·{" "}
                  <span className="num">{money(event.package_per_person)}</span>
                </td>
                <td className="px-3 py-2 num text-end font-bold">
                  {money(Number(event.package_per_person) * event.pax)}
                </td>
              </tr>
            )}
            {event.items.map((item) => (
              <tr key={item.id} className="border-b border-line">
                <td className="px-3 py-2">
                  <span className="text-[10.5px] text-muted me-2">
                    {ITEM_KIND_AR[item.kind] ?? item.kind}
                  </span>
                  {item.description_ar}
                  {Number(item.quantity) !== 1 && (
                    <span className="num text-muted">
                      {" "}
                      × {Number(item.quantity)}
                    </span>
                  )}
                  {item.is_complimentary && (
                    <span className="text-[10.5px] font-bold rounded-full px-1.5 py-0.5 bg-accent-soft text-accent ms-2">
                      مجاملة
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 num text-end font-bold">{money(item.total)}</td>
              </tr>
            ))}
            <tr className="border-b border-line bg-surface-2">
              <td className="px-3 py-2 font-bold">المجموع</td>
              <td className="px-3 py-2 num text-end font-bold">{money(event.subtotal)}</td>
            </tr>
            <tr className="border-b border-line">
              <td className="px-3 py-2 text-muted">الخدمة</td>
              <td className="px-3 py-2 num text-end">{money(event.service_charge)}</td>
            </tr>
            <tr className="border-b border-line">
              <td className="px-3 py-2 text-muted">الضريبة</td>
              <td className="px-3 py-2 num text-end">{money(event.tax)}</td>
            </tr>
            <tr className="bg-accent-soft">
              <td className="px-3 py-2.5 font-bold text-accent">الإجمالي</td>
              <td className="px-3 py-2.5 num text-end font-bold text-accent text-[15px]">
                {money(event.grand_total)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-3 text-[13px] mb-4 flex-wrap">
        <span className="text-muted">العربون:</span>
        <span className="num font-bold">
          {money(event.deposit_paid)} / {money(event.deposit_required)}
        </span>
        {Number(event.deposit_outstanding) > 0 ? (
          <span className="num text-bad font-bold">
            ناقص {money(event.deposit_outstanding)}
          </span>
        ) : (
          <span className="text-good font-bold">مكتمل</span>
        )}
        {canManage && Number(event.deposit_outstanding) > 0 && (
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => onDeposit(event.deposit_outstanding)}
          >
            سجّل الباقي
          </Button>
        )}
      </div>

      {event.setup_notes && (
        <>
          <h3 className="text-[12px] font-bold text-muted mb-2">تعليمات التشغيل</h3>
          <p className="text-[13px] leading-relaxed text-ink-2 mb-4">{event.setup_notes}</p>
        </>
      )}

      {canManage && next.length > 0 && (
        <div className="border-t border-line pt-4">
          {next.some(([s]) => needsReason(s)) && (
            <input
              className="w-full h-10 px-3 rounded-[6px] border border-line bg-surface text-[13.5px] mb-2"
              placeholder="السبب (مطلوب للإلغاء أو الضياع)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
          <div className="flex items-center gap-2 flex-wrap">
            {next.map(([status, label]) => (
              <Button
                key={status}
                variant={needsReason(status) ? "ghost" : "primary"}
                disabled={busy || (needsReason(status) && !reason.trim())}
                onClick={() => onStatus(status, reason.trim() || undefined)}
              >
                {label}
              </Button>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
