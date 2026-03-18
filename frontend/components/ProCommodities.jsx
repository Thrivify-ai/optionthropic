/**
 * Pro Commodities — live MCX prices, quick signals, long signals, explanations.
 * CRUDEOIL, NATGAS, GOLD, SILVER.
 */
import { useEffect, useState } from "react";
import { proApi } from "../lib/proApi";
import clsx from "clsx";

const COMMODITIES = ["CRUDEOIL", "NATGAS", "GOLD", "SILVER"];
const POLL_MS = 15000;

const SIGNAL_META = {
  LONG: {
    label: "LONG",
    icon: "▲",
    color: "text-emerald-400",
    bg: "bg-emerald-500/15",
    border: "border-emerald-500/30",
  },
  SHORT: {
    label: "SHORT",
    icon: "▼",
    color: "text-red-400",
    bg: "bg-red-500/15",
    border: "border-red-500/30",
  },
  WAIT: {
    label: "WAIT",
    icon: "◆",
    color: "text-slate-400",
    bg: "bg-slate-500/10",
    border: "border-slate-500/20",
  },
};

export default function ProCommodities() {
  const [data, setData] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = () => {
      proApi.commodities().then((res) => {
        setData(res || {});
        setLoading(false);
      }).catch(() => setLoading(false));
    };
    fetchData();
    const id = setInterval(fetchData, POLL_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="rounded-xl border border-surface-border bg-surface-card/80 p-4 shadow-lg">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
        Commodities (MCX)
      </p>
      <p className="text-[9px] text-slate-600 mb-4">
        Live prices · Quick (1–3m) · Long (5m/30m/60m) · Updates every 15s
      </p>

      <div className="space-y-4">
        {COMMODITIES.map((sym) => {
          const d = data[sym] || {};
          const price = d.price ?? "—";
          const change = d.change ?? 0;
          const changePct = d.change_pct ?? null;
          const quickSig = d.quick_signal || "WAIT";
          const longSig = d.long_signal || "WAIT";
          const qMeta = SIGNAL_META[quickSig] || SIGNAL_META.WAIT;
          const lMeta = SIGNAL_META[longSig] || SIGNAL_META.WAIT;
          const up = change > 0;
          const down = change < 0;

          return (
            <div
              key={sym}
              className="rounded-lg border border-surface-border/50 bg-surface/40 p-3 space-y-2"
            >
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs font-bold text-slate-400 uppercase">
                  {sym}
                </span>
                <span className="text-lg font-bold font-mono text-slate-100">
                  {loading ? "…" : Number(price).toLocaleString("en-IN")}
                </span>
                <span
                  className={clsx(
                    "text-sm font-mono font-semibold",
                    up && "text-emerald-400",
                    down && "text-red-400",
                    !up && !down && "text-slate-500"
                  )}
                >
                  {loading ? "" : change >= 0 ? `+${change}` : change}
                  {changePct != null && !loading && (
                    <span className="ml-0.5 opacity-80">
                      ({changePct >= 0 ? "+" : ""}{changePct}%)
                    </span>
                  )}
                </span>
              </div>

              <div className="flex flex-wrap gap-2">
                <span
                  className={clsx(
                    "inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold border",
                    qMeta.border,
                    qMeta.bg,
                    qMeta.color
                  )}
                >
                  {qMeta.icon} Quick: {qMeta.label}
                </span>
                <span
                  className={clsx(
                    "inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold border",
                    lMeta.border,
                    lMeta.bg,
                    lMeta.color
                  )}
                >
                  {lMeta.icon} Long: {lMeta.label}
                </span>
              </div>

              <p className="text-xs text-slate-300 leading-snug">
                "{d.explanation || "No data yet."}"
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
