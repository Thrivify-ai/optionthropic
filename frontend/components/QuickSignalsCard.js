/**
 * QuickSignalsCard — high-speed 6-step signal engine
 * Trade-signal style cards with buy history below. Persists to backend for analytics.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { analyticsApi } from "../lib/api";
import { isMarketOpen } from "./MarketTicker";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const POLL_MS = 15_000;
const MAX_HISTORY_DISPLAY = 4;  // show last 4 per symbol; rest stored in backend

const META = {
  "Buy CE": {
    label: "BUY CE", icon: "▲", desc: "Bullish — buy calls",
    color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/40",
  },
  "Buy PE": {
    label: "BUY PE", icon: "▼", desc: "Bearish — buy puts",
    color: "text-red-400",     bg: "bg-red-500/15",     border: "border-red-500/40",
  },
  Wait: {
    label: "WAIT",  icon: "◆", desc: "No clear entry",
    color: "text-slate-400",   bg: "bg-slate-500/10",   border: "border-surface-border",
  },
};

const HOLD_TIP = "Scalping: hold 2–5 min. Exit on momentum flip or target hit.";

function HistoryEntry({ entry }) {
  const meta = META[entry.signal] ?? META.Wait;
  return (
    <div
      className={clsx(
        "flex items-center justify-between gap-2 py-1.5 px-2 rounded text-[10px]",
        entry.signal === "Buy CE" ? "bg-emerald-500/5 border-l-2 border-emerald-500/50" : "bg-red-500/5 border-l-2 border-red-500/50",
      )}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-mono text-slate-500 w-14 shrink-0">{entry.time}</span>
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
        <span className={clsx("font-mono font-bold shrink-0", entry.momentum > 0 ? "text-emerald-400" : "text-red-400")}>
          {entry.momentum > 0 ? "+" : ""}{entry.momentum}
        </span>
      )}
    </div>
  );
}

function SymbolCard({ symbol, data, prev, history, loading, countdown, open }) {
  const qs = data?.quick_signal ?? "Wait";
  const meta = META[qs] ?? META.Wait;
  const changed = prev?.quick_signal && prev.quick_signal !== qs;
  const mom = data?.momentum;
  const support = data?.support != null ? Number(data.support).toLocaleString("en-IN") : null;
  const resistance = data?.resistance != null ? Number(data.resistance).toLocaleString("en-IN") : null;
  const symbolHistory = history.filter((e) => e.symbol === symbol).slice(0, MAX_HISTORY_DISPLAY);

  return (
    <div className={clsx("card border flex flex-col gap-4 shadow-lg shadow-black/20", meta.border)}>
      {/* Header — trade-signal style */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-semibold mb-0.5">
            {symbol}
          </p>
          <p className={clsx("text-xl font-bold leading-none", meta.color)}>
            {meta.icon} {qs}
          </p>
          <p className="text-xs text-slate-500 mt-1">{meta.desc}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={clsx("text-xs font-bold px-2.5 py-1 rounded-full", meta.bg, meta.color)}>
            {meta.icon} {meta.label}
          </span>
          <span className="text-[10px] text-slate-600 font-mono">{countdown}s</span>
        </div>
      </div>

      {/* Hold-time tip for scalping */}
      {(qs === "Buy CE" || qs === "Buy PE") && (
        <p className="text-[10px] text-amber-400/90 bg-amber-500/5 border border-amber-500/20 rounded-lg px-2.5 py-1.5">
          ⏱ {HOLD_TIP}
        </p>
      )}

      {/* Signal details */}
      {loading ? (
        <div className="h-16 rounded-lg bg-surface-border/20 animate-pulse" />
      ) : (
        <div className={clsx("rounded-lg border px-3 py-2 flex flex-col gap-1", changed ? "ring-1 ring-white/20" : "", "border-surface-border/50")}>
          {mom != null && (
            <span className={clsx("text-xs font-mono font-bold", mom > 0 ? "text-emerald-400" : mom < 0 ? "text-red-400" : "text-slate-500")}>
              Momentum {mom > 0 ? "+" : ""}{mom}
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

      {/* Buy history — below signal */}
      <div>
        <p className="text-[9px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
          Buy History
        </p>
        <div className="min-h-[48px] max-h-28 overflow-y-auto rounded border border-surface-border/50 bg-surface/30 divide-y divide-surface-border/30" style={{ scrollbarGutter: "stable" }}>
          {symbolHistory.length === 0 ? (
            <div className="py-3 px-2 text-[9px] text-slate-500 text-center">No buys yet</div>
          ) : (
            symbolHistory.map((e) => <HistoryEntry key={e.id} entry={e} />)
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
  const lastSavedRef = useRef({});  // { "NIFTY|Buy CE": timestamp } — skip save within 90s
  const [open, setOpen] = useState(isMarketOpen());

  const loadHistory = useCallback(() => {
    analyticsApi.buySignalHistory().then((list) => {
      if (Array.isArray(list) && list.length > 0) {
        const seen = new Set();
        setHistory(
          list
            .filter((e) => e.signal === "Buy CE" || e.signal === "Buy PE")
            .filter((e) => {
              const t = e.created_at ? new Date(e.created_at).getTime() : 0;
              const min = Math.floor(t / 60000);
              const key = `${e.symbol}|${e.signal}|${e.level ?? ""}|${min}`;
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            })
            .map((e) => ({
              id: e.id,
              time: e.created_at ? new Date(e.created_at).toLocaleTimeString("en-IN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }) : null,
              symbol: e.symbol,
              signal: e.signal,
              level: e.level,
              momentum: e.momentum,
            }))
        );
      }
    }).catch(() => {});
  }, []);

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
      setPrev((p) => ({ ...signals }));
      setSignals(map);
      setLastUpdate(new Date());

      const now = new Date();
      const timeStr = now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
      const newBuys = results.filter((r) => {
        const sig = r.quick_signal ?? "Wait";
        const prevSig = signals[r.symbol]?.quick_signal ?? "Wait";
        return (sig === "Buy CE" || sig === "Buy PE") && prevSig !== sig;
      });

      const nowTs = Date.now();
      const COOLDOWN_MS = 90_000;
      for (const r of newBuys) {
        const sig = r.quick_signal ?? "Wait";
        const key = `${r.symbol}|${sig}`;
        if (lastSavedRef.current[key] && nowTs - lastSavedRef.current[key] < COOLDOWN_MS) continue;
        lastSavedRef.current[key] = nowTs;
        const saved = await analyticsApi.saveBuySignal({
          symbol: r.symbol,
          signal: sig,
          level: r.current_price ?? null,
          momentum: r.momentum ?? null,
          reason: r.reason ?? null,
        });
        if (saved) {
          setHistory((h) => {
            if (h.some((e) => e.id === saved.id)) return h;
            const entry = {
              id: saved.id,
              time: timeStr,
              symbol: r.symbol,
              signal: sig,
              level: r.current_price ?? null,
              momentum: r.momentum ?? null,
            };
            return [entry, ...h];
          });
        }
      }

      countRef.current = POLL_MS / 1000;
      setCountdown(POLL_MS / 1000);
    } catch {
      // ignore
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
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-slate-100">⚡ Quick Signals</span>
          <span className="text-[10px] text-slate-500 hidden sm:inline">Momentum · Breakout · OI · 15s refresh</span>
          <span className={clsx("text-[10px] font-semibold px-2 py-0.5 rounded-full", open ? "bg-emerald-500/10 text-emerald-400" : "bg-slate-500/10 text-slate-500")}>
            {open ? "LIVE" : "CLOSED"}
          </span>
        </div>
        <span className="text-[10px] text-slate-600 font-mono">
          {lastUpdate ? lastUpdate.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}
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
            countdown={countdown}
            open={open}
          />
        ))}
      </div>

      <p className="text-[9px] text-slate-600">
        ⚡ Momentum · Volume · S/R breakouts · OI · Buy history saved for analytics · Not financial advice
      </p>
    </div>
  );
}
