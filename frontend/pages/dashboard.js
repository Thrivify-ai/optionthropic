import { useState, useEffect, useCallback } from "react";
import Layout from "../components/Layout";
import { analyticsApi } from "../lib/api";
import { isMarketOpen } from "../components/MarketTicker";
import MarketBiasPanel   from "../components/MarketBiasPanel";
import TradeSignalsPanel from "../components/TradeSignalsPanel";
import AIInsightsPanel   from "../components/AIInsightsPanel";
import TimeFactorCard    from "../components/TimeFactorCard";
import MarketTicker      from "../components/MarketTicker";
import QuickSignalsCard  from "../components/QuickSignalsCard";
import CommoditiesPanel  from "../components/CommoditiesPanel";
import OptionsDashboard  from "../components/OptionsDashboard";
import GammaWallChart    from "../components/GammaWallChart";
import OptionsFlowPanel  from "../components/OptionsFlowPanel";
import AlertsPanel       from "../components/AlertsPanel";
import clsx from "clsx";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const TABS    = [
  { id: "signals",  label: "Signals",   icon: "📊" },
  { id: "deepdive", label: "Deep Dive", icon: "🔬" },
  { id: "charts",   label: "Charts",    icon: "📈" },
  { id: "commodities", label: "Commodities", icon: "🥇" },
];

