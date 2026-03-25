import { useEffect, useState } from "react";
import clsx from "clsx";

import { analyticsApi } from "../lib/api";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];

const SIGNAL_META = {
  "Buy CE": {
    label: "BUY CE",
    color: "text-emerald-300",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/20",
    desc: "Bullish call setup",
  },
  "Buy PE": {
    label: "BUY PE",
    color: "text-red-300",
    bg: "bg-red-500/10",
    border: "border-red-500/20",
    desc: "Bearish put setup",
  },
  Wait: {
    label: "WAIT",
    color: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    desc: "No aligned entry",
  },
  "Hold CE": {
    label: "HOLD CE",
    color: "text-cyan-300",
    bg: "bg-cyan-500/10",
    border: "border-cyan-500/20",
    desc: "Bullish trade remains valid",
  },
  "Hold PE": {
    label: "HOLD PE",
    color: "text-cyan-300",
    bg: "bg-cyan-500/10",
    border: "border-cyan-500/20",
    desc: "Bearish trade remains valid",
  },
  "Exit CE": {
    label: "EXIT CE",
    color: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    desc: "Close the bullish trade",
  },
  "Exit PE": {
    label: "EXIT PE",
    color: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    desc: "Close the bearish trade",
  },
};

function BiasTag({ label, bias }) {
  const tone =
    bias === "Bullish"
      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
      : bias === "Bearish"
        ? "border-red-500/20 bg-red-500/10 text-red-300"
        : "border-white/10 bg-white/5 text-slate-300";

  return (
    <div className={clsx("rounded-xl border px-3 py-2 text-center", tone)}>
      <p className="text-xs font-semibold">{bias ?? "-"}</p>
      <p className="mt-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
    </div>
  );
}

function ConfidenceBar({ confidence }) {
  const style =
    confidence >= 70
      ? { label: "HIGH", bar: "from-emerald-500 to-brand-400", text: "text-emerald-300" }
      : confidence >= 45
        ? { label: "MEDIUM", bar: "from-amber-500 to-yellow-400", text: "text-amber-300" }
        : { label: "LOW", bar: "from-slate-500 to-slate-400", text: "text-slate-300" };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className={clsx("font-semibold", style.text)}>Confidence {confidence}%</span>
        <span className="text-slate-500">{style.label}</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-surface-border">
        <div
          className={clsx("h-full rounded-full bg-gradient-to-r transition-all duration-700", style.bar)}
          style={{ width: `${confidence}%` }}
        />
      </div>
    </div>
  );
}

