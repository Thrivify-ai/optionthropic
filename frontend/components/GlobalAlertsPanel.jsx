import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";

import { analyticsApi } from "../lib/api";

const REFRESH_MS = 30_000;
const MAX_ITEMS = 6;
const MAX_ITEMS_COMPACT = 3;

function parseNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatTime(value) {
  if (!value) return "Just now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Just now";
  return date.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatRelative(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.max(0, Math.floor(diffMs / 60000));
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const hours = Math.floor(diffMin / 60);
  return `${hours}h ago`;
}

function extractSymbols(alert) {
  const raw =
    alert?.symbols ||
    alert?.affected_symbols ||
    alert?.symbol_list ||
    alert?.market_symbols ||
    [];
  if (Array.isArray(raw)) return raw.filter(Boolean).slice(0, 4);
  if (typeof raw === "string") return raw.split(/[,|]/).map((item) => item.trim()).filter(Boolean).slice(0, 4);
  if (alert?.symbol) return [alert.symbol];
  return [];
}

function extractPotential(alert) {
  return (
    parseNumber(alert?.impact_score) ??
    parseNumber(alert?.potential_score) ??
    parseNumber(alert?.move_score) ??
    parseNumber(alert?.rating) ??
    parseNumber(alert?.score) ??
    0
  );
}

function extractSeverity(alert, potential) {
  const raw = String(alert?.severity || alert?.priority || "").toUpperCase();
  if (raw.includes("CRIT")) return "CRITICAL";
  if (raw.includes("HIGH")) return "HIGH";
  if (potential >= 90) return "CRITICAL";
  if (potential >= 75) return "HIGH";
  return "HIGH";
}

function normalizeAlert(alert) {
  const potential = extractPotential(alert);
  const severity = extractSeverity(alert, potential);
  const symbols = extractSymbols(alert);
  const source = alert?.source || alert?.provider || alert?.publisher || "Unknown source";
  const title = alert?.headline || alert?.title || alert?.event || "Global market alert";
  const time = formatTime(alert?.published_at || alert?.timestamp || alert?.created_at);

  return {
    id: alert?.id ?? `${source}-${title}-${time}`,
    title,
    source,
    time,
    relativeTime: formatRelative(alert?.published_at || alert?.timestamp || alert?.created_at),
    symbols,
    rationale: alert?.summary || alert?.rationale || alert?.reason || alert?.description || "High-impact event flagged for market monitoring.",
    potential,
    severity,
    category: alert?.category || alert?.type || alert?.tag || "Macro",
    url: alert?.url || alert?.link || null,
  };
}

function SeverityPill({ severity }) {
  const tone =
    severity === "CRITICAL"
      ? "border-red-500/30 bg-red-500/10 text-red-300"
      : "border-amber-500/30 bg-amber-500/10 text-amber-300";

  return (
    <span className={clsx("rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider", tone)}>
      {severity}
    </span>
  );
}

function MarketPotentialBar({ value }) {
  const width = Math.max(0, Math.min(100, value));
  const tone =
    width >= 90
      ? "from-red-500 to-orange-400"
      : width >= 75
        ? "from-amber-500 to-yellow-400"
        : "from-sky-500 to-cyan-400";

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wider text-slate-500">
        <span>Market move potential</span>
        <span>{width}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-border">
        <div className={clsx("h-full rounded-full bg-gradient-to-r", tone)} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function AlertCard({ alert, compact = false }) {
  const isCritical = alert.severity === "CRITICAL";
  return (
    <div className={clsx(
      "rounded-2xl border shadow-lg shadow-black/15 transition-all duration-200 hover:-translate-y-1 hover:shadow-2xl",
      compact ? "p-3" : "p-4",
      isCritical ? "border-red-500/25 bg-red-500/5" : "border-amber-500/20 bg-amber-500/5"
    )}>
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-slate-500">
              {alert.category}
            </p>
            <h4 className={clsx("mt-1 font-semibold text-slate-100 line-clamp-2", compact ? "text-sm" : "text-base")}>
              {alert.title}
            </h4>
          </div>
          <div className="flex flex-col items-end gap-1">
            <SeverityPill severity={alert.severity} />
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-mono text-slate-300">
              Score {alert.potential}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">
            {alert.source}
          </span>
          <span className="font-mono">{alert.time}</span>
          {alert.relativeTime ? <span>{alert.relativeTime}</span> : null}
        </div>

        <MarketPotentialBar value={alert.potential} />

        <div className="flex flex-wrap gap-2">
          {alert.symbols.length > 0 ? (
            alert.symbols.map((symbol) => (
              <span
                key={symbol}
                className="rounded-full border border-surface-border bg-surface/60 px-2.5 py-1 text-[11px] font-medium text-slate-300"
              >
                {symbol}
              </span>
            ))
          ) : (
            <span className="rounded-full border border-surface-border bg-surface/60 px-2.5 py-1 text-[11px] font-medium text-slate-400">
              Broader market
            </span>
          )}
        </div>

        <p className={clsx("leading-relaxed text-slate-300", compact ? "line-clamp-3 text-xs" : "text-sm")}>
          {alert.rationale}
        </p>
      </div>
    </div>
  );
}

export default function GlobalAlertsPanel({ compact = false }) {
  const [payload, setPayload] = useState({ alerts: [], generated_at: null, cached: false });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      analyticsApi
        .globalNewsAlerts()
        .then((data) => {
          if (cancelled) return;
          setPayload({
            ...data,
            alerts: Array.isArray(data?.alerts) ? data.alerts : [],
          });
          setError(null);
        })
        .catch(() => {
          if (cancelled) return;
          setPayload({ alerts: [], generated_at: null, cached: false });
          setError("Critical news feed unavailable right now.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };

    load();
    const id = setInterval(load, REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const criticalAlerts = useMemo(() => {
    const items = (payload.alerts || [])
      .map(normalizeAlert)
      .filter((alert) => alert.severity === "CRITICAL" || alert.potential >= 70)
      .sort((a, b) => b.potential - a.potential)
      .slice(0, compact ? MAX_ITEMS_COMPACT : MAX_ITEMS);

    return items;
  }, [compact, payload.alerts]);

  return (
    <div className={clsx(
      "rounded-[2rem] border border-white/10 bg-[radial-gradient(circle_at_top_right,_rgba(239,68,68,0.12),_transparent_28%),linear-gradient(135deg,rgba(15,23,42,0.98),rgba(9,14,24,0.92))] shadow-2xl shadow-black/20",
      compact ? "p-4" : "p-5"
    )}>
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-rose-300/90">
            Critical Global Alerts
          </p>
          <h3 className={clsx("mt-1 font-semibold text-slate-100", compact ? "text-xl" : "text-2xl")}>
            Only the headlines that can move the tape.
          </h3>
          {!compact ? (
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
              This feed filters aggressively. If an event cannot plausibly move Indian indices,
              it does not show up here.
            </p>
          ) : (
            <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-400">
              Compact rail of high-impact world alerts.
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-300">
            {loading ? "Loading" : `${criticalAlerts.length} critical`}
          </span>
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            {payload.cached ? "Cached" : "Live"}
          </span>
          {payload.generated_at ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-mono text-slate-400">
              {formatTime(payload.generated_at)}
            </span>
          ) : null}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {loading ? (
          Array.from({ length: compact ? 2 : 3 }).map((_, index) => (
            <div key={index} className="h-28 animate-pulse rounded-2xl border border-surface-border bg-surface/40" />
          ))
        ) : error ? (
          <div className="rounded-2xl border border-dashed border-surface-border bg-surface/40 px-4 py-6 text-sm text-slate-400">
            {error}
          </div>
        ) : criticalAlerts.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-surface-border bg-surface/40 px-4 py-6 text-sm text-slate-400">
            No critical global alerts right now. The feed stays hidden until something can actually move the market.
          </div>
        ) : (
          criticalAlerts.map((alert) => <AlertCard key={alert.id} alert={alert} compact={compact} />)
        )}
      </div>
    </div>
  );
}
