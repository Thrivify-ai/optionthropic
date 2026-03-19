/**
 * Pro Signals — live ticks, quick signals, swing signals, explanations.
 * Free users see upgrade prompt; Pro/Enterprise/admin see full content.
 */
import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import ProTicker from "../components/ProTicker";
import QuickSignalsPro from "../components/QuickSignalsPro";
import SwingSignalsPro from "../components/SwingSignalsPro";
import ExplanationCard from "../components/ExplanationCard";
import ProCommodities from "../components/ProCommodities";
import UpgradePrompt from "../components/UpgradePrompt";
import { authApi } from "../lib/api";

function hasProAccess(user) {
  if (!user) return false;
  if (user.is_admin) return true;
  return user.plan === "pro" || user.plan === "enterprise";
}

export default function ProSignals() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    authApi
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Layout>
        <div className="card animate-pulse h-64" />
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

  return (
    <Layout>
      <div className="space-y-6">
        <div>
          <h2 className="font-bold text-slate-100 text-xl leading-none">
            Pro Signals
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Live ticks · 10s quick signals · Swing trend · Simple explanations
          </p>
        </div>

        <section>
          <ProTicker />
        </section>

        <section>
          <h3 className="text-sm font-semibold text-slate-200 mb-2">
            Quick Signals ⚡
          </h3>
          <QuickSignalsPro />
        </section>

        <section>
          <h3 className="text-sm font-semibold text-slate-200 mb-2">
            Swing Signals
          </h3>
          <SwingSignalsPro />
        </section>

        <section>
          <h3 className="text-sm font-semibold text-slate-200 mb-2">
            Explanation
          </h3>
          <ExplanationCard />
        </section>

        <section>
          <h3 className="text-sm font-semibold text-slate-200 mb-2">
            Commodities
          </h3>
          <ProCommodities />
        </section>

        <p className="text-[9px] text-slate-600">
          Pro Signals · Informational only · Not financial advice
        </p>
      </div>
    </Layout>
  );
}
