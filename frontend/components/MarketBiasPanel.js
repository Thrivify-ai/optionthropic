/**
 * Section 1 — Market Sentiment
 * Shows live sentiment, probability, key levels and smart money for all 3 indices.
 */
import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];

const fmt = (v, d = 0) => {
  const n = Number(v);
  return v == null || isNaN(n) ? "—" : n.toFixed(d);
};

// ─── Signal derivation ────────────────────────────────────────────────────────

function deriveAll(pcr, gamma, mp, traps, flow) {
  const pcrOi = Number(pcr?.pcr_oi || 0);
  const spot   = Number(gamma?.underlying_price || 0);
  const callW  = Number(gamma?.call_wall || 0);
  const putW   = Number(gamma?.put_wall  || 0);
  const maxP   = Number(mp?.max_pain_strike || 0);

  // ── Bias score (–4 → +4) ──
  let score = 0;
  let signals = 0;

  if (pcrOi > 0) {
    signals++;
    if (pcrOi > 1.2)      score += 2;
    else if (pcrOi > 1.0) score += 1;
    else if (pcrOi < 0.8) score -= 2;
    else                   score -= 1;
  }

  if (spot && callW && putW) {
    signals++;
    const rng = callW - putW;
    const pos = rng > 0 ? (spot - putW) / rng : 0.5;
    if (pos > 0.65)      score += 1;
    else if (pos < 0.35) score -= 1;
  }

  if (spot && maxP) {
    signals++;
    if (maxP > spot * 1.005)      score += 1;
    else if (maxP < spot * 0.995) score -= 1;
  }

  const flows = flow?.flows || [];
  const summary = flow?.summary || {};
  const callPrem = Number(summary.total_call_premium || 0);
  const putPrem  = Number(summary.total_put_premium  || 0);
  if (flows.length) {
    signals++;
    const dom = summary.dominant_flow || "";
    if (dom === "put_writing" || putPrem > callPrem * 1.5) score += 1;
    else if (dom === "call_writing" || callPrem > putPrem * 1.5) score -= 1;
    else if (dom === "put_buying") score -= 1;
    else if (dom === "call_buying") score += 1;
  }

  // ── Bias label ──
  let bias;
  if (score >= 2)       bias = { label: "BULLISH", icon: "▲", color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/40" };
  else if (score <= -2) bias = { label: "BEARISH", icon: "▼", color: "text-red-400",     bg: "bg-red-500/15",     border: "border-red-500/40"     };
  else                  bias = { label: "NEUTRAL", icon: "◆", color: "text-yellow-400",  bg: "bg-yellow-500/15", border: "border-yellow-500/40"  };

  // ── Upside probability (10–90 clamped) ──
  let up = 50;
  if (pcrOi > 0) up = 50 + Math.min(25, (pcrOi - 1.0) * 30);
  if (spot && callW && putW) {
    const rng = callW - putW;
    const pos = rng > 0 ? (spot - putW) / rng : 0.5;
    up = up * 0.7 + pos * 100 * 0.3;
  }
  if (spot && maxP) up += ((maxP - spot) / (spot || 1)) * 100 * 0.5;
  up = Math.max(10, Math.min(90, Math.round(up)));

  // ── Confidence based on signal alignment ──
  const maxScore = signals * 2;
  const alignedRatio = maxScore > 0 ? Math.abs(score) / maxScore : 0;
  let confidence;
  if      (alignedRatio >= 0.7) confidence = { label: "HIGH",   color: "text-emerald-400", bg: "bg-emerald-500/15" };
  else if (alignedRatio >= 0.4) confidence = { label: "MEDIUM", color: "text-yellow-400",  bg: "bg-yellow-500/15"  };
  else                          confidence = { label: "LOW",     color: "text-slate-400",   bg: "bg-slate-500/15"   };

  // ── Smart money text ──
  let smartMoney = "No significant smart money activity";
  if (flows.length) {
    const dom = summary.dominant_flow || "";
    if (dom === "put_writing" || putPrem > callPrem * 1.5) smartMoney = "Put writers actively defending support";
    else if (dom === "call_writing" || callPrem > putPrem * 1.5) smartMoney = "Call writers capping resistance";
    else if (dom === "put_buying") smartMoney = "Protective put buying — hedging detected";
    else if (dom === "call_buying") smartMoney = "Bullish call buying — upside bets placed";
    else smartMoney = putPrem > callPrem ? "Put flow dominant — cautious bias" : "Call flow dominant — optimistic bias";
  }

  // ── Liquidity trap ──
  const trapList = traps?.traps || [];
  const trapText = trapList.length
    ? trapList.slice(0, 2).map(t => `${Number(t.strike).toLocaleString("en-IN")}`).join(" · ")
    : null;

  return { bias, up, down: 100 - up, confidence, smartMoney, trapText, score, signals, pcrOi };
}

// ─── Single index card ────────────────────────────────────────────────────────

function SentimentCard({ symbol, zerodhaStatus, raw, loading, noData }) {
  if (loading) return (
    <div className="card animate-pulse min-h-[320px] flex flex-col gap-3 p-5 shadow-lg shadow-black/10">
      <div className="h-4 bg-surface-border/50 rounded w-20" />
      <div className="h-7 bg-surface-border/50 rounded w-36" />
      <div className="h-2 bg-surface-border/30 rounded w-full mt-2" />
      {[1,2,3,4].map(i => <div key={i} className="h-3 bg-surface-border/20 rounded w-full" />)}
    </div>
  );

  if (noData) {
    const z = zerodhaStatus || {};
    let msg = "No data available yet.";
    if (symbol === "SENSEX") {
      if (!z.token_set) msg = "Set ZERODHA_ACCESS_TOKEN in .env and restart the backend.";
      else if (!z.token_valid) msg = "Zerodha token is invalid or expired. Run generate_token.py, copy the new token into .env as ZERODHA_ACCESS_TOKEN, then run: docker compose up --force-recreate --no-deps -d backend";
      else if (z.bfo_sensex_instruments === 0) msg = "Token is valid but no SENSEX options found. Enable BSE F&O (BFO) segment in your Zerodha account (Kite → Account → Segments).";
      else msg = "SENSEX data should appear in 1–2 minutes.";
    } else {
      if (!z.token_valid && z.data_source === "ZERODHA") msg = "Refresh Zerodha token (generate_token.py → .env → restart backend) to get live data.";
    }
    return (
      <div className="card border border-surface-border min-h-[320px] flex flex-col items-center justify-center gap-2 p-6 shadow-lg shadow-black/10">
        <span className="text-2xl">📭</span>
        <p className="font-semibold text-slate-300">{symbol}</p>
        <p className="text-xs text-slate-500 text-center leading-relaxed">{msg}</p>
        {z.message && <p className="text-[10px] text-slate-600 mt-1">{z.message}</p>}
      </div>
    );
  }

  const { pcr, sr, gamma, mp, traps, flow } = raw;
  const d = deriveAll(pcr, gamma, mp, traps, flow);

  const spot        = Number(gamma?.underlying_price || sr?.underlying_price || 0);
  const topSupport  = sr?.support?.[0]?.strike;
  const topResist   = sr?.resistance?.[0]?.strike;

  return (
    <div className={clsx("card border flex flex-col gap-4 shadow-lg shadow-black/20", d.bias.border)}>

      {/* Header row */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-semibold mb-0.5">{symbol}</p>
          <p className="text-2xl font-bold font-mono text-slate-100 leading-none">
            {spot ? spot.toLocaleString("en-IN") : "—"}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            PCR · <span className={d.pcrOi > 1 ? "text-emerald-400" : "text-red-400"}>
              {fmt(d.pcrOi, 2)}
            </span>
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className={clsx("text-xs font-bold px-2.5 py-1 rounded-full", d.bias.bg, d.bias.color)}>
            {d.bias.icon} {d.bias.label}
          </span>
          <span className={clsx("text-[11px] font-semibold px-2 py-0.5 rounded-full", d.confidence.bg, d.confidence.color)}>
            {d.confidence.label} CONFIDENCE
          </span>
        </div>
      </div>

      {/* Probability bar */}
      <div>
        <div className="flex justify-between text-[11px] mb-1">
          <span className="text-emerald-400 font-semibold">▲ Upside {d.up}%</span>
          <span className="text-red-400 font-semibold">{d.down}% Downside ▼</span>
        </div>
        <div className="h-2.5 rounded-full bg-surface-border overflow-hidden flex">
          <div className="h-full bg-gradient-to-r from-emerald-600 to-emerald-400 transition-all duration-700 rounded-l-full"
               style={{ width: `${d.up}%` }} />
          <div className="h-full bg-gradient-to-l from-red-600 to-red-400 transition-all duration-700 rounded-r-full"
               style={{ width: `${d.down}%` }} />
        </div>
        <p className="text-[10px] text-slate-600 mt-1">
          Based on {d.signals} signal{d.signals !== 1 ? "s" : ""}: PCR · Gamma walls · Max pain · Smart money
        </p>
      </div>

      {/* Support / Resistance */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 px-3 py-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Support</p>
          <p className="text-sm font-bold font-mono text-emerald-400">
            {topSupport ? Number(topSupport).toLocaleString("en-IN") : "—"}
          </p>
          <p className="text-[10px] text-slate-600">Put OI wall</p>
        </div>
        <div className="rounded-lg bg-red-500/5 border border-red-500/20 px-3 py-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Resistance</p>
          <p className="text-sm font-bold font-mono text-red-400">
            {topResist ? Number(topResist).toLocaleString("en-IN") : "—"}
          </p>
          <p className="text-[10px] text-slate-600">Call OI wall</p>
        </div>
      </div>

      {/* Smart Money */}
      <div className="border-t border-surface-border/60 pt-3">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Smart Money</p>
        <p className="text-xs text-slate-300 leading-snug">{d.smartMoney}</p>
      </div>

      {/* Liquidity Trap */}
      <div className="border-t border-surface-border/60 pt-3">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Liquidity Trap</p>
        {d.trapText
          ? <p className="text-xs text-yellow-400 font-mono">⚠ {d.trapText}</p>
          : <p className="text-xs text-slate-500">None detected</p>}
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
    const first = Object.keys(overview).length === 0;
    if (first) setLoading(true);
    analyticsApi.dashboardOverview().then((data) => {
      setOverview(data?.symbols || {});
      onDataLoaded?.();
    }).finally(() => {
      if (first) setLoading(false);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {SYMBOLS.map(s => (
        <SentimentCard
          key={s}
          symbol={s}
          zerodhaStatus={zerodhaStatus}
          raw={overview[s] ? {
            pcr: overview[s]?.options_chain?.pcr,
            sr: overview[s]?.options_chain?.support_resistance,
            gamma: overview[s]?.gamma_walls,
            mp: overview[s]?.max_pain,
            traps: overview[s]?.liquidity_traps,
            flow: overview[s]?.options_flow,
          } : null}
          loading={loading}
          noData={!loading && !overview[s]}
        />
      ))}
    </div>
  );
}
