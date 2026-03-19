/**
 * Section 2 — Trade Signals
 * Backend-driven multi-timeframe signal cards styled to match Market Sentiment.
 */
import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];

const SIGNAL_META = {
  "Buy CE": {
    label:  "BUY CE",
    icon:   "▲",
    color:  "text-emerald-400",
    bg:     "bg-emerald-500/15",
    border: "border-emerald-500/40",
    badge:  "bg-emerald-500/15 text-emerald-400",
    conf:   "HIGH CONFIDENCE",
    desc:   "Bullish — buy calls",
  },
  "Buy PE": {
    label:  "BUY PE",
    icon:   "▼",
    color:  "text-red-400",
    bg:     "bg-red-500/15",
    border: "border-red-500/40",
    badge:  "bg-red-500/15 text-red-400",
    conf:   "HIGH CONFIDENCE",
    desc:   "Bearish — buy puts",
  },
  Wait: {
    label:  "WAIT",
    icon:   "◆",
    color:  "text-yellow-400",
    bg:     "bg-yellow-500/15",
    border: "border-yellow-500/40",
    badge:  "bg-yellow-500/15 text-yellow-400",
    conf:   "LOW CONFIDENCE",
    desc:   "No clear consensus",
  },
};

function BiasTag({ label, bias }) {
  const color =
    bias === "Bullish" ? "text-emerald-400 bg-emerald-500/15" :
    bias === "Bearish" ? "text-red-400 bg-red-500/15"         :
                        "text-yellow-400 bg-yellow-500/15";
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className={clsx("text-[9px] font-bold px-1.5 py-0.5 rounded", color)}>
        {bias ?? "—"}
      </span>
      <span className="text-[8px] text-slate-600 uppercase tracking-wider">{label}</span>
    </div>
  );
}

