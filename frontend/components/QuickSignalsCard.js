import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";

import { analyticsApi } from "../lib/api";
import { isMarketOpen } from "./MarketTicker";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const POLL_MS = 15_000;
const MAX_HISTORY_DISPLAY = 4;

const META = {
  "Buy CE": {
    label: "BUY CE",
    code: "CE",
    desc: "Bullish intraday entry",
    color: "text-emerald-300",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/20",
  },
  "Buy PE": {
    label: "BUY PE",
    code: "PE",
    desc: "Bearish intraday entry",
    color: "text-red-300",
    bg: "bg-red-500/10",
    border: "border-red-500/20",
  },
  "Hold CE": {
    label: "HOLD CE",
    code: "HC",
    desc: "Bullish trade is still active",
    color: "text-cyan-300",
    bg: "bg-cyan-500/10",
    border: "border-cyan-500/20",
  },
  "Hold PE": {
    label: "HOLD PE",
    code: "HP",
    desc: "Bearish trade is still active",
    color: "text-cyan-300",
    bg: "bg-cyan-500/10",
    border: "border-cyan-500/20",
  },
  "Exit CE": {
    label: "EXIT CE",
    code: "XC",
    desc: "Close the bullish trade",
    color: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
  },
  "Exit PE": {
    label: "EXIT PE",
    code: "XP",
    desc: "Close the bearish trade",
    color: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
  },
  Wait: {
    label: "WAIT",
    code: "WT",
    desc: "No clear entry",
    color: "text-slate-300",
    bg: "bg-white/5",
    border: "border-surface-border",
  },
};

const STATE_META = {
  active: { label: "ACTIVE", color: "text-emerald-300", bg: "bg-emerald-500/10" },
  candidate: { label: "SETUP", color: "text-amber-300", bg: "bg-amber-500/10" },
  cooldown: { label: "COOLDOWN", color: "text-sky-300", bg: "bg-sky-500/10" },
  idle: { label: "IDLE", color: "text-slate-400", bg: "bg-slate-500/10" },
  entry: { label: "ENTRY", color: "text-brand-300", bg: "bg-brand-500/10" },
  hold: { label: "HOLD", color: "text-cyan-300", bg: "bg-cyan-500/10" },
  exit: { label: "EXIT", color: "text-amber-300", bg: "bg-amber-500/10" },
};

const HOLD_TIP = "Active scalp: stay in the trade while structure holds. Exit only on invalidation or when follow-through fades after enough points are captured.";

