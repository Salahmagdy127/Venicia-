/** ملف النزيل — الهوية والتفضيلات والمناسبات، وده اللي بيخلي النزيل الراجع يتعامل معاملة خاصة. */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, get } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate, money } from "@/lib/format";
import type { Guest } from "@/lib/types";
import { Button, ErrorState, Loading, cx, inputClass } from "./ui";
import { IconPlus, IconTrash, IconX } from "./Icons";

const ID_TYPES = ["NATIONAL_ID", "PASSPORT", "DRIVING_LICENSE"] as const;

/** بنود جاهزة عشان الاستقبال ميكتبش من الأول كل مرة */
const PREF_SUGGESTIONS: [string, string][] = [
  ["الدور", "دور عالي"],
  ["الموقع", "بعيد عن الريسبشن"],
  ["السرير", "سرير مزدوج"],
  ["المخدة", "وسادة إضافية"],
  ["الإطلالة", "على البحيرة"],
];

type Pair = { key: string; value: string };

function toPairs(obj: Record<string, unknown> | null | undefined): Pair[] {
  if (!obj) return [];
  return Object.entries(obj).map(([key, value]) => ({ key, value: String(value ?? "") }));
}

function toObject(pairs: Pair[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of pairs) {
    const key = p.key.trim();
    if (key) out[key] = p.value.trim();
  }
  return out;
}

