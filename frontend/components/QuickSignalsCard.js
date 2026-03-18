/**
 * QuickSignalsCard — high-speed 6-step signal engine
 *
 * Three cards: NIFTY, BANKNIFTY, SENSEX. Each card shows signal + buy-signal history.
 * History only captures Buy CE / Buy PE — no Wait.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { analyticsApi } from "../lib/api";
import { isMarketOpen } from "./MarketTicker";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const POLL_MS = 15_000;
const MAX_HISTORY = 40;
const HISTORY_STORAGE_KEY = "optionthropic_quick_signal_history";
let historyId = 0;

function loadPersistedHistory() {
  try {
    const raw = typeof window !== "undefined" && window.localStorage?.getItem(HISTORY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) {
      const buyOnly = parsed.filter((e) => e.signal === "Buy CE" || e.signal === "Buy PE");
      const maxId = Math.max(0, ...buyOnly.map((e) => e.id || 0));
      if (maxId > historyId) historyId = maxId;
      return buyOnly.slice(0, MAX_HISTORY);
    }
  } catch {
    // ignore
  }
  return [];
}

function savePersistedHistory(history) {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
    }
  } catch {
    // ignore
  }
}

const META = {
  "Buy CE": {
    label: "BUY CE", icon: "▲",
    color: "text-emerald-400", bg: "bg-emerald-500/15",
    row: "bg-emerald-500/5 border-emerald-500/20",
  },
  "Buy PE": {
    label: "BUY PE", icon: "▼",
    color: "text-red-400",     bg: "bg-red-500/15",
    row: "bg-red-500/5 border-red-500/20",
  },
  Wait: {
    label: "WAIT",  icon: "◆",
    color: "text-slate-400",   bg: "bg-slate-500/10",
    row: "bg-transparent border-transparent",
  },
};

// ─── History entry (Buy CE/PE only) ──────────────────────────────────────────

function HistoryEntry({ entry }) {
  const qs   = entry.signal;
  const meta = META[qs] ?? META.Wait;

  return (
    <div
      className={clsx(
        "flex items-center justify-between gap-2 py-1.5 px-2 rounded text-[10px]",
        qs === "Buy CE"
          ? "bg-emerald-500/5 border-l-2 border-emerald-500/50"
          : "bg-red-500/5 border-l-2 border-red-500/50",
      )}
    >
      <div className="flex items-center gap-2 min-w-0 shrink">
        <span className="font-mono text-slate-500 shrink-0 w-12">{entry.time}</span>
        <span className={clsx("font-bold shrink-0", meta.color)}>
          {meta.icon} {entry.signal}
        </span>
        {entry.level != null && (
          <span className="font-mono text-slate-400 shrink-0">
            @ {Number(entry.level).toLocaleString("en-IN")}
          </span>
        )}
      </div>
      {entry.momentum != null && entry.momentum !== 0 && (
        <span
          className={clsx(
            "font-mono font-bold shrink-0",
            entry.momentum > 0 ? "text-emerald-400" : "text-red-400",
          )}
        >
          {entry.momentum > 0 ? "+" : ""}{entry.momentum}
        </span>
      )}
    </div>
  );
}

// ─── Single symbol card (signal + history) ────────────────────────────────────

function SymbolCard({ symbol, data, prev, history, loading, lastUpdate, countdown, open }) {
  const qs   = data?.quick_signal ?? "Wait";
  const meta = META[qs] ?? META.Wait;
  const changed = prev?.quick_signal && prev.quick_signal !== qs;
  const mom     = data?.momentum;
  const momUp   = mom != null && mom > 0;
  const momDown = mom != null && mom < 0;
  const support    = data?.support    != null ? Number(data.support).toLocaleString("en-IN")    : null;
  const resistance = data?.resistance != null ? Number(data.resistance).toLocaleString("en-IN") : null;

  const symbolHistory = history.filter((e) => e.symbol === symbol);

  return (
    <div
      className={clsx(
        "card border flex flex-col gap-3 shadow-lg shadow-black/20 min-w-0",
        qs === "Buy CE" ? "border-emerald-500/40" :
        qs === "Buy PE" ? "border-red-500/40"   :
                          "border-surface-border",
      )}
    >
      {/* Header: symbol + countdown */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">
          {symbol}
        </span>
        <span className="text-[10px] text-slate-600 font-mono">{countdown}s</span>
      </div>

      {/* Main content: signal + history side by side (history on left) */}
      <div className="flex gap-3 min-h-0 flex-1">
        {/* History (left) */}
        <div className="w-28 shrink-0 flex flex-col">
          <p className="text-[9px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
            Buy History
          </p>
          <div
            className="flex-1 min-h-[60px] max-h-24 overflow-y-auto rounded border border-surface-border/50 bg-surface/30 divide-y divide-surface-border/30"
            style={{ scrollbarGutter: "stable" }}
          >
            {symbolHistory.length === 0 ? (
              <div className="py-3 px-2 text-[9px] text-slate-500 text-center">
                No buys yet
              </div>
            ) : (
              symbolHistory.map((e) => <HistoryEntry key={e.id} entry={e} />)
            )}
          </div>
        </div>

        {/* Signal (right) */}
        <div className="flex-1 min-w-0">
          {loading ? (
            <div className="h-20 rounded-lg bg-surface-border/20 animate-pulse" />
          ) : (
            <div
              className={clsx(
                "rounded-lg border px-3 py-2.5 flex flex-col gap-1 transition-all duration-500",
                changed ? "ring-1 ring-white/20" : "",
                meta.row,
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className={clsx(
                  "flex items-center gap-1 text-xs font-bold px-2.5 py-0.5 rounded-full shrink-0",
                  meta.bg, meta.color,
                )}>
                  {meta.icon} {meta.label}
                </span>
                {mom != null && (
                  <span className={clsx(
                    "text-xs font-mono font-bold",
                    momUp ? "text-emerald-400" : momDown ? "text-red-400" : "text-slate-500",
                  )}>
                    {momUp ? "+" : ""}{mom}
                  </span>
                )}
              </div>
              {data?.volume_spike && (
                <span className="text-[9px] font-bold text-amber-400">VOL ⚡</span>
              )}
              {(data?.breakout || data?.breakdown) && (
                <span className="text-[9px] font-bold text-sky-400">
                  {data.breakout ? "BREAKOUT" : "BREAKDOWN"}
                </span>
              )}
              <p className="text-[10px] text-slate-500 leading-snug line-clamp-2">
                {data?.reason || "—"}
              </p>
              {(support || resistance) && (
                <div className="flex gap-3 text-[9px]">
                  {support && <span className="text-emerald-500 font-mono">S {support}</span>}
                  {resistance && <span className="text-red-400 font-mono">R {resistance}</span>}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main (3 cards) ───────────────────────────────────────────────────────────

export default function QuickSignalsCard() {
  const [signals,    setSignals]    = useState({});
  const [prevSignals, setPrev]      = useState({});
  const [history,    setHistory]   = useState(() => loadPersistedHistory());
  const [loading,    setLoading]   = useState(true);
  const [countdown,  setCountdown] = useState(POLL_MS / 1000);
  const [lastUpdate, setLastUpdate] = useState(null);
  const countRef = useRef(POLL_MS / 1000);
  const [open, setOpen] = useState(isMarketOpen());

  const fetchAll = useCallback(async () => {
    if (!isMarketOpen()) {
      setOpen(false);
      return;
    }
    setOpen(true);
    try {
      const results = await Promise.all(
        SYMBOLS.map((s) =>
          analyticsApi.quickSignalEngine(s).catch(() => ({
            symbol: s, quick_signal: "Wait", reason: "Unavailable",
          }))
        )
      );
      const map = {};
      results.forEach((r) => { map[r.symbol] = r; });

      setPrev((p) => ({ ...p, ...signals }));
      setSignals(map);
      setLastUpdate(new Date());

      // ── History: only Buy CE and Buy PE (no Wait) ─────────────────────────
      const now = new Date();
      const timeStr = now.toLocaleTimeString("en-IN", {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
      });
      const newEntries = results
        .filter((r) => {
          const sig = r.quick_signal ?? "Wait";
          return sig === "Buy CE" || sig === "Buy PE";
        })
        .map((r) => ({
          id:       ++historyId,
          time:     timeStr,
          symbol:   r.symbol,
          signal:   r.quick_signal ?? "Wait",
          level:    r.current_price ?? null,
          momentum: r.momentum ?? null,
        }));

      if (newEntries.length) {
        setHistory((h) => {
          const next = [...newEntries, ...h].slice(0, MAX_HISTORY);
          savePersistedHistory(next);
          return next;
        });
      }

      countRef.current = POLL_MS / 1000;
      setCountdown(POLL_MS / 1000);
    } catch {
      // silently ignore
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-slate-100">⚡ Quick Signals</span>
          <span className="text-[10px] text-slate-500 hidden sm:inline">
            Momentum · Breakout · OI · 15 s refresh
          </span>
          <span className={clsx(
            "text-[10px] font-semibold px-2 py-0.5 rounded-full",
            open ? "bg-emerald-500/10 text-emerald-400" : "bg-slate-500/10 text-slate-500"
          )}>
            {open ? "LIVE" : "CLOSED"}
          </span>
        </div>
        <span className="text-[10px] text-slate-600 font-mono">
          {lastUpdate
            ? lastUpdate.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
            : "—"}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {SYMBOLS.map((s) => (
          <SymbolCard
            key={s}
            symbol={s}
            data={signals[s]}
            prev={prevSignals[s]}
            history={history}
            loading={loading}
            lastUpdate={lastUpdate}
            countdown={countdown}
            open={open}
          />
        ))}
      </div>

      <p className="text-[9px] text-slate-600">
        ⚡ Reacts to 1-min momentum · volume spikes · S/R breakouts · OI shifts · Buy history only · Not financial advice
      </p>
    </div>
  );
}