function HistoryEntry({ entry }) {
  const meta = META[entry.signal] ?? META.Wait;
  return (
    <div
      className={clsx(
        "flex items-center justify-between gap-2 rounded-xl px-2.5 py-2 text-[10px]",
        entry.signal === "Buy CE" ? "bg-emerald-500/5" : "bg-red-500/5"
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="w-14 shrink-0 font-mono text-slate-500">{entry.time}</span>
        <span className={clsx("shrink-0 font-bold", meta.color)}>{entry.signal}</span>
        {entry.level != null ? (
          <span className="shrink-0 font-mono text-slate-400">
            @ {Number(entry.level).toLocaleString("en-IN")}
          </span>
        ) : null}
      </div>
      {entry.momentum != null && entry.momentum !== 0 ? (
        <span
          className={clsx(
            "shrink-0 font-mono font-bold",
            entry.momentum > 0 ? "text-emerald-300" : "text-red-300"
          )}
        >
          {entry.momentum > 0 ? "+" : ""}
          {entry.momentum}
        </span>
      ) : null}
    </div>
  );
}

function StatPill({ children, tone = "neutral" }) {
  const toneClass =
    tone === "good"
      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
      : tone === "danger"
        ? "border-red-500/20 bg-red-500/10 text-red-300"
        : tone === "warn"
          ? "border-amber-500/20 bg-amber-500/10 text-amber-300"
          : "border-white/10 bg-white/5 text-slate-300";

  return (
    <span className={clsx("rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]", toneClass)}>
      {children}
    </span>
  );
}

function SymbolCard({ symbol, data, prev, history, loading, countdown }) {
  const quickSignal = data?.quick_signal ?? "Wait";
  const meta = META[quickSignal] ?? META.Wait;
  const stateKey = data?.trade_state ?? data?.state ?? (quickSignal === "Wait" ? "idle" : "active");
  const stateMeta = STATE_META[stateKey] ?? STATE_META.idle;
  const changed = prev?.quick_signal && prev.quick_signal !== quickSignal;
  const confidence = Number.isFinite(data?.confidence) ? data.confidence : null;
  const momentum = data?.momentum;
  const stabilityCycles = data?.stability_cycles ?? 0;
  const stateReason = data?.state_reason;
  const rawSignal = data?.raw_signal ?? "Wait";
  const activeAgeSeconds = Number.isFinite(data?.active_age_seconds) ? data.active_age_seconds : null;
  const cooldownSeconds = Number.isFinite(data?.cooldown_seconds_remaining) ? data.cooldown_seconds_remaining : null;
  const support = data?.support != null ? Number(data.support).toLocaleString("en-IN") : null;
  const resistance = data?.resistance != null ? Number(data.resistance).toLocaleString("en-IN") : null;
  const entryPrice = data?.entry_price != null ? Number(data.entry_price).toLocaleString("en-IN") : null;
  const currentPoints = Number.isFinite(data?.current_points) ? data.current_points : null;
  const successThreshold = Number.isFinite(data?.success_threshold_points) ? data.success_threshold_points : null;
  const stopPoints = Number.isFinite(data?.stop_points) ? data.stop_points : null;
  const symbolHistory = history.filter((entry) => entry.symbol === symbol).slice(0, MAX_HISTORY_DISPLAY);

  return (
    <div className={clsx("card flex flex-col gap-4 border", meta.border)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="section-kicker">{symbol}</p>
          <h3 className={clsx("mt-2 text-2xl font-semibold tracking-tight", meta.color)}>
            {quickSignal}
          </h3>
          <p className="mt-1 text-xs text-slate-500">{meta.desc}</p>
        </div>

        <div className="flex flex-col items-end gap-1.5">
          <StatPill tone={quickSignal === "Buy CE" ? "good" : quickSignal === "Buy PE" ? "danger" : "neutral"}>
            {meta.code}
          </StatPill>
          <span className={clsx("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em]", stateMeta.bg, stateMeta.color)}>
            {stateMeta.label}
          </span>
          <span className="font-mono text-[10px] text-slate-500">{countdown}s</span>
        </div>
      </div>

      {(quickSignal === "Buy CE" || quickSignal === "Buy PE" || quickSignal === "Hold CE" || quickSignal === "Hold PE") ? (
        <div className="rounded-2xl border border-amber-500/15 bg-amber-500/8 px-3 py-2">
          <p className="text-[11px] leading-relaxed text-amber-300">{HOLD_TIP}</p>
        </div>
      ) : null}

      {loading ? (
        <div className="h-28 animate-pulse rounded-[1.25rem] border border-surface-border bg-white/5" />
      ) : (
        <div
          className={clsx(
            "rounded-[1.35rem] border border-surface-border bg-white/5 p-3 transition-all duration-200",
            changed ? "ring-1 ring-brand-400/20" : ""
          )}
        >
          <div className="flex items-center justify-between gap-3">
            <span className={clsx("text-[11px] font-semibold uppercase tracking-[0.18em]", stateMeta.color)}>
              {stateMeta.label}
              {rawSignal !== "Wait" && stateKey !== "active" ? ` -> ${rawSignal}` : ""}
            </span>
            {confidence != null ? <span className="font-mono text-xs text-slate-400">Conf {confidence}</span> : null}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {momentum != null ? (
              <StatPill tone={momentum > 0 ? "good" : momentum < 0 ? "danger" : "neutral"}>
                Momentum {momentum > 0 ? "+" : ""}
                {momentum}
              </StatPill>
            ) : null}
            {stabilityCycles > 0 ? <StatPill>Cycles {stabilityCycles}</StatPill> : null}
            {activeAgeSeconds != null && stateKey === "active" ? <StatPill>Live {activeAgeSeconds}s</StatPill> : null}
            {cooldownSeconds != null && cooldownSeconds > 0 ? <StatPill>Cooldown {cooldownSeconds}s</StatPill> : null}
            {currentPoints != null ? (
              <StatPill tone={currentPoints >= 0 ? "good" : "danger"}>
                {currentPoints >= 0 ? "+" : ""}
                {currentPoints} pts
              </StatPill>
            ) : null}
          </div>

          <p className="mt-3 text-xs leading-relaxed text-slate-300">{data?.reason || "No active setup yet."}</p>
          {stateReason && stateReason !== data?.reason ? (
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{stateReason}</p>
          ) : null}

          {(support || resistance) ? (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/5 px-3 py-2">
                <p className="text-[10px] text-slate-500">Support</p>
                <p className="mt-1 font-mono text-sm font-semibold text-emerald-300">{support || "-"}</p>
              </div>
              <div className="rounded-xl border border-red-500/15 bg-red-500/5 px-3 py-2">
                <p className="text-[10px] text-slate-500">Resistance</p>
                <p className="mt-1 font-mono text-sm font-semibold text-red-300">{resistance || "-"}</p>
              </div>
            </div>
          ) : null}

          {(entryPrice || successThreshold != null || stopPoints != null) ? (
            <div className="mt-3 grid grid-cols-3 gap-2">
              <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                <p className="text-[10px] text-slate-500">Entry</p>
                <p className="mt-1 font-mono text-sm font-semibold text-slate-200">{entryPrice || "-"}</p>
              </div>
              <div className="rounded-xl border border-brand-500/20 bg-brand-500/8 px-3 py-2">
                <p className="text-[10px] text-slate-500">Book Win</p>
                <p className="mt-1 font-mono text-sm font-semibold text-brand-300">
                  {successThreshold != null ? `+${successThreshold}` : "-"}
                </p>
              </div>
              <div className="rounded-xl border border-red-500/15 bg-red-500/5 px-3 py-2">
                <p className="text-[10px] text-slate-500">Stop</p>
                <p className="mt-1 font-mono text-sm font-semibold text-red-300">
                  {stopPoints != null ? `-${stopPoints}` : "-"}
                </p>
              </div>
            </div>
          ) : null}
        </div>
      )}

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
          Buy History
        </p>
        <div className="min-h-[56px] max-h-32 space-y-1 overflow-y-auto rounded-[1.25rem] border border-surface-border bg-white/5 p-2">
          {symbolHistory.length === 0 ? (
            <div className="py-3 text-center text-[10px] text-slate-500">No buys saved yet</div>
          ) : (
            symbolHistory.map((entry) => <HistoryEntry key={entry.id} entry={entry} />)
          )}
        </div>
      </div>
    </div>
  );
}

export default function QuickSignalsCard() {
  const [signals, setSignals] = useState({});
  const [prevSignals, setPrev] = useState({});
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [countdown, setCountdown] = useState(POLL_MS / 1000);
  const [lastUpdate, setLastUpdate] = useState(null);
  const countRef = useRef(POLL_MS / 1000);
  const lastSavedRef = useRef({});
  const [open, setOpen] = useState(isMarketOpen());

  const loadHistory = useCallback(() => {
    analyticsApi
      .buySignalHistory()
      .then((list) => {
        if (!Array.isArray(list) || list.length === 0) return;
        const seen = new Set();
        setHistory(
          list
            .filter((entry) => entry.signal === "Buy CE" || entry.signal === "Buy PE")
            .filter((entry) => {
              const time = entry.created_at ? new Date(entry.created_at).getTime() : 0;
              const minuteBucket = Math.floor(time / 60000);
              const key = `${entry.symbol}|${entry.signal}|${entry.level ?? ""}|${minuteBucket}`;
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            })
            .map((entry) => ({
              id: entry.id,
              time: entry.created_at
                ? new Date(entry.created_at).toLocaleTimeString("en-IN", {
                    hour12: false,
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })
                : null,
              symbol: entry.symbol,
              signal: entry.signal,
              level: entry.level,
              momentum: entry.momentum,
            }))
        );
      })
      .catch(() => {});
  }, []);

  const fetchAll = useCallback(async () => {
    if (!isMarketOpen()) {
      setOpen(false);
      return;
    }

    setOpen(true);

    try {
      const results = await Promise.all(
        SYMBOLS.map((symbol) =>
          analyticsApi.quickSignalEngine(symbol).catch(() => ({
            symbol,
            quick_signal: "Wait",
            reason: "Unavailable",
          }))
        )
      );

      const nextSignals = {};
      results.forEach((row) => {
        nextSignals[row.symbol] = row;
      });

      setPrev(() => ({ ...signals }));
      setSignals(nextSignals);
      setLastUpdate(new Date());

      const nowTs = Date.now();
      const timeStr = new Date().toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
      const cooldownMs = 90_000;

      const newBuys = results.filter((row) => {
        const signal = row.quick_signal ?? "Wait";
        const prevSignal = signals[row.symbol]?.quick_signal ?? "Wait";
        return (signal === "Buy CE" || signal === "Buy PE") && prevSignal !== signal;
      });

      for (const row of newBuys) {
        const signal = row.quick_signal ?? "Wait";
        const key = `${row.symbol}|${signal}`;
        if (lastSavedRef.current[key] && nowTs - lastSavedRef.current[key] < cooldownMs) continue;

        lastSavedRef.current[key] = nowTs;
        const saved = await analyticsApi.saveBuySignal({
          symbol: row.symbol,
          signal,
          level: row.current_price ?? null,
          momentum: row.momentum ?? null,
          reason: row.reason ?? null,
          confidence: row.confidence ?? 0,
          engine: "QUICK",
          payload: row,
        });

        if (saved) {
          setHistory((current) => {
            if (current.some((entry) => entry.id === saved.id)) return current;
            const entry = {
              id: saved.id,
              time: timeStr,
              symbol: row.symbol,
              signal,
              level: row.current_price ?? null,
              momentum: row.momentum ?? null,
            };
            return [entry, ...current];
          });
        }
      }

      countRef.current = POLL_MS / 1000;
      setCountdown(POLL_MS / 1000);
    } catch {
      // Ignore fetch noise in the UI.
    } finally {
      setLoading(false);
    }
  }, [signals]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, POLL_MS);
    return () => clearInterval(id);
  }, [fetchAll]);

  useEffect(() => {
    const id = setInterval(() => setOpen(isMarketOpen()), 15_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      countRef.current = Math.max(0, countRef.current - 1);
      setCountdown(countRef.current);
    }, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-4">
      <div className="surface-panel rounded-[1.75rem] px-4 py-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="section-kicker">Fast Tape</p>
            <h3 className="mt-1 text-lg font-semibold text-slate-100">Quick Signals</h3>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              Momentum, breakout, volume, and OI confirmation on a 15 second refresh cycle.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatPill tone={open ? "good" : "neutral"}>{open ? "LIVE" : "CLOSED"}</StatPill>
            <StatPill>15s cycle</StatPill>
            <span className="font-mono text-[11px] text-slate-500">
              {lastUpdate
                ? lastUpdate.toLocaleTimeString("en-IN", {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })
                : "--:--:--"}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {SYMBOLS.map((symbol) => (
          <SymbolCard
            key={symbol}
            symbol={symbol}
            data={signals[symbol]}
            prev={prevSignals[symbol]}
            history={history}
            loading={loading}
            countdown={countdown}
          />
        ))}
      </div>

      <p className="text-[10px] text-slate-500">
        Quick signal inputs: momentum, volume, support and resistance, OI, and saved buy history for analytics.
      </p>
    </div>
  );
}
