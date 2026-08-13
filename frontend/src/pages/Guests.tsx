/** النزلاء — قايمة بترقيم بالمؤشّر (keyset)، فالصفحة رقم 900 بتفتح زي الأولى. */

import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { get, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatDate, money } from "@/lib/format";
import type { GuestPage } from "@/lib/types";
import PageHeader from "@/components/PageHeader";
import GuestProfile from "@/components/GuestProfile";
import { Button, EmptyState, ErrorState, Loading, cx } from "@/components/ui";
import { IconSearch } from "@/components/Icons";

export default function Guests() {
  const { t, locale } = useI18n();
  const [term, setTerm] = useState("");
  const [returningOnly, setReturningOnly] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  const q = useInfiniteQuery({
    queryKey: ["guests", term, returningOnly],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      get<GuestPage>(
        `/guests${qs({
          search: term,
          returning_only: returningOnly || undefined,
          limit: 50,
          cursor: pageParam ?? undefined,
        })}`,
      ),
    getNextPageParam: (last) => (last.has_more ? last.next_cursor : undefined),
  });

  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      <PageHeader title={t("guest.title")} subtitle={`${rows.length}+`}>
        <label className="relative flex items-center">
          <span className="absolute start-0 ps-2.5 text-muted pointer-events-none">
            <IconSearch size={16} />
          </span>
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder={t("guest.search")}
            className="h-9 w-[300px] ps-8 pe-3 rounded-[6px] bg-surface border border-line-strong text-[13px] outline-none focus:border-accent"
          />
        </label>
        <button
          onClick={() => setReturningOnly((v) => !v)}
          className={cx(
            "h-9 px-3 rounded-[6px] border text-[13px] font-bold",
            returningOnly
              ? "bg-accent text-accent-ink border-accent"
              : "border-line-strong text-ink-2 hover:bg-surface-2",
          )}
        >
          {t("guest.returningOnly")}
        </button>
      </PageHeader>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {q.isLoading && <Loading />}
        {q.isError && <ErrorState onRetry={() => q.refetch()} />}
        {!q.isLoading && rows.length === 0 && <EmptyState />}

        {rows.length > 0 && (
          <table className="w-full border-collapse text-[13px]">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr className="text-muted text-[12px]">
                <Th className="text-start ps-5">{t("res.guest")}</Th>
                <Th className="text-start">{t("guest.phone")}</Th>
                <Th className="text-start">{t("guest.city")}</Th>
                <Th className="text-end">{t("guest.stays")}</Th>
                <Th className="text-end">{t("guest.nights")}</Th>
                <Th className="text-end">{t("guest.revenue")}</Th>
                <Th className="text-end pe-5">{t("guest.lastStay")}</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((g) => (
                <tr
                  key={g.id}
                  onClick={() => setSelected(g.id)}
                  className="cursor-pointer hover:bg-surface-2/70"
                >
                  <td className="px-3 ps-5 py-2.5 border-b border-line">
                    <div className="flex items-center gap-2">
                      <span className="font-bold">{g.full_name}</span>
                      {g.is_vip && (
                        <span className="text-[10.5px] font-bold rounded-full bg-gold-soft text-gold px-1.5">
                          VIP
                        </span>
                      )}
                      {g.is_blacklisted && (
                        <span className="text-[10.5px] font-bold rounded-full bg-bad/15 text-bad px-1.5">
                          {t("guest.blacklisted")}
                        </span>
                      )}
                      {g.total_stays > 1 && (
                        <span className="text-[10.5px] font-bold rounded-full bg-accent-soft text-accent px-1.5">
                          {t("folio.returning")}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="num px-3 py-2.5 border-b border-line text-ink-2">
                    {g.phone ?? "—"}
                  </td>
                  <td className="px-3 py-2.5 border-b border-line text-ink-2">{g.city ?? "—"}</td>
                  <td className="num text-end px-3 py-2.5 border-b border-line font-bold">
                    {g.total_stays}
                  </td>
                  <td className="num text-end px-3 py-2.5 border-b border-line text-ink-2">
                    {g.total_nights}
                  </td>
                  <td className="num text-end px-3 py-2.5 border-b border-line font-bold">
                    {money(g.total_revenue, 0)}
                  </td>
                  <td className="num text-end px-3 pe-5 py-2.5 border-b border-line text-muted">
                    {g.last_stay_date ? formatDate(g.last_stay_date, locale) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {q.hasNextPage && (
          <div className="p-4 flex justify-center">
            <Button onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>
              {q.isFetchingNextPage ? "…" : t("guest.loadMore")}
            </Button>
          </div>
        )}
      </div>

      <GuestProfile guestId={selected} onClose={() => setSelected(null)} />
    </>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}
