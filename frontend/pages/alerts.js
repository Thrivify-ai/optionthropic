import { useState } from "react";
import Layout from "../components/Layout";
import AlertsPanel from "../components/AlertsPanel";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];

export default function AlertsPage() {
  const [symbol, setSymbol] = useState("NIFTY");

  return (
    <Layout>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="font-bold text-slate-100 text-lg">Alerts Feed</h2>
          <p className="text-slate-500 text-sm mt-0.5">
            Real-time alerts refresh every 30 seconds
          </p>
        </div>
        <div className="flex gap-1 bg-surface-card border border-surface-border rounded-lg p-1">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              onClick={() => setSymbol(s)}
              className={clsx(
                "px-3 py-1 rounded-md text-sm font-medium transition-all",
                symbol === s
                  ? "bg-brand-600 text-white"
                  : "text-slate-400 hover:text-slate-100"
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-2xl">
        <AlertsPanel symbol={symbol} limit={100} />
      </div>
    </Layout>
  );
}
