/**
 * Pro Commodities - dashboard-style cards per commodity with signals and news context.
 */
import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";

import { analyticsApi } from "../lib/api";
import { proApi } from "../lib/proApi";

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

const NEWS_KEYWORDS = {
  CRUDEOIL: ["oil", "crude", "brent", "opec", "refinery"],
  NATGAS: ["natural gas", "natgas", "lng", "gas supply"],
  GOLD: ["gold", "bullion", "safe haven", "treasury yield", "bond yield", "inflation"],
  SILVER: ["silver", "precious metals", "bullion", "inflation", "safe haven"],
};

function normalizeNumber(value, decimals = 2) {
  if (value == null) return "—";
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return "—";
  return parsed.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function extractAffected(alert) {
  if (Array.isArray(alert?.affected_symbols)) return alert.affected_symbols;
  if (Array.isArray(alert?.symbols)) return alert.symbols;
  return [];
}

function alertMatchesCommodity(symbol, alert) {
  const affected = extractAffected(alert);
  if (affected.includes(symbol)) return true;

  const haystack = `${alert?.title || ""} ${alert?.summary || ""} ${alert?.impact_reason || ""}`.toLowerCase();
  return (NEWS_KEYWORDS[symbol] || []).some((keyword) => haystack.includes(keyword));
}

function buildCommodityInsight(symbol, alerts) {
  const relevant = (alerts || [])
    .filter((alert) => alertMatchesCommodity(symbol, alert))
    .sort((a, b) => Number(b?.impact_score || 0) - Number(a?.impact_score || 0));

  return relevant[0] || null;
}

function NewsImpactPill({ score }) {
  const numeric = Number(score || 0);
  const tone =
    numeric >= 85
      ? "border-red-500/30 bg-red-500/10 text-red-300"
      : numeric >= 70
        ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
        : "border-white/10 bg-white/5 text-slate-300";

  return (
    <span className={clsx("rounded-full border px-2.5 py-1 text-[10px] font-mono font-semibold", tone)}>
      Impact {numeric || 0}
    </span>
  );
}

function CommodityCard({ symbol, data, newsAlert, loading }) {
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
    <div className={clsx("card border flex flex-col gap-4 shadow-lg shadow-black/20 transition-all duration-200 hover:-translate-y-1 hover:shadow-2xl", primaryMeta.border)}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-semibold mb-0.5">{LABELS[symbol] || symbol}</p>
          <p className="text-xl font-bold font-mono text-slate-100 leading-none">
            {loading ? "…" : price != null ? normalizeNumber(price) : "—"}
          </p>
          <p className={clsx("text-xs mt-1 font-mono", up ? "text-emerald-400" : down ? "text-red-400" : "text-slate-500")}>
            {loading ? "" : changePct != null ? `${change >= 0 ? "+" : ""}${normalizeNumber(change)} (${changePct >= 0 ? "+" : ""}${changePct}%)` : "—"}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex gap-1">
            <span className={clsx("text-[10px] px-2 py-0.5 rounded font-bold", qMeta.bg, qMeta.color)}>Quick {qMeta.icon}</span>
            <span className={clsx("text-[10px] px-2 py-0.5 rounded font-bold", lMeta.bg, lMeta.color)}>Long {lMeta.icon}</span>
          </div>
          {newsAlert ? <NewsImpactPill score={newsAlert.impact_score} /> : null}
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

      <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2 flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">News insight</p>
          <span className="text-[10px] text-slate-500">
            {newsAlert?.source || "No critical news"}
          </span>
        </div>
        {newsAlert ? (
          <>
            <p className="text-xs text-slate-200 leading-snug">{newsAlert.title}</p>
            <p className="text-[10px] text-slate-400 leading-snug">
              {newsAlert.impact_reason || newsAlert.summary || "High-impact global cue tracked for this commodity."}
            </p>
          </>
        ) : (
          <p className="text-xs text-slate-500 leading-snug">
            No critical world-news trigger is currently elevating risk for this commodity.
          </p>
        )}
      </div>
    </div>
  );
}

export default function ProCommodities() {
  const [data, setData] = useState({});
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;

    const fetchData = () => {
      Promise.all([
        proApi.commodities().catch(() => ({})),
        analyticsApi.globalNewsAlerts().catch(() => ({ alerts: [] })),
      ])
        .then(([commodities, alertsPayload]) => {
          if (!alive) return;
          setData(commodities || {});
          setAlerts(Array.isArray(alertsPayload?.alerts) ? alertsPayload.alerts : []);
          setLoading(false);
        })
        .catch(() => {
          if (!alive) return;
          setData({});
          setAlerts([]);
          setLoading(false);
        });
    };

    fetchData();
    const id = setInterval(fetchData, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const alertMap = useMemo(() => {
    const next = {};
    for (const symbol of COMMODITIES) {
      next[symbol] = buildCommodityInsight(symbol, alerts);
    }
    return next;
  }, [alerts]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-slate-100">Commodities Desk</span>
        <span className="text-[10px] text-slate-500">MCX prices · Quick + long signals · News-driven insight · 15s refresh</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {COMMODITIES.map((sym) => (
          <CommodityCard
            key={sym}
            symbol={sym}
            data={data[sym]}
            newsAlert={alertMap[sym]}
            loading={loading}
          />
        ))}
      </div>
    </div>
  );
}
