/**
 * CommoditiesPanel - top 4 MCX commodities with cleaner conviction display.
 */
import { useEffect, useState } from "react";
import clsx from "clsx";

import { analyticsApi } from "../lib/api";

const SYMBOLS = ["CRUDEOIL", "NATGAS", "GOLD", "SILVER"];

const SIG_META = {
  LONG: { label: "LONG", icon: "▲", color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/30" },
  SHORT: { label: "SHORT", icon: "▼", color: "text-red-400", bg: "bg-red-500/15", border: "border-red-500/30" },
  "HOLD LONG": { label: "HOLD LONG", icon: "HL", color: "text-cyan-300", bg: "bg-cyan-500/15", border: "border-cyan-500/30" },
  "HOLD SHORT": { label: "HOLD SHORT", icon: "HS", color: "text-cyan-300", bg: "bg-cyan-500/15", border: "border-cyan-500/30" },
  "EXIT LONG": { label: "EXIT LONG", icon: "XL", color: "text-amber-300", bg: "bg-amber-500/15", border: "border-amber-500/30" },
  "EXIT SHORT": { label: "EXIT SHORT", icon: "XS", color: "text-amber-300", bg: "bg-amber-500/15", border: "border-amber-500/30" },
  WAIT: { label: "WAIT", icon: "◆", color: "text-slate-400", bg: "bg-slate-500/10", border: "border-surface-border" },
};

function fmt(value, decimals = 2) {
  if (value == null) return "—";
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return "—";
  return parsed.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function Badge({ signal }) {
  const meta = SIG_META[signal] ?? SIG_META.WAIT;
  return (
    <span className={clsx("rounded-full px-2.5 py-1 text-[11px] font-bold", meta.bg, meta.color)}>
      {meta.icon} {meta.label}
    </span>
  );
}

function ConfPill({ value }) {
  const numeric = Number(value ?? 0);
  const style =
    numeric >= 70
      ? "text-emerald-400 bg-emerald-500/10"
      : numeric >= 45
        ? "text-amber-400 bg-amber-500/10"
        : "text-slate-500 bg-slate-500/10";
  return (
    <span className={clsx("rounded-full px-2 py-0.5 text-[10px] font-mono font-semibold", style)}>
      {Number.isFinite(numeric) ? `${Math.round(numeric)}%` : "—"}
    </span>
  );
}

function NewsImpactPill({ value }) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  const style =
    numeric >= 85
      ? "text-red-300 bg-red-500/10"
      : numeric >= 70
        ? "text-amber-300 bg-amber-500/10"
        : "text-slate-400 bg-slate-500/10";
  return (
    <span className={clsx("rounded-full px-2 py-0.5 text-[10px] font-mono font-semibold", style)}>
      Impact {Math.round(numeric)}
    </span>
  );
}

function VolatilityPill({ value }) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  return (
    <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-mono font-semibold text-slate-300">
      Vol x{numeric.toFixed(2)}
    </span>
  );
}

function TradeLine({ payload }) {
  const trade = payload?.trade || {};
  const points = trade.latest_points ?? payload?.current_points;
  const win = trade.success_threshold_points ?? payload?.success_threshold_points;
  const stop = trade.stop_points ?? payload?.stop_points;
  const entry = trade.entry_price ?? payload?.entry_price;
  if (points == null && win == null && stop == null && entry == null) return null;

  const numericPoints = Number(points ?? 0);
  return (
    <p className="mt-1 font-mono text-[10px] text-slate-500">
      {entry != null ? `Entry ${fmt(entry)} · ` : ""}
      {points != null ? `Pts ${numericPoints >= 0 ? "+" : ""}${fmt(numericPoints)} · ` : ""}
      Win {win != null ? `+${fmt(win)}` : "-"} · Stop {stop != null ? `-${fmt(stop)}` : "-"}
    </p>
  );
}

function SetupPill({ state, direction, count, required }) {
  if (state !== "setup" || !direction) return null;
  return (
    <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-mono font-semibold text-amber-300">
      {direction} setup {count ?? 0}/{required ?? "?"}
    </span>
  );
}

