/**
 * CommoditiesPanel — top 4 MCX commodities with price + signals + insights.
 *
 * Shows: CRUDEOIL, NATGAS, GOLD, SILVER.
 * Polling: every 30s (commodities can move after 15:30 IST).
 */
import { useEffect, useState } from "react";
import clsx from "clsx";
import { analyticsApi } from "../lib/api";

const SYMBOLS = ["CRUDEOIL", "NATGAS", "GOLD", "SILVER"];

const SIG_META = {
  LONG:  { label: "LONG",  icon: "▲", color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/30" },
  SHORT: { label: "SHORT", icon: "▼", color: "text-red-400",     bg: "bg-red-500/15",     border: "border-red-500/30" },
  WAIT:  { label: "WAIT",  icon: "◆", color: "text-slate-400",   bg: "bg-slate-500/10",   border: "border-surface-border" },
};

function fmt(val, d = 2) {
  if (val == null) return "—";
  const n = Number(val);
  if (Number.isNaN(n)) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function Badge({ signal }) {
  const meta = SIG_META[signal] ?? SIG_META.WAIT;
  return (
    <span className={clsx("text-[11px] font-bold px-2.5 py-1 rounded-full", meta.bg, meta.color)}>
      {meta.icon} {meta.label}
    </span>
  );
}

function ConfPill({ value }) {
  const v = Number(value ?? 0);
  const style =
    v >= 70 ? "text-emerald-400 bg-emerald-500/10" :
    v >= 45 ? "text-amber-400 bg-amber-500/10" :
              "text-slate-500 bg-slate-500/10";
  return (
    <span className={clsx("text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full", style)}>
      {Number.isFinite(v) ? `${Math.round(v)}%` : "—"}
    </span>
  );
}

function CommodityCard({ symbol, prices, tick }) {
  const [quick, setQuick] = useState(null);
  const [longS, setLong]  = useState(null);
  const [ins, setIns]     = useState(null);

  useEffect(() => {
    let alive = true;
    Promise.all([
      analyticsApi.commodityQuickSignal(symbol).catch(() => ({ signal: "WAIT", reason: "Unavailable" })),
      analyticsApi.commodityLongSignal(symbol).catch(() => ({ signal: "WAIT", reason: "Unavailable" })),
      analyticsApi.commodityInsights(symbol).catch(() => ({ insight: "Unavailable" })),
    ]).then(([q, l, i]) => {
      if (!alive) return;
      setQuick(q);
      setLong(l);
      setIns(i);
    });
    return () => { alive = false; };
  }, [symbol, tick]);

  const p = prices?.[symbol];
  const price = p?.price;
  const change = p?.change;
  const pct = p?.change_pct;
  const up = change != null && change > 0;
  const down = change != null && change < 0;

  const quickSig = quick?.signal ?? "WAIT";
  const longSig  = longS?.signal ?? "WAIT";
  const quickConf = quick?.confidence ?? 0;
  const longConf  = longS?.confidence ?? 0;

  return (
    <div className={clsx("card border flex flex-col gap-4 shadow-lg shadow-black/20", (SIG_META[longSig] ?? SIG_META.WAIT).border)}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-semibold mb-0.5">{symbol}</p>
          <p className="text-2xl font-bold font-mono text-slate-100 leading-none">{fmt(price)}</p>
          <p className={clsx("text-xs mt-1 font-mono", up ? "text-emerald-400" : down ? "text-red-400" : "text-slate-500")}>
            {change != null ? `${up ? "+" : ""}${fmt(change)} (${up ? "+" : ""}${pct ?? 0}%)` : "—"}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">LT</span>
            <Badge signal={longSig} />
            <ConfPill value={longConf} />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">QS</span>
            <Badge signal={quickSig} />
            <ConfPill value={quickConf} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2">
        <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Long-term</p>
          <p className="text-xs text-slate-300 leading-snug">{longS?.reason || "—"}</p>
          {(longS?.pct_30m != null || longS?.pct_60m != null) && (
            <p className="text-[10px] text-slate-600 mt-1 font-mono">
              30m {longS?.pct_30m ?? 0}% · 60m {longS?.pct_60m ?? 0}%
            </p>
          )}
        </div>
        <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Quick signal</p>
          <p className="text-xs text-slate-300 leading-snug">{quick?.reason || "—"}</p>
          {(quick?.momentum_1m != null || quick?.momentum_3m != null) && (
            <p className="text-[10px] text-slate-600 mt-1 font-mono">
              1m {quick?.momentum_1m ?? "—"} · 3m {quick?.momentum_3m ?? "—"}
            </p>
          )}
        </div>
        <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">AI insight</p>
          <p className="text-xs text-slate-300 leading-snug">{ins?.insight || "—"}</p>
        </div>
      </div>
    </div>
  );
}

export default function CommoditiesPanel() {
  const [prices, setPrices] = useState(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    const load = () =>
      analyticsApi.mcxPrices()
        .then((d) => { if (alive) setPrices(d); })
        .catch(() => {});
    load();
    const id = setInterval(() => {
      setTick((t) => t + 1);
      load();
    }, 15_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (prices?.error) {
    return (
      <div className="card border border-surface-border shadow-lg shadow-black/10 flex flex-col items-center justify-center gap-2 p-6">
        <span className="text-2xl">📭</span>
        <p className="font-semibold text-slate-300">Commodities</p>
        <p className="text-xs text-slate-500 text-center leading-relaxed">
          {prices.error}
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {SYMBOLS.map((s) => (
        <CommodityCard key={s} symbol={s} prices={prices} tick={tick} />
      ))}
    </div>
  );
}