function formatRelative(date) {
  if (!date) return "";
  const sec = Math.floor((Date.now() - date.getTime()) / 1000);
  if (sec < 10) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min ago`;
  return `${Math.floor(min / 60)}h ago`;
}

function SectionLabel({ number, title }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-brand-600/90 text-white text-xs font-bold shadow-sm">
        {number}
      </span>
      <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
      <div className="flex-1 h-px bg-surface-border/80 ml-2" />
    </div>
  );
}

export default function Dashboard() {
  const [tab, setTab]                       = useState("signals");
  const [symbol, setSymbol]                 = useState("NIFTY");
  const [lastDataUpdate, setLastDataUpdate] = useState(null);
  const [tickerLastUpdate, setTickerLastUpdate] = useState(null);
  const [, setRelativeTick]                 = useState(0);
  const [refreshTick, setRefreshTick]       = useState(0);
  const [movementTick, setMovementTick]     = useState(0);
  const [marketOpen, setMarketOpen]         = useState(isMarketOpen());

  // Never set "last updated" to the viewer's current time.
  // Always use the DB-backed timestamp from /api/last-refresh.
  const onDataLoaded = useCallback(() => {
    analyticsApi.lastRefresh().then((data) => {
      if (data?.last_refresh_utc) setLastDataUpdate(new Date(data.last_refresh_utc));
    });
  }, []);

  // General heartbeat:
  // - Always updates marketOpen state.
  // - Bumps refreshTick every 30 s during market hours for timely Trade Signals updates.
  useEffect(() => {
    const id = setInterval(() => {
      const mo = isMarketOpen();
      setMarketOpen(mo);
      if (mo) setRefreshTick((t) => t + 1);
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  // Movement-driven tick — only check + bump when market is open
  useEffect(() => {
    const checkMovement = () => {
      if (!isMarketOpen()) return;
      Promise.all(
        SYMBOLS.map((s) => analyticsApi.movement(s).catch(() => ({ movement_significant: false })))
      ).then((results) => {
        if (results.some((r) => r?.movement_significant)) {
          setMovementTick((t) => t + 1);
        }
      });
    };
    checkMovement();
    const id = setInterval(checkMovement, 60_000);
    return () => clearInterval(id);
  }, []);

  // Last-refresh timestamp — always fetch on mount so "Closed at" shows the correct time.
  // Interval polling only runs when market is open.
  useEffect(() => {
    // Initial unconditional fetch — gives us the last-known data time even when closed
    analyticsApi.lastRefresh().then((data) => {
      if (data?.last_refresh_utc) setLastDataUpdate(new Date(data.last_refresh_utc));
    });

    const id = setInterval(() => {
      if (!isMarketOpen()) return;          // stop calling after close
      analyticsApi.lastRefresh().then((data) => {
        if (data?.last_refresh_utc) setLastDataUpdate(new Date(data.last_refresh_utc));
      });
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  const displayUpdate = marketOpen && tickerLastUpdate ? tickerLastUpdate : lastDataUpdate;

  // Relative-time label ticker — only runs while market is open; freezes on close
  useEffect(() => {
    if (!displayUpdate || !marketOpen) return;
    const id = setInterval(() => setRelativeTick((t) => t + 1), 10_000);
    return () => clearInterval(id);
  }, [displayUpdate, marketOpen]);

  const dotClass = displayUpdate && marketOpen
    ? "bg-emerald-500 animate-pulse"
    : lastDataUpdate && !marketOpen
      ? "bg-amber-500"
      : "bg-slate-500";

  return (
    <Layout subheader={<MarketTicker refreshTick={refreshTick} onTickerUpdate={setTickerLastUpdate} />}>
      {/* ── Top bar ── */}
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <h2 className="font-bold text-slate-100 text-xl leading-none">Options Analytics</h2>
          <p className="text-xs text-slate-500 mt-0.5">NSE · BSE derivatives · Real-time positioning</p>
        </div>

        <div className="flex items-center gap-4 shrink-0 flex-wrap">
          {/* Last updated pill */}
          <div className="flex items-center gap-2 text-xs bg-surface-card/80 border border-surface-border rounded-lg px-3 py-1.5">
            <span className={`inline-block h-2 w-2 rounded-full ${dotClass}`} title="Data status" />
            <span className="text-slate-400">
              {displayUpdate ? (
                <>
                  {marketOpen ? "Live" : "Closed at"}:{" "}
                  <span className="text-slate-200 font-medium">
                    {displayUpdate.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                  </span>
                  {/* Show relative time only while market is open */}
                  {marketOpen && (
                    <span className="ml-1 text-slate-500">({formatRelative(displayUpdate)})</span>
                  )}
                </>
              ) : (
                marketOpen ? "Fetching…" : "Market closed"
              )}
            </span>
          </div>

          {/* Tab switcher */}
          <div className="flex gap-1 bg-surface-card border border-surface-border rounded-xl p-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={clsx(
                  "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all",
                  tab === t.id
                    ? "bg-brand-600 text-white shadow"
                    : "text-slate-400 hover:text-slate-100 hover:bg-white/5"
                )}
              >
                <span>{t.icon}</span>
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ══ TAB 1 — SIGNALS ══════════════════════════════════════════ */}
      {tab === "signals" && (
        <div className="space-y-8">
          <div className="space-y-3">
            <SectionLabel number="⚡" title="Quick Signals" />
            <QuickSignalsCard />
          </div>
          <div className="space-y-3">
            <SectionLabel number="1" title="Market Sentiment" />
            <MarketBiasPanel onDataLoaded={onDataLoaded} refreshTick={refreshTick} />
          </div>
          <div className="space-y-3">
            <SectionLabel number="2" title="Trade Signals" />
            <TradeSignalsPanel refreshTick={refreshTick} />
          </div>
          <div className="space-y-3">
            <SectionLabel number="3" title="AI Market Insights" />
            <AIInsightsPanel onDataLoaded={onDataLoaded} refreshTick={movementTick} />
          </div>
          <TimeFactorCard symbol="NIFTY" refreshTick={refreshTick} onDataLoaded={onDataLoaded} />
        </div>
      )}

      {/* ══ TAB 2 — DEEP DIVE ════════════════════════════════════════ */}
      {tab === "deepdive" && (
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500 shrink-0">Select index:</span>
            <div className="flex gap-1 bg-surface-card border border-surface-border rounded-lg p-1">
              {SYMBOLS.map((s) => (
                <button
                  key={s}
                  onClick={() => setSymbol(s)}
                  className={clsx(
                    "px-4 py-1.5 rounded-md text-sm font-medium transition-all",
                    symbol === s
                      ? "bg-brand-600 text-white shadow-sm"
                      : "text-slate-400 hover:text-slate-100 hover:bg-white/5"
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
            <div className="flex-1 h-px bg-surface-border" />
            <span className="text-xs text-slate-500 shrink-0">Showing: {symbol}</span>
          </div>

          <OptionsDashboard symbol={symbol} onDataLoaded={onDataLoaded} refreshTick={refreshTick} />
          <GammaWallChart   symbol={symbol} onDataLoaded={onDataLoaded} refreshTick={refreshTick} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <OptionsFlowPanel symbol={symbol} onDataLoaded={onDataLoaded} refreshTick={refreshTick} />
            <AlertsPanel      symbol={symbol} />
          </div>
        </div>
      )}

      {/* ══ TAB 4 — COMMODITIES ═══════════════════════════════════════ */}
      {tab === "commodities" && (
        <div className="space-y-5">
          <div className="space-y-3">
            <SectionLabel number="1" title="Top 4 Commodities" />
            <CommoditiesPanel />
          </div>
          <p className="text-[10px] text-slate-600">
            Signals are futures-based (price/momentum/timeframe alignment). Refreshes every 15 s.
          </p>
        </div>
      )}
      {/* ══ TAB 3 — CHARTS (coming soon) ════════════════════════════ */}
      {tab === "charts" && (
        <div className="flex flex-col items-center justify-center py-24 gap-6">
          <span className="text-6xl opacity-30">📈</span>
          <div className="text-center">
            <h3 className="text-xl font-bold text-slate-300 mb-2">Charts — Coming Soon</h3>
            <p className="text-sm text-slate-500 max-w-md leading-relaxed">
              TradingView index charts for NIFTY · BANKNIFTY · SENSEX, plus
              proprietary analytics charts powered by our own data.
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-2 mt-1">
            {[
              "Index Candlesticks",
              "PCR Over Time",
              "OI Distribution",
              "OI Buildup Heatmap",
              "Volume Profile",
            ].map((f) => (
              <span
                key={f}
                className="text-[11px] text-slate-500 bg-surface-card border border-surface-border rounded-lg px-3 py-1.5"
              >
                {f}
              </span>
            ))}
          </div>
        </div>
      )}
    </Layout>
  );
}