function SignalCard({ symbol, data, loading, error }) {
  if (loading) {
    return (
      <div className="card min-h-[300px] animate-pulse">
        <div className="space-y-3">
          <div className="h-4 w-20 rounded bg-surface-border/50" />
          <div className="h-8 w-40 rounded bg-surface-border/40" />
          <div className="h-20 rounded-[1.25rem] bg-surface-border/20" />
          <div className="h-24 rounded-[1.25rem] bg-surface-border/20" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card flex min-h-[300px] items-center justify-center">
        <div className="text-center">
          <p className="section-kicker">{symbol}</p>
          <p className="mt-2 text-sm text-slate-400">Signal unavailable</p>
        </div>
      </div>
    );
  }

  const signal = data?.signal ?? "Wait";
  const confidence = Number(data?.confidence ?? 0);
  const outlook = data?.outlook ?? data?.bias_60m ?? "Neutral";
  const state = data?.state ?? (signal === "Wait" ? "idle" : "active");
  const entryReady = Boolean(data?.entry_ready ?? signal !== "Wait");
  const support = data?.support != null ? Number(data.support).toLocaleString("en-IN") : null;
  const resistance = data?.resistance != null ? Number(data.resistance).toLocaleString("en-IN") : null;
  const meta = SIGNAL_META[signal] ?? SIGNAL_META.Wait;
  const trade = data?.trade ?? null;
  const entryPrice = trade?.entry_price != null ? Number(trade.entry_price).toLocaleString("en-IN") : null;
  const latestPoints = Number.isFinite(trade?.latest_points) ? trade.latest_points : null;
  const successThreshold = Number.isFinite(trade?.success_threshold_points) ? trade.success_threshold_points : null;
  const stopPoints = Number.isFinite(trade?.stop_points) ? trade.stop_points : null;

  const stateStyle =
    state === "active"
      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
      : state === "exit"
        ? "border-amber-500/20 bg-amber-500/10 text-amber-300"
      : state === "setup"
        ? "border-amber-500/20 bg-amber-500/10 text-amber-300"
        : state === "watch"
          ? "border-sky-500/20 bg-sky-500/10 text-sky-300"
          : "border-white/10 bg-white/5 text-slate-300";

  return (
    <div className={clsx("card flex flex-col gap-4 border", meta.border)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="section-kicker">{symbol}</p>
          <h3 className={clsx("mt-2 text-2xl font-semibold tracking-tight", meta.color)}>{signal}</h3>
          <p className="mt-1 text-xs text-slate-500">{meta.desc}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className={clsx("rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]", meta.bg, meta.color)}>
            {meta.label}
          </span>
          <span className={clsx("rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]", stateStyle)}>
            {String(state)}
          </span>
        </div>
      </div>

      <div className="rounded-[1.3rem] border border-surface-border bg-white/5 p-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-400">
            Outlook <span className="font-semibold text-slate-100">{outlook}</span>
          </p>
          <span className={clsx(
            "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]",
            entryReady ? "bg-brand-500/10 text-brand-300" : "bg-white/5 text-slate-300"
          )}>
            {entryReady ? "Entry ready" : "Waiting"}
          </span>
        </div>
        <div className="mt-3">
          <ConfidenceBar confidence={confidence} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/5 px-3 py-3">
          <p className="text-[10px] text-slate-500">Support</p>
          <p className="mt-1 font-mono text-sm font-semibold text-emerald-300">{support ?? "-"}</p>
          <p className="mt-1 text-[10px] text-slate-500">Put OI wall</p>
        </div>
        <div className="rounded-xl border border-red-500/15 bg-red-500/5 px-3 py-3">
          <p className="text-[10px] text-slate-500">Resistance</p>
          <p className="mt-1 font-mono text-sm font-semibold text-red-300">{resistance ?? "-"}</p>
          <p className="mt-1 text-[10px] text-slate-500">Call OI wall</p>
        </div>
      </div>

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
          Timeframe Alignment
        </p>
        <div className="grid grid-cols-3 gap-2">
          <BiasTag label="5 min" bias={data?.bias_5m} />
          <BiasTag label="30 min" bias={data?.bias_30m} />
          <BiasTag label="60 min" bias={data?.bias_60m} />
        </div>
      </div>

      <div className="rounded-[1.25rem] border border-surface-border bg-white/5 p-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Signal Reason</p>
        <p className="mt-2 text-sm leading-relaxed text-slate-300">{data?.reason || "Awaiting cleaner alignment."}</p>
      </div>

      {(entryPrice || latestPoints != null || successThreshold != null || stopPoints != null) ? (
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3">
            <p className="text-[10px] text-slate-500">Entry</p>
            <p className="mt-1 font-mono text-sm font-semibold text-slate-100">{entryPrice ?? "-"}</p>
            <p className="mt-1 text-[10px] text-slate-500">Managed trade</p>
          </div>
          <div className="rounded-xl border border-brand-500/20 bg-brand-500/8 px-3 py-3">
            <p className="text-[10px] text-slate-500">Captured</p>
            <p className={clsx("mt-1 font-mono text-sm font-semibold", latestPoints != null && latestPoints >= 0 ? "text-emerald-300" : "text-red-300")}>
              {latestPoints != null ? `${latestPoints >= 0 ? "+" : ""}${latestPoints}` : "-"}
            </p>
            <p className="mt-1 text-[10px] text-slate-500">
              Win {successThreshold != null ? `+${successThreshold}` : "-"} / Stop {stopPoints != null ? `-${stopPoints}` : "-"}
            </p>
          </div>
        </div>
      ) : null}

      <p className="text-[10px] text-slate-500">Multi-timeframe logic: PCR, OI buildup, writer dominance, and price action.</p>
    </div>
  );
}

export default function TradeSignalsPanel({ refreshTick }) {
  const [overview, setOverview] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const firstLoad = Object.keys(overview).length === 0;
    if (firstLoad) setLoading(true);
    setError(null);

    analyticsApi
      .dashboardOverview()
      .then((data) => setOverview(data?.symbols || {}))
      .catch(() => setError("Signal unavailable"))
      .finally(() => {
        if (firstLoad) setLoading(false);
      });
  }, [refreshTick]);

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {SYMBOLS.map((symbol) => (
        <SignalCard
          key={symbol}
          symbol={symbol}
          data={overview[symbol]?.trading_signal}
          loading={loading}
          error={error}
        />
      ))}
    </div>
  );
}
