/**
 * Explanation Card — simple language explanations per symbol.
 */
import { useEffect, useState } from "react";
import { proApi } from "../lib/proApi";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const POLL_MS = 15000;

export default function ExplanationCard() {
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
        Simple Explanation
      </p>
      <div className="space-y-3">
        {SYMBOLS.map((sym) => {
          const s = signals[sym] || {};
          const text = s.explanation || "No data yet.";
          return (
            <div
              key={sym}
              className="rounded-lg border border-surface-border/50 bg-surface/40 px-3 py-2.5"
            >
              <p className="text-[10px] font-bold text-slate-400 uppercase mb-1">
                {sym}
              </p>
              <p className="text-sm text-slate-200 leading-snug">
                "{text}"
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
