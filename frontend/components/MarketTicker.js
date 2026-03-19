/**
 * MarketTicker — top bar showing live prices + day change for NIFTY, BANKNIFTY, SENSEX.
 *
 * Behaviour:
 * - Always fetches on mount so last-known prices are visible even when closed.
 * - Checks market-open status every 15 s so "Live" / "Closed" flips quickly at
 *   09:00 IST open or 15:30 IST close.
 * - Price data refreshes every 60 s while market is open; pauses when closed.
 * - On the transition from closed → open the first live fetch fires immediately.
 */
import { useEffect, useRef, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

const SYMBOLS       = ["NIFTY", "BANKNIFTY", "SENSEX"];
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

export function isMarketOpen() {
  const now  = new Date(Date.now() + IST_OFFSET_MS);
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes();
  return mins >= 9 * 60 && mins <= 15 * 60 + 30;
}

function fmt(val) {
  if (val == null) return "—";
  return Number(val).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtAbs(val) {
  if (val == null) return "";
  return Math.abs(val).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
function round(n, d) {
  return Math.round(n * Math.pow(10, d)) / Math.pow(10, d);
}

function PriceItem({ symbol, data, live }) {
  const price     = data?.price;
  const change    = data?.change;
  const changePct = data?.change_pct;

  const up   = change != null && change > 0;
  const down = change != null && change < 0;

  return (
    <div className="flex items-center gap-2 shrink-0">
      <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">
        {symbol}
      </span>
      {live && (
        <span className="text-[8px] font-bold text-emerald-500 uppercase tracking-wider animate-pulse">
          Live
        </span>
      )}
      <span
        className={clsx(
          "text-sm font-mono font-semibold tabular-nums transition-colors duration-200",
          up ? "text-emerald-400" : down ? "text-red-400" : "text-slate-200"
        )}
      >
        {fmt(price)}
      </span>
      {change != null && change !== 0 && (
        <span
          className={clsx(
            "hidden sm:flex items-center gap-0.5 text-[10px] font-mono font-semibold",
            up ? "text-emerald-500" : "text-red-400"
          )}
        >
          {up ? "▲" : "▼"} {fmtAbs(change)}
          {changePct != null && (
            <span className="opacity-75">
              &nbsp;({up ? "+" : ""}{changePct}%)
            </span>
          )}
        </span>
      )}
    </div>
  );
}

export default function MarketTicker({ refreshTick, onTickerUpdate }) {
  const [prices, setPrices] = useState({});
  const [liveMode, setLiveMode] = useState(false);  // true when tick-by-tick data flows
  const [open, setOpen]     = useState(isMarketOpen());
  const wasOpenRef          = useRef(isMarketOpen());
  const priceTimerRef       = useRef(null);

  const loadPrices = () => {
    analyticsApi.marketPrices()
      .then((data) => {
        if (data && Object.keys(data).length > 0) {
          setPrices(data);
          setLiveMode(false);
          onTickerUpdate?.(new Date());
        }
      })
      .catch(() => {});
  };

  const pollPrices = () => {
    analyticsApi.liveTicks()
      .then((data) => {
        if (data && Object.keys(data).length > 0) {
          const withPct = {};
          for (const [sym, d] of Object.entries(data)) {
            const price = d.price;
            const change = d.change;
            const prevClose = price != null && change != null ? price - change : null;
            withPct[sym] = {
              ...d,
              change_pct: prevClose && change != null ? round((change / prevClose) * 100, 2) : null,
            };
          }
          setPrices(withPct);
          setLiveMode(true);
          onTickerUpdate?.(new Date());
        } else {
          loadPrices();
          setLiveMode(false);
        }
      })
      .catch(() => {
        loadPrices();
        setLiveMode(false);
      });
  };

  const startPricePolling = () => {
    if (priceTimerRef.current) return;
    pollPrices();
    priceTimerRef.current = setInterval(pollPrices, 5_000);
  };

  const stopPricePolling = () => {
    if (priceTimerRef.current) {
      clearInterval(priceTimerRef.current);
      priceTimerRef.current = null;
    }
    setLiveMode(false);
    loadPrices();
  };

  useEffect(() => {
    loadPrices();
    if (isMarketOpen()) startPricePolling();

    const statusTimer = setInterval(() => {
      const mo = isMarketOpen();
      setOpen(mo);
      if (mo && !wasOpenRef.current) {
        pollPrices();
        startPricePolling();
      } else if (!mo && wasOpenRef.current) {
        stopPricePolling();
        loadPrices();
      }
      wasOpenRef.current = mo;
    }, 15_000);

    return () => {
      clearInterval(statusTimer);
      stopPricePolling();
    };
  }, []);

  useEffect(() => {
    if (refreshTick > 0 && isMarketOpen()) pollPrices();
  }, [refreshTick]);

  return (
    <div className="w-full border-b border-surface-border bg-surface-card/70 backdrop-blur-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-9 flex items-center justify-between gap-4">

        {/* Market status badge */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span
            className={clsx(
              "inline-block h-1.5 w-1.5 rounded-full",
              open ? "bg-emerald-500 animate-pulse" : "bg-slate-500"
            )}
          />
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 whitespace-nowrap">
            {open ? "Market Open" : "Market Closed"}
          </span>
        </div>

        {/* Prices — tick-by-tick when live, otherwise 60s refresh */}
        <div className="flex items-center gap-6 sm:gap-10 flex-1 justify-center">
          {SYMBOLS.map((sym) => (
            <PriceItem key={sym} symbol={sym} data={prices[sym]} live={open && liveMode} />
          ))}
        </div>

        {/* Live IST clock */}
        <ISTClock />
      </div>
    </div>
  );
}

function ISTClock() {
  const [time, setTime] = useState("");
  useEffect(() => {
    const tick = () => {
      const ist = new Date(Date.now() + IST_OFFSET_MS);
      const hh  = String(ist.getUTCHours()).padStart(2, "0");
      const mm  = String(ist.getUTCMinutes()).padStart(2, "0");
      const ss  = String(ist.getUTCSeconds()).padStart(2, "0");
      setTime(`${hh}:${mm}:${ss} IST`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="text-[10px] font-mono text-slate-600 shrink-0 hidden sm:block">
      {time}
    </span>
  );
}
