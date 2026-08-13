/** الهاوس كيبينج — حالة كل وحدة، وتغييرها بضغطة واحدة. */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, get } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { HK_COLOR } from "@/lib/status";
import type { HousekeepingBoard, UnitStatus } from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import { ErrorState, Loading, cx } from "@/components/ui";

const HK_STATES = ["DIRTY", "CLEANING", "CLEAN", "INSPECTED"] as const;

type Filter = "all" | "priority" | (typeof HK_STATES)[number];

export default function Housekeeping() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [filter, setFilter] = useState<Filter>("all");
  const [toast, setToast] = useState<string | null>(null);

  const board = useQuery({
    queryKey: ["housekeeping"],
    queryFn: () => get<HousekeepingBoard>("/housekeeping"),
    refetchInterval: 60_000,
  });

  const setStatus = useMutation({
    mutationFn: (v: { unitId: number; status: string }) =>
      api<UnitStatus>(`/units/${v.unitId}/status`, {
        method: "PATCH",
        body: { housekeeping_status: v.status },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["housekeeping"] }),
    onError: (err) =>
      setToast(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const units = board.data?.units ?? [];

  const shown = useMemo(() => {
    if (filter === "all") return units;
    if (filter === "priority") return units.filter((u) => u.departs_today && u.arrives_today);
    return units.filter((u) => u.housekeeping_status === filter);
  }, [units, filter]);

  // التجميع بالمنطقة — ده اللي السوبرفايزر بيمشي بيه فعلياً في القرية
  const byZone = useMemo(() => {
    const map = new Map<string, UnitStatus[]>();
    for (const u of shown) {
      const zone = (locale === "ar" ? u.zone_ar : u.zone_en) || "—";
      const list = map.get(zone);
      if (list) list.push(u);
      else map.set(zone, [u]);
    }
    return [...map.entries()];
  }, [shown, locale]);

  const b = board.data;
  const priorityCount = units.filter((u) => u.departs_today && u.arrives_today).length;
  const canEdit = can("housekeeping.update");

  return (
    <>
      <PageHeader
        title={t("hk.title")}
        subtitle={b ? formatDate(b.business_date, locale) : "—"}
      >
        {b && (
          <StatStrip
            items={[
              { label: t("hk.DIRTY"), value: String(b.dirty), tone: b.dirty > 0 ? "warn" : "ink" },
              { label: t("hk.CLEANING"), value: String(b.cleaning), tone: "accent" },
              { label: t("hk.CLEAN"), value: String(b.clean), tone: "good" },
              { label: t("hk.INSPECTED"), value: String(b.inspected) },
              { label: t("hk.outOfOrder"), value: String(b.out_of_order), tone: b.out_of_order > 0 ? "bad" : "ink" },
            ]}
          />
        )}
      </PageHeader>

      {/* الفلاتر */}
      <div className="shrink-0 px-5 py-2.5 border-b border-line bg-surface flex items-center gap-1.5 flex-wrap">
        <Chip active={filter === "all"} onClick={() => setFilter("all")}>
          {t("hk.allUnits")} <span className="num">{units.length}</span>
        </Chip>
        <Chip
          active={filter === "priority"}
          onClick={() => setFilter("priority")}
          tone="bad"
          title={t("hk.priorityHint")}
        >
          {t("hk.priority")} <span className="num">{priorityCount}</span>
        </Chip>
        {HK_STATES.map((s) => (
          <Chip key={s} active={filter === s} onClick={() => setFilter(s)} dot={HK_COLOR[s]}>
            {t(`hk.${s}`)}{" "}
            <span className="num">
              {units.filter((u) => u.housekeeping_status === s).length}
            </span>
          </Chip>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {board.isLoading && <Loading />}
        {board.isError && <ErrorState onRetry={() => board.refetch()} />}

        <div className="flex flex-col gap-5">
          {byZone.map(([zone, list]) => (
            <section key={zone}>
              <h2 className="text-[13px] font-bold text-muted mb-2">
                {zone} · <span className="num">{list.length}</span>
              </h2>
              <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(190px,1fr))]">
                {list.map((u) => (
                  <UnitCard
                    key={u.id}
                    unit={u}
                    canEdit={canEdit && u.condition === "OPERATIONAL"}
                    busy={setStatus.isPending}
                    onSet={(status) => setStatus.mutate({ unitId: u.id, status })}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>

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

function UnitCard({
  unit,
  canEdit,
  busy,
  onSet,
}: {
  unit: UnitStatus;
  canEdit: boolean;
  busy: boolean;
  onSet: (status: string) => void;
}) {
  const { t } = useI18n();
  const ooo = unit.condition !== "OPERATIONAL";
  const priority = unit.departs_today && unit.arrives_today;

  return (
    <div
      className={cx(
        "border rounded-[8px] p-2.5 flex flex-col gap-2 bg-surface",
        priority ? "border-bad/50" : "border-line",
        ooo && "hatched",
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{ background: HK_COLOR[unit.housekeeping_status] }}
        />
        <span className={cx("num text-[15px] font-bold", ooo && "line-through text-muted")}>
          {unit.label}
        </span>
        <span className="text-[11px] text-muted truncate ms-auto">{unit.category_name_ar}</span>
      </div>

      <div className="flex items-center gap-1 flex-wrap min-h-[18px]">
        {unit.is_occupied && (
          <Tag tone="accent">{t("hk.occupied")}</Tag>
        )}
        {unit.departs_today && <Tag tone="warn">{t("hk.departsToday")}</Tag>}
        {unit.arrives_today && <Tag tone="good">{t("hk.arrivesToday")}</Tag>}
        {ooo && <Tag tone="bad">{t(`cond.${unit.condition}`, unit.condition)}</Tag>}
      </div>

      {canEdit && (
        <div className="grid grid-cols-4 gap-1">
          {HK_STATES.map((s) => (
            <button
              key={s}
              disabled={busy || unit.housekeeping_status === s}
              onClick={() => onSet(s)}
              title={t(`hk.${s}`)}
              aria-label={t(`hk.${s}`)}
              className={cx(
                "h-7 rounded-[4px] border text-[10.5px] font-bold transition-colors",
                unit.housekeeping_status === s
                  ? "text-white border-transparent"
                  : "border-line text-ink-2 hover:bg-surface-2",
              )}
              style={
                unit.housekeeping_status === s ? { background: HK_COLOR[s] } : undefined
              }
            >
              {t(`hk.${s}`).slice(0, 6)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Tag({ children, tone }: { children: React.ReactNode; tone: string }) {
  const map: Record<string, string> = {
    accent: "bg-accent-soft text-accent",
    warn: "bg-warn/15 text-warn",
    good: "bg-good/15 text-good",
    bad: "bg-bad/15 text-bad",
  };
  return (
    <span className={cx("text-[10px] font-bold rounded-full px-1.5 py-0.5", map[tone])}>
      {children}
    </span>
  );
}

function Chip({
  active,
  onClick,
  children,
  dot,
  tone,
  title,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  dot?: string;
  tone?: "bad";
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={cx(
        "h-8 px-3 rounded-full border text-[12.5px] font-bold flex items-center gap-1.5",
        active
          ? "bg-accent text-accent-ink border-accent"
          : tone === "bad"
            ? "border-bad/40 text-bad hover:bg-bad/10"
            : "border-line text-ink-2 hover:bg-surface-2",
      )}
    >
      {dot && !active && (
        <span className="w-2 h-2 rounded-full" style={{ background: dot }} />
      )}
      {children}
    </button>
  );
}
