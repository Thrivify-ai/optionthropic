import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/router";
import clsx from "clsx";

import Layout from "../../components/Layout";
import { analyticsApi } from "../../lib/api";
import { getStoredUser, isAuthenticated } from "../../lib/auth";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOIL", "NATGAS", "GOLD", "SILVER"];
const STEP_OPTIONS = [90, 120, 150, 180];

function StatCard({ label, value, hint, tone = "default" }) {
  const toneClass =
    tone === "green"
      ? "text-emerald-300"
      : tone === "red"
        ? "text-rose-300"
        : tone === "blue"
          ? "text-sky-300"
          : "text-slate-100";

  return (
    <div className="card">
      <p className="section-kicker">{label}</p>
      <p className={clsx("mt-2 text-2xl font-semibold", toneClass)}>{value}</p>
      {hint ? <p className="mt-2 text-xs leading-relaxed text-slate-500">{hint}</p> : null}
    </div>
  );
}

function EngineSummaryCard({ title, summary, meta }) {
  return (
    <div className="card space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="section-kicker">Engine Summary</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-100">{title}</h3>
        </div>
        <span className="stat-pill border-white/10 text-slate-300">
          {summary?.trades ?? 0} trades
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Win Rate"
          value={summary?.win_rate_pct != null ? `${summary.win_rate_pct}%` : "No trades"}
          hint="Wins are measured from captured points after entry to exit."
          tone="green"
        />
        <StatCard
          label="Average"
          value={summary?.avg_points != null ? `${summary.avg_points > 0 ? "+" : ""}${summary.avg_points}` : "-"}
          hint="Average points captured across closed sandbox trades."
          tone={summary?.avg_points > 0 ? "green" : summary?.avg_points < 0 ? "red" : "default"}
        />
        <StatCard
          label="Best"
          value={summary?.best_points != null ? `${summary.best_points > 0 ? "+" : ""}${summary.best_points}` : "-"}
          hint="Largest realized move captured by this engine."
          tone="blue"
        />
        <StatCard
          label="Worst"
          value={summary?.worst_points != null ? `${summary.worst_points > 0 ? "+" : ""}${summary.worst_points}` : "-"}
          hint="Deepest realized drawdown or losing exit."
          tone={summary?.worst_points < 0 ? "red" : "default"}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Directional frames</p>
          <p className="mt-2 text-sm font-semibold text-slate-100">{meta.directionalFrames}</p>
        </div>
        <div className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Average confidence</p>
          <p className="mt-2 text-sm font-semibold text-slate-100">{meta.avgConfidence != null ? meta.avgConfidence : "-"}</p>
        </div>
        <div className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Entries / Exits</p>
          <p className="mt-2 text-sm font-semibold text-slate-100">{meta.entries} / {meta.exits}</p>
        </div>
      </div>
    </div>
  );
}

function toneForSignal(signal) {
  if (signal === "Buy CE") return "text-emerald-300 bg-emerald-500/10 border-emerald-500/20";
  if (signal === "Buy PE") return "text-rose-300 bg-rose-500/10 border-rose-500/20";
  if (signal === "EXIT") return "text-amber-300 bg-amber-500/10 border-amber-500/20";
  if (signal === "HOLD") return "text-sky-300 bg-sky-500/10 border-sky-500/20";
  return "text-slate-300 bg-white/5 border-white/10";
}

