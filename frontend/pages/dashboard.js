import { useState, useEffect, useCallback } from "react";
import clsx from "clsx";

import Layout from "../components/Layout";
import { analyticsApi } from "../lib/api";
import { isMarketOpen } from "../components/MarketTicker";
import MarketBiasPanel from "../components/MarketBiasPanel";
import TradeSignalsPanel from "../components/TradeSignalsPanel";
import AIInsightsPanel from "../components/AIInsightsPanel";
import TimeFactorCard from "../components/TimeFactorCard";
import MarketTicker from "../components/MarketTicker";
import CommoditiesPanel from "../components/CommoditiesPanel";
import OptionsDashboard from "../components/OptionsDashboard";
import GammaWallChart from "../components/GammaWallChart";
import OptionsFlowPanel from "../components/OptionsFlowPanel";
import AlertsPanel from "../components/AlertsPanel";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const TABS = [
  { id: "signals", label: "Signals", icon: "SG" },
  { id: "deepdive", label: "Deep Dive", icon: "DD" },
  { id: "charts", label: "Charts", icon: "CH" },
  { id: "commodities", label: "Commodities", icon: "CM" },
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
    <div className="mb-2 flex items-center gap-2">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-brand-600/90 text-xs font-bold text-white shadow-sm shadow-brand-500/20">
        {number}
      </span>
      <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
      <div className="ml-2 h-px flex-1 bg-surface-border/80" />
    </div>
  );
}

