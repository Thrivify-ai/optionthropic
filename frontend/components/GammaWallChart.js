import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { analyticsApi } from "../lib/api";

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-surface-card border border-surface-border rounded-lg p-3 text-xs shadow-xl">
      <p className="font-semibold text-slate-200 mb-1">Strike: {label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: {Number(p.value).toLocaleString("en-IN")}
        </p>
      ))}
    </div>
  );
};

export default function GammaWallChart({ symbol, onDataLoaded, refreshTick }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    analyticsApi
      .gammaWalls(symbol)
      .then((d) => { setData(d); onDataLoaded?.(); })
      .catch(() => setError("Failed to load gamma wall data"))
      .finally(() => setLoading(false));
  }, [symbol, onDataLoaded, refreshTick]);

  if (loading)
    return (
      <div className="card h-80 flex items-center justify-center animate-pulse">
        <span className="text-slate-500 text-sm">Loading gamma data…</span>
      </div>
    );

  if (error)
    return (
      <div className="card h-80 flex items-center justify-center">
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    );

  const chartData = (data?.chart_data || []).map((d) => ({
    strike: d.strike,
    "Call OI": d.call_oi,
    "Put OI": d.put_oi,
  }));

  return (
    <div className="card">
      <div className="mb-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-100">Gamma Wall Analysis</h3>
          <div className="flex gap-4 text-xs">
            <span className="text-emerald-400">
              Put Wall: {data?.put_wall?.toLocaleString("en-IN") ?? "—"}
            </span>
            <span className="text-red-400">
              Call Wall: {data?.call_wall?.toLocaleString("en-IN") ?? "—"}
            </span>
            <span className="text-yellow-400">
              Spot: {data?.underlying_price?.toLocaleString("en-IN") ?? "—"}
            </span>
          </div>
        </div>
        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
          Strikes with peak open interest act as <span className="text-red-400">resistance (Call Wall)</span> and{" "}
          <span className="text-emerald-400">support (Put Wall)</span>. Option sellers with large positions at these
          strikes will hedge to defend them — making the index "sticky" near these levels. A break through a gamma
          wall can trigger sharp, accelerated moves.
        </p>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis
            dataKey="strike"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickLine={false}
            tickFormatter={(v) => (Number(v) / 1000).toFixed(0) + "K"}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: "12px", color: "#94a3b8" }}
          />
          {data?.underlying_price && (
            <ReferenceLine
              x={data.underlying_price}
              stroke="#fbbf24"
              strokeDasharray="4 2"
              label={{ value: "Spot", fill: "#fbbf24", fontSize: 11 }}
            />
          )}
          {data?.call_wall && (
            <ReferenceLine x={data.call_wall} stroke="#f87171" strokeDasharray="4 2" />
          )}
          {data?.put_wall && (
            <ReferenceLine x={data.put_wall} stroke="#34d399" strokeDasharray="4 2" />
          )}
          <Bar dataKey="Call OI" fill="#818cf8" radius={[2, 2, 0, 0]} />
          <Bar dataKey="Put OI" fill="#34d399" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
