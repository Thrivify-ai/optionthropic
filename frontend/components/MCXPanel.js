/**
 * MCXPanel — crude oil + natural gas ticker panel.
 *
 * New component: reads /api/mcx-prices and displays two instruments.
 */
import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

function fmt(val) {
  if (val == null) return "—";
  return Number(val).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function Item({ label, row }) {
  const price = row?.price;
  const ch    = row?.change;
  const pct   = row?.change_pct;
  const up    = ch != null && ch > 0;
  const down  = ch != null && ch < 0;

  return (
    <div className="card border border-surface-border shadow-lg shadow-black/10 flex flex-col gap-2">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-semibold mb-0.5">
            {label}
          </p>
          <p className="text-2xl font-bold font-mono text-slate-100 leading-none">
            {fmt(price)}
          </p>
          <p className="text-[10px] text-slate-600 mt-1 font-mono truncate">
            {row?.symbol || ""}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span
            className={clsx(
              "text-xs font-bold px-2.5 py-1 rounded-full",
              up ? "bg-emerald-500/15 text-emerald-400" :
              down ? "bg-red-500/15 text-red-400" :
                     "bg-slate-500/10 text-slate-400"
            )}
          >
            {up ? "▲" : down ? "▼" : "◆"} {ch != null ? fmt(ch) : "—"}
            {pct != null ? ` (${up ? "+" : ""}${pct}%)` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}

export default function MCXPanel() {
  const [data, setData] = useState(null);
  const [err, setErr]   = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      analyticsApi.mcxPrices()
        .then((d) => { if (alive) { setData(d); setErr(null); } })
        .catch(() => { if (alive) setErr("MCX data unavailable"); });

    load();
    const id = setInterval(load, 30_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (err || data?.error) {
    return (
      <div className="card border border-surface-border shadow-lg shadow-black/10 flex flex-col items-center justify-center gap-2 p-6">
        <span className="text-2xl">📭</span>
        <p className="font-semibold text-slate-300">MCX</p>
        <p className="text-xs text-slate-500 text-center leading-relaxed">
          {data?.error || err}
        </p>
        <p className="text-[10px] text-slate-600 text-center">
          Ensure `DATA_SOURCE=ZERODHA`, `ZERODHA_API_KEY`, and `ZERODHA_ACCESS_TOKEN` are set.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Item label="CRUDEOIL" row={data?.CRUDEOIL} />
      <Item label="NATGAS"   row={data?.NATGAS} />
    </div>
  );
}

