/** المخازن — الأرصدة والوصفات والمشتريات وتقرير الفرق. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, get, post, qs } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { formatDate, money } from "@/lib/format";
import type {
  PurchaseBoard,
  RecipeOut,
  StockBoard,
  StockMovementOut,
  VarianceReport,
} from "@/lib/types";
import PageHeader, { StatStrip } from "@/components/PageHeader";
import ReceivePurchase from "@/components/ReceivePurchase";
import { Button, Card, ErrorState, Loading, Pill, cx, inputClass } from "@/components/ui";
import { IconWarning } from "@/components/Icons";

type Tab = "levels" | "variance" | "purchases" | "recipes" | "ledger";

const TABS: Tab[] = ["levels", "variance", "purchases", "recipes", "ledger"];

const MOVE_TONE: Record<string, "good" | "bad" | "gold" | "muted"> = {
  PURCHASE: "good",
  TRANSFER_IN: "good",
  ISSUE: "muted",
  TRANSFER_OUT: "muted",
  WASTE: "bad",
  ADJUSTMENT: "gold",
  RETURN: "gold",
};

const PO_TONE: Record<string, "muted" | "gold" | "accent" | "good" | "bad"> = {
  DRAFT: "muted",
  SENT: "gold",
  PARTIAL: "accent",
  RECEIVED: "good",
  CANCELLED: "bad",
};

export default function Stock() {
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const qc = useQueryClient();

  const [tab, setTab] = useState<Tab>("levels");
  const [search, setSearch] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [receiving, setReceiving] = useState<number | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const board = useQuery({
    queryKey: ["stock", search, lowOnly],
    queryFn: () =>
      get<StockBoard>(`/stock${qs({ search: search || undefined, low_only: lowOnly || undefined })}`),
  });

  const variance = useQuery({
    queryKey: ["stock-variance"],
    queryFn: () => get<VarianceReport>("/stock/variance?days=90"),
    enabled: tab === "variance",
  });

  const purchases = useQuery({
    queryKey: ["stock-purchases"],
    queryFn: () => get<PurchaseBoard>("/stock/purchases?limit=40"),
    enabled: tab === "purchases" || tab === "levels",
  });

  const recipes = useQuery({
    queryKey: ["stock-recipes"],
    queryFn: () => get<RecipeOut[]>("/stock/recipes"),
    enabled: tab === "recipes",
  });

  const ledger = useQuery({
    queryKey: ["stock-ledger"],
    queryFn: () => get<StockMovementOut[]>("/stock/movements?days=30&limit=120"),
    enabled: tab === "ledger",
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["stock"] });
    qc.invalidateQueries({ queryKey: ["stock-variance"] });
    qc.invalidateQueries({ queryKey: ["stock-purchases"] });
    qc.invalidateQueries({ queryKey: ["stock-recipes"] });
    qc.invalidateQueries({ queryKey: ["stock-ledger"] });
  }

  const recost = useMutation({
    mutationFn: () => post<{ message_ar: string }>("/stock/recipes/refresh-costs", {}),
    onSuccess: (r) => {
      setFlash(r.message_ar);
      refresh();
    },
    onError: (err) => setFlash(err instanceof ApiError ? err.text(locale) : t("state.error")),
  });

  const b = board.data;
  const canManage = can("stock.manage");
  const cur = locale === "ar" ? "ج.م" : "EGP";

  return (
    <>
      <PageHeader title={t("st.title")} subtitle={t("st.subtitle")}>
        {b && (
          <StatStrip
            items={[
              { label: t("st.value"), value: money(b.total_value, 0) },
              { label: t("st.items"), value: String(b.total_items) },
              {
                label: t("st.lowStock"),
                value: String(b.low_stock),
                tone: b.low_stock > 0 ? "warn" : "good",
              },
              ...(purchases.data
                ? [
                    {
                      label: t("st.monthSpend"),
                      value: money(purchases.data.spend_this_month, 0),
                    },
                  ]
                : []),
            ]}
          />
        )}
        {canManage && tab === "recipes" && (
          <Button disabled={recost.isPending} onClick={() => recost.mutate()}>
            {t("st.refreshCosts")}
          </Button>
        )}
      </PageHeader>

      <div className="flex-1 min-h-0 overflow-y-auto p-5 flex flex-col gap-4 max-w-[1500px]">
        {board.isLoading && <Loading />}
        {board.isError && <ErrorState onRetry={() => board.refetch()} />}

        {flash && (
          <div className="rounded-[6px] border border-good/40 bg-good/10 px-4 py-3 text-[13px] text-good">
            {flash}
          </div>
        )}

        {b && b.negative > 0 && (
          <div className="rounded-[6px] border border-bad/40 bg-bad/10 px-4 py-3 text-[13px] text-bad flex items-center gap-2">
            <IconWarning size={16} />
            {t("st.negativeAlert").replace("{n}", String(b.negative))}
          </div>
        )}

        {/* التبويبات */}
        <div className="flex items-center rounded-[6px] border border-line-strong overflow-hidden w-fit">
          {TABS.map((x) => (
            <button
              key={x}
              onClick={() => setTab(x)}
              className={cx(
                "h-9 px-4 text-[13px] font-bold border-e border-line-strong last:border-e-0",
                tab === x ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-surface-2",
              )}
            >
              {t(`st.tab.${x}`)}
            </button>
          ))}
        </div>

        {/* ── الأرصدة */}
        {tab === "levels" && b && (
          <Card
            title={t("st.tab.levels")}
            padded={false}
            action={
              <div className="flex items-center gap-2">
                <input
                  className={cx(inputClass, "h-9 w-[180px] text-[13px]")}
                  placeholder={t("st.searchHint")}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <label className="flex items-center gap-1.5 text-[12.5px] font-bold text-ink-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={lowOnly}
                    onChange={(e) => setLowOnly(e.target.checked)}
                  />
                  {t("st.lowOnly")}
                </label>
              </div>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead className="sticky top-0 bg-surface">
                  <tr className="text-muted text-[12px]">
                    <Th className="text-start ps-5">{t("st.item")}</Th>
                    <Th className="text-start">{t("st.category")}</Th>
                    <Th className="text-end">{t("st.onHand")}</Th>
                    <Th className="text-end">{t("st.reorderAt")}</Th>
                    <Th className="text-end">{t("st.avgCost")}</Th>
                    <Th className="text-end pe-5">{t("st.value")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {b.items.map((i) => (
                    <tr key={i.id} className={cx("hover:bg-surface-2/50", i.is_low && "bg-warn/5")}>
                      <td className="px-3 ps-5 py-2.5 border-b border-line">
                        <span className="font-bold">{i.name_ar}</span>
                        {i.is_critical && (
                          <span className="text-[10.5px] text-warn ms-1.5 font-bold">
                            {t("st.critical")}
                          </span>
                        )}
                        <div className="num text-[11px] text-muted">{i.code}</div>
                      </td>
                      <td className="px-3 py-2.5 border-b border-line text-ink-2">
                        {i.category_ar}
                      </td>
                      <td
                        className={cx(
                          "num text-end px-3 py-2.5 border-b border-line font-bold",
                          Number(i.on_hand) < 0 ? "text-bad" : i.is_low ? "text-warn" : "",
                        )}
                      >
                        {Number(i.on_hand).toLocaleString("en-US", {
                          maximumFractionDigits: 2,
                        })}
                        <span className="text-[11px] text-muted ms-1">
                          {t(`st.unit.${i.unit}`, i.unit)}
                        </span>
                      </td>
                      <td className="num text-end px-3 py-2.5 border-b border-line text-muted">
                        {Number(i.reorder_level) > 0
                          ? Number(i.reorder_level).toLocaleString("en-US")
                          : "—"}
                      </td>
                      <td className="num text-end px-3 py-2.5 border-b border-line">
                        {money(i.average_cost, 0)}
                      </td>
                      <td className="num text-end px-3 pe-5 py-2.5 border-b border-line font-bold">
                        {money(i.value, 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {/* ── الفرق */}
        {tab === "variance" && (
          <Card
            title={t("st.tab.variance")}
            padded={false}
            action={
              variance.data && (
                <span className="num text-[12.5px] text-muted">
                  {formatDate(variance.data.start_date, locale)} →{" "}
                  {formatDate(variance.data.end_date, locale)}
                </span>
              )
            }
          >
            {variance.isLoading && <Loading />}
            <p className="text-[12.5px] text-muted leading-relaxed px-5 py-3 border-b border-line">
              {t("st.varianceHint")}
            </p>
            {variance.data?.was_clamped && (
              <p className="text-[12px] text-warn px-5 py-2 border-b border-line">
                {t("st.clamped").replace(
                  "{d}",
                  formatDate(variance.data.tracking_since ?? "", locale),
                )}
              </p>
            )}
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead className="sticky top-0 bg-surface">
                  <tr className="text-muted text-[12px]">
                    <Th className="text-start ps-5">{t("st.item")}</Th>
                    <Th className="text-end">{t("st.theoretical")}</Th>
                    <Th className="text-end">{t("st.actual")}</Th>
                    <Th className="text-end">{t("st.waste")}</Th>
                    <Th className="text-end">{t("st.gap")}</Th>
                    <Th className="text-end pe-5">{t("st.impact")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {variance.data?.rows.map((r) => {
                    const gap = Number(r.variance);
                    return (
                      <tr key={r.stock_item_id} className="hover:bg-surface-2/50">
                        <td className="px-3 ps-5 py-2.5 border-b border-line font-bold">
                          {r.item_name_ar}
                        </td>
                        <td className="num text-end px-3 py-2.5 border-b border-line text-muted">
                          {Number(r.theoretical).toFixed(2)}
                        </td>
                        <td className="num text-end px-3 py-2.5 border-b border-line">
                          {Number(r.actual).toFixed(2)}
                        </td>
                        <td className="num text-end px-3 py-2.5 border-b border-line text-warn">
                          {Number(r.waste) > 0 ? Number(r.waste).toFixed(2) : "—"}
                        </td>
                        <td
                          className={cx(
                            "num text-end px-3 py-2.5 border-b border-line font-bold",
                            gap > 0 ? "text-bad" : gap < 0 ? "text-good" : "",
                          )}
                        >
                          {gap > 0 ? "+" : ""}
                          {gap.toFixed(2)}
                        </td>
                        <td
                          className={cx(
                            "num text-end px-3 pe-5 py-2.5 border-b border-line font-bold",
                            Number(r.cost_impact) > 0 && "text-bad",
                          )}
                        >
                          {money(r.cost_impact, 0)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                {variance.data && (
                  <tfoot>
                    <tr className="bg-surface-2">
                      <td className="px-5 py-2.5 font-bold" colSpan={5}>
                        {t("st.totalImpact")}
                        {variance.data.uncovered_items > 0 && (
                          <span className="text-[11.5px] text-warn font-normal ms-3">
                            {t("st.uncovered").replace(
                              "{n}",
                              String(variance.data.uncovered_items),
                            )}
                          </span>
                        )}
                      </td>
                      <td className="num text-end px-5 py-2.5 font-bold text-accent">
                        {money(variance.data.total_impact, 0)} <span className="text-[11px]">{cur}</span>
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </Card>
        )}

        {/* ── المشتريات */}
        {tab === "purchases" && (
          <Card title={t("st.tab.purchases")} padded={false}>
            {purchases.isLoading && <Loading />}
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead className="sticky top-0 bg-surface">
                  <tr className="text-muted text-[12px]">
                    <Th className="text-start ps-5">{t("st.poNumber")}</Th>
                    <Th className="text-start">{t("st.supplier")}</Th>
                    <Th className="text-start">{t("res.status")}</Th>
                    <Th className="text-end">{t("st.lines")}</Th>
                    <Th className="text-end">{t("res.grandTotal")}</Th>
                    <Th className="text-start">{t("st.orderDate")}</Th>
                    <Th className="text-end pe-5" />
                  </tr>
                </thead>
                <tbody>
                  {purchases.data?.orders.map((o) => (
                    <tr key={o.id} className="hover:bg-surface-2/50">
                      <td className="num px-3 ps-5 py-2.5 border-b border-line font-bold">
                        {o.number}
                      </td>
                      <td className="px-3 py-2.5 border-b border-line">{o.supplier_name_ar}</td>
                      <td className="px-3 py-2.5 border-b border-line">
                        <Pill tone={PO_TONE[o.status] ?? "muted"}>{t(`st.po.${o.status}`)}</Pill>
                      </td>
                      <td className="num text-end px-3 py-2.5 border-b border-line text-muted">
                        {o.lines.length}
                      </td>
                      <td className="num text-end px-3 py-2.5 border-b border-line font-bold">
                        {money(o.grand_total, 0)}
                      </td>
                      <td className="num px-3 py-2.5 border-b border-line text-muted">
                        {formatDate(o.order_date, locale)}
                      </td>
                      <td className="text-end px-3 pe-5 py-2.5 border-b border-line">
                        {canManage && ["SENT", "PARTIAL"].includes(o.status) && (
                          <Button size="sm" onClick={() => setReceiving(o.id)}>
                            {t("st.receive")}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {/* ── الوصفات */}
        {tab === "recipes" && (
          <Card title={t("st.tab.recipes")} padded={false}>
            {recipes.isLoading && <Loading />}
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead className="sticky top-0 bg-surface">
                  <tr className="text-muted text-[12px]">
                    <Th className="text-start ps-5">{t("st.dish")}</Th>
                    <Th className="text-start">{t("st.ingredients")}</Th>
                    <Th className="text-end">{t("st.dishCost")}</Th>
                    <Th className="text-end">{t("res.price")}</Th>
                    <Th className="text-end pe-5">{t("st.margin")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {recipes.data?.map((r) => (
                    <tr key={r.menu_item_id} className="hover:bg-surface-2/50 align-top">
                      <td className="px-3 ps-5 py-2.5 border-b border-line font-bold">
                        {r.menu_item_name_ar}
                      </td>
                      <td className="px-3 py-2.5 border-b border-line text-[12px] text-ink-2">
                        {r.lines
                          .map(
                            (l) =>
                              `${l.item_name_ar} ${Number(l.gross_quantity).toFixed(3)}`,
                          )
                          .join(" · ")}
                      </td>
                      <td className="num text-end px-3 py-2.5 border-b border-line">
                        {money(r.cost, 2)}
                      </td>
                      <td className="num text-end px-3 py-2.5 border-b border-line">
                        {money(r.menu_item_price, 0)}
                      </td>
                      <td
                        className={cx(
                          "num text-end px-3 pe-5 py-2.5 border-b border-line font-bold",
                          Number(r.margin_percent) < 50 ? "text-warn" : "text-good",
                        )}
                      >
                        {Number(r.margin_percent).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {/* ── كشف الحركة */}
        {tab === "ledger" && (
          <Card title={t("st.tab.ledger")} padded={false}>
            {ledger.isLoading && <Loading />}
            <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead className="sticky top-0 bg-surface">
                  <tr className="text-muted text-[12px]">
                    <Th className="text-start ps-5">{t("rep.date")}</Th>
                    <Th className="text-start">{t("st.item")}</Th>
                    <Th className="text-start">{t("st.warehouse")}</Th>
                    <Th className="text-start">{t("st.moveKind")}</Th>
                    <Th className="text-end">{t("pos.qty")}</Th>
                    <Th className="text-end">{t("st.balanceAfter")}</Th>
                    <Th className="text-start pe-5">{t("ch.reason")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.data?.map((m) => {
                    const out = ["ISSUE", "WASTE", "TRANSFER_OUT", "RETURN"].includes(m.kind);
                    return (
                      <tr key={m.id} className="hover:bg-surface-2/50">
                        <td className="num px-3 ps-5 py-2 border-b border-line text-muted">
                          {formatDate(m.business_date, locale)}
                        </td>
                        <td className="px-3 py-2 border-b border-line">{m.item_name_ar}</td>
                        <td className="px-3 py-2 border-b border-line text-ink-2">
                          {m.warehouse_name_ar}
                        </td>
                        <td className="px-3 py-2 border-b border-line">
                          <Pill tone={MOVE_TONE[m.kind] ?? "muted"}>
                            {t(`st.move.${m.kind}`)}
                          </Pill>
                        </td>
                        <td
                          className={cx(
                            "num text-end px-3 py-2 border-b border-line font-bold",
                            out ? "text-bad" : "text-good",
                          )}
                        >
                          {out ? "−" : "+"}
                          {Number(m.quantity).toFixed(3)}
                        </td>
                        <td className="num text-end px-3 py-2 border-b border-line text-muted">
                          {Number(m.balance_after).toFixed(2)}
                        </td>
                        <td className="px-3 pe-5 py-2 border-b border-line text-[12px] text-muted truncate max-w-[220px]">
                          {m.reason ?? "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        <p className="text-[12px] text-muted leading-relaxed max-w-[80ch]">{t("st.note")}</p>
      </div>

      {receiving !== null && purchases.data && (
        <ReceivePurchase
          order={purchases.data.orders.find((o) => o.id === receiving)!}
          onClose={() => setReceiving(null)}
          onDone={() => {
            setReceiving(null);
            refresh();
          }}
        />
      )}
    </>
  );
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cx("font-bold px-3 py-2.5 border-b border-line", className)}>{children}</th>
  );
}