export default function GuestProfile({
  guestId,
  onClose,
}: {
  guestId: number | null;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [editing, setEditing] = useState(false);
  const [banner, setBanner] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const [form, setForm] = useState({
    phone: "",
    email: "",
    city: "",
    nationality: "EG",
    id_type: "NATIONAL_ID" as string,
    id_number: "",
    is_vip: false,
    whatsapp_opt_in: false,
    marketing_opt_in: false,
    dietary_notes: "",
    notes: "",
  });
  const [prefs, setPrefs] = useState<Pair[]>([]);
  const [occasions, setOccasions] = useState<Pair[]>([]);

  const open = guestId !== null;

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["guest", guestId],
    queryFn: () => get<Guest>(`/guests/${guestId}`),
    enabled: open,
  });

  // نملا الفورم من الداتا أول ما توصل
  useEffect(() => {
    if (!data) return;
    setForm({
      phone: data.phone ?? "",
      email: data.email ?? "",
      city: data.city ?? "",
      nationality: data.nationality ?? "EG",
      id_type: data.id_type,
      id_number: data.id_number ?? "",
      is_vip: data.is_vip,
      whatsapp_opt_in: data.whatsapp_opt_in,
      marketing_opt_in: data.marketing_opt_in ?? false,
      dietary_notes: data.dietary_notes ?? "",
      notes: data.notes ?? "",
    });
    setPrefs(toPairs(data.preferences));
    setOccasions(toPairs(data.occasions));
  }, [data]);

  useEffect(() => {
    if (!open) {
      setEditing(false);
      setBanner(null);
    }
  }, [open]);

  const save = useMutation({
    mutationFn: () =>
      api<Guest>(`/guests/${guestId}`, {
        method: "PATCH",
        body: {
          ...form,
          phone: form.phone || null,
          email: form.email || null,
          city: form.city || null,
          id_number: form.id_number || null,
          dietary_notes: form.dietary_notes || null,
          notes: form.notes || null,
          preferences: toObject(prefs),
          occasions: toObject(occasions),
        },
      }),
    onSuccess: () => {
      setBanner({ tone: "good", text: t("gp.saved") });
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["guest", guestId] });
      qc.invalidateQueries({ queryKey: ["guests"] });
    },
    onError: (err) =>
      setBanner({
        tone: "bad",
        text: err instanceof ApiError ? err.text(locale) : t("state.error"),
      }),
  });

  if (!open) return null;
  const g = data;
  const canEdit = can("guest.edit");

  return (
    <div className="fixed inset-0 z-50 flex bg-black/45" onClick={onClose}>
      <aside
        className="ms-auto h-full w-full max-w-[560px] bg-surface border-s border-line flex flex-col"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("gp.title")}
      >
        <header className="shrink-0 px-5 py-4 border-b border-line flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[17px] font-bold truncate">{g?.full_name ?? "—"}</span>
              {g?.is_vip && (
                <span className="text-[11.5px] font-bold rounded-full bg-gold-soft text-gold px-2 py-0.5">
                  VIP
                </span>
              )}
              {g && g.total_stays > 1 && (
                <span className="text-[11.5px] font-bold rounded-full bg-accent-soft text-accent px-2 py-0.5">
                  {t("folio.returning")}
                </span>
              )}
              {g?.is_blacklisted && (
                <span className="text-[11.5px] font-bold rounded-full bg-bad/15 text-bad px-2 py-0.5">
                  {t("guest.blacklisted")}
                </span>
              )}
            </div>
            {g && g.total_stays > 1 && (
              <div className="text-[12.5px] text-accent mt-0.5">{t("gp.returningBanner")}</div>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label={t("action.close")}
            className="w-8 h-8 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2 shrink-0"
          >
            <IconX size={18} />
          </button>
        </header>

        {/* الإحصاءات */}
        {g && (
          <div className="shrink-0 px-5 py-3 border-b border-line grid grid-cols-4 gap-3 bg-surface-2/50">
            <Stat label={t("guest.stays")} value={String(g.total_stays)} />
            <Stat label={t("guest.nights")} value={String(g.total_nights)} />
            <Stat label={t("guest.revenue")} value={money(g.total_revenue, 0)} />
            <Stat
              label={t("guest.lastStay")}
              value={g.last_stay_date ? formatDate(g.last_stay_date, locale) : "—"}
              small
            />
          </div>
        )}

        <div className="flex-1 overflow-y-auto min-h-0 p-5 flex flex-col gap-5">
          {isLoading && <Loading />}
          {isError && <ErrorState onRetry={() => refetch()} />}

          {banner && (
            <div
              className={cx(
                "rounded-[6px] px-3.5 py-2.5 text-[13px] border",
                banner.tone === "good"
                  ? "border-good/40 bg-good/10 text-good"
                  : "border-bad/40 bg-bad/10 text-bad",
              )}
            >
              {banner.text}
            </div>
          )}

          {g && (
            <>
              {/* الهوية */}
              <Section title={t("gp.identity")}>
                <div className="grid grid-cols-2 gap-3">
                  <Field label={t("book.idType")}>
                    {editing ? (
                      <select
                        className={inputClass}
                        value={form.id_type}
                        onChange={(e) => setForm({ ...form, id_type: e.target.value })}
                      >
                        {ID_TYPES.map((k) => (
                          <option key={k} value={k}>
                            {t(`id.${k}`, k)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Value>{t(`id.${g.id_type}`, g.id_type)}</Value>
                    )}
                  </Field>
                  <Field label={t("book.idNumber")}>
                    {editing ? (
                      <input
                        className={`${inputClass} num`}
                        value={form.id_number}
                        onChange={(e) => setForm({ ...form, id_number: e.target.value })}
                      />
                    ) : (
                      <Value mono>{g.id_number ?? "—"}</Value>
                    )}
                  </Field>
                  <Field label={t("book.nationality")}>
                    {editing ? (
                      <input
                        className={inputClass}
                        value={form.nationality}
                        onChange={(e) => setForm({ ...form, nationality: e.target.value })}
                      />
                    ) : (
                      <Value mono>{g.nationality}</Value>
                    )}
                  </Field>
                  <Field label={t("guest.city")}>
                    {editing ? (
                      <input
                        className={inputClass}
                        value={form.city}
                        onChange={(e) => setForm({ ...form, city: e.target.value })}
                      />
                    ) : (
                      <Value>{g.city ?? "—"}</Value>
                    )}
                  </Field>
                </div>
              </Section>

              {/* التواصل */}
              <Section title={t("gp.contact")}>
                <div className="grid grid-cols-2 gap-3">
                  <Field label={t("guest.phone")}>
                    {editing ? (
                      <input
                        className={`${inputClass} num`}
                        value={form.phone}
                        onChange={(e) => setForm({ ...form, phone: e.target.value })}
                      />
                    ) : (
                      <Value mono>{g.phone ?? "—"}</Value>
                    )}
                  </Field>
                  <Field label="Email">
                    {editing ? (
                      <input
                        className={inputClass}
                        value={form.email}
                        onChange={(e) => setForm({ ...form, email: e.target.value })}
                      />
                    ) : (
                      <Value>{g.email ?? "—"}</Value>
                    )}
                  </Field>
                </div>
                <div className="flex flex-wrap gap-4 mt-1">
                  <Check
                    label={t("gp.whatsapp")}
                    checked={editing ? form.whatsapp_opt_in : g.whatsapp_opt_in}
                    disabled={!editing}
                    onChange={(v) => setForm({ ...form, whatsapp_opt_in: v })}
                  />
                  <Check
                    label={t("gp.markVip")}
                    checked={editing ? form.is_vip : g.is_vip}
                    disabled={!editing}
                    onChange={(v) => setForm({ ...form, is_vip: v })}
                  />
                </div>
              </Section>

              {/* التفضيلات */}
              <Section title={t("gp.prefs")} hint={t("gp.prefsHint")}>
                <PairEditor
                  pairs={prefs}
                  setPairs={setPrefs}
                  editing={editing}
                  suggestions={PREF_SUGGESTIONS}
                  emptyText={t("gp.noPrefs")}
                />
              </Section>

              {/* المناسبات */}
              <Section title={t("gp.occasions")}>
                <PairEditor
                  pairs={occasions}
                  setPairs={setOccasions}
                  editing={editing}
                  suggestions={[
                    ["عيد الجواز", ""],
                    ["عيد ميلاد", ""],
                  ]}
                  emptyText={t("state.empty")}
                />
              </Section>

              <Section title={t("gp.dietary")}>
                {editing ? (
                  <input
                    className={inputClass}
                    value={form.dietary_notes}
                    onChange={(e) => setForm({ ...form, dietary_notes: e.target.value })}
                  />
                ) : (
                  <Value>{form.dietary_notes || "—"}</Value>
                )}
              </Section>

              <Section title={t("gp.notes")}>
                {editing ? (
                  <input
                    className={inputClass}
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  />
                ) : (
                  <Value>{form.notes || "—"}</Value>
                )}
              </Section>
            </>
          )}
        </div>

        {g && canEdit && (
          <footer className="shrink-0 px-5 py-3.5 border-t border-line flex items-center gap-2">
            {editing ? (
              <>
                <Button
                  variant="primary"
                  disabled={save.isPending}
                  onClick={() => save.mutate()}
                >
                  {save.isPending ? "…" : t("action.save")}
                </Button>
                <Button variant="ghost" onClick={() => setEditing(false)}>
                  {t("action.cancel")}
                </Button>
              </>
            ) : (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                {t("gp.edit")}
              </Button>
            )}
            <div className="flex-1" />
            <Button variant="ghost" onClick={onClose}>
              {t("action.close")}
            </Button>
          </footer>
        )}
      </aside>
    </div>
  );
}

/* ─────────────────────────────────────────────────── مساعدات */
function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="text-[13px] font-bold text-muted mb-2">{title}</h3>
      {hint && <p className="text-[11.5px] text-muted mb-2 leading-relaxed">{hint}</p>}
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] text-muted">{label}</span>
      {children}
    </label>
  );
}

function Value({ children, mono }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <span className={cx("text-[13.5px] font-bold h-10 flex items-center", mono && "num")}>
      {children}
    </span>
  );
}

