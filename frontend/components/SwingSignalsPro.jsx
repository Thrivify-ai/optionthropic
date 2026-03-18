/**
 * Swing Signals Pro — longer-term trend signals.
 */
import { useEffect, useState } from "react";
import { proApi } from "../lib/proApi";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const POLL_MS = 15000;

const META = {
  "Buy CE": {
    label: "BUY CE",
    icon: "▲",
    color: "text-emerald-400",
    bg: "bg-emerald-500/15",
    border: "border-emerald-500/30",
  },
  "Buy PE": {
    label: "BUY PE",
    icon: "▼",
    color: "text-red-400",
    bg: "bg-red-500/15",
    border: "border-red-500/30",
  },
  Wait: {
    label: "WAIT",
    icon: "◆",
    color: "text-slate-400",
    bg: "bg-slate-500/10",
    border: "border-slate-500/20",
  },
};

export default function SwingSignalsPro() {
  const [signals, setSignals] = useState({});

  useEffect(() => {
    const fetchSignals = () => {
      proApi.signals().then((data) => {
        setSignals(data || {});
      });
    };
    fetchSignals();
    const id = setInterval(fetchSignals, POLL_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="rounded-xl border border-surface-border bg-surface-card/80 p-4 shadow-lg">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-3">
        Swing Signals
      </p>
      <p className="text-[9px] text-slate-600 mb-3">Multi-timeframe trend · Updates every 15s</p>
      <div className="flex flex-wrap gap-3">
        {SYMBOLS.map((sym) => {
          const s = signals[sym] || {};
          const sig = s.swing_signal || "Wait";
          const meta = META[sig] || META.Wait;
          return (
            <div
              key={sym}
              className={clsx(
                "flex items-center gap-2 px-4 py-2.5 rounded-lg border",
                meta.border,
                meta.bg
              )}
            >
              <span className="text-xs font-bold text-slate-400 uppercase w-20">
                {sym}
              </span>
              <span className={clsx("font-bold", meta.color)}>
                {meta.icon} {meta.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
