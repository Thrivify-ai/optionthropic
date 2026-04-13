/**
 * Pro commodities desk with cleaner setup vs active language.
 */
import { useEffect, useState } from "react";
import clsx from "clsx";

import { proApi } from "../lib/proApi";
import { analyticsApi } from "../lib/api";

const COMMODITIES = ["CRUDEOIL", "NATGAS", "GOLD", "SILVER"];
const POLL_MS = 15_000;

const LABELS = {
  CRUDEOIL: "Crude Oil",
  NATGAS: "Natural Gas",
  GOLD: "Gold",
  SILVER: "Silver",
};

const META = {
  LONG: { label: "LONG", icon: "▲", color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/40" },
  SHORT: { label: "SHORT", icon: "▼", color: "text-red-400", bg: "bg-red-500/15", border: "border-red-500/40" },
  "HOLD LONG": { label: "HOLD LONG", icon: "HL", color: "text-cyan-300", bg: "bg-cyan-500/15", border: "border-cyan-500/40" },
  "HOLD SHORT": { label: "HOLD SHORT", icon: "HS", color: "text-cyan-300", bg: "bg-cyan-500/15", border: "border-cyan-500/40" },
  "EXIT LONG": { label: "EXIT LONG", icon: "XL", color: "text-amber-300", bg: "bg-amber-500/15", border: "border-amber-500/40" },
  "EXIT SHORT": { label: "EXIT SHORT", icon: "XS", color: "text-amber-300", bg: "bg-amber-500/15", border: "border-amber-500/40" },
  WAIT: { label: "WAIT", icon: "◆", color: "text-slate-400", bg: "bg-slate-500/10", border: "border-slate-500/20" },
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

function VolatilityPill({ ratio }) {
  const numeric = Number(ratio || 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  return (
    <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] font-mono font-semibold text-slate-300">
      Vol x{numeric.toFixed(2)}
    </span>
  );
}

function TradeLine({ trade, points, win, stop }) {
  const latestPoints = trade?.latest_points ?? points;
  const success = trade?.success_threshold_points ?? win;
  const stopPoints = trade?.stop_points ?? stop;
  const entry = trade?.entry_price;
  if (latestPoints == null && success == null && stopPoints == null && entry == null) return null;

  const numericPoints = Number(latestPoints ?? 0);
  return (
    <p className="mt-1 font-mono text-[10px] leading-snug text-slate-500">
      {entry != null ? `Entry ${normalizeNumber(entry)} · ` : ""}
      {latestPoints != null ? `Pts ${numericPoints >= 0 ? "+" : ""}${normalizeNumber(numericPoints)} · ` : ""}
      Win {success != null ? `+${normalizeNumber(success)}` : "-"} · Stop {stopPoints != null ? `-${normalizeNumber(stopPoints)}` : "-"}
    </p>
  );
}

function SetupPill({ state, direction, count, required }) {
  if (state !== "setup" || !direction) return null;
  return (
    <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-mono font-semibold text-amber-300">
      {direction} setup {count ?? 0}/{required ?? "?"}
    </span>
  );
}

function CommodityCard({ symbol, data, loading }) {
  const payload = data || {};
  const price = payload.price ?? null;
  const change = payload.change ?? 0;
  const changePct = payload.change_pct ?? null;
  const quickSig = (payload.quick_signal || "WAIT").trim();
  const longSig = (payload.long_signal || "WAIT").trim();
  const qMeta = META[quickSig] || META.WAIT;
  const lMeta = META[longSig] || META.WAIT;
  const up = change > 0;
  const down = change < 0;
  const primarySig = quickSig !== "WAIT" ? quickSig : longSig;
  const primaryMeta = META[primarySig] || META.WAIT;
  const newsAlert = payload.news_alert || null;

  return (
    <div
      className={clsx(
        "card flex flex-col gap-4 border shadow-lg shadow-black/20 transition-all duration-200 hover:-translate-y-1 hover:shadow-2xl",
        primaryMeta.border
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="mb-0.5 text-xs font-semibold uppercase tracking-widest text-slate-500">{LABELS[symbol] || symbol}</p>
          <p className="text-xl font-bold font-mono leading-none text-slate-100">
            {loading ? "…" : price != null ? normalizeNumber(price) : "—"}
          </p>
          <p className={clsx("mt-1 text-xs font-mono", up ? "text-emerald-400" : down ? "text-red-400" : "text-slate-500")}>
            {loading ? "" : changePct != null ? `${change >= 0 ? "+" : ""}${normalizeNumber(change)} (${changePct >= 0 ? "+" : ""}${changePct}%)` : "—"}
          </p>
        </div>

        <div className="flex flex-col items-end gap-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">Quick</span>
            <span className={clsx("rounded px-2 py-0.5 text-[10px] font-bold", qMeta.bg, qMeta.color)}>
              {qMeta.icon}
            </span>
            <span className="text-[10px] font-mono text-slate-400">{payload.quick_confidence ?? 0}%</span>
          </div>
          <SetupPill
            state={payload.quick_state}
            direction={payload.quick_setup_direction}
            count={payload.quick_confirmation_count}
            required={payload.quick_required_confirmations}
          />
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">Long</span>
            <span className={clsx("rounded px-2 py-0.5 text-[10px] font-bold", lMeta.bg, lMeta.color)}>
              {lMeta.icon}
            </span>
            <span className="text-[10px] font-mono text-slate-400">{payload.long_confidence ?? 0}%</span>
          </div>
          <SetupPill
            state={payload.long_state}
            direction={payload.long_setup_direction}
            count={payload.long_confirmation_count}
            required={payload.long_required_confirmations}
          />
          {newsAlert ? <NewsImpactPill score={payload.news_impact_score} /> : null}
          <VolatilityPill ratio={payload.quick_volatility_ratio || payload.long_volatility_ratio} />
        </div>
      </div>

      <div className="rounded-lg border border-surface-border/50 px-3 py-2">
        <p className="text-[11px] font-medium leading-snug text-slate-300">
          {payload.explanation || "No data yet."}
        </p>
        {payload.quick_reason ? <p className="mt-1 text-[10px] text-slate-500">Quick: {payload.quick_reason}</p> : null}
        <TradeLine
          trade={payload.quick_trade}
          points={payload.quick_current_points}
          win={payload.quick_success_threshold_points}
          stop={payload.quick_stop_points}
        />
        {payload.long_reason ? <p className="mt-1 text-[10px] text-slate-500">Long: {payload.long_reason}</p> : null}
        <TradeLine
          trade={payload.long_trade}
          points={payload.long_current_points}
          win={payload.long_success_threshold_points}
          stop={payload.long_stop_points}
        />
      </div>

      <div className="rounded-lg border border-surface-border/50 bg-surface/20 px-3 py-2">
        <div className="mb-1 flex items-center justify-between gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">News insight</p>
          <span className="text-[10px] text-slate-500">{payload.news_source || "No critical news"}</span>
        </div>
        {newsAlert ? (
          <>
            <p className="text-xs leading-snug text-slate-200">{payload.news_title || newsAlert.title}</p>
            <p className="text-[10px] leading-snug text-slate-400">
              {payload.news_reason || newsAlert.impact_reason || newsAlert.summary || "High-impact global cue tracked for this commodity."}
            </p>
          </>
        ) : (
          <p className="text-xs leading-snug text-slate-500">
            No critical world-news trigger is currently elevating risk for this commodity.
          </p>
        )}
      </div>
    </div>
  );
}

export default function ProCommodities() {
  const [data, setData] = useState({});
  const [loading, setLoading] = useState(true);
  const [marketStatus, setMarketStatus] = useState(null);

  useEffect(() => {
    let alive = true;

    const fetchData = () => {
      proApi
        .commodities()
        .then((commodities) => {
          if (!alive) return;
          setData(commodities || {});
          setLoading(false);
        })
        .catch(() => {
          if (!alive) return;
          setData({});
          setLoading(false);
        });
    };

    const fetchStatus = () =>
      analyticsApi
        .marketStatus()
        .then((status) => {
          if (alive) setMarketStatus(status);
          return Boolean(status?.mcx?.is_open);
        })
        .catch(() => false);

    fetchData();
    fetchStatus();
    const id = setInterval(async () => {
      const mcxOpen = await fetchStatus();
      if (mcxOpen) fetchData();
    }, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const mcxOpen = Boolean(marketStatus?.mcx?.is_open);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-slate-100">Commodities Desk</span>
          <span className="text-[10px] text-slate-500">MCX prices · managed quick and long reads · news context</span>
        </div>
        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300">
          {mcxOpen ? "MCX live · 15s refresh" : `${marketStatus?.mcx?.reason || "MCX status"} · stable`}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {COMMODITIES.map((symbol) => (
          <CommodityCard key={symbol} symbol={symbol} data={data[symbol]} loading={loading} />
        ))}
      </div>
    </div>
  );
}
