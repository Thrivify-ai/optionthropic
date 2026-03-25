import { useEffect, useState } from "react";
import clsx from "clsx";

import { analyticsApi } from "../lib/api";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];

const fmt = (value, digits = 0) => {
  const num = Number(value);
  return value == null || Number.isNaN(num) ? "-" : num.toFixed(digits);
};

function deriveAll(pcr, gamma, maxPain, traps, flow) {
  const pcrOi = Number(pcr?.pcr_oi || 0);
  const spot = Number(gamma?.underlying_price || 0);
  const callWall = Number(gamma?.call_wall || 0);
  const putWall = Number(gamma?.put_wall || 0);
  const maxPainStrike = Number(maxPain?.max_pain_strike || 0);

  let score = 0;
  let signals = 0;

  if (pcrOi > 0) {
    signals += 1;
    if (pcrOi > 1.2) score += 2;
    else if (pcrOi > 1.0) score += 1;
    else if (pcrOi < 0.8) score -= 2;
    else score -= 1;
  }

  if (spot && callWall && putWall) {
    signals += 1;
    const range = callWall - putWall;
    const position = range > 0 ? (spot - putWall) / range : 0.5;
    if (position > 0.65) score += 1;
    else if (position < 0.35) score -= 1;
  }

  if (spot && maxPainStrike) {
    signals += 1;
    if (maxPainStrike > spot * 1.005) score += 1;
    else if (maxPainStrike < spot * 0.995) score -= 1;
  }

  const flows = flow?.flows || [];
  const summary = flow?.summary || {};
  const callPremium = Number(summary.total_call_premium || 0);
  const putPremium = Number(summary.total_put_premium || 0);

  if (flows.length) {
    signals += 1;
    const dominant = summary.dominant_flow || "";
    if (dominant === "put_writing" || putPremium > callPremium * 1.5) score += 1;
    else if (dominant === "call_writing" || callPremium > putPremium * 1.5) score -= 1;
    else if (dominant === "put_buying") score -= 1;
    else if (dominant === "call_buying") score += 1;
  }

  let bias;
  if (score >= 2) {
    bias = {
      label: "BULLISH",
      color: "text-emerald-300",
      bg: "bg-emerald-500/10",
      border: "border-emerald-500/20",
    };
  } else if (score <= -2) {
    bias = {
      label: "BEARISH",
      color: "text-red-300",
      bg: "bg-red-500/10",
      border: "border-red-500/20",
    };
  } else {
    bias = {
      label: "NEUTRAL",
      color: "text-amber-300",
      bg: "bg-amber-500/10",
      border: "border-amber-500/20",
    };
  }

  let upside = 50;
  if (pcrOi > 0) upside = 50 + Math.min(25, (pcrOi - 1.0) * 30);
  if (spot && callWall && putWall) {
    const range = callWall - putWall;
    const position = range > 0 ? (spot - putWall) / range : 0.5;
    upside = upside * 0.7 + position * 100 * 0.3;
  }
  if (spot && maxPainStrike) upside += ((maxPainStrike - spot) / (spot || 1)) * 100 * 0.5;
  upside = Math.max(10, Math.min(90, Math.round(upside)));

  const maxScore = signals * 2;
  const alignedRatio = maxScore > 0 ? Math.abs(score) / maxScore : 0;
  let confidence;
  if (alignedRatio >= 0.7) confidence = { label: "HIGH", color: "text-emerald-300", bg: "bg-emerald-500/10" };
  else if (alignedRatio >= 0.4) confidence = { label: "MEDIUM", color: "text-amber-300", bg: "bg-amber-500/10" };
  else confidence = { label: "LOW", color: "text-slate-300", bg: "bg-white/5" };

  let smartMoney = "No significant smart money activity";
  if (flows.length) {
    const dominant = summary.dominant_flow || "";
    if (dominant === "put_writing" || putPremium > callPremium * 1.5) {
      smartMoney = "Put writers are actively defending support.";
    } else if (dominant === "call_writing" || callPremium > putPremium * 1.5) {
      smartMoney = "Call writers are capping resistance.";
    } else if (dominant === "put_buying") {
      smartMoney = "Protective put buying suggests caution.";
    } else if (dominant === "call_buying") {
      smartMoney = "Call buyers are leaning into upside conviction.";
    }
  }

  const trapList = traps?.traps || [];
  const trapText = trapList.length
    ? trapList.slice(0, 2).map((item) => `${Number(item.strike).toLocaleString("en-IN")}`).join(" | ")
    : null;

  return {
    bias,
    upside,
    downside: 100 - upside,
    confidence,
    smartMoney,
    trapText,
    score,
    signals,
    pcrOi,
  };
}