function CommodityCard({ symbol, prices, tick }) {
  const [quick, setQuick] = useState(null);
  const [longSignal, setLongSignal] = useState(null);
  const [insight, setInsight] = useState(null);

  useEffect(() => {
    let alive = true;

    analyticsApi.commodityInsights(symbol).catch(() => ({ insight: "Unavailable" })).then((insightPayload) => {
      if (!alive) return;
      setInsight(insightPayload);
      setQuick({
        signal: insightPayload?.quick_signal ?? "WAIT",
        state: insightPayload?.quick_state ?? "idle",
        entry_ready: insightPayload?.quick_entry_ready ?? false,
        setup_direction: insightPayload?.quick_setup_direction,
        confirmation_count: insightPayload?.quick_confirmation_count,
        required_confirmations: insightPayload?.quick_required_confirmations,
        confidence: insightPayload?.quick_confidence ?? 0,
        reason: insightPayload?.quick_reason || "Unavailable",
        momentum_1m: insightPayload?.quick_momentum_1m,
        momentum_3m: insightPayload?.quick_momentum_3m,
        momentum_5m: insightPayload?.quick_momentum_5m,
        trade: insightPayload?.quick_trade,
        entry_price: insightPayload?.quick_trade?.entry_price,
        current_points: insightPayload?.quick_current_points,
        success_threshold_points: insightPayload?.quick_success_threshold_points,
        stop_points: insightPayload?.quick_stop_points,
      });
      setLongSignal({
        signal: insightPayload?.long_signal ?? "WAIT",
        state: insightPayload?.long_state ?? "idle",
        entry_ready: insightPayload?.long_entry_ready ?? false,
        setup_direction: insightPayload?.long_setup_direction,
        confirmation_count: insightPayload?.long_confirmation_count,
        required_confirmations: insightPayload?.long_required_confirmations,
        confidence: insightPayload?.long_confidence ?? 0,
        reason: insightPayload?.long_reason || "Unavailable",
        pct_5m: insightPayload?.long_pct_5m,
        pct_30m: insightPayload?.long_pct_30m,
        pct_60m: insightPayload?.long_pct_60m,
        trade: insightPayload?.long_trade,
        entry_price: insightPayload?.long_trade?.entry_price,
        current_points: insightPayload?.long_current_points,
        success_threshold_points: insightPayload?.long_success_threshold_points,
        stop_points: insightPayload?.long_stop_points,
      });
    });

    return () => {
      alive = false;
    };
  }, [symbol, tick]);

  const priceData = prices?.[symbol];
  const price = priceData?.price;
  const change = priceData?.change;
  const changePct = priceData?.change_pct;
  const up = change != null && change > 0;
  const down = change != null && change < 0;

  const quickSig = quick?.signal ?? "WAIT";
  const longSig = longSignal?.signal ?? "WAIT";
  const quickConf = quick?.confidence ?? 0;
  const longConf = longSignal?.confidence ?? 0;
  const primaryBorder = (SIG_META[longSig] ?? SIG_META.WAIT).border;

  return (
    <div className={clsx("card flex flex-col gap-4 border shadow-lg shadow-black/20", primaryBorder)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="mb-0.5 text-xs font-semibold uppercase tracking-widest text-slate-500">{symbol}</p>
          <p className="text-2xl font-bold font-mono leading-none text-slate-100">{fmt(price)}</p>
          <p className={clsx("mt-1 text-xs font-mono", up ? "text-emerald-400" : down ? "text-red-400" : "text-slate-500")}>
            {change != null ? `${up ? "+" : ""}${fmt(change)} (${up ? "+" : ""}${changePct ?? 0}%)` : "—"}
          </p>
        </div>

        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">LT</span>
            <Badge signal={longSig} />
            <ConfPill value={longConf} />
          </div>
          <SetupPill
            state={longSignal?.state}
            direction={longSignal?.setup_direction}
            count={longSignal?.confirmation_count}
            required={longSignal?.required_confirmations}
          />
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">QS</span>
            <Badge signal={quickSig} />
            <ConfPill value={quickConf} />
          </div>
          <SetupPill
            state={quick?.state}
            direction={quick?.setup_direction}
            count={quick?.confirmation_count}
            required={quick?.required_confirmations}
          />
          <NewsImpactPill value={insight?.news_impact_score} />
          <VolatilityPill value={insight?.quick_volatility_ratio || insight?.long_volatility_ratio} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2">
        <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Long-term</p>
          <p className="text-xs leading-snug text-slate-300">{longSignal?.reason || "—"}</p>
          {(longSignal?.pct_5m != null || longSignal?.pct_30m != null || longSignal?.pct_60m != null) && (
            <p className="mt-1 font-mono text-[10px] text-slate-600">
              5m {longSignal?.pct_5m ?? 0}% · 30m {longSignal?.pct_30m ?? 0}% · 60m {longSignal?.pct_60m ?? 0}%
            </p>
          )}
          <TradeLine payload={longSignal} />
        </div>

        <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Quick signal</p>
          <p className="text-xs leading-snug text-slate-300">{quick?.reason || "—"}</p>
          {(quick?.momentum_1m != null || quick?.momentum_3m != null || quick?.momentum_5m != null) && (
            <p className="mt-1 font-mono text-[10px] text-slate-600">
              1m {quick?.momentum_1m ?? "—"} · 3m {quick?.momentum_3m ?? "—"} · 5m {quick?.momentum_5m ?? "—"}
            </p>
          )}
          <TradeLine payload={quick} />
        </div>

        <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">AI insight</p>
          <p className="text-xs leading-snug text-slate-300">{insight?.insight || "—"}</p>
        </div>

        <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2">
          <div className="mb-1 flex items-center justify-between gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Critical news</p>
            <span className="text-[10px] text-slate-500">{insight?.news_source || "No critical news"}</span>
          </div>
          {insight?.news_title ? (
            <>
              <p className="text-xs leading-snug text-slate-200">{insight.news_title}</p>
              <p className="mt-1 text-[10px] text-slate-500">
                {insight?.news_reason || "Global macro cue is active for this commodity."}
              </p>
            </>
          ) : (
            <p className="text-xs leading-snug text-slate-500">
              No critical world-news trigger is currently elevating risk for this commodity.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CommoditiesPanel() {
  const [prices, setPrices] = useState(null);
  const [tick, setTick] = useState(0);
  const [marketStatus, setMarketStatus] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      analyticsApi
        .mcxPrices()
        .then((data) => {
          if (alive) setPrices(data);
        })
        .catch(() => {});

    const loadStatus = () =>
      analyticsApi
        .marketStatus()
        .then((status) => {
          if (alive) setMarketStatus(status);
          return Boolean(status?.mcx?.is_open);
        })
        .catch(() => false);

    load();
    loadStatus();
    const id = setInterval(async () => {
      const mcxOpen = await loadStatus();
      if (!mcxOpen) return;
      setTick((value) => value + 1);
      load();
    }, 15_000);

    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (prices?.error) {
    return (
      <div className="card flex flex-col items-center justify-center gap-2 border border-surface-border p-6 shadow-lg shadow-black/10">
        <span className="text-2xl">📭</span>
        <p className="font-semibold text-slate-300">Commodities</p>
        <p className="text-center text-xs leading-relaxed text-slate-500">{prices.error}</p>
      </div>
    );
  }

  const mcxOpen = Boolean(marketStatus?.mcx?.is_open);
  const statusLabel = mcxOpen ? "MCX live" : marketStatus?.mcx?.reason || "MCX status loading";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-surface-border bg-white/5 px-3 py-2">
        <span className="text-xs font-semibold text-slate-300">{statusLabel}</span>
        <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
          {mcxOpen ? "15s refresh" : "Stable until MCX reopens"}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {SYMBOLS.map((symbol) => (
          <CommodityCard key={symbol} symbol={symbol} prices={prices} tick={tick} />
        ))}
      </div>
    </div>
  );
}