function PricePathChart({ frames }) {
  const chart = useMemo(() => {
    if (!frames?.length) return null;
    const width = 960;
    const height = 300;
    const padX = 28;
    const padY = 24;
    const prices = frames.map((frame) => frame.price);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceSpan = Math.max(maxPrice - minPrice, 1);
    const xStep = frames.length > 1 ? (width - padX * 2) / (frames.length - 1) : 0;
    const yForPrice = (price) => height - padY - ((price - minPrice) / priceSpan) * (height - padY * 2);

    const line = frames
      .map((frame, index) => `${padX + index * xStep},${yForPrice(frame.price)}`)
      .join(" ");

    const quickMarkers = frames
      .filter((frame) => frame.quick?.state === "entry" || frame.quick?.state === "exit")
      .map((frame) => ({
        x: padX + (frame.step - 1) * xStep,
        y: yForPrice(frame.price),
        color: frame.quick.state === "entry" ? "#21d1a5" : "#fb923c",
        label: `Quick ${frame.quick.state}`,
      }));

    const longMarkers = frames
      .filter((frame) => frame.long?.state === "entry" || frame.long?.state === "exit")
      .map((frame) => ({
        x: padX + (frame.step - 1) * xStep,
        y: yForPrice(frame.price),
        color: frame.long.state === "entry" ? "#38bdf8" : "#f472b6",
        label: `Long ${frame.long.state}`,
      }));

    const gridLines = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const price = maxPrice - priceSpan * ratio;
      const y = padY + (height - padY * 2) * ratio;
      return { price, y };
    });

    return { width, height, line, quickMarkers, longMarkers, gridLines, minPrice, maxPrice };
  }, [frames]);

  if (!chart) {
    return <div className="card text-sm text-slate-400">Run a sandbox scenario to see the price path.</div>;
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="section-kicker">Synthetic Tape</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-100">Price path with quick and long markers</h3>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="stat-pill border-emerald-500/20 bg-emerald-500/10 text-emerald-300">Quick entry</span>
          <span className="stat-pill border-amber-500/20 bg-amber-500/10 text-amber-300">Quick exit</span>
          <span className="stat-pill border-sky-500/20 bg-sky-500/10 text-sky-300">Long entry</span>
          <span className="stat-pill border-fuchsia-500/20 bg-fuchsia-500/10 text-fuchsia-300">Long exit</span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${chart.width} ${chart.height}`} className="min-w-[760px] w-full">
          {chart.gridLines.map((line) => (
            <g key={`grid-${line.y}`}>
              <line
                x1="22"
                x2={chart.width - 16}
                y1={line.y}
                y2={line.y}
                stroke="rgba(122,164,192,0.14)"
                strokeDasharray="3 8"
              />
              <text x="0" y={line.y + 4} fill="rgba(148, 163, 184, 0.85)" fontSize="11">
                {line.price.toFixed(2)}
              </text>
            </g>
          ))}

          <polyline
            fill="none"
            stroke="#33c8ff"
            strokeWidth="3"
            strokeLinejoin="round"
            strokeLinecap="round"
            points={chart.line}
          />

          {chart.quickMarkers.map((marker, index) => (
            <circle key={`q-${index}`} cx={marker.x} cy={marker.y} r="5.5" fill={marker.color}>
              <title>{marker.label}</title>
            </circle>
          ))}
          {chart.longMarkers.map((marker, index) => (
            <rect
              key={`l-${index}`}
              x={marker.x - 4.5}
              y={marker.y - 4.5}
              width="9"
              height="9"
              rx="2.5"
              fill={marker.color}
            >
              <title>{marker.label}</title>
            </rect>
          ))}
        </svg>
      </div>

      <div className="flex flex-wrap gap-3 text-xs text-slate-500">
        <span>Low: {chart.minPrice.toFixed(2)}</span>
        <span>High: {chart.maxPrice.toFixed(2)}</span>
        <span>Total frames: {frames.length}</span>
      </div>
    </div>
  );
}

function FrameTable({ frames }) {
  return (
    <div className="card overflow-hidden">
      <div className="flex items-start justify-between gap-3 p-5 pb-4">
        <div>
          <p className="section-kicker">Frame Audit</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-100">Step-by-step signal inspection</h3>
        </div>
        <span className="text-xs text-slate-500">Scroll to inspect the full synthetic session.</span>
      </div>

      <div className="max-h-[32rem] overflow-auto border-t border-surface-border">
        <table className="w-full min-w-[1120px] text-left">
          <thead className="sticky top-0 z-10 bg-surface-card">
            <tr className="text-[10px] uppercase tracking-[0.22em] text-slate-500">
              <th className="p-3">Step</th>
              <th className="p-3">Time</th>
              <th className="p-3">Phase</th>
              <th className="p-3">Price</th>
              <th className="p-3">Quick</th>
              <th className="p-3">Q State</th>
              <th className="p-3">Q Conf</th>
              <th className="p-3">Q Points</th>
              <th className="p-3">Long</th>
              <th className="p-3">L State</th>
              <th className="p-3">L Conf</th>
              <th className="p-3">L Points</th>
            </tr>
          </thead>
          <tbody>
            {frames?.map((frame) => (
              <tr key={frame.step} className="border-t border-surface-border/60 hover:bg-white/5">
                <td className="p-3 font-mono text-xs text-slate-400">{frame.step}</td>
                <td className="p-3 text-xs text-slate-400">
                  {new Date(frame.timestamp).toLocaleTimeString("en-IN", {
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                  })}
                </td>
                <td className="p-3 text-sm text-slate-300">{frame.phase.replaceAll("_", " ")}</td>
                <td className="p-3 font-mono text-sm text-slate-100">{frame.price.toFixed(2)}</td>
                <td className="p-3">
                  <span className={clsx("inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold", toneForSignal(frame.quick?.signal))}>
                    {frame.quick?.signal || "Wait"}
                  </span>
                </td>
                <td className="p-3 text-xs uppercase tracking-[0.16em] text-slate-400">{frame.quick?.state || "-"}</td>
                <td className="p-3 font-mono text-sm text-slate-200">{frame.quick?.confidence ?? "-"}</td>
                <td className="p-3 font-mono text-sm text-slate-200">
                  {frame.quick?.points != null ? `${frame.quick.points > 0 ? "+" : ""}${frame.quick.points}` : "-"}
                </td>
                <td className="p-3">
                  <span className={clsx("inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold", toneForSignal(frame.long?.signal))}>
                    {frame.long?.signal || "Wait"}
                  </span>
                </td>
                <td className="p-3 text-xs uppercase tracking-[0.16em] text-slate-400">{frame.long?.state || "-"}</td>
                <td className="p-3 font-mono text-sm text-slate-200">{frame.long?.confidence ?? "-"}</td>
                <td className="p-3 font-mono text-sm text-slate-200">
                  {frame.long?.points != null ? `${frame.long.points > 0 ? "+" : ""}${frame.long.points}` : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AdminSandbox() {
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);
  const [scenarios, setScenarios] = useState([]);
  const [symbol, setSymbol] = useState("NIFTY");
  const [scenario, setScenario] = useState("trend_up_news");
  const [steps, setSteps] = useState(120);
  const [seed, setSeed] = useState(7);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const runSandbox = async (nextParams = {}) => {
    const params = {
      symbol,
      scenario,
      steps,
      seed,
      ...nextParams,
    };
    setRunning(true);
    setError(null);
    try {
      const data = await analyticsApi.runSandbox(params);
      setResult(data);
    } catch (err) {
      setError(err?.message || "Failed to run sandbox.");
    } finally {
      setRunning(false);
      setLoading(false);
    }
  };

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
    analyticsApi
      .sandboxScenarios()
      .then((data) => {
        const list = data?.scenarios || [];
        setScenarios(list);
        if (list.length && !list.some((item) => item.name === scenario)) {
          setScenario(list[0].name);
        }
      })
      .catch((err) => setError(err?.message || "Failed to load sandbox scenarios."));
  }, [router, scenario]);

  useEffect(() => {
    if (!authChecked) return;
    runSandbox();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authChecked]);

  const scenarioMeta = useMemo(
    () => scenarios.find((item) => item.name === scenario),
    [scenarios, scenario]
  );

  const quickMeta = useMemo(() => {
    const frames = result?.frames || [];
    const directional = frames.filter((frame) => frame.quick?.signal && frame.quick.signal !== "Wait");
    const confFrames = directional.filter((frame) => Number.isFinite(frame.quick?.confidence));
    return {
      directionalFrames: directional.length,
      avgConfidence: confFrames.length
        ? Math.round(confFrames.reduce((sum, frame) => sum + frame.quick.confidence, 0) / confFrames.length)
        : null,
      entries: frames.filter((frame) => frame.quick?.state === "entry").length,
      exits: frames.filter((frame) => frame.quick?.state === "exit").length,
    };
  }, [result]);

  const longMeta = useMemo(() => {
    const frames = result?.frames || [];
    const directional = frames.filter((frame) => frame.long?.signal && frame.long.signal !== "Wait");
    const confFrames = directional.filter((frame) => Number.isFinite(frame.long?.confidence));
    return {
      directionalFrames: directional.length,
      avgConfidence: confFrames.length
        ? Math.round(confFrames.reduce((sum, frame) => sum + frame.long.confidence, 0) / confFrames.length)
        : null,
      entries: frames.filter((frame) => frame.long?.state === "entry").length,
      exits: frames.filter((frame) => frame.long?.state === "exit").length,
    };
  }, [result]);

  const phaseBreakdown = useMemo(() => {
    const counts = new Map();
    for (const frame of result?.frames || []) {
      counts.set(frame.phase, (counts.get(frame.phase) || 0) + 1);
    }
    return Array.from(counts.entries()).map(([phase, count]) => ({ phase, count }));
  }, [result]);

  if (!authChecked || !getStoredUser()?.is_admin) {
    return <Layout><div className="card h-64 animate-pulse" /></Layout>;
  }

  return (
    <Layout>
      <div className="space-y-6">
        <section className="surface-panel rounded-[2rem] p-5">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <p className="section-kicker">Weekend Validation Lab</p>
              <h2 className="mt-2 text-3xl font-semibold leading-tight text-slate-100">
                Replay synthetic market regimes through the real quick and long engines.
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-slate-400">
                Use this sandbox to stress the signal stack on weekends or before changing thresholds.
                It does not write fake market data into production tables.
              </p>
            </div>

            <div className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3 text-xs text-slate-400">
              <p className="font-semibold uppercase tracking-[0.2em] text-slate-500">Current scenario</p>
              <p className="mt-2 text-sm font-semibold text-slate-100">{scenarioMeta?.name || scenario}</p>
              <p className="mt-1 max-w-sm leading-relaxed">{scenarioMeta?.description || "Loading scenario notes..."}</p>
            </div>
          </div>
        </section>

        <section className="card space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="section-kicker">Controls</p>
              <h3 className="mt-1 text-lg font-semibold text-slate-100">Scenario runner</h3>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  const nextSeed = Math.floor(Math.random() * 9999) + 1;
                  setSeed(nextSeed);
                  runSandbox({ seed: nextSeed });
                }}
                className="btn-ghost text-sm"
                disabled={running}
              >
                Shuffle Seed
              </button>
              <button
                onClick={() => runSandbox()}
                className="btn-primary text-sm"
                disabled={running}
              >
                {running ? "Running..." : "Run Sandbox"}
              </button>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <label className="space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Symbol</span>
              <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="input">
                {SYMBOLS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Scenario</span>
              <select value={scenario} onChange={(e) => setScenario(e.target.value)} className="input">
                {scenarios.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Steps</span>
              <select value={steps} onChange={(e) => setSteps(Number(e.target.value))} className="input">
                {STEP_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Seed</span>
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value) || 1)}
                className="input"
                min="1"
              />
            </label>
          </div>

          {error ? <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">{error}</div> : null}
        </section>

        {loading && !result ? <div className="card h-64 animate-pulse" /> : null}

        {result ? (
          <>
            <div className="grid gap-6 xl:grid-cols-2">
              <EngineSummaryCard title="Quick Sandbox" summary={result.summary?.quick} meta={quickMeta} />
              <EngineSummaryCard title="Long Sandbox" summary={result.summary?.long} meta={longMeta} />
            </div>

            <div className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
              <PricePathChart frames={result.frames} />

              <div className="card space-y-4">
                <div>
                  <p className="section-kicker">Session Notes</p>
                  <h3 className="mt-1 text-lg font-semibold text-slate-100">Run metadata</h3>
                </div>
                <div className="grid gap-3">
                  <div className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Symbol</p>
                    <p className="mt-2 text-sm font-semibold text-slate-100">{result.symbol}</p>
                  </div>
                  <div className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Scenario</p>
                    <p className="mt-2 text-sm font-semibold text-slate-100">{result.scenario}</p>
                    <p className="mt-1 text-xs leading-relaxed text-slate-500">{result.description}</p>
                  </div>
                  <div className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Seed / Steps</p>
                    <p className="mt-2 text-sm font-semibold text-slate-100">{result.seed} / {result.steps}</p>
                  </div>
                  <div className="rounded-2xl border border-surface-border bg-white/5 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Phase mix</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {phaseBreakdown.map((item) => (
                        <span key={item.phase} className="stat-pill border-white/10 text-slate-300">
                          {item.phase.replaceAll("_", " ")} x{item.count}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <FrameTable frames={result.frames} />
          </>
        ) : null}
      </div>
    </Layout>
  );
}
