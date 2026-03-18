/**
 * Pro Ticker — live tick data for NIFTY, BANKNIFTY, SENSEX.
 */
import { useEffect, useState } from "react";
import { proApi } from "../lib/proApi";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const POLL_MS = 2000;

export default function ProTicker() {
  const [ticks, setTicks] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchTicks = () => {
      proApi.ticks().then((data) => {
        setTicks(data || {});
        setLoading(false);
      }).catch(() => setLoading(false));
    };
    fetchTicks();
    const id = setInterval(fetchTicks, POLL_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="rounded-xl border border-surface-border bg-surface-card/80 p-4 shadow-lg">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
        Live Tick Data
      </p>
      <p className="text-[9px] text-slate-600 mb-3">Change vs previous close</p>
      <div className="flex flex-wrap gap-4">
        {SYMBOLS.map((sym) => {
          const d = ticks[sym] || {};
          const price = d.price ?? "—";
          const change = d.change ?? 0;
          const up = change > 0;
          const down = change < 0;
          return (
            <div
              key={sym}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-surface/60 border border-surface-border/50"
            >
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
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