function SentimentCard({ symbol, zerodhaStatus, raw, loading, noData }) {
  if (loading) {
    return (
      <div className="card min-h-[330px] animate-pulse">
        <div className="space-y-3">
          <div className="h-4 w-20 rounded bg-surface-border/50" />
          <div className="h-8 w-36 rounded bg-surface-border/40" />
          <div className="h-20 rounded-[1.25rem] bg-surface-border/20" />
          <div className="h-24 rounded-[1.25rem] bg-surface-border/20" />
        </div>
      </div>
    );
  }

  if (noData) {
    const status = zerodhaStatus || {};
    let message = "No data available yet.";

    if (symbol === "SENSEX") {
      if (!status.token_set) message = "Set ZERODHA_ACCESS_TOKEN in .env and restart the backend.";
      else if (!status.token_valid) message = "Zerodha token is invalid or expired. Refresh it and restart the backend.";
      else if (status.bfo_sensex_instruments === 0) message = "Enable BSE F&O in Zerodha to load SENSEX options.";
      else message = "SENSEX data should appear shortly.";
    } else if (!status.token_valid && status.data_source === "ZERODHA") {
      message = "Refresh the Zerodha token to resume live data.";
    }

    return (
      <div className="card flex min-h-[330px] items-center justify-center">
        <div className="text-center">
          <p className="section-kicker">{symbol}</p>
          <p className="mt-2 text-sm text-slate-400">{message}</p>
          {status.message ? <p className="mt-2 text-[11px] text-slate-500">{status.message}</p> : null}
        </div>
      </div>
    );
  }

  const { pcr, sr, gamma, mp, traps, flow } = raw;
  const derived = deriveAll(pcr, gamma, mp, traps, flow);
  const spot = Number(gamma?.underlying_price || sr?.underlying_price || 0);
  const support = sr?.support?.[0]?.strike;
  const resistance = sr?.resistance?.[0]?.strike;

  return (
    <div className={clsx("card flex flex-col gap-4 border", derived.bias.border)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="section-kicker">{symbol}</p>
          <p className="mt-2 text-2xl font-semibold text-slate-100">
            {spot ? spot.toLocaleString("en-IN") : "-"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            PCR <span className={derived.pcrOi > 1 ? "text-emerald-300" : "text-red-300"}>{fmt(derived.pcrOi, 2)}</span>
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className={clsx("rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]", derived.bias.bg, derived.bias.color)}>
            {derived.bias.label}
          </span>
          <span className={clsx("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]", derived.confidence.bg, derived.confidence.color)}>
            {derived.confidence.label}
          </span>
        </div>
      </div>

      <div className="rounded-[1.3rem] border border-surface-border bg-white/5 p-3">
        <div className="mb-1 flex items-center justify-between text-[11px]">
          <span className="font-semibold text-emerald-300">Upside {derived.upside}%</span>
          <span className="font-semibold text-red-300">Downside {derived.downside}%</span>
        </div>
        <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-border">
          <div
            className="h-full rounded-l-full bg-gradient-to-r from-emerald-500 to-brand-400 transition-all duration-700"
            style={{ width: `${derived.upside}%` }}
          />
          <div
            className="h-full rounded-r-full bg-gradient-to-l from-red-500 to-red-300 transition-all duration-700"
            style={{ width: `${derived.downside}%` }}
          />
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          Built from {derived.signals} aligned inputs: PCR, gamma walls, max pain, and options flow.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/5 px-3 py-3">
          <p className="text-[10px] text-slate-500">Support</p>
          <p className="mt-1 font-mono text-sm font-semibold text-emerald-300">
            {support ? Number(support).toLocaleString("en-IN") : "-"}
          </p>
          <p className="mt-1 text-[10px] text-slate-500">Put OI wall</p>
        </div>
        <div className="rounded-xl border border-red-500/15 bg-red-500/5 px-3 py-3">
          <p className="text-[10px] text-slate-500">Resistance</p>
          <p className="mt-1 font-mono text-sm font-semibold text-red-300">
            {resistance ? Number(resistance).toLocaleString("en-IN") : "-"}
          </p>
          <p className="mt-1 text-[10px] text-slate-500">Call OI wall</p>
        </div>
      </div>

      <div className="rounded-[1.25rem] border border-surface-border bg-white/5 p-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Smart Money</p>
        <p className="mt-2 text-sm leading-relaxed text-slate-300">{derived.smartMoney}</p>
      </div>

      <div className="rounded-[1.25rem] border border-surface-border bg-white/5 p-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Liquidity Trap</p>
        <p className={clsx("mt-2 text-sm", derived.trapText ? "text-amber-300" : "text-slate-400")}>
          {derived.trapText || "None detected"}
        </p>
      </div>
    </div>
  );
}

export default function MarketBiasPanel({ onDataLoaded, refreshTick }) {
  const [zerodhaStatus, setZerodhaStatus] = useState(null);
  const [overview, setOverview] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    analyticsApi.zerodhaStatus().then(setZerodhaStatus);
  }, []);

  useEffect(() => {
    const firstLoad = Object.keys(overview).length === 0;
    if (firstLoad) setLoading(true);

    analyticsApi
      .dashboardOverview()
      .then((data) => {
        setOverview(data?.symbols || {});
        onDataLoaded?.();
      })
      .finally(() => {
        if (firstLoad) setLoading(false);
      });
  }, [refreshTick, onDataLoaded]);

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {SYMBOLS.map((symbol) => (
        <SentimentCard
          key={symbol}
          symbol={symbol}
          zerodhaStatus={zerodhaStatus}
          raw={overview[symbol] ? {
            pcr: overview[symbol]?.options_chain?.pcr,
            sr: overview[symbol]?.options_chain?.support_resistance,
            gamma: overview[symbol]?.gamma_walls,
            mp: overview[symbol]?.max_pain,
            traps: overview[symbol]?.liquidity_traps,
            flow: overview[symbol]?.options_flow,
          } : null}
          loading={loading}
          noData={!loading && !overview[symbol]}
        />
      ))}
    </div>
  );
}
