import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import { authApi } from "../lib/api";

export default function Profile() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    authApi
      .me()
      .then(setUser)
      .catch(() => setError("Failed to load profile"))
      .finally(() => setLoading(false));
  }, []);

  const PLAN_FEATURES = {
    free: [
      "NIFTY analytics (delayed 15 min)",
      "5 alerts per day",
      "Basic gamma walls",
    ],
    pro: [
      "All symbols — real-time",
      "Unlimited alerts",
      "AI market insights",
      "Smart money flow",
      "Liquidity trap detection",
    ],
    enterprise: [
      "Everything in Pro",
      "Dedicated support",
      "Custom alert rules",
      "API access",
    ],
  };

  return (
    <Layout>
      <div className="max-w-xl">
        <h2 className="font-bold text-slate-100 text-lg mb-6">Your Profile</h2>

        {loading && (
          <div className="card animate-pulse h-32" />
        )}
        {error && <p className="text-red-400">{error}</p>}

        {user && (
          <div className="space-y-4">
            <div className="card space-y-3">
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                  First name
                </p>
                <p className="text-slate-200">{user.first_name || user.email?.split("@")?.[0] || "Member"}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                  Email
                </p>
                <p className="text-slate-200">{user.email}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                  Plan
                </p>
                <span className="badge-blue capitalize">{user.plan}</span>
              </div>
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                  Member since
                </p>
                <p className="text-slate-300 text-sm">
                  {new Date(user.created_at).toLocaleDateString("en-IN", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })}
                </p>
              </div>
              {user.is_admin && (
                <div>
                  <span className="badge-yellow">Admin</span>
                </div>
              )}
            </div>

            <div className="card">
              <h3 className="font-semibold text-slate-100 mb-3">
                Plan Features —{" "}
                <span className="text-brand-400 capitalize">{user.plan}</span>
              </h3>
              <ul className="space-y-1.5">
                {(PLAN_FEATURES[user.plan] || []).map((f, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm text-slate-300">
                    <span className="text-emerald-400 text-xs">✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              {user.plan !== "enterprise" && (
                <button className="btn-primary mt-4 text-sm">
                  Upgrade Plan
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
