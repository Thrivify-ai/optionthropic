import { useEffect, useState } from "react";
import clsx from "clsx";

import { analyticsApi } from "../lib/api";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];

const SYMBOL_META = {
  NIFTY: { label: "NIFTY 50", accent: "text-brand-300", border: "border-brand-500/20", glow: "from-brand-500/10" },
  BANKNIFTY: { label: "BANK NIFTY", accent: "text-sky-300", border: "border-sky-500/20", glow: "from-sky-500/10" },
  SENSEX: { label: "BSE SENSEX", accent: "text-amber-300", border: "border-amber-500/20", glow: "from-amber-500/10" },
};

function InsightCard({ symbol, data, loading, error, deferMs = 0 }) {
  const [ready, setReady] = useState(!deferMs);
  const meta = SYMBOL_META[symbol] || SYMBOL_META.NIFTY;

  useEffect(() => {
    if (deferMs <= 0) {
      setReady(true);
      return undefined;
    }

    const timer = setTimeout(() => setReady(true), deferMs);
    return () => clearTimeout(timer);
  }, [deferMs]);

  if (!ready) {
    return <div className={clsx("card min-h-[210px] animate-pulse border bg-gradient-to-br to-surface-card", meta.border, meta.glow)} />;
  }

  return (
    <div className={clsx("card flex min-h-[210px] flex-col gap-3 border bg-gradient-to-br to-surface-card", meta.border, meta.glow)}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={clsx("flex h-9 w-9 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-xs font-bold", meta.accent)}>
            AI
          </span>
          <div>
            <p className="section-kicker">Desk Note</p>
            <h4 className={clsx("mt-1 text-sm font-semibold", meta.accent)}>{meta.label}</h4>
          </div>
        </div>
        {data?.cached ? (
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300">
            Cached
          </span>
        ) : null}
      </div>

      {loading ? (
        <div className="flex flex-1 flex-col gap-2 animate-pulse">
          <div className="h-3 w-full rounded bg-white/5" />
          <div className="h-3 w-5/6 rounded bg-white/5" />
          <div className="h-3 w-3/4 rounded bg-white/5" />
          <p className="mt-2 text-xs text-slate-500">Generating AI insight...</p>
        </div>
      ) : error ? (
        <p className="flex-1 text-sm text-slate-500">{error}</p>
      ) : (
        <p className="flex-1 text-sm leading-relaxed text-slate-200">
          {data?.insight || "No AI insight available yet. Once data and cache are ready, the desk note will appear here."}
        </p>
      )}
    </div>
  );
}

export default function AIInsightsPanel({ onDataLoaded, refreshTick }) {
  const [overview, setOverview] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const firstLoad = Object.keys(overview).length === 0;
    let retryTimer = null;

    if (firstLoad) setLoading(true);
    setError(null);

    analyticsApi
      .dashboardOverview()
      .then((data) => {
        const symbols = data?.symbols || {};
        setOverview(symbols);
        onDataLoaded?.();

        if (Object.values(symbols).some((entry) => entry?.ai_summary?.pending)) {
          retryTimer = setTimeout(() => {
            analyticsApi
              .dashboardOverview()
              .then((nextData) => setOverview(nextData?.symbols || {}))
              .catch(() => {});
          }, 8000);
        }
      })
      .catch(() => setError("AI insight unavailable"))
      .finally(() => {
        if (firstLoad) setLoading(false);
      });

    return () => {
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [refreshTick, onDataLoaded]);

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {SYMBOLS.map((symbol, index) => (
        <InsightCard
          key={symbol}
          symbol={symbol}
          data={overview[symbol]?.ai_summary}
          loading={loading}
          error={error}
          deferMs={index * 350}
        />
      ))}
    </div>
  );
}
