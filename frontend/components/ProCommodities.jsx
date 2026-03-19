/**
 * Pro Commodities — dashboard-style cards per commodity.
 * CRUDEOIL, NATGAS, GOLD, SILVER. Clean data + brief explanation.
 */
import { useEffect, useState } from "react";
import { proApi } from "../lib/proApi";
import clsx from "clsx";

const COMMODITIES = ["CRUDEOIL", "NATGAS", "GOLD", "SILVER"];
const POLL_MS = 15000;

const LABELS = {
  CRUDEOIL: "Crude Oil",
  NATGAS: "Natural Gas",
  GOLD: "Gold",
  SILVER: "Silver",
};

const META = {
  LONG: { label: "LONG", icon: "▲", desc: "Bullish bias", color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/40" },
  SHORT: { label: "SHORT", icon: "▼", desc: "Bearish bias", color: "text-red-400", bg: "bg-red-500/15", border: "border-red-500/40" },
  WAIT: { label: "WAIT", icon: "◆", desc: "No clear direction", color: "text-slate-400", bg: "bg-slate-500/10", border: "border-slate-500/20" },
};

function CommodityCard({ symbol, data, loading }) {
  const d = data || {};
  const price = d.price ?? null;
  const change = d.change ?? 0;
  const changePct = d.change_pct ?? null;
  const quickSig = (d.quick_signal || "WAIT").trim();
  const longSig = (d.long_signal || "WAIT").trim();
  const qMeta = META[quickSig] || META.WAIT;
  const lMeta = META[longSig] || META.WAIT;
  const up = change > 0;
  const down = change < 0;
  const primarySig = quickSig !== "WAIT" ? quickSig : longSig;
  const primaryMeta = META[primarySig] || META.WAIT;

  return (
    <div className={clsx("card border flex flex-col gap-4 shadow-lg shadow-black/20", primaryMeta.border)}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-semibold mb-0.5">{LABELS[symbol] || symbol}</p>
          <p className="text-xl font-bold font-mono text-slate-100 leading-none">
            {loading ? "…" : price != null ? Number(price).toLocaleString("en-IN") : "—"}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            {loading ? "" : changePct != null ? `${change >= 0 ? "+" : ""}${change} (${changePct >= 0 ? "+" : ""}${changePct}%)` : "—"}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={clsx("text-xs font-semibold", up && "text-emerald-400", down && "text-red-400", !up && !down && "text-slate-500")}>
            {loading ? "" : change >= 0 ? `+${change}` : change}
          </span>
          <div className="flex gap-1">
            <span className={clsx("text-[10px] px-2 py-0.5 rounded font-bold", qMeta.bg, qMeta.color)}>Quick {qMeta.icon}</span>
            <span className={clsx("text-[10px] px-2 py-0.5 rounded font-bold", lMeta.bg, lMeta.color)}>Long {lMeta.icon}</span>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-surface-border/50 px-3 py-2 flex flex-col gap-1.5">
        <p className="text-[11px] text-slate-300 leading-snug font-medium">
          {d.explanation || "No data yet."}
        </p>
        {d.quick_reason && quickSig !== "WAIT" && (
          <p className="text-[10px] text-slate-500">Quick: {d.quick_reason}</p>
        )}
        {d.long_reason && longSig !== "WAIT" && (
          <p className="text-[10px] text-slate-500">Long: {d.long_reason}</p>
        )}
      </div>
    </div>
  );
}

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
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-slate-100">🥇 Commodities (MCX)</span>
        <span className="text-[10px] text-slate-500">Live prices · Quick (1–3m) · Long (5m/30m/60m) · 15s refresh</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {COMMODITIES.map((sym) => (
          <CommodityCard key={sym} symbol={sym} data={data[sym]} loading={loading} />
        ))}
      </div>
    </div>
  );
}
