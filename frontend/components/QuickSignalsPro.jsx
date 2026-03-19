/**
 * Quick Signals Pro — 10s momentum, card per index, last 4 buy signals.
 * Dashboard-style layout.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { proApi } from "../lib/proApi";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const POLL_MS = 12000;
const MAX_HISTORY_DISPLAY = 4;
const SAVE_COOLDOWN_MS = 90_000;

const META = {
  "Buy CE": { label: "BUY CE", icon: "▲", desc: "Bullish — buy calls", color: "text-emerald-400", bg: "bg-emerald-500/15", border: "border-emerald-500/40" },
  "Buy PE": { label: "BUY PE", icon: "▼", desc: "Bearish — buy puts", color: "text-red-400", bg: "bg-red-500/15", border: "border-red-500/40" },
  Wait: { label: "WAIT", icon: "◆", desc: "No clear entry", color: "text-slate-400", bg: "bg-slate-500/10", border: "border-slate-500/20" },
};

const HOLD_TIP = "Scalping: hold 2–5 min. Exit on momentum flip or target hit.";

function HistoryEntry({ entry }) {
  const m = META[entry.signal] ?? META.Wait;
  return (
    <div className={clsx("flex items-center justify-between gap-2 py-1.5 px-2 rounded text-[10px]", entry.signal === "Buy CE" ? "bg-emerald-500/5 border-l-2 border-emerald-500/50" : "bg-red-500/5 border-l-2 border-red-500/50")}>
      <span className="font-mono text-slate-500 w-14 shrink-0">{entry.time}</span>
      <span className={clsx("font-bold shrink-0", m.color)}>{m.icon} {entry.signal}</span>
      {entry.level != null && <span className="font-mono text-slate-400 shrink-0">@ {Number(entry.level).toLocaleString("en-IN")}</span>}
    </div>
  );
}

function SymbolCard({ symbol, signal, meta, price, onCapture, history, countdown }) {
  const symbolHistory = history.filter((e) => e.symbol === symbol).slice(0, MAX_HISTORY_DISPLAY);
  return (
    <div className={clsx("card border flex flex-col gap-4 shadow-lg shadow-black/20", meta.border)}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest font-semibold mb-0.5">{symbol}</p>
          <p className={clsx("text-xl font-bold leading-none", meta.color)}>{meta.icon} {signal}</p>
          <p className="text-xs text-slate-500 mt-1">{meta.desc}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={clsx("text-xs font-bold px-2.5 py-1 rounded-full", meta.bg, meta.color)}>{meta.icon} {meta.label}</span>
          <span className="text-[10px] text-slate-600 font-mono">{countdown}s</span>
        </div>
      </div>
      {(signal === "Buy CE" || signal === "Buy PE") && (
        <>
          <p className="text-[10px] text-amber-400/90 bg-amber-500/5 border border-amber-500/20 rounded-lg px-2.5 py-1.5">⏱ {HOLD_TIP}</p>
          <button onClick={() => onCapture(symbol, signal, price)} className="text-[10px] px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-slate-300 border border-surface-border w-fit">Capture</button>
        </>
      )}
      <div>
        <p className="text-[9px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Buy History</p>
        <div className="min-h-[48px] max-h-28 overflow-y-auto rounded border border-surface-border/50 bg-surface/30 divide-y divide-surface-border/30">
          {symbolHistory.length === 0 ? <div className="py-3 px-2 text-[9px] text-slate-500 text-center">No buys yet</div> : symbolHistory.map((e) => <HistoryEntry key={e.id} entry={e} />)}
        </div>
      </div>
    </div>
  );
}

export default function QuickSignalsPro() {
  const [signals, setSignals] = useState({});
  const [ticks, setTicks] = useState({});
  const [history, setHistory] = useState([]);
  const [countdown, setCountdown] = useState(POLL_MS / 1000);
  const countRef = useRef(POLL_MS / 1000);
  const lastSavedRef = useRef({});

  const loadHistory = useCallback(() => {
    proApi.buySignalHistory().then((list) => {
      if (Array.isArray(list) && list.length > 0) {
        const seen = new Set();
        const isQuick = (e) => !(e.reason || "").toLowerCase().includes("swing");
        setHistory(
          list
            .filter((e) => (e.signal === "Buy CE" || e.signal === "Buy PE") && isQuick(e))
            .filter((e) => {
              const t = e.created_at ? new Date(e.created_at).getTime() : 0;
              const key = `${e.symbol}|${e.signal}|${e.level ?? ""}|${Math.floor(t / 60000)}`;
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            })
            .map((e) => ({ id: e.id, time: e.created_at ? new Date(e.created_at).toLocaleTimeString("en-IN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }) : null, symbol: e.symbol, signal: e.signal, level: e.level }))
        );
      }
    }).catch(() => {});
  }, []);

  const captureSignal = useCallback(async (symbol, signal, level) => {
    if (signal !== "Buy CE" && signal !== "Buy PE") return;
    const key = `${symbol}|${signal}`;
    if (lastSavedRef.current[key] && Date.now() - lastSavedRef.current[key] < SAVE_COOLDOWN_MS) return;
    lastSavedRef.current[key] = Date.now();
    const saved = await proApi.saveBuySignal({ symbol, signal, level, momentum: null, reason: null });
    if (saved) {
      setHistory((h) => {
        if (h.some((e) => e.id === saved.id)) return h;
        return [{ id: saved.id, time: new Date(saved.created_at).toLocaleTimeString("en-IN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }), symbol, signal, level }, ...h];
      });
    }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  useEffect(() => {
    const fetchSignals = () => {
      proApi.signals().then((data) => setSignals(data || {}));
      proApi.ticks().then((data) => setTicks(data || {}));
      countRef.current = POLL_MS / 1000;
      setCountdown(POLL_MS / 1000);
    };
    fetchSignals();
    const id = setInterval(fetchSignals, POLL_MS);
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
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-slate-100">⚡ Quick Signals</span>
        <span className="text-[10px] text-slate-500">10s momentum · Updates every 12s</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {SYMBOLS.map((sym) => {
          const s = signals[sym] || {};
          const sig = s.quick_signal || "Wait";
          const meta = META[sig] || META.Wait;
          const price = (ticks[sym] || {}).price ?? null;
          return <SymbolCard key={sym} symbol={sym} signal={sig} meta={meta} price={price} onCapture={captureSignal} history={history} countdown={countdown} />;
        })}
      </div>
    </div>
  );
}
