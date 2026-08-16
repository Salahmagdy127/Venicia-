/**
 * علاقات النزلاء — الشرائح والشكاوى وملف النزيل.
 *
 * الشاشة دي مبتعرضش بيانات جديدة — بتعرض **قرارات**. لكل شريحة زرار
 * بينقل لقايمة أسماء بأرقام تليفوناتهم، ولكل شكوى ساعة بتعدّ لحد ما
 * حد يرد.
 *
 * وزمن الرد معروض في وش الشاشة مش جوّه تقرير: هو المقياس الوحيد
 * اللي بيفرق بين شكوى بتتحل وشكوى بتتحوّل مراجعة بنجمة واحدة.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, get } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatDate, money } from "@/lib/format";
import type {
  CrmProfile,
  CrmSegmentRow,
  CrmSegmentSummary,
  FeedbackBoard,
  FeedbackItem,
} from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import { Button, EmptyState, ErrorState, Loading, Modal, cx } from "@/components/ui";
import { IconStar } from "@/components/Icons";

const KIND_AR: Record<string, string> = {
  COMPLAINT: "شكوى",
  COMPLIMENT: "ثناء",
  SUGGESTION: "اقتراح",
  REVIEW: "تقييم",
};

const KIND_TONE: Record<string, string> = {
  COMPLAINT: "border-bad/45 text-bad",
  COMPLIMENT: "border-good/45 text-good",
  SUGGESTION: "border-line text-ink-2",
  REVIEW: "border-accent/45 text-accent",
};

const STATUS_AR: Record<string, string> = {
  OPEN: "مفتوحة",
  ACKNOWLEDGED: "اترد عليها",
  RESOLVED: "اتحلّت",
  ESCALATED: "متصعّدة",
  CLOSED: "مقفولة",
};

const CHANNEL_AR: Record<string, string> = {
  IN_HOUSE: "أثناء الإقامة",
  EMAIL: "إيميل",
  PHONE: "تليفون",
  GOOGLE: "جوجل",
  BOOKING_COM: "بوكينج",
  SOCIAL: "سوشيال",
  SURVEY: "استبيان",
};

const SEGMENT_AR: Record<string, string> = {
  VIP: "كبير",
  REPEAT: "متكرر",
  CORPORATE: "شركة",
  LAPSED: "غايب",
  RISK: "متابعة",
  BLACKLIST: "محظور",
  REACHABLE: "موافق",
  NEW: "جديد",
};

function hours(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  if (n < 1) return `${Math.round(n * 60)} د`;
  return `${n.toFixed(1)} س`;
}

export default function Crm() {
  const [tab, setTab] = useState<"feedback" | "segments">("feedback");
  const [profile, setProfile] = useState<number | null>(null);

  return (
    <>
      <PageHeader
        title="علاقات النزلاء"
        subtitle="الشرايح والشكاوى وزمن الرد"
      />

      <div className="shrink-0 px-5 border-b border-line bg-surface flex items-center gap-1">
        {(
          [
            ["feedback", "الشكاوى والتقييمات"],
            ["segments", "الشرائح"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cx(
              "h-10 px-4 text-[13.5px] font-bold border-b-2 -mb-px transition-colors",
              tab === key
                ? "border-accent text-accent"
                : "border-transparent text-muted hover:text-ink-2",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "feedback" ? <Feedback onGuest={setProfile} /> : <Segments onGuest={setProfile} />}

      {profile != null && (
        <GuestProfile guestId={profile} onClose={() => setProfile(null)} />
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════ الشكاوى
function Feedback({ onGuest }: { onGuest: (id: number) => void }) {
  const { locale } = useI18n();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>("");
  const [toast, setToast] = useState<string | null>(null);
  const [closing, setClosing] = useState<FeedbackItem | null>(null);

  const board = useQuery({
    queryKey: ["feedback", filter],
    queryFn: () =>
      get<FeedbackBoard>(`/crm/feedback${filter ? `?status=${filter}` : ""}`),
  });

  const act = useMutation({
    mutationFn: (v: { id: number; action: string; body?: unknown }) =>
      api(`/crm/feedback/${v.id}/${v.action}`, { method: "POST", body: v.body ?? {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["feedback"] });
      setClosing(null);
    },
    onError: (err) => setToast(err instanceof ApiError ? err.messageAr : "حصل خطأ"),
  });

  if (board.isLoading) return <Loading />;
  if (board.isError) return <ErrorState onRetry={() => board.refetch()} />;
  const b = board.data!;

  return (
    <>
      <div className="shrink-0 px-5 py-3 border-b border-line bg-surface flex items-center gap-4 flex-wrap">
        <StatStrip
          items={[
            { label: "مفتوحة", value: String(b.open), tone: b.open ? "warn" : "ink" },
            {
              label: `فات ميعاد الرد (${b.ack_target_hours}س)`,
              value: String(b.overdue),
              tone: b.overdue ? "bad" : "good",
            },
            { label: "متصعّدة", value: String(b.escalated), tone: b.escalated ? "bad" : "ink" },
            { label: "اتحلّت ٣٠ يوم", value: String(b.resolved_30d), tone: "good" },
            { label: "متوسط الرد", value: hours(b.average_ack_hours), tone: "accent" },
            { label: "متوسط الحل", value: hours(b.average_resolve_hours) },
            {
              label: "متوسط التقييم",
              value: b.average_rating ? `★ ${b.average_rating}` : "—",
              tone: Number(b.average_rating ?? 0) >= 4 ? "good" : "warn",
            },
            { label: "تعويضات ٣٠ يوم", value: money(b.compensation_30d) },
          ]}
        />
      </div>

      <div className="shrink-0 px-5 py-2.5 border-b border-line bg-surface flex items-center gap-1.5 flex-wrap">
        {[
          ["", "الكل"],
          ["OPEN", "مفتوحة"],
          ["ACKNOWLEDGED", "اترد عليها"],
          ["ESCALATED", "متصعّدة"],
          ["RESOLVED", "اتحلّت"],
        ].map(([value, label]) => (
          <button
            key={value}
            onClick={() => setFilter(value)}
            className={cx(
              "h-8 px-3 rounded-full border text-[12.5px] font-bold",
              filter === value
                ? "bg-accent text-accent-ink border-accent"
                : "border-line text-ink-2 hover:bg-surface-2",
            )}
          >
            {label}
          </button>
        ))}
        {Object.entries(b.by_department).length > 0 && (
          <span className="ms-auto text-[12px] text-muted">
            شكاوى ٣٠ يوم:{" "}
            {Object.entries(b.by_department)
              .sort((a, c) => c[1] - a[1])
              .map(([dept, count]) => `${dept} ${count}`)
              .join(" · ")}
          </span>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {!b.items.length && <EmptyState title="مفيش ملاحظات" />}
        <div className="flex flex-col gap-2">
          {b.items.map((item) => (
            <div
              key={item.id}
              className={cx(
                "border rounded-[8px] p-3 bg-surface",
                item.is_overdue ? "border-bad/45" : "border-line",
              )}
            >
              <div className="flex items-center gap-2 flex-wrap mb-1.5">
                <span className="num text-[11px] text-muted">{item.number}</span>
                <span
                  className={cx(
                    "text-[10.5px] font-bold rounded-full px-2 py-0.5 border",
                    KIND_TONE[item.kind],
                  )}
                >
                  {KIND_AR[item.kind] ?? item.kind}
                </span>
                <span className="text-[10.5px] text-muted">
                  {CHANNEL_AR[item.channel] ?? item.channel}
                </span>
                {item.department && (
                  <span className="text-[10.5px] font-bold rounded-full px-2 py-0.5 bg-surface-2 text-ink-2">
                    {item.department}
                  </span>
                )}
                {item.rating != null && (
                  <span className="flex items-center gap-0.5 text-[11px] font-bold text-gold">
                    <IconStar size={12} />
                    <span className="num">{item.rating}</span>
                  </span>
                )}
                {item.is_overdue && (
                  <span className="text-[10.5px] font-bold rounded-full px-2 py-0.5 bg-bad/15 text-bad">
                    فات ميعاد الرد
                  </span>
                )}
                <span className="text-[11px] text-muted ms-auto">
                  {formatDate(item.received_at.slice(0, 10), locale)}
                  {item.hours_to_ack != null && (
                    <> · رد بعد {hours(item.hours_to_ack)}</>
                  )}
                </span>
              </div>

              <div className="text-[14px] font-bold">{item.subject}</div>
              {item.body && (
                <div className="text-[12.5px] text-ink-2 mt-1 leading-relaxed">
                  {item.body}
                </div>
              )}

              <div className="flex items-center gap-2 flex-wrap mt-2.5">
                <button
                  className="text-[12.5px] font-bold text-accent hover:underline"
                  onClick={() => item.guest_id && onGuest(item.guest_id)}
                  disabled={!item.guest_id}
                >
                  {item.guest_name}
                </button>
                <span className="text-[12px] text-muted">
                  · {STATUS_AR[item.status] ?? item.status}
                </span>
                {Number(item.compensation) > 0 && (
                  <span className="num text-[12px] text-warn font-bold">
                    تعويض {money(item.compensation)}
                  </span>
                )}
                {item.resolution && (
                  <span className="text-[12px] text-good truncate max-w-[40%]">
                    ✓ {item.resolution}
                  </span>
                )}

                <div className="flex items-center gap-1.5 ms-auto">
                  {item.status === "OPEN" && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={act.isPending}
                      onClick={() => act.mutate({ id: item.id, action: "acknowledge" })}
                    >
                      سجّل الرد
                    </Button>
                  )}
                  {!["RESOLVED", "CLOSED"].includes(item.status) && (
                    <>
                      <Button size="sm" onClick={() => setClosing(item)}>
                        اقفلها
                      </Button>
                      {item.status !== "ESCALATED" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={act.isPending}
                          onClick={() => act.mutate({ id: item.id, action: "escalate" })}
                        >
                          صعّد
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {closing && (
        <ResolveModal
          item={closing}
          busy={act.isPending}
          onClose={() => setClosing(null)}
          onSave={(resolution, compensation) =>
            act.mutate({
              id: closing.id,
              action: "resolve",
              body: { resolution, compensation: compensation || null },
            })
          }
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

function ResolveModal({
  item,
  busy,
  onClose,
  onSave,
}: {
  item: FeedbackItem;
  busy: boolean;
  onClose: () => void;
  onSave: (resolution: string, compensation: string) => void;
}) {
  const [resolution, setResolution] = useState("");
  const [compensation, setCompensation] = useState("");

  return (
    <Modal
      open
      onClose={onClose}
      width={520}
      title={`قفل ${item.number}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            إلغاء
          </Button>
          <Button
            disabled={busy || !resolution.trim()}
            onClick={() => onSave(resolution.trim(), compensation)}
          >
            اقفلها
          </Button>
        </>
      }
    >
      <div className="text-[13.5px] font-bold mb-3">{item.subject}</div>
      <label className="text-[12px] font-bold text-muted block mb-1.5">اتعمل إيه</label>
      <textarea
        className="w-full min-h-[100px] p-3 rounded-[6px] border border-line bg-surface text-[13.5px] leading-relaxed resize-none"
        value={resolution}
        placeholder="اتواصلنا مع النزيل واتنقل لوحدة تانية…"
        onChange={(e) => setResolution(e.target.value)}
      />
      <label className="text-[12px] font-bold text-muted block mt-4 mb-1.5">
        التعويض (لو فيه)
      </label>
      <input
        className="num w-40 h-10 px-3 rounded-[6px] border border-line bg-surface text-[13.5px]"
        inputMode="decimal"
        value={compensation}
        placeholder="0.00"
        onChange={(e) => setCompensation(e.target.value)}
      />
      <p className="text-[12px] text-muted mt-3 leading-relaxed">
        التعويض بيتسجّل عشان يتقاس مع زمن الرد. الشكوى اللي بتتحل بسرعة
        بتكلّف أقل — وده بيبان في الرقمين مع بعض.
      </p>
    </Modal>
  );
}

// ═══════════════════════════════════════════════════════ الشرائح
function Segments({ onGuest }: { onGuest: (id: number) => void }) {
  const { locale } = useI18n();
  const [code, setCode] = useState("VIP");

  const summary = useQuery({
    queryKey: ["crm-segments"],
    queryFn: () => get<CrmSegmentSummary[]>("/crm/segments"),
  });

  const rows = useQuery({
    queryKey: ["crm-segment", code],
    queryFn: () => get<CrmSegmentRow[]>(`/crm/segments/${code}?limit=200`),
  });

  if (summary.isLoading) return <Loading />;
  if (summary.isError) return <ErrorState onRetry={() => summary.refetch()} />;

  return (
    <>
      <div className="shrink-0 px-5 py-3 border-b border-line bg-surface flex items-center gap-2 flex-wrap">
        {(summary.data ?? []).map((s) => (
          <button
            key={s.code}
            onClick={() => setCode(s.code)}
            className={cx(
              "border rounded-[8px] px-3 py-2 text-start min-w-[130px] transition-colors",
              code === s.code
                ? "border-accent bg-accent-soft"
                : "border-line hover:bg-surface-2",
            )}
          >
            <div className="flex items-baseline gap-2">
              <span className="num text-[19px] font-bold leading-none">{s.guests}</span>
              <span className="text-[12px] font-bold text-ink-2">{s.name_ar}</span>
            </div>
            <div className="num text-[11px] text-muted mt-1">{money(s.value)} ج</div>
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {rows.isLoading && <Loading />}
        {rows.data && !rows.data.length && (
          <EmptyState title="مفيش نزلاء في الشريحة دي" />
        )}
        {rows.data && rows.data.length > 0 && (
          <div className="border border-line rounded-[8px] overflow-hidden">
            <table className="w-full text-[13px]">
              <thead className="bg-surface-2 text-muted text-[11.5px]">
                <tr>
                  <th className="px-3 py-2 text-start font-bold">النزيل</th>
                  <th className="px-3 py-2 text-start font-bold">تواصل</th>
                  <th className="px-3 py-2 text-end font-bold">إقامات</th>
                  <th className="px-3 py-2 text-end font-bold">ليالي</th>
                  <th className="px-3 py-2 text-start font-bold">آخر إقامة</th>
                  <th className="px-3 py-2 text-end font-bold">الإنفاق</th>
                  <th className="px-3 py-2 text-start font-bold">شرائح</th>
                </tr>
              </thead>
              <tbody>
                {rows.data.map((row) => (
                  <tr
                    key={row.guest_id}
                    className="border-t border-line hover:bg-surface-2 cursor-pointer"
                    onClick={() => onGuest(row.guest_id)}
                  >
                    <td className="px-3 py-2 font-bold">{row.name}</td>
                    <td className="px-3 py-2 num text-muted text-[12px]">
                      {row.phone || row.email || "—"}
                    </td>
                    <td className="px-3 py-2 num text-end">{row.stays}</td>
                    <td className="px-3 py-2 num text-end">{row.nights}</td>
                    <td className="px-3 py-2 text-[12px] text-muted">
                      {row.last_stay ? formatDate(row.last_stay, locale) : "—"}
                    </td>
                    <td className="px-3 py-2 num text-end font-bold">
                      {money(row.total_spend)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1 flex-wrap">
                        {row.segments.map((tag) => (
                          <span
                            key={tag}
                            className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-surface-2 text-ink-2"
                          >
                            {SEGMENT_AR[tag] ?? tag}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

// ═══════════════════════════════════════════════════ ملف النزيل
function GuestProfile({ guestId, onClose }: { guestId: number; onClose: () => void }) {
  const { locale } = useI18n();
  const profile = useQuery({
    queryKey: ["crm-profile", guestId],
    queryFn: () => get<CrmProfile>(`/crm/guests/${guestId}`),
  });

  const p = profile.data;
  const buckets: [string, string][] = p
    ? [
        ["إقامة", p.spend.rooms],
        ["أكل وشرب", p.spend.food],
        ["سبا", p.spend.spa],
        ["أنشطة", p.spend.activities],
        ["أخرى", p.spend.other],
      ]
    : [];
  const max = Math.max(1, ...buckets.map(([, v]) => Number(v)));

  return (
    <Modal open onClose={onClose} width={600} title={p?.name ?? "ملف النزيل"}>
      {profile.isLoading && <Loading />}
      {p && (
        <>
          <div className="flex gap-1.5 flex-wrap mb-4">
            {p.segments.map((tag) => (
              <span
                key={tag}
                className="text-[11px] font-bold rounded-full px-2 py-0.5 border border-accent/40 text-accent bg-accent-soft"
              >
                {SEGMENT_AR[tag] ?? tag}
              </span>
            ))}
          </div>

          <div className="grid grid-cols-4 gap-2 mb-5">
            {[
              ["إقامات", String(p.stays)],
              ["ليالي", String(p.nights)],
              ["متوسط الإقامة", money(p.average_per_stay)],
              ["متوسط الليلة", money(p.average_per_night)],
            ].map(([label, value]) => (
              <div key={label} className="border border-line rounded-[8px] p-2.5">
                <div className="num text-[17px] font-bold leading-none">{value}</div>
                <div className="text-[11px] text-muted mt-1">{label}</div>
              </div>
            ))}
          </div>

          <h3 className="text-[12px] font-bold text-muted mb-2">
            الإنفاق الكامل ·{" "}
            <span className="num text-ink">{money(p.spend.total)}</span> ج
          </h3>
          <div className="flex flex-col gap-1.5 mb-5">
            {buckets.map(([label, value]) => (
              <div key={label} className="flex items-center gap-3">
                <span className="text-[12.5px] w-[70px] shrink-0 text-ink-2">{label}</span>
                <div className="flex-1 h-4 bg-surface-2 rounded-[3px] overflow-hidden">
                  <div
                    className="h-full bg-accent rounded-[3px] transition-[width] duration-500"
                    style={{ width: `${(Number(value) / max) * 100}%` }}
                  />
                </div>
                <span className="num text-[12.5px] font-bold w-[92px] text-end">
                  {money(value)}
                </span>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px]">
            <Row label="أول إقامة" value={p.first_stay ? formatDate(p.first_stay, locale) : "—"} />
            <Row label="آخر إقامة" value={p.last_stay ? formatDate(p.last_stay, locale) : "—"} />
            <Row
              label="من آخر زيارة"
              value={p.days_since_last != null ? `${p.days_since_last} يوم` : "—"}
            />
            <Row label="حجوزات سبا وأنشطة" value={String(p.service_bookings)} />
            <Row label="إلغاءات" value={String(p.cancellations)} />
            <Row label="لم يحضر" value={String(p.no_shows)} />
            <Row label="ملاحظات مفتوحة" value={String(p.open_feedback)} />
          </div>
        </>
      )}
    </Modal>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-line py-1.5">
      <span className="text-muted">{label}</span>
      <span className="num font-bold">{value}</span>
    </div>
  );
}
