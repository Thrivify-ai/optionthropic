/**
 * Admin Signal Analytics — collate buy signals, market moves, win/loss.
 * Admin-only.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import Layout from "../../components/Layout";
import { adminApi } from "../../lib/api";
import { getStoredUser, isAuthenticated } from "../../lib/auth";
import clsx from "clsx";

function MoveCell({ move, outcomeForMove }) {
  if (move == null) return "—";
  const good = outcomeForMove === "Won";
  return <span className={clsx("font-mono", good ? "text-emerald-400" : outcomeForMove === "Lost" ? "text-red-400" : "text-slate-400")}>{move >= 0 ? "+" : ""}{move}</span>;
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString("en-IN", { hour12: false }) : "—";
}

function formatPoints(value) {
  if (value == null) return "—";
  const numeric = Number(value);
  return `${numeric >= 0 ? "+" : ""}${numeric}`;
}

function CalibrationTable({ title, rows }) {
  const showVersion = rows?.some((row) => row.signal_version);
  return (
    <div className="card overflow-hidden">
      <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border">
        {title}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead className="bg-surface-card border-b border-surface-border">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              {showVersion && <th className="p-3">Version</th>}
              <th className="p-3">Confidence</th>
              <th className="p-3">Trade Events</th>
              <th className="p-3">Won</th>
              <th className="p-3">Lost</th>
              <th className="p-3">Unknown</th>
              <th className="p-3">Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {!rows?.length && (
              <tr><td colSpan={showVersion ? 7 : 6} className="p-6 text-center text-slate-500">No calibration data yet</td></tr>
            )}
            {rows?.map((row) => (
              <tr key={`${title}-${row.signal_version ?? "legacy"}-${row.bucket}`} className="border-b border-surface-border/50 hover:bg-white/5">
                {showVersion && <td className="p-3 font-mono text-slate-300">{row.signal_version ?? "legacy"}</td>}
                <td className="p-3 font-mono text-slate-200">{row.bucket}</td>
                <td className="p-3">{row.total}</td>
                <td className="p-3 text-emerald-400">{row.won}</td>
                <td className="p-3 text-red-400">{row.lost}</td>
                <td className="p-3 text-slate-400">{row.unknown}</td>
                <td className="p-3 font-mono text-slate-200">{row.win_rate_pct != null ? `${row.win_rate_pct}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SegmentTable({ title, rows }) {
  return (
    <div className="card overflow-hidden">
      <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border">
        {title}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead className="bg-surface-card border-b border-surface-border">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              <th className="p-3">Segment</th>
              <th className="p-3">Total</th>
              <th className="p-3">Won</th>
              <th className="p-3">Lost</th>
              <th className="p-3">Unknown</th>
              <th className="p-3">Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {!rows?.length && (
              <tr><td colSpan={6} className="p-6 text-center text-slate-500">No segment data yet</td></tr>
            )}
            {rows?.map((row) => (
              <tr key={`${title}-${row.value}`} className="border-b border-surface-border/50 hover:bg-white/5">
                <td className="p-3 font-mono text-slate-200">{row.value}</td>
                <td className="p-3">{row.total}</td>
                <td className="p-3 text-emerald-400">{row.won}</td>
                <td className="p-3 text-red-400">{row.lost}</td>
                <td className="p-3 text-slate-400">{row.unknown}</td>
                <td className="p-3 font-mono text-slate-200">{row.win_rate_pct != null ? `${row.win_rate_pct}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DecisionMixTable({ title, rows }) {
  const tradeRows = (rows || []).filter((row) => row.signal && row.signal !== "Wait");
  return (
    <div className="card overflow-hidden">
      <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border">
        {title}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead className="bg-surface-card border-b border-surface-border">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              <th className="p-3">Version</th>
              <th className="p-3">Signal</th>
              <th className="p-3">Total</th>
              <th className="p-3">Avg Conf</th>
            </tr>
          </thead>
          <tbody>
            {!tradeRows.length && (
              <tr><td colSpan={4} className="p-6 text-center text-slate-500">No trade-signal mix yet</td></tr>
            )}
            {tradeRows.map((row) => (
              <tr key={`${title}-${row.signal_version}-${row.signal}`} className="border-b border-surface-border/50 hover:bg-white/5">
                <td className="p-3 font-mono text-slate-200">{row.signal_version}</td>
                <td className="p-3 font-semibold text-slate-200">{row.signal}</td>
                <td className="p-3">{row.total}</td>
                <td className="p-3 font-mono text-slate-200">{row.avg_confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MonitorWindowTable({ title, windowData }) {
  const engines = Object.keys(windowData || {}).filter((engine) => {
    const row = windowData?.[engine] || {};
    return ["QUICK", "MAIN"].includes(engine) || Number(row.trade_event_total || 0) > 0;
  });
  const visibleEngines = engines.length ? engines : ["QUICK", "MAIN"];
  return (
    <div className="card overflow-hidden">
      <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border">
        {title}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead className="bg-surface-card border-b border-surface-border">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              <th className="p-3">Engine</th>
              <th className="p-3">Total</th>
              <th className="p-3">Buy CE</th>
              <th className="p-3">Buy PE</th>
              <th className="p-3">Long</th>
              <th className="p-3">Short</th>
              <th className="p-3">Hold</th>
              <th className="p-3">Exit</th>
              <th className="p-3">Entry Share</th>
              <th className="p-3">Avg Conf</th>
            </tr>
          </thead>
          <tbody>
            {visibleEngines.map((engine) => {
              const row = windowData?.[engine] || {};
              return (
                <tr key={`${title}-${engine}`} className="border-b border-surface-border/50 hover:bg-white/5">
                  <td className="p-3 font-semibold text-slate-200">{engine}</td>
                  <td className="p-3">{row.trade_event_total ?? 0}</td>
                  <td className="p-3 text-emerald-400">{row.buy_ce ?? 0}</td>
                  <td className="p-3 text-red-400">{row.buy_pe ?? 0}</td>
                  <td className="p-3 text-emerald-300">{row.long ?? 0}</td>
                  <td className="p-3 text-red-300">{row.short ?? 0}</td>
                  <td className="p-3 text-cyan-300">{row.hold ?? 0}</td>
                  <td className="p-3 text-amber-300">{row.exit ?? 0}</td>
                  <td className="p-3 font-mono text-slate-200">{row.entry_share_pct != null ? `${row.entry_share_pct}%` : "—"}</td>
                  <td className="p-3 font-mono text-slate-200">{row.avg_confidence != null ? row.avg_confidence : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EntryBlockReasonTable({ title, rows, total }) {
  return (
    <div className="card overflow-hidden">
      <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border flex items-center gap-3">
        {title}
        <span className="text-xs font-normal text-slate-500">{total ?? 0} blocks (24h)</span>
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead className="bg-surface-card border-b border-surface-border">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              <th className="p-3">Reason</th>
              <th className="p-3">Count</th>
              <th className="p-3">Share</th>
            </tr>
          </thead>
          <tbody>
            {!rows?.length && (
              <tr><td colSpan={3} className="p-6 text-center text-slate-500">No entry blocks recorded</td></tr>
            )}
            {rows?.map((row) => (
              <tr key={`${title}-${row.reason}`} className="border-b border-surface-border/50 hover:bg-white/5">
                <td className="p-3 text-slate-200">{row.reason}</td>
                <td className="p-3 font-mono text-slate-200">{row.count}</td>
                <td className="p-3 font-mono text-slate-200">{row.share_pct != null ? `${row.share_pct}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ManagedDailyPnlTable({ rows, days }) {
  return (
    <div className="card overflow-hidden">
      <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border flex items-center gap-3">
        Managed Trade Daily P&L
        <span className="text-xs font-normal text-slate-500">Last {days ?? 14} days</span>
      </p>
      <div className="overflow-x-auto max-h-[36vh] overflow-y-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 bg-surface-card border-b border-surface-border">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              <th className="p-3">Day (IST)</th>
              <th className="p-3">Engine</th>
              <th className="p-3">Total</th>
              <th className="p-3">Won</th>
              <th className="p-3">Lost</th>
              <th className="p-3">Scratch</th>
              <th className="p-3">Win Rate</th>
              <th className="p-3">Net Points</th>
              <th className="p-3">Avg Points</th>
            </tr>
          </thead>
          <tbody>
            {!rows?.length && (
              <tr><td colSpan={9} className="p-8 text-center text-slate-500">No managed trades in this window</td></tr>
            )}
            {rows?.map((row, idx) => (
              <tr key={`${row.trade_day}-${row.engine}-${idx}`} className="border-b border-surface-border/50 hover:bg-white/5">
                <td className="p-3 font-mono text-slate-300">{row.trade_day}</td>
                <td className="p-3 font-semibold text-slate-200">{row.engine}</td>
                <td className="p-3">{row.total}</td>
                <td className="p-3 text-emerald-400">{row.won}</td>
                <td className="p-3 text-red-400">{row.lost}</td>
                <td className="p-3 text-slate-400">{row.scratch}</td>
                <td className="p-3 font-mono text-slate-200">{row.win_rate_pct != null ? `${row.win_rate_pct}%` : "—"}</td>
                <td className={clsx("p-3 font-mono", row.net_points > 0 ? "text-emerald-400" : row.net_points < 0 ? "text-red-400" : "text-slate-300")}>
                  {row.net_points != null ? row.net_points : "—"}
                </td>
                <td className="p-3 font-mono text-slate-200">{row.avg_points != null ? row.avg_points : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ManagedSummaryCards({ summaryByEngine }) {
  const rows = Object.entries(summaryByEngine || {});
  if (!rows.length) return null;

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      {rows.map(([engine, row]) => (
        <div key={engine} className="card border border-surface-border p-4">
          <p className="section-kicker">{engine}</p>
          <div className="mt-3 flex items-end justify-between gap-3">
            <div>
              <p className="text-2xl font-semibold text-slate-100">
                {row.win_rate_pct != null ? `${row.win_rate_pct}%` : "Pending"}
              </p>
              <p className="mt-1 text-xs text-slate-500">Managed win rate</p>
            </div>
            <div className="text-right font-mono text-xs text-slate-400">
              <p>{row.entries ?? row.total ?? 0} entries</p>
              <p>{row.closed ?? 0} closed</p>
              <p>{row.open ?? 0} open</p>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-400">
            <span>Avg hold: <b className="text-slate-200">{row.avg_duration_label ?? "—"}</b></span>
            <span className="text-right">Protect exits: <b className="text-amber-300">{row.protective_exits ?? 0}</b></span>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2 text-center text-[10px]">
            <span className="rounded-lg bg-emerald-500/10 py-1 text-emerald-300">W {row.won ?? 0}</span>
            <span className="rounded-lg bg-red-500/10 py-1 text-red-300">L {row.lost ?? 0}</span>
            <span className="rounded-lg bg-slate-500/10 py-1 text-slate-300">S {row.scratch ?? 0}</span>
            <span className={clsx("rounded-lg py-1", Number(row.net_points || 0) >= 0 ? "bg-emerald-500/10 text-emerald-300" : "bg-red-500/10 text-red-300")}>
              {Number(row.net_points || 0) >= 0 ? "+" : ""}{row.net_points ?? 0}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function ManagedTradesTable({ rows }) {
  return (
    <div className="card overflow-hidden">
      <p className="flex items-center gap-3 border-b border-surface-border p-4 text-sm font-semibold text-slate-200">
        Entry-to-Exit Trade Ledger
        <span className="text-xs font-normal text-slate-500">BUY to EXIT is the source of truth for win rate</span>
      </p>
      <div className="max-h-[42vh] overflow-x-auto overflow-y-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 border-b border-surface-border bg-surface-card">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              <th className="p-3">Entry Time</th>
              <th className="p-3">Exit Time</th>
              <th className="p-3">Held</th>
              <th className="p-3">Engine</th>
              <th className="p-3">Symbol</th>
              <th className="p-3">Entry</th>
              <th className="p-3">Exit</th>
              <th className="p-3">Points</th>
              <th className="p-3">MFE / MAE</th>
              <th className="p-3">Result</th>
              <th className="p-3">Exit Type</th>
              <th className="p-3">Reason</th>
            </tr>
          </thead>
          <tbody>
            {!rows?.length && (
              <tr><td colSpan={12} className="p-8 text-center text-slate-500">No managed BUY-to-EXIT trades in this period</td></tr>
            )}
            {rows?.map((row) => {
              const points = row.captured_points ?? row.realized_points ?? row.latest_points;
              const result = row.result_label || (row.status === "OPEN" ? "Open" : "Unknown");
              const bullish = row.entry_signal?.includes("CE") || row.entry_signal === "LONG";
              return (
                <tr key={`${row.engine}-${row.id}`} className="border-b border-surface-border/50 hover:bg-white/5">
                  <td className="p-3 font-mono text-xs text-slate-400">
                    {formatDateTime(row.entry_time)}
                  </td>
                  <td className="p-3 font-mono text-xs text-slate-400">{row.exit_time ? formatDateTime(row.exit_time) : "Open"}</td>
                  <td className="p-3 font-mono text-xs text-slate-300">{row.trade_duration_label ?? "—"}</td>
                  <td className="p-3 font-semibold text-slate-200">{row.engine}</td>
                  <td className="p-3 font-semibold text-slate-200">{row.symbol}</td>
                  <td className={clsx("p-3 font-bold", bullish ? "text-emerald-400" : "text-red-400")}>
                    {row.entry_signal}
                    <span className="ml-2 font-mono text-xs font-normal text-slate-500">
                      @ {row.entry_price ?? "—"} / {row.entry_confidence ?? 0}%
                    </span>
                  </td>
                  <td className="p-3 text-slate-300">
                    {row.exit_signal || row.latest_signal || "—"}
                    <span className="ml-2 font-mono text-xs text-slate-500">
                      @ {row.exit_price ?? row.latest_price ?? "—"}
                    </span>
                  </td>
                  <td className={clsx("p-3 font-mono", Number(points || 0) > 0 ? "text-emerald-400" : Number(points || 0) < 0 ? "text-red-400" : "text-slate-300")}>
                    {formatPoints(points)}
                  </td>
                  <td className="p-3 font-mono text-xs text-slate-300">
                    {formatPoints(row.max_favorable_points)}
                    <span className="mx-1 text-slate-600">/</span>
                    {formatPoints(row.max_adverse_points)}
                  </td>
                  <td className="p-3">
                    <span className={clsx(
                      "rounded px-2 py-0.5 text-xs font-bold",
                      result === "Won" && "bg-emerald-500/20 text-emerald-400",
                      result === "Lost" && "bg-red-500/20 text-red-400",
                      result === "Scratch" && "bg-slate-500/20 text-slate-300",
                      result === "Open" && "bg-cyan-500/20 text-cyan-300",
                      result === "Unknown" && "bg-slate-500/20 text-slate-400"
                    )}>
                      {result}
                    </span>
                  </td>
                  <td className="p-3">
                    <span className={clsx(
                      "rounded px-2 py-0.5 text-xs font-bold",
                      row.protective_exit ? "bg-amber-500/20 text-amber-300" : "bg-slate-500/20 text-slate-300"
                    )}>
                      {row.exit_type || row.status}
                    </span>
                  </td>
                  <td className="max-w-[360px] truncate p-3 text-xs text-slate-500">
                    {row.exit_reason || row.entry_reason || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AdminAnalytics() {
  const router = useRouter();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(7);

  const [authChecked, setAuthChecked] = useState(false);
  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    const user = getStoredUser();
    if (!user?.is_admin) {
      router.replace("/dashboard");
      return;
    }
    setAuthChecked(true);
  }, [router]);

  useEffect(() => {
    adminApi
      .signalAnalytics(days, 200)
      .then(setData)
      .catch((e) => setError(e.message || "Failed to load"))
      .finally(() => setLoading(false));
  }, [days]);

  if (!authChecked || !getStoredUser()?.is_admin) {
    return <Layout><div className="card animate-pulse h-64" /></Layout>;
  }

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="font-bold text-slate-100 text-xl">Signal Analytics</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              BUY to EXIT trade lifecycle, hold time, captured points, and win/loss quality. WAIT is diagnostics only.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link href="/admin/sandbox" className="btn-ghost text-sm">
              Open Sandbox Lab
            </Link>
            <span className="text-xs text-slate-500">Period:</span>
            {[7, 14, 30].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={clsx(
                  "px-3 py-1.5 rounded-lg text-sm font-medium",
                  days === d ? "bg-brand-600 text-white" : "bg-surface-card border border-surface-border text-slate-400 hover:text-slate-200"
                )}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {loading && <div className="card animate-pulse h-48" />}
        {error && <div className="card border-red-500/50 text-red-400 p-4">{error}</div>}
        {data && !loading && (
          <>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <MonitorWindowTable
                title="Trade Event Mix (Last 3h)"
                windowData={data.signal_monitor?.decision_windows?.["3h"]}
              />
              <MonitorWindowTable
                title="Trade Event Mix (Last 24h)"
                windowData={data.signal_monitor?.decision_windows?.["24h"]}
              />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <EntryBlockReasonTable
                title="Quick Entry Block Reasons"
                total={data.signal_monitor?.entry_block_reasons_24h?.QUICK?.total}
                rows={data.signal_monitor?.entry_block_reasons_24h?.QUICK?.top_reasons}
              />
              <EntryBlockReasonTable
                title="Long Entry Block Reasons"
                total={data.signal_monitor?.entry_block_reasons_24h?.MAIN?.total}
                rows={data.signal_monitor?.entry_block_reasons_24h?.MAIN?.top_reasons}
              />
            </div>

            <ManagedDailyPnlTable
              rows={data.signal_monitor?.managed_daily_pnl}
              days={data.signal_monitor?.days}
            />

            <ManagedSummaryCards summaryByEngine={data.managed_summary_by_engine} />

            <ManagedTradesTable rows={data.managed_trades} />

            <p className="text-xs text-slate-500">
              Managed trades are the scorecard: only real entries, holds, exits, duration, and captured points count toward win rate. WAIT decisions stay out of P&L and remain useful only for block diagnostics.
            </p>

            {/* Quick Signals — short-term (2m, 3m) */}
            <div className="card overflow-hidden">
              <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border flex items-center gap-3">
                Quick Horizon Checks (2m, 3m)
                <span className="text-xs font-normal text-slate-500">
                  {data.quick_summary?.total ?? 0} total · Won {data.quick_summary?.won ?? 0} · Lost {data.quick_summary?.lost ?? 0}
                  {data.quick_summary?.win_rate_pct != null && ` · ${data.quick_summary.win_rate_pct}% directional hit rate`}
                </span>
              </p>
              <div className="overflow-x-auto max-h-[40vh] overflow-y-auto">
                <table className="w-full text-left">
                  <thead className="sticky top-0 bg-surface-card border-b border-surface-border">
                    <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                      <th className="p-3">Time</th>
                      <th className="p-3">Symbol</th>
                      <th className="p-3">Signal</th>
                      <th className="p-3">@ Signal</th>
                      <th className="p-3">2m</th>
                      <th className="p-3">Move 2m</th>
                      <th className="p-3">3m</th>
                      <th className="p-3">Move 3m</th>
                      <th className="p-3">Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.quick_signals?.length === 0 && (
                      <tr><td colSpan={9} className="p-8 text-center text-slate-500">No quick signals in this period</td></tr>
                    )}
                    {data.quick_signals?.map((s) => {
                      const outcome = s.outcome_2m !== "Unknown" ? s.outcome_2m : s.outcome_3m;
                      return (
                        <tr key={s.id} className="border-b border-surface-border/50 hover:bg-white/5">
                          <td className="p-3 font-mono text-xs text-slate-400">{s.created_at ? new Date(s.created_at).toLocaleString("en-IN", { hour12: false }) : "—"}</td>
                          <td className="p-3 font-semibold text-slate-200">{s.symbol}</td>
                          <td className="p-3"><span className={clsx("font-bold", s.signal === "Buy CE" ? "text-emerald-400" : "text-red-400")}>{s.signal}</span></td>
                          <td className="p-3 font-mono text-sm">{s.price_at_signal != null ? s.price_at_signal.toLocaleString("en-IN") : "—"}</td>
                          <td className="p-3 font-mono text-sm">{s.price_2m != null ? s.price_2m.toLocaleString("en-IN") : "—"}</td>
                          <td className="p-3 font-mono text-sm"><MoveCell move={s.move_2m} outcomeForMove={s.outcome_2m} /></td>
                          <td className="p-3 font-mono text-sm">{s.price_3m != null ? s.price_3m.toLocaleString("en-IN") : "—"}</td>
                          <td className="p-3 font-mono text-sm"><MoveCell move={s.move_3m} outcomeForMove={s.outcome_3m} /></td>
                          <td className="p-3"><span className={clsx("text-xs font-bold px-2 py-0.5 rounded", outcome === "Won" && "bg-emerald-500/20 text-emerald-400", outcome === "Lost" && "bg-red-500/20 text-red-400", outcome === "Unknown" && "bg-slate-500/20 text-slate-400")}>{outcome}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Long Signals — long-term (5m, 10m, 30m) */}
            <div className="card overflow-hidden">
              <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border flex items-center gap-3">
                Long Horizon Checks (5m, 10m, 30m)
                <span className="text-xs font-normal text-slate-500">
                  {data.long_summary?.total ?? 0} total · Won {data.long_summary?.won ?? 0} · Lost {data.long_summary?.lost ?? 0}
                  {data.long_summary?.win_rate_pct != null && ` · ${data.long_summary.win_rate_pct}% directional hit rate`}
                </span>
              </p>
              <div className="overflow-x-auto max-h-[40vh] overflow-y-auto">
                <table className="w-full text-left">
                  <thead className="sticky top-0 bg-surface-card border-b border-surface-border">
                    <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                      <th className="p-3">Time</th>
                      <th className="p-3">Symbol</th>
                      <th className="p-3">Signal</th>
                      <th className="p-3">@ Signal</th>
                      <th className="p-3">5m</th>
                      <th className="p-3">Move</th>
                      <th className="p-3">10m</th>
                      <th className="p-3">Move</th>
                      <th className="p-3">30m</th>
                      <th className="p-3">Move</th>
                      <th className="p-3">Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.long_signals?.length === 0 && (
                      <tr><td colSpan={11} className="p-8 text-center text-slate-500">No long signals in this period</td></tr>
                    )}
                    {data.long_signals?.map((s) => {
                      const outcome = s.outcome_5m !== "Unknown" ? s.outcome_5m : s.outcome_10m !== "Unknown" ? s.outcome_10m : s.outcome_30m;
                      return (
                        <tr key={s.id} className="border-b border-surface-border/50 hover:bg-white/5">
                          <td className="p-3 font-mono text-xs text-slate-400">{s.created_at ? new Date(s.created_at).toLocaleString("en-IN", { hour12: false }) : "—"}</td>
                          <td className="p-3 font-semibold text-slate-200">{s.symbol}</td>
                          <td className="p-3"><span className={clsx("font-bold", s.signal === "Buy CE" ? "text-emerald-400" : "text-red-400")}>{s.signal}</span></td>
                          <td className="p-3 font-mono text-sm">{s.price_at_signal != null ? s.price_at_signal.toLocaleString("en-IN") : "—"}</td>
                          <td className="p-3 font-mono text-sm">{s.price_5m != null ? s.price_5m.toLocaleString("en-IN") : "—"}</td>
                          <td className="p-3 font-mono text-sm"><MoveCell move={s.move_5m} outcomeForMove={s.outcome_5m} /></td>
                          <td className="p-3 font-mono text-sm">{s.price_10m != null ? s.price_10m.toLocaleString("en-IN") : "—"}</td>
                          <td className="p-3 font-mono text-sm"><MoveCell move={s.move_10m} outcomeForMove={s.outcome_10m} /></td>
                          <td className="p-3 font-mono text-sm">{s.price_30m != null ? s.price_30m.toLocaleString("en-IN") : "—"}</td>
                          <td className="p-3 font-mono text-sm"><MoveCell move={s.move_30m} outcomeForMove={s.outcome_30m} /></td>
                          <td className="p-3"><span className={clsx("text-xs font-bold px-2 py-0.5 rounded", outcome === "Won" && "bg-emerald-500/20 text-emerald-400", outcome === "Lost" && "bg-red-500/20 text-red-400", outcome === "Unknown" && "bg-slate-500/20 text-slate-400")}>{outcome}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <CalibrationTable title="Quick Confidence Calibration" rows={data.quick_calibration} />
            <CalibrationTable title="Long Confidence Calibration" rows={data.long_calibration} />

            <div className="card overflow-hidden">
              <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border flex items-center gap-3">
                Quant Outcomes (Option Economics)
                <span className="text-xs font-normal text-slate-500">
                  Quick {data.quick_quant_summary?.total ?? 0} total · Long {data.long_quant_summary?.total ?? 0} total
                </span>
              </p>
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-0 xl:divide-x divide-surface-border">
                <div className="p-4 space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Quick Option Premium Outcomes</p>
                  <div className="overflow-x-auto max-h-[32vh] overflow-y-auto">
                    <table className="w-full text-left">
                      <thead className="sticky top-0 bg-surface-card border-b border-surface-border">
                        <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                          <th className="p-2">Time</th>
                          <th className="p-2">Version</th>
                          <th className="p-2">Signal</th>
                          <th className="p-2">Opt @Entry</th>
                          <th className="p-2">2m</th>
                          <th className="p-2">3m</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.quick_quant_signals?.slice(0, 40).map((row) => (
                          <tr key={`quick-quant-${row.id}`} className="border-b border-surface-border/50 hover:bg-white/5">
                            <td className="p-2 font-mono text-[11px] text-slate-400">{row.entry_time ? new Date(row.entry_time).toLocaleString("en-IN", { hour12: false }) : "—"}</td>
                            <td className="p-2 font-mono text-[11px] text-slate-300">{row.signal_version}</td>
                            <td className={clsx("p-2 font-bold", row.signal === "Buy CE" ? "text-emerald-400" : "text-red-400")}>{row.signal}</td>
                            <td className="p-2 font-mono text-[11px]">{row.option_entry_ltp != null ? row.option_entry_ltp : "—"}</td>
                            <td className="p-2 font-mono text-[11px]"><MoveCell move={row.option_move_2m} outcomeForMove={row.option_outcome_2m} /></td>
                            <td className="p-2 font-mono text-[11px]"><MoveCell move={row.option_move_3m} outcomeForMove={row.option_outcome_3m} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div className="p-4 space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Long Option Premium Outcomes</p>
                  <div className="overflow-x-auto max-h-[32vh] overflow-y-auto">
                    <table className="w-full text-left">
                      <thead className="sticky top-0 bg-surface-card border-b border-surface-border">
                        <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                          <th className="p-2">Time</th>
                          <th className="p-2">Version</th>
                          <th className="p-2">Signal</th>
                          <th className="p-2">Opt @Entry</th>
                          <th className="p-2">5m</th>
                          <th className="p-2">10m</th>
                          <th className="p-2">30m</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.long_quant_signals?.slice(0, 40).map((row) => (
                          <tr key={`long-quant-${row.id}`} className="border-b border-surface-border/50 hover:bg-white/5">
                            <td className="p-2 font-mono text-[11px] text-slate-400">{row.entry_time ? new Date(row.entry_time).toLocaleString("en-IN", { hour12: false }) : "—"}</td>
                            <td className="p-2 font-mono text-[11px] text-slate-300">{row.signal_version}</td>
                            <td className={clsx("p-2 font-bold", row.signal === "Buy CE" ? "text-emerald-400" : "text-red-400")}>{row.signal}</td>
                            <td className="p-2 font-mono text-[11px]">{row.option_entry_ltp != null ? row.option_entry_ltp : "—"}</td>
                            <td className="p-2 font-mono text-[11px]"><MoveCell move={row.option_move_5m} outcomeForMove={row.option_outcome_5m} /></td>
                            <td className="p-2 font-mono text-[11px]"><MoveCell move={row.option_move_10m} outcomeForMove={row.option_outcome_10m} /></td>
                            <td className="p-2 font-mono text-[11px]"><MoveCell move={row.option_move_30m} outcomeForMove={row.option_outcome_30m} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>

            <CalibrationTable title="Quant Calibration By Version" rows={data.quant_calibration} />

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <SegmentTable title="Quick By Session" rows={data.quick_segments?.session_bucket} />
              <SegmentTable title="Quick By Vol Regime" rows={data.quick_segments?.vol_regime} />
              <SegmentTable title="Quick By Breakout Class" rows={data.quick_segments?.breakout_class} />
              <SegmentTable title="Quick By Expiry Bucket" rows={data.quick_segments?.expiry_bucket} />
              <SegmentTable title="Long By Session" rows={data.long_segments?.session_bucket} />
              <SegmentTable title="Long By Vol Regime" rows={data.long_segments?.vol_regime} />
              <SegmentTable title="Long By Breakout Class" rows={data.long_segments?.breakout_class} />
              <SegmentTable title="Long By Expiry Bucket" rows={data.long_segments?.expiry_bucket} />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <DecisionMixTable title="Quick Live vs Shadow Trade Signals" rows={data.quick_decision_mix} />
              <DecisionMixTable title="Long Live vs Shadow Trade Signals" rows={data.long_decision_mix} />
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
