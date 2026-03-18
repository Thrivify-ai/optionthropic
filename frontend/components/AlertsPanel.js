import { useEffect, useState } from "react";
import { analyticsApi } from "../lib/api";
import clsx from "clsx";

const SEVERITY_STYLES = {
  HIGH: "border-l-4 border-red-500 bg-red-900/10",
  MEDIUM: "border-l-4 border-yellow-500 bg-yellow-900/10",
  INFO: "border-l-4 border-blue-500 bg-blue-900/10",
};

const SEVERITY_BADGE = {
  HIGH: "badge-red",
  MEDIUM: "badge-yellow",
  INFO: "badge-blue",
};

function AlertItem({ alert }) {
  return (
    <div
      className={clsx(
        "rounded-lg px-4 py-3 mb-2",
        SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.INFO
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={SEVERITY_BADGE[alert.severity] || "badge-blue"}>
              {alert.alert_type.replace(/_/g, " ")}
            </span>
            <span className="text-xs text-slate-500">
              {new Date(alert.timestamp).toLocaleTimeString("en-IN")}
            </span>
          </div>
          <p className="text-sm text-slate-300 leading-snug">{alert.description}</p>
        </div>
      </div>
    </div>
  );
}

export default function AlertsPanel({ symbol, limit = 20 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchAlerts = () => {
    if (!symbol) return;
    setLoading(true);
    analyticsApi
      .alerts(symbol, limit)
      .then(setData)
      .catch(() => setError("Failed to load alerts"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 15_000); // poll every 15s for live alerts
    return () => clearInterval(interval);
  }, [symbol]);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-slate-100">
          Live Alerts
          {data?.count > 0 && (
            <span className="ml-2 text-xs bg-red-600 text-white rounded-full px-1.5 py-0.5">
              {data.count}
            </span>
          )}
        </h3>
        <button
          onClick={fetchAlerts}
          className="btn-ghost text-xs"
          disabled={loading}
        >
          Refresh
        </button>
      </div>

      {loading && (
        <div className="text-center py-8 text-slate-500 text-sm animate-pulse">
          Loading alerts…
        </div>
      )}
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {!loading && !error && (
        <div className="max-h-80 overflow-y-auto pr-1">
          {(data?.alerts || []).length === 0 ? (
            <p className="text-center text-slate-500 text-sm py-6">
              No alerts for {symbol} yet.
            </p>
          ) : (
            data.alerts.map((alert) => <AlertItem key={alert.id} alert={alert} />)
          )}
        </div>
      )}
    </div>
  );
}
