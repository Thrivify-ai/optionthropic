import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";

export default function MarketSummary({ symbol }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    analyticsApi
      .marketSummary(symbol)
      .then(setData)
      .catch(() => setError("Failed to load market summary"))
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading)
    return (
      <div className="card animate-pulse h-24 flex items-center justify-center">
        <span className="text-slate-500 text-sm">Generating AI insight…</span>
      </div>
    );

  if (error)
    return (
      <div className="card border-red-800/40">
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    );

  return (
    <div className="card border-brand-500/30 bg-gradient-to-br from-brand-900/20 to-surface-card">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600/20 text-brand-400 text-sm font-bold">
            AI
          </span>
        </div>
        <div>
          <p className="text-xs font-semibold text-brand-400 uppercase tracking-wider mb-1">
            AI Market Insight · {symbol}
            {data?.cached && (
              <span className="ml-2 text-slate-500 normal-case">(cached)</span>
            )}
          </p>
          <p className="text-slate-200 text-sm leading-relaxed">
            {data?.insight || "No insight available."}
          </p>
        </div>
      </div>
    </div>
  );
}
