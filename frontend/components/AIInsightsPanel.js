/**
 * Section 3 — AI Market Summaries
 * Shows AI-generated market insights for all 3 indices simultaneously.
 */
import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];

const SYMBOL_META = {
  NIFTY:     { label: "NIFTY 50",    color: "text-brand-400",   border: "border-brand-500/30",   bg: "from-brand-900/20"     },
  BANKNIFTY: { label: "BANK NIFTY",  color: "text-purple-400",  border: "border-purple-500/30",  bg: "from-purple-900/20"    },
  SENSEX:    { label: "BSE SENSEX",  color: "text-orange-400",  border: "border-orange-500/30",  bg: "from-orange-900/20"    },
};

function InsightCard({ symbol, onDataLoaded, refreshTick, deferMs = 0 }) {
  const [data, setData]    = useState(null);
  const [loading, setLoad] = useState(true);
  const [error, setError]  = useState(null);
  const [ready, setReady]  = useState(!deferMs);
  const meta = SYMBOL_META[symbol] || SYMBOL_META.NIFTY;

  useEffect(() => {
    if (deferMs > 0) {
      const t = setTimeout(() => setReady(true), deferMs);
      return () => clearTimeout(t);
    } else {
      setReady(true);
    }
  }, [deferMs]);

  useEffect(() => {
    if (!symbol || !ready) return;
    const firstLoad = !data;
    if (firstLoad) setLoad(true);
    setError(null);
    analyticsApi
      .marketSummary(symbol)
      .then((d) => { setData(d); onDataLoaded?.(); })
      .catch(() => setError("AI insight unavailable"))
      .finally(() => { if (firstLoad) setLoad(false); });
  }, [symbol, onDataLoaded, refreshTick, ready]);

  return (
    <div className={clsx(
      "card border bg-gradient-to-br to-surface-card flex flex-col gap-3 min-h-[180px] shadow-lg shadow-black/20",
      meta.border, meta.bg
    )}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className={clsx(
          "flex h-7 w-7 items-center justify-center rounded-lg text-[10px] font-black shrink-0",
          "bg-white/10", meta.color
        )}>
          AI
        </span>
        <div>
          <p className={clsx("text-xs font-bold uppercase tracking-wider", meta.color)}>
            {meta.label}
          </p>
          {data?.cached && (
            <span className="text-[9px] text-slate-500">(cached result)</span>
          )}
        </div>
      </div>

      {/* Content */}
      {loading && (
        <div className="flex-1 flex flex-col gap-2 animate-pulse">
          <div className="h-3 bg-white/5 rounded w-full" />
          <div className="h-3 bg-white/5 rounded w-5/6" />
          <div className="h-3 bg-white/5 rounded w-4/6" />
          <p className="text-xs text-slate-500 mt-1">Generating AI insight…</p>
        </div>
      )}
      {error && (
        <p className="text-xs text-slate-500 flex-1">{error}</p>
      )}
      {!loading && !error && (
        <p className="text-sm text-slate-200 leading-relaxed flex-1">
          {data?.insight || "No AI insight available. Ensure data is flowing from Zerodha."}
        </p>
      )}
    </div>
  );
}

export default function AIInsightsPanel({ onDataLoaded, refreshTick }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {SYMBOLS.map((s, i) => (
        <InsightCard
          key={s}
          symbol={s}
          onDataLoaded={onDataLoaded}
          refreshTick={refreshTick}
          deferMs={i * 500}
        />
      ))}
    </div>
  );
}