const QUICK_META = {
  "Buy CE": { label: "BUY CE", icon: "▲", color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/30" },
  "Buy PE": { label: "BUY PE", icon: "▼", color: "text-red-400",     bg: "bg-red-500/15",     border: "border-red-500/30"     },
  "Watch":  { label: "WATCH",  icon: "◉", color: "text-amber-400",   bg: "bg-amber-500/15",   border: "border-amber-500/30"   },
  "Wait":   { label: "WAIT",   icon: "◆", color: "text-slate-400",   bg: "bg-slate-500/10",   border: "border-slate-500/20"   },
};

function SignalCard({ symbol, data, quickData, loading, error }) {
  if (loading) {
    return (
      <div className="card animate-pulse min-h-[320px] flex flex-col gap-3 p-5 shadow-lg shadow-black/10">
        <div className="h-4 bg-surface-border/50 rounded w-20" />
        <div className="h-7 bg-surface-border/50 rounded w-36" />
        <div className="h-2 bg-surface-border/30 rounded w-full mt-2" />
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-3 bg-surface-border/20 rounded w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="card border border-surface-border min-h-[320px] flex flex-col items-center justify-center gap-2 p-6 shadow-lg shadow-black/10">
        <span className="text-2xl">📭</span>
        <p className="font-semibold text-slate-300">{symbol}</p>
        <p className="text-xs text-slate-500 text-center">Signal unavailable</p>
      </div>
    );
  }

  const signal     = data?.signal     ?? "Wait";
  const confidence = Number(data?.confidence ?? 0);
  const support    = data?.support    != null ? Number(data.support).toLocaleString("en-IN")    : null;
  const resistance = data?.resistance != null ? Number(data.resistance).toLocaleString("en-IN") : null;
  const meta       = SIGNAL_META[signal] ?? SIGNAL_META.Wait;

  // Confidence label matches MarketBiasPanel style
  const confStyle =
    confidence >= 70 ? { label: "HIGH",   color: "text-emerald-400", bg: "bg-emerald-500/15" } :
    confidence >= 45 ? { label: "MEDIUM", color: "text-yellow-400",  bg: "bg-yellow-500/15"  } :
                       { label: "LOW",    color: "text-slate-400",   bg: "bg-slate-500/15"   };

  return (
    <div className={clsx("card border flex flex-col gap-4 shadow-lg shadow-black/20", meta.border)}>

      {/* ── Header row — mirrors SentimentCard exactly ──────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-semibold mb-0.5">
            {symbol}
          </p>
          <p className={clsx("text-2xl font-bold leading-none", meta.color)}>
            {meta.icon} {signal}
          </p>
          <p className="text-xs text-slate-500 mt-1">{meta.desc}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className={clsx("text-xs font-bold px-2.5 py-1 rounded-full", meta.bg, meta.color)}>
            {meta.icon} {meta.label}
          </span>
          <span className={clsx("text-[11px] font-semibold px-2 py-0.5 rounded-full", confStyle.bg, confStyle.color)}>
            {confStyle.label} CONFIDENCE
          </span>
        </div>
      </div>

      {/* ── Confidence bar — same layout as probability bar ──────────────── */}
      <div>
        <div className="flex justify-between text-[11px] mb-1">
          <span className={clsx("font-semibold", confStyle.color)}>
            Confidence {confidence}%
          </span>
          <span className="text-slate-500 font-semibold">
            Threshold 70%
          </span>
        </div>
        <div className="h-2.5 rounded-full bg-surface-border overflow-hidden flex">
          <div
            className={clsx(
              "h-full transition-all duration-700 rounded-l-full",
              confidence >= 70
                ? "bg-gradient-to-r from-emerald-600 to-emerald-400"
                : confidence >= 45
                  ? "bg-gradient-to-r from-yellow-600 to-yellow-400"
                  : "bg-slate-600"
            )}
            style={{ width: `${confidence}%` }}
          />
          <div
            className="h-full bg-surface-border/40 transition-all duration-700 rounded-r-full"
            style={{ width: `${100 - confidence}%` }}
          />
        </div>
        <p className="text-[10px] text-slate-600 mt-1">
          Multi-timeframe: PCR · OI buildup · Writer dominance · Price action
        </p>
      </div>

      {/* ── Support / Resistance tiles — identical to SentimentCard ─────── */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 px-3 py-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Support</p>
          <p className="text-sm font-bold font-mono text-emerald-400">
            {support ?? "—"}
          </p>
          <p className="text-[10px] text-slate-600">Put OI wall</p>
        </div>
        <div className="rounded-lg bg-red-500/5 border border-red-500/20 px-3 py-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Resistance</p>
          <p className="text-sm font-bold font-mono text-red-400">
            {resistance ?? "—"}
          </p>
          <p className="text-[10px] text-slate-600">Call OI wall</p>
        </div>
      </div>

      {/* ── Multi-timeframe bias chips ────────────────────────────────────── */}
      <div className="border-t border-surface-border/60 pt-3">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
          Timeframe Alignment
        </p>
        <div className="flex items-center justify-around">
          <BiasTag label="5 min"  bias={data?.bias_5m}  />
          <BiasTag label="30 min" bias={data?.bias_30m} />
          <BiasTag label="60 min" bias={data?.bias_60m} />
        </div>
      </div>

      {/* ── Reason ───────────────────────────────────────────────────────── */}
      <div className="border-t border-surface-border/60 pt-3">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
          Signal Reason
        </p>
        <p className="text-xs text-slate-300 leading-snug">
          {data?.reason || "Awaiting data."}
        </p>
      </div>

      {/* ── Quick Signal (10 min OI buildup) ─────────────────────────────── */}
      {(() => {
        const qs   = quickData?.quick_signal ?? "Wait";
        const qm   = QUICK_META[qs] ?? QUICK_META.Wait;
        const type = quickData?.buildup_type;
        const strike = quickData?.key_strike
          ? Number(quickData.key_strike).toLocaleString("en-IN")
          : null;
        const strength  = quickData?.strength;
        const hasSignal = qs !== "Wait";
        return (
          <div className={clsx(
            "border rounded-lg px-3 py-2.5 flex flex-col gap-1.5",
            hasSignal ? qm.border : "border-surface-border/40"
          )}>
            {/* header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  ⚡ Quick Signal
                </span>
                <span className="text-[9px] text-slate-600 font-mono">10 min OI</span>
              </div>
              <div className="flex items-center gap-1.5">
                {strength && (
                  <span className="text-[9px] font-semibold text-slate-500 uppercase">
                    {strength}
                  </span>
                )}
                <span className={clsx("text-[10px] font-bold px-2 py-0.5 rounded-full", qm.bg, qm.color)}>
                  {qm.icon} {qm.label}
                </span>
              </div>
            </div>
            {/* buildup type + key strike */}
            {(type || strike) && (
              <div className="flex items-center gap-2 flex-wrap">
                {type && (
                  <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded", qm.bg, qm.color)}>
                    {type}
                  </span>
                )}
                {strike && (
                  <span className="text-[10px] text-slate-400 font-mono">
                    @ {strike}
                  </span>
                )}
              </div>
            )}
            {/* reason */}
            <p className="text-[10px] text-slate-400 leading-snug">
              {quickData?.reason || "Scanning last 10 min…"}
            </p>
            {/* news placeholder */}
            <div className="flex items-center gap-1.5 pt-0.5 border-t border-surface-border/30 mt-0.5">
              <span className="text-[9px] text-slate-600">📰 News boost:</span>
              <span className="text-[9px] text-slate-600 italic">
                {quickData?.news_boost ? "Active" : "Coming soon"}
              </span>
            </div>
          </div>
        );
      })()}

      <p className="text-[9px] text-slate-600 border-t border-surface-border/40 pt-2">
        ⚠ Informational only · Not financial advice
      </p>
    </div>
  );
}

export default function TradeSignalsPanel({ refreshTick }) {
  const [overview, setOverview] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const first = Object.keys(overview).length === 0;
    if (first) setLoading(true);
    setError(null);
    analyticsApi.dashboardOverview()
      .then((data) => setOverview(data?.symbols || {}))
      .catch(() => setError("Signal unavailable"))
      .finally(() => { if (first) setLoading(false); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {SYMBOLS.map((s) => (
        <SignalCard
          key={s}
          symbol={s}
          data={overview[s]?.trading_signal}
          quickData={overview[s]?.quick_signal}
          loading={loading}
          error={error}
        />
      ))}
    </div>
  );
}
