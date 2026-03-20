/**
 * Admin Signal Analytics — collate buy signals, market moves, win/loss.
 * Admin-only.
 */
import { useEffect, useState } from "react";
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
              <th className="p-3">Total</th>
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
            {!rows?.length && (
              <tr><td colSpan={4} className="p-6 text-center text-slate-500">No decision mix yet</td></tr>
            )}
            {rows?.map((row) => (
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
              Quick (2m, 3m) · Long (5m, 10m, 30m) · Classified by source
            </p>
          </div>
          <div className="flex items-center gap-2">
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
            <p className="text-xs text-slate-500">
              Quick = persisted quick-signal events · Long = persisted main-signal events · Short-term: 2m/3m · Long-term: 5m/10m/30m
            </p>

            {/* Quick Signals — short-term (2m, 3m) */}
            <div className="card overflow-hidden">
              <p className="text-sm font-semibold text-slate-200 p-4 border-b border-surface-border flex items-center gap-3">
                ⚡ Quick Signals (2m, 3m)
                <span className="text-xs font-normal text-slate-500">
                  {data.quick_summary?.total ?? 0} total · Won {data.quick_summary?.won ?? 0} · Lost {data.quick_summary?.lost ?? 0}
                  {data.quick_summary?.win_rate_pct != null && ` · ${data.quick_summary.win_rate_pct}% win rate`}
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
                📈 Long Signals (5m, 10m, 30m)
                <span className="text-xs font-normal text-slate-500">
                  {data.long_summary?.total ?? 0} total · Won {data.long_summary?.won ?? 0} · Lost {data.long_summary?.lost ?? 0}
                  {data.long_summary?.win_rate_pct != null && ` · ${data.long_summary.win_rate_pct}% win rate`}
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
              <DecisionMixTable title="Quick Live vs Shadow Mix" rows={data.quick_decision_mix} />
              <DecisionMixTable title="Long Live vs Shadow Mix" rows={data.long_decision_mix} />
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
