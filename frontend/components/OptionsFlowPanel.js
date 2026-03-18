import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

const fmt = (value, decimals = 1) => {
  const n = Number(value);
  if (value == null || isNaN(n)) return "—";
  return n.toFixed(decimals);
};

const FLOW_COLORS = {
  SWEEP: "badge-red",
  BLOCK: "badge-blue",
  UNUSUAL: "badge-yellow",
  NORMAL: "badge-green",
};

const FLOW_EXPLAIN = {
  SWEEP:   "Swept the order book — aggressive, directional bet by smart money",
  BLOCK:   "Large institutional block trade — significant conviction",
  UNUSUAL: "Volume/premium significantly above average for this strike",
  NORMAL:  "Standard retail flow within normal parameters",
};

function FlowRow({ flow }) {
  const isBullish = flow.option_type === "CE";
  const flowType = flow.flow_type;
  return (
    <tr
      className="border-b border-surface-border hover:bg-white/5 transition-colors"
      title={FLOW_EXPLAIN[flowType] || flowType}
    >
      <td className="px-3 py-2 font-mono text-sm text-slate-200">
        {Number(flow.strike).toLocaleString("en-IN")}
      </td>
      <td className="px-3 py-2">
        <span
          className={clsx(
            "text-xs font-bold px-2 py-0.5 rounded",
            isBullish
              ? "bg-emerald-500/15 text-emerald-400"
              : "bg-red-500/15 text-red-400"
          )}
        >
          {flow.option_type === "CE" ? "CALL" : "PUT"}
        </span>
      </td>
      <td className="px-3 py-2 text-sm text-slate-300 font-mono">
        {Number(flow.volume).toLocaleString("en-IN")}
      </td>
      <td className="px-3 py-2 text-sm text-slate-300 font-mono">
        ₹{fmt(Number(flow.premium) / 100000)}L
      </td>
      <td className="px-3 py-2">
        <span
          className={FLOW_COLORS[flowType] || "badge-blue"}
          title={FLOW_EXPLAIN[flowType]}
        >
          {flowType}
        </span>
      </td>
      <td
        className={clsx(
          "px-3 py-2 text-xs font-mono",
          Number(flow.distance_from_spot_pct) > 0 ? "text-red-400" : "text-emerald-400"
        )}
      >
        {Number(flow.distance_from_spot_pct) > 0 ? "+" : ""}
        {fmt(flow.distance_from_spot_pct)}%
      </td>
    </tr>
  );
}

export default function OptionsFlowPanel({ symbol, onDataLoaded, refreshTick }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    analyticsApi
      .optionsFlow(symbol)
      .then((d) => { setData(d); onDataLoaded?.(); })
      .catch(() => setError("Failed to load options flow"))
      .finally(() => setLoading(false));
  }, [symbol, onDataLoaded, refreshTick]);

  const callPrem = Number(data?.summary?.total_call_premium || 0);
  const putPrem = Number(data?.summary?.total_put_premium || 0);
  const callDominating = callPrem > putPrem;

  return (
    <div className="card">
      {/* Header */}
      <div className="mb-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-100">Smart Money Flow</h3>
          {data?.summary && (
            <div className="flex gap-3 text-xs">
              <span className="text-slate-400">
                Call Premium:{" "}
                <span className="text-emerald-400 font-semibold">
                  ₹{fmt(callPrem / 10000000)}Cr
                </span>
              </span>
              <span className="text-slate-400">
                Put Premium:{" "}
                <span className="text-red-400 font-semibold">
                  ₹{fmt(putPrem / 10000000)}Cr
                </span>
              </span>
            </div>
          )}
        </div>
        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
          Large options trades classified by how they were executed. <span className="text-red-300">SWEEP</span> = aggressive
          directional bet. <span className="text-blue-300">BLOCK</span> = institutional size. <span className="text-yellow-300">UNUSUAL</span> = volume
          spike above normal. "vs Spot" shows how far the strike is from the current index level (OTM distance).
        </p>

        {/* Premium flow bias indicator */}
        {data?.summary && (
          <div className="mt-3 flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-surface-border overflow-hidden flex">
              <div
                className="h-full bg-emerald-500 transition-all duration-700"
                style={{ width: `${Math.round((callPrem / (callPrem + putPrem || 1)) * 100)}%` }}
              />
              <div
                className="h-full bg-red-500 transition-all duration-700"
                style={{ width: `${Math.round((putPrem / (callPrem + putPrem || 1)) * 100)}%` }}
              />
            </div>
            <span className={clsx("text-xs font-semibold", callDominating ? "text-emerald-400" : "text-red-400")}>
              {callDominating ? "Call" : "Put"} flow dominating
            </span>
          </div>
        )}
      </div>

      {loading && (
        <div className="text-center py-8 text-slate-500 text-sm animate-pulse">
          Loading flow data…
        </div>
      )}
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {!loading && !error && (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-xs text-slate-500 uppercase tracking-wider border-b border-surface-border">
                <th className="px-3 py-2">Strike</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Volume</th>
                <th className="px-3 py-2">Premium</th>
                <th className="px-3 py-2">Classification</th>
                <th className="px-3 py-2">vs Spot</th>
              </tr>
            </thead>
            <tbody>
              {(data?.flows || []).map((flow, i) => (
                <FlowRow key={i} flow={flow} />
              ))}
            </tbody>
          </table>
          {!data?.flows?.length && (
            <p className="text-center text-slate-500 text-sm py-6">
              No large flow events detected yet. Flow populates when significant option trades occur.
            </p>
          )}
        </div>
      )}

      {/* Classification legend */}
      {!loading && !error && data?.flows?.length > 0 && (
        <div className="mt-4 pt-3 border-t border-surface-border grid grid-cols-2 gap-1.5">
          {Object.entries(FLOW_EXPLAIN).map(([key, desc]) => (
            <div key={key} className="flex items-start gap-1.5 text-xs text-slate-500">
              <span className={clsx(FLOW_COLORS[key] || "badge-blue", "mt-0.5 shrink-0")}>{key}</span>
              <span>{desc}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
