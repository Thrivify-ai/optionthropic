import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

const fmt = (value, decimals = 2) => {
  const n = Number(value);
  if (value == null || isNaN(n)) return "—";
  return n.toFixed(decimals);
};

// ─── Tooltip helper ────────────────────────────────────────────────────────────

function Tip({ text }) {
  return (
    <span
      className="ml-1.5 inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-slate-700 text-slate-400 text-[9px] cursor-help"
      title={text}
      aria-label={text}
    >
      ?
    </span>
  );
}

// ─── Stat card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color = "text-slate-100", explain }) {
  return (
    <div className="card flex flex-col gap-1">
      <span className="text-xs text-slate-500 uppercase tracking-wider flex items-center">
        {label}
        {explain && <Tip text={explain} />}
      </span>
      <span className={clsx("text-2xl font-bold font-mono", color)}>
        {value ?? "—"}
      </span>
      {sub && <span className="text-xs text-slate-400">{sub}</span>}
    </div>
  );
}

// ─── Support/Resistance table ─────────────────────────────────────────────────

function SRTable({ title, rows, valueKey, explain }) {
  return (
    <div>
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1 flex items-center">
        {title}
        {explain && <Tip text={explain} />}
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-slate-600">
            <th className="py-1 text-left font-normal">Strike</th>
            <th className="py-1 text-right font-normal">Open Interest</th>
          </tr>
        </thead>
        <tbody>
          {(rows || []).slice(0, 5).map((r, i) => (
            <tr key={i} className="border-b border-surface-border/50">
              <td className="py-1.5 font-mono text-slate-200">
                {r.strike?.toLocaleString("en-IN")}
              </td>
              <td className="py-1.5 text-right text-slate-400">
                {Number(r[valueKey] || 0).toLocaleString("en-IN")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Section heading with explanation ─────────────────────────────────────────

function SectionHeader({ title, subtitle, badge }) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-2">
        <h3 className="font-semibold text-slate-100">{title}</h3>
        {badge}
      </div>
      {subtitle && (
        <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{subtitle}</p>
      )}
    </div>
  );
}

// ─── Signal badge ─────────────────────────────────────────────────────────────

function SignalBadge({ value }) {
  const map = {
    WRITING: { cls: "badge-blue", label: "WRITING" },
    UNWINDING: { cls: "badge-red", label: "UNWINDING" },
    BUILDING: { cls: "badge-green", label: "BUILDING" },
    COVERING: { cls: "badge-yellow", label: "COVERING" },
  };
  const s = map[value] || { cls: "badge-blue", label: value };
  return <span className={s.cls}>{s.label}</span>;
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function OptionsDashboard({ symbol, onDataLoaded, refreshTick }) {
  const [chain, setChain] = useState(null);
  const [mp, setMp] = useState(null);
  const [traps, setTraps] = useState(null);
  const [shifts, setShifts] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    Promise.all([
      analyticsApi.optionsChain(symbol),
      analyticsApi.maxPain(symbol),
      analyticsApi.liquidityTraps(symbol),
      analyticsApi.positioningShifts(symbol),
    ])
      .then(([c, m, t, s]) => {
        setChain(c);
        setMp(m);
        setTraps(t);
        setShifts(s);
        onDataLoaded?.();
      })
      .finally(() => setLoading(false));
  }, [symbol, onDataLoaded, refreshTick]);

  if (loading)
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-pulse">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card h-20 bg-surface-card/50" />
        ))}
      </div>
    );

  const pcr = chain?.pcr;
  const sr = chain?.support_resistance;
  const sentimentColor =
    pcr?.sentiment === "BULLISH"
      ? "text-emerald-400"
      : pcr?.sentiment === "BEARISH"
      ? "text-red-400"
      : "text-yellow-400";

  const trapCount = traps?.traps?.length ?? 0;

  return (
    <div className="space-y-5">

      {/* ── KPI row ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Underlying"
          value={sr?.underlying_price?.toLocaleString("en-IN")}
          sub={symbol}
          explain="Current live spot price of the index from the options market"
        />
        <StatCard
          label="PCR (OI)"
          value={fmt(pcr?.pcr_oi, 2)}
          sub={`Sentiment: ${pcr?.sentiment ?? "—"}`}
          color={sentimentColor}
          explain="Put-Call Ratio by Open Interest. Above 1.2 = bullish (more put writers = floor). Below 0.8 = bearish (more call writers = ceiling)."
        />
        <StatCard
          label="Max Pain"
          value={mp?.max_pain_strike?.toLocaleString("en-IN")}
          sub={`Spot deviation: ${fmt(mp?.deviation_from_spot_pct, 1)}%`}
          explain="The strike price where total option sellers lose the least money. Near expiry, the index tends to gravitate toward this level."
        />
        <StatCard
          label="Liquidity Traps"
          value={trapCount}
          sub={trapCount > 0 ? "Caution: sticky strikes nearby" : "No traps detected"}
          color={trapCount > 0 ? "text-yellow-400" : "text-slate-100"}
          explain="Strikes with abnormally high OI that can trap price — acting as a magnet or sudden reversal point when breached."
        />
      </div>

      {/* ── Support / Resistance ── */}
      <div className="card">
        <SectionHeader
          title="Key Support &amp; Resistance"
          subtitle="Strikes where option sellers have concentrated their positions — these act as price walls. Call writers create resistance; put writers create support."
        />
        <div className="grid grid-cols-2 gap-6">
          <SRTable
            title="Resistance (Call OI)"
            rows={sr?.resistance}
            valueKey="call_oi"
            explain="Strikes with heavy call open interest. Sellers here profit if index stays below, so they defend these levels."
          />
          <SRTable
            title="Support (Put OI)"
            rows={sr?.support}
            valueKey="put_oi"
            explain="Strikes with heavy put open interest. Sellers here profit if index stays above, so they defend these levels."
          />
        </div>

        {/* Liquidity trap detail */}
        {trapCount > 0 && (
          <div className="mt-4 pt-4 border-t border-surface-border">
            <p className="text-xs font-semibold text-yellow-400 uppercase tracking-wider mb-2">
              ⚠ Active Liquidity Traps
            </p>
            <div className="flex flex-wrap gap-2">
              {traps.traps.slice(0, 5).map((t, i) => (
                <div
                  key={i}
                  className="text-xs bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-1.5"
                >
                  <span className="font-mono text-yellow-300">
                    {Number(t.strike).toLocaleString("en-IN")}
                  </span>
                  <span className="ml-2 text-slate-400 capitalize">
                    {t.side || "both"} · {Number(t.oi || 0).toLocaleString("en-IN")} OI
                  </span>
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-600 mt-2">
              These strikes have disproportionate OI — price can stall, reverse, or spike sharply when they are tested or breached.
            </p>
          </div>
        )}
      </div>

      {/* ── Positioning shifts ── */}
      <div className="card">
        <SectionHeader
          title="Intraday Positioning Shifts"
          subtitle="Shows how institutional traders are repositioning — WRITING means new short positions being added, UNWINDING means positions being closed. Large OI changes signal smart money conviction."
          badge={
            shifts?.price_direction && (
              <span
                className={clsx(
                  "text-xs font-normal px-2 py-0.5 rounded-full",
                  shifts.price_direction === "UP"
                    ? "text-emerald-400 bg-emerald-400/10"
                    : "text-red-400 bg-red-400/10"
                )}
              >
                Spot {shifts.price_direction === "UP" ? "▲" : "▼"}{" "}
                {fmt(shifts.underlying_change, 1)} pts
              </span>
            )
          }
        />

        {/* Signal legend */}
        <div className="flex flex-wrap gap-3 mb-4 text-xs text-slate-400">
          <span><span className="badge-blue mr-1">WRITING</span>New shorts added — expects price to stay away</span>
          <span><span className="badge-red mr-1">UNWINDING</span>Shorts being covered — conviction weakening</span>
          <span><span className="badge-green mr-1">BUILDING</span>Fresh longs added — bullish view</span>
          <span><span className="badge-yellow mr-1">COVERING</span>Longs being closed — caution</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 uppercase tracking-wider">
                <th className="px-3 py-2 text-left">Strike</th>
                <th className="px-3 py-2 text-left">
                  Call Signal
                  <Tip text="Change in call open interest and its implication" />
                </th>
                <th className="px-3 py-2 text-left">
                  Put Signal
                  <Tip text="Change in put open interest and its implication" />
                </th>
                <th className="px-3 py-2 text-right">
                  Call ΔOI
                  <Tip text="Absolute change in call open interest this session" />
                </th>
                <th className="px-3 py-2 text-right">
                  Put ΔOI
                  <Tip text="Absolute change in put open interest this session" />
                </th>
              </tr>
            </thead>
            <tbody>
              {(shifts?.shifts || []).slice(0, 8).map((s, i) => (
                <tr
                  key={i}
                  className="border-b border-surface-border/50 hover:bg-white/5 transition-colors"
                >
                  <td className="px-3 py-2 font-mono text-slate-200">
                    {s.strike?.toLocaleString("en-IN")}
                  </td>
                  <td className="px-3 py-2">
                    <SignalBadge value={s.call_signal} />
                  </td>
                  <td className="px-3 py-2">
                    <SignalBadge value={s.put_signal} />
                  </td>
                  <td
                    className={clsx(
                      "px-3 py-2 text-right font-mono text-xs",
                      s.call_oi_change >= 0 ? "text-emerald-400" : "text-red-400"
                    )}
                  >
                    {s.call_oi_change >= 0 ? "+" : ""}
                    {Number(s.call_oi_change).toLocaleString("en-IN")}
                  </td>
                  <td
                    className={clsx(
                      "px-3 py-2 text-right font-mono text-xs",
                      s.put_oi_change >= 0 ? "text-emerald-400" : "text-red-400"
                    )}
                  >
                    {s.put_oi_change >= 0 ? "+" : ""}
                    {Number(s.put_oi_change).toLocaleString("en-IN")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!shifts?.shifts?.length && (
            <p className="text-center text-slate-500 text-sm py-6">
              No positioning shift data yet. Data populates as the market trades.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
