import { useState } from "react";
import Layout from "../components/Layout";

export default function Settings() {
  const [pollInterval, setPollInterval] = useState(60);
  const [alerts, setAlerts] = useState({
    large_flow: true,
    gamma_wall: true,
    max_pain_drift: true,
    positioning_shift: false,
  });
  const [saved, setSaved] = useState(false);

  const save = (e) => {
    e.preventDefault();
    // Placeholder — real implementation would PATCH /auth/me/settings
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <Layout>
      <div className="max-w-xl">
        <h2 className="font-bold text-slate-100 text-lg mb-6">Settings</h2>

        <form onSubmit={save} className="space-y-5">
          {/* Alert preferences */}
          <div className="card">
            <h3 className="font-semibold text-slate-100 mb-4">
              Alert Notifications
            </h3>
            <div className="space-y-3">
              {Object.entries(alerts).map(([key, val]) => (
                <label key={key} className="flex items-center justify-between">
                  <span className="text-sm text-slate-300 capitalize">
                    {key.replace(/_/g, " ")}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setAlerts((prev) => ({ ...prev, [key]: !prev[key] }))
                    }
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                      val ? "bg-brand-600" : "bg-surface-border"
                    }`}
                  >
                    <span
                      className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                        val ? "translate-x-4" : "translate-x-0.5"
                      }`}
                    />
                  </button>
                </label>
              ))}
            </div>
          </div>

          {/* Data settings */}
          <div className="card">
            <h3 className="font-semibold text-slate-100 mb-4">Data Refresh</h3>
            <div>
              <label className="block text-sm text-slate-400 mb-1.5">
                Display refresh interval (seconds)
              </label>
              <select
                className="input"
                value={pollInterval}
                onChange={(e) => setPollInterval(Number(e.target.value))}
              >
                <option value={30}>30</option>
                <option value={60}>60</option>
                <option value={120}>120</option>
                <option value={300}>300</option>
              </select>
              <p className="text-xs text-slate-500 mt-1">
                Backend polling interval is controlled server-side.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button type="submit" className="btn-primary">
              Save changes
            </button>
            {saved && (
              <span className="text-emerald-400 text-sm">Saved!</span>
            )}
          </div>
        </form>
      </div>
    </Layout>
  );
}