export default function Dashboard() {
  const [tab, setTab] = useState("signals");
  const [symbol, setSymbol] = useState("NIFTY");
  const [lastDataUpdate, setLastDataUpdate] = useState(null);
  const [tickerLastUpdate, setTickerLastUpdate] = useState(null);
  const [, setRelativeTick] = useState(0);
  const [refreshTick, setRefreshTick] = useState(0);
  const [movementTick, setMovementTick] = useState(0);
  const [marketOpen, setMarketOpen] = useState(isMarketOpen());

  const onDataLoaded = useCallback(() => {
    analyticsApi.lastRefresh().then((data) => {
      if (data?.last_refresh_utc) setLastDataUpdate(new Date(data.last_refresh_utc));
    });
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      const open = isMarketOpen();
      setMarketOpen(open);
      if (open) setRefreshTick((tick) => tick + 1);
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const checkMovement = () => {
      if (!isMarketOpen()) return;
      Promise.all(
        SYMBOLS.map((item) =>
          analyticsApi.movement(item).catch(() => ({ movement_significant: false }))
        )
      ).then((results) => {
        if (results.some((item) => item?.movement_significant)) {
          setMovementTick((tick) => tick + 1);
        }
      });
    };

    checkMovement();
    const id = setInterval(checkMovement, 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    analyticsApi.lastRefresh().then((data) => {
      if (data?.last_refresh_utc) setLastDataUpdate(new Date(data.last_refresh_utc));
    });

    const id = setInterval(() => {
      if (!isMarketOpen()) return;
      analyticsApi.lastRefresh().then((data) => {
        if (data?.last_refresh_utc) setLastDataUpdate(new Date(data.last_refresh_utc));
      });
    }, 30_000);

    return () => clearInterval(id);
  }, []);

  const displayUpdate = marketOpen && tickerLastUpdate ? tickerLastUpdate : lastDataUpdate;

  useEffect(() => {
    if (!displayUpdate || !marketOpen) return undefined;
    const id = setInterval(() => setRelativeTick((tick) => tick + 1), 10_000);
    return () => clearInterval(id);
  }, [displayUpdate, marketOpen]);

  const dotClass = displayUpdate && marketOpen
    ? "bg-emerald-500 animate-pulse"
    : lastDataUpdate && !marketOpen
      ? "bg-amber-500"
      : "bg-slate-500";

  return (
    <Layout subheader={<MarketTicker refreshTick={refreshTick} onTickerUpdate={setTickerLastUpdate} />}>
      <section className="surface-panel mb-6 rounded-[2rem] p-5">
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="section-kicker">Core Workspace</p>
              <h2 className="mt-2 text-3xl font-semibold leading-tight text-slate-100">
                Options analytics, cleaned up for real decision-making.
              </h2>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
                Live market structure, disciplined trade signals, and AI-backed context for
                NIFTY, BANKNIFTY, and SENSEX.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              <span className="stat-pill border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
                3 indices
              </span>
              <span className="stat-pill border-sky-500/20 bg-sky-500/10 text-sky-300">
                Multi-timeframe
              </span>
              <span className="stat-pill border-white/10 text-slate-300">
                Aurora Desk
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex items-center gap-2 rounded-2xl border border-surface-border bg-white/5 px-4 py-3 text-xs">
              <span className={`inline-block h-2.5 w-2.5 rounded-full ${dotClass}`} title="Data status" />
              <span className="text-slate-400">
                {displayUpdate ? (
                  <>
                    {marketOpen ? "Live" : "Closed at"}{" "}
                    <span className="font-semibold text-slate-100">
                      {displayUpdate.toLocaleTimeString("en-IN", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                    {marketOpen ? (
                      <span className="ml-1 text-slate-500">({formatRelative(displayUpdate)})</span>
                    ) : null}
                  </>
                ) : marketOpen ? (
                  "Fetching..."
                ) : (
                  "Market closed"
                )}
              </span>
            </div>

            <div className="flex flex-wrap gap-2 rounded-2xl border border-surface-border bg-white/5 p-1.5">
              {TABS.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setTab(item.id)}
                  className={clsx(
                    "flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all",
                    tab === item.id
                      ? "bg-brand-600 text-white shadow-lg shadow-brand-500/20"
                      : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
                  )}
                >
                  <span className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-white/10 bg-white/5 text-[10px] font-semibold">
                    {item.icon}
                  </span>
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {tab === "signals" && (
        <div className="space-y-8">
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

      {tab === "deepdive" && (
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <span className="shrink-0 text-xs text-slate-500">Select index:</span>
            <div className="flex gap-1 rounded-lg border border-surface-border bg-surface-card p-1">
              {SYMBOLS.map((item) => (
                <button
                  key={item}
                  onClick={() => setSymbol(item)}
                  className={clsx(
                    "rounded-md px-4 py-1.5 text-sm font-medium transition-all",
                    symbol === item
                      ? "bg-brand-600 text-white shadow-sm shadow-brand-500/20"
                      : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
                  )}
                >
                  {item}
                </button>
              ))}
            </div>
            <div className="h-px flex-1 bg-surface-border" />
            <span className="shrink-0 text-xs text-slate-500">Showing: {symbol}</span>
          </div>

          <OptionsDashboard symbol={symbol} onDataLoaded={onDataLoaded} refreshTick={refreshTick} />
          <GammaWallChart symbol={symbol} onDataLoaded={onDataLoaded} refreshTick={refreshTick} />

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <OptionsFlowPanel symbol={symbol} onDataLoaded={onDataLoaded} refreshTick={refreshTick} />
            <AlertsPanel symbol={symbol} />
          </div>
        </div>
      )}

      {tab === "commodities" && (
        <div className="space-y-5">
          <div className="space-y-3">
            <SectionLabel number="1" title="Top 4 Commodities" />
            <CommoditiesPanel />
          </div>
          <p className="text-[10px] text-slate-600">
            Signals are futures-based with price, momentum, and timeframe alignment. Refreshes every 15s.
          </p>
        </div>
      )}

      {tab === "charts" && (
        <div className="flex flex-col items-center justify-center gap-6 py-24">
          <span className="text-6xl opacity-30">/</span>
          <div className="text-center">
            <h3 className="mb-2 text-xl font-bold text-slate-300">Charts - Coming Soon</h3>
            <p className="max-w-md text-sm leading-relaxed text-slate-500">
              TradingView index charts for NIFTY, BANKNIFTY, and SENSEX, plus proprietary analytics
              charts powered by our own data.
            </p>
          </div>
          <div className="mt-1 flex flex-wrap justify-center gap-2">
            {[
              "Index Candlesticks",
              "PCR Over Time",
              "OI Distribution",
              "OI Buildup Heatmap",
              "Volume Profile",
            ].map((item) => (
              <span
                key={item}
                className="rounded-lg border border-surface-border bg-surface-card px-3 py-1.5 text-[11px] text-slate-500"
              >
                {item}
              </span>
            ))}
          </div>
        </div>
      )}
    </Layout>
  );
}
