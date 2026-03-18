/**
 * Time factor card — shows current IST, key intraday windows (10:30–10:55, 12:30, 1:20, 2:55 PM),
 * and options-derived bias during those windows. Can also appear as a live alert.
 */
import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

const BIAS_STYLE = {
  BULLISH: { color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/40" },
  BEARISH:  { color: "text-red-400",     bg: "bg-red-500/15",     border: "border-red-500/40" },
  NEUTRAL:  { color: "text-slate-400",   bg: "bg-slate-500/15",   border: "border-slate-500/40" },
};

export default function TimeFactorCard({ symbol = "NIFTY", refreshTick, onDataLoaded }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    analyticsApi
      .timeFactor(symbol)
      .then((d) => { setData(d); onDataLoaded?.(); })
      .catch(() => setData({ ist_now: "", window: null, bias: "NEUTRAL", message: "Unavailable", in_window: false }))
      .finally(() => setLoading(false));
  }, [symbol, refreshTick, onDataLoaded]);

  if (loading) {
    return (
      <div className="card border border-surface-border p-4 animate-pulse flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-surface-border/50" />
        <div className="flex-1 space-y-1">
          <div className="h-3 w-24 bg-surface-border/40 rounded" />
          <div className="h-3 w-32 bg-surface-border/30 rounded" />
        </div>
      </div>
    );
  }

  const biasStyle = BIAS_STYLE[data?.bias] || BIAS_STYLE.NEUTRAL;
  const inWindow = data?.in_window ?? false;

  return (
    <div
      className={clsx(
        "card border p-4 flex flex-col gap-2",
        inWindow ? biasStyle.border : "border-surface-border"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-lg" title="Key intraday times">🕐</span>
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Time factor
            </p>
            <p className="text-sm font-mono text-slate-200">{data?.ist_now || "—"}</p>
          </div>
        </div>
        <span
          className={clsx(
            "text-xs font-bold px-2.5 py-1 rounded-full shrink-0",
            biasStyle.bg,
            biasStyle.color
          )}
        >
          {data?.bias || "NEUTRAL"}
        </span>
      </div>
      {data?.window ? (
        <div className="rounded-lg bg-white/5 border border-surface-border/60 px-3 py-2">
          <p className="text-xs font-semibold text-slate-300">{data.window.label}</p>
          <p className="text-[11px] text-slate-500 mt-0.5">{data.window.description}</p>
        </div>
      ) : (
        <p className="text-[11px] text-slate-500">{data?.message || "No key window"}</p>
      )}
      <p className="text-[10px] text-slate-600 border-t border-surface-border/40 pt-2">
        Key windows: 10:30–10:55 · 12:30 · 1:20 · 2:55 PM IST
      </p>
    </div>
  );
}