function Stat({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <div>
      <div className="text-[11px] text-muted">{label}</div>
      <div className={cx("num font-bold leading-tight", small ? "text-[12.5px]" : "text-[17px]")}>
        {value}
      </div>
    </div>
  );
}

function Check({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      className={cx(
        "flex items-center gap-2 text-[13px]",
        disabled ? "text-ink-2" : "text-ink cursor-pointer",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

function PairEditor({
  pairs,
  setPairs,
  editing,
  suggestions,
  emptyText,
}: {
  pairs: Pair[];
  setPairs: (p: Pair[]) => void;
  editing: boolean;
  suggestions: [string, string][];
  emptyText: string;
}) {
  const { t } = useI18n();

  if (!editing) {
    if (pairs.length === 0) return <span className="text-[13px] text-muted">{emptyText}</span>;
    return (
      <div className="flex flex-wrap gap-1.5">
        {pairs.map((p) => (
          <span
            key={p.key}
            className="text-[12px] rounded-full bg-surface-2 px-2.5 py-1 text-ink-2"
          >
            <span className="font-bold text-ink">{p.key}</span>
            {p.value && <> · {p.value}</>}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {pairs.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            className={`${inputClass} flex-1`}
            placeholder={t("gp.prefKey")}
            value={p.key}
            onChange={(e) => {
              const next = [...pairs];
              next[i] = { ...next[i], key: e.target.value };
              setPairs(next);
            }}
          />
          <input
            className={`${inputClass} flex-1`}
            placeholder={t("gp.prefValue")}
            value={p.value}
            onChange={(e) => {
              const next = [...pairs];
              next[i] = { ...next[i], value: e.target.value };
              setPairs(next);
            }}
          />
          <button
            onClick={() => setPairs(pairs.filter((_, x) => x !== i))}
            aria-label={t("folio.void")}
            className="w-8 h-8 grid place-items-center rounded-[6px] text-muted hover:text-bad hover:bg-bad/10 shrink-0"
          >
            <IconTrash size={15} />
          </button>
        </div>
      ))}

      <div className="flex flex-wrap gap-1.5 items-center">
        <button
          onClick={() => setPairs([...pairs, { key: "", value: "" }])}
          className="flex items-center gap-1 text-[12.5px] font-bold text-accent"
        >
          <IconPlus size={14} />
          {t("gp.addPref")}
        </button>
        {suggestions
          .filter(([k]) => !pairs.some((p) => p.key === k))
          .map(([k, v]) => (
            <button
              key={k}
              onClick={() => setPairs([...pairs, { key: k, value: v }])}
              className="text-[11.5px] rounded-full border border-line px-2 py-0.5 text-ink-2 hover:bg-surface-2"
            >
              + {k}
            </button>
          ))}
      </div>
    </div>
  );
}
