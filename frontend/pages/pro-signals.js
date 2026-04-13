import { useEffect, useState } from "react";
import clsx from "clsx";

import Layout from "../components/Layout";
import ProTicker from "../components/ProTicker";
import ProCommodities from "../components/ProCommodities";
import QuickSignalsCard from "../components/QuickSignalsCard";
import TradeSignalsPanel from "../components/TradeSignalsPanel";
import MarketBiasPanel from "../components/MarketBiasPanel";
import AIInsightsPanel from "../components/AIInsightsPanel";
import GlobalAlertsPanel from "../components/GlobalAlertsPanel";
import UpgradePrompt from "../components/UpgradePrompt";
import { analyticsApi, authApi } from "../lib/api";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"];
const REFRESH_MS = 15000;
const MAX_HISTORY_ROWS = 12;
const ACTIVE_INDEX_SIGNALS = ["Buy CE", "Buy PE", "Hold CE", "Hold PE"];
const TABS = [
  { id: "markets", label: "Markets", icon: "MK" },
  { id: "commodities", label: "Commodities", icon: "CM" },
];

function hasProAccess(user) {
  if (!user) return false;
  if (user.is_admin) return true;
  return user.plan === "pro" || user.plan === "enterprise";
}

function normalizeHistory(list) {
  if (!Array.isArray(list)) return [];

  const seen = new Set();

  return list
    .filter((entry) => entry?.signal === "Buy CE" || entry?.signal === "Buy PE")
    .filter((entry) => {
      const ts = entry?.created_at ? new Date(entry.created_at).getTime() : 0;
      const minuteBucket = Math.floor(ts / 60000);
      const key = `${entry.symbol}|${entry.signal}|${entry.level ?? ""}|${minuteBucket}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((entry) => ({
      ...entry,
      timeLabel: entry?.created_at
        ? (entry?.datetime_ist ||
          new Date(entry.created_at).toLocaleString("en-IN", {
            hour12: false,
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }))
        : "--:--:--",
      levelLabel:
        entry?.level != null ? Number(entry.level).toLocaleString("en-IN") : "Spot unavailable",
      momentumLabel:
        entry?.momentum != null && Number(entry.momentum) !== 0
          ? `${Number(entry.momentum) > 0 ? "+" : ""}${Number(entry.momentum).toFixed(0)}`
          : null,
    }))
    .slice(0, MAX_HISTORY_ROWS);
}

function SectionHeader({ kicker, title, description, badge, badgeTone = "amber" }) {
  const tone =
    badgeTone === "emerald"
      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
      : badgeTone === "sky"
        ? "border-sky-500/20 bg-sky-500/10 text-sky-300"
        : "border-amber-500/20 bg-amber-500/10 text-amber-300";

  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <div>
        <p className="section-kicker">{kicker}</p>
        <h3 className="mt-2 text-2xl font-semibold text-slate-100">{title}</h3>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">{description}</p>
      </div>
      {badge ? (
        <span className={clsx("stat-pill w-fit", tone)}>
          {badge}
        </span>
      ) : null}
    </div>
  );
}

function RecentDeskCalls({ history, loading }) {
  const symbolCounts = SYMBOLS.map((symbol) => ({
    symbol,
    count: history.filter((entry) => entry.symbol === symbol).length,
  }));

  return (
    <div className="surface-panel rounded-[2rem] p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="section-kicker">Recent Desk Calls</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-100">Suggested spots, organized.</h2>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            Review the exact spot, direction, and momentum the desk suggested without digging through raw logs.
          </p>
        </div>
        <span className="stat-pill border-white/10 text-slate-300">
          {loading ? "Loading history" : `${history.length} tracked calls`}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {symbolCounts.map(({ symbol, count }) => (
          <span
            key={symbol}
            className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-slate-300"
          >
            {symbol} {count}
          </span>
        ))}
      </div>

      <div className="mt-4 space-y-2">
        {loading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="h-[84px] animate-pulse rounded-2xl border border-surface-border bg-surface/40"
            />
          ))
        ) : history.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-surface-border bg-surface/40 px-4 py-6 text-center text-sm text-slate-500">
            No quick calls have been saved yet.
          </div>
        ) : (
          history.map((entry) => {
            const signalTone =
              entry.signal === "Buy CE"
                ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
                : "border-red-500/20 bg-red-500/10 text-red-300";

            return (
              <div
                key={entry.id}
                className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-white/20"
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-slate-500">{entry.timeLabel}</span>
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[11px] font-semibold text-slate-200">
                      {entry.symbol}
                    </span>
                    <span className={clsx("rounded-full border px-2 py-1 text-[11px] font-semibold", signalTone)}>
                      {entry.signal}
                    </span>
                    <span className="text-xs text-slate-400">
                      Spot <span className="font-mono text-slate-200">{entry.levelLabel}</span>
                    </span>
                  </div>
                  <span className={clsx(
                    "text-xs font-semibold",
                    entry.momentumLabel == null
                      ? "text-slate-500"
                      : Number(entry.momentum) >= 0
                        ? "text-emerald-300"
                        : "text-red-300"
                  )}>
                    {entry.momentumLabel ? `Momentum ${entry.momentumLabel}` : "Momentum n/a"}
                  </span>
                </div>
                <p className="mt-2 line-clamp-2 text-sm leading-relaxed text-slate-400">
                  {entry.reason || "Saved from the quick signal desk."}
                </p>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export default function ProSignals() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("markets");
  const [overview, setOverview] = useState({});
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    authApi
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (loading || !hasProAccess(user)) return undefined;

    let cancelled = false;

    const loadDesk = () => {
      Promise.all([
        analyticsApi.dashboardOverview(true),
        analyticsApi.buySignalHistory(null, { todayOnly: true, limit: 200 }),
      ])
        .then(([overviewData, historyData]) => {
          if (cancelled) return;
          setOverview(overviewData?.symbols || {});
          setHistory(normalizeHistory(historyData));
        })
        .catch(() => {
          if (cancelled) return;
          setOverview({});
          setHistory([]);
        })
        .finally(() => {
          if (cancelled) return;
          setOverviewLoading(false);
          setHistoryLoading(false);
        });
    };

    loadDesk();
    const id = setInterval(() => {
      setRefreshTick((tick) => tick + 1);
      loadDesk();
    }, REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [loading, user]);

  if (loading) {
    return (
      <Layout>
        <div className="card h-64 animate-pulse" />
      </Layout>
    );
  }

  if (!hasProAccess(user)) {
    return (
      <Layout>
        <UpgradePrompt />
      </Layout>
    );
  }

  const symbolEntries = SYMBOLS.map((symbol) => overview[symbol] || {});
  const quickStates = symbolEntries.map((entry) => entry.quick_signal || {});
  const longStates = symbolEntries.map((entry) => entry.trading_signal || {});

  const activeQuick = quickStates.filter((entry) => ACTIVE_INDEX_SIGNALS.includes(entry.quick_signal)).length;
  const formingQuick = quickStates.filter((entry) => entry.state === "candidate" || entry.state === "setup").length;
  const activeLong = longStates.filter((entry) => ACTIVE_INDEX_SIGNALS.includes(entry.signal)).length;
  const bullishOutlook = longStates.filter((entry) => entry.outlook === "Bullish" || entry.bias_60m === "Bullish").length;
  const bearishOutlook = longStates.filter((entry) => entry.outlook === "Bearish" || entry.bias_60m === "Bearish").length;

  return (
    <Layout>
      <div className="space-y-6">
        <section className="surface-panel rounded-[2rem] p-5">
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="stat-pill border-brand-500/20 bg-brand-500/10 text-brand-300">
                    Pro Desk
                  </span>
                  <span className="stat-pill border-white/10 text-slate-300">
                    Aurora workflow
                  </span>
                </div>
                <h1 className="mt-3 text-3xl font-semibold leading-tight text-slate-100">
                  Signals first. Everything else stays in support.
                </h1>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
                  Aurora keeps the execution layer visually first, then adds long bias, market context,
                  commodities, and alerts without letting the page turn noisy.
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                <span className="stat-pill border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
                  {overviewLoading ? "Quick --" : `Quick ${activeQuick}`}
                </span>
                <span className="stat-pill border-sky-500/20 bg-sky-500/10 text-sky-300">
                  {overviewLoading ? "Setups --" : `Setups ${formingQuick}`}
                </span>
                <span className="stat-pill border-amber-500/20 bg-amber-500/10 text-amber-300">
                  {overviewLoading ? "Long --" : `Long ${activeLong}`}
                </span>
                <span className="stat-pill border-white/10 text-slate-300">
                  {historyLoading ? "Calls --" : `Calls ${history.length}`}
                </span>
              </div>
            </div>

            <div className="rounded-[1.5rem] border border-white/10 bg-white/5 p-3">
              <ProTicker />
            </div>

            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
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

              <p className="text-xs text-slate-500">
                {tab === "markets" && "Quick signals, long bias, market conditions, AI desk notes, and critical alerts."}
                {tab === "commodities" && "Cross-asset watchlist with news-aware commodity cards."}
              </p>
            </div>
          </div>
        </section>

        {tab === "markets" && (
          <section className="space-y-6">
            <section className="space-y-4">
              <SectionHeader
                kicker="Pro execution layer"
                title="Quick Signals"
                description="Fast intraday entries built for discipline, not overtrading."
                badge="Live Now"
                badgeTone="amber"
              />
              <QuickSignalsCard />
            </section>

            <section className="space-y-4">
              <SectionHeader
                kicker="Directional context"
                title="Trade Signal (Long)"
                description="Higher-timeframe direction and entry readiness to keep quick trades aligned with the tape."
                badge={overviewLoading ? "Loading" : `${bullishOutlook} Bullish | ${bearishOutlook} Bearish`}
                badgeTone="sky"
              />
              <TradeSignalsPanel refreshTick={refreshTick} />
            </section>

            <section className="space-y-4">
              <SectionHeader
                kicker="Market state"
                title="Market Conditions"
                description="Writer positioning, support and resistance, and whether the tape is trending or trapped."
                badge="Decision Context"
                badgeTone="emerald"
              />
              <MarketBiasPanel refreshTick={refreshTick} />
            </section>

            <section className="space-y-4">
              <SectionHeader
                kicker="Desk intelligence"
                title="Live Insights"
                description="AI notes that explain the tape after the signal stack, not before it."
                badge="AI Layer"
                badgeTone="amber"
              />
              <AIInsightsPanel refreshTick={refreshTick} />
            </section>

            <section className="space-y-4">
              <SectionHeader
                kicker="Event radar"
                title="Critical Alerts and Desk History"
                description="Global headline risk and the recent desk calls that mattered, without leaving the market workflow."
                badge={historyLoading ? "Loading" : `${history.length} recent calls`}
                badgeTone="sky"
              />
              <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
                <div className="space-y-4">
                  <GlobalAlertsPanel />
                </div>
                <div className="space-y-4">
                  <RecentDeskCalls history={history} loading={historyLoading} />
                </div>
              </div>
            </section>
          </section>
        )}

        {tab === "commodities" && (
          <section className="space-y-4">
            <SectionHeader
              kicker="Cross-asset"
              title="Commodities"
              description="MCX cards for crude, natural gas, gold, and silver with quick and long-term signals."
              badge="Quick + Long"
              badgeTone="sky"
            />
            <ProCommodities />
          </section>
        )}

      </div>
    </Layout>
  );
}
