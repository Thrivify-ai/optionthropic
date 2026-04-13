import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import clsx from "clsx";

import Layout from "../../components/Layout";
import { adminApi } from "../../lib/api";
import { getStoredUser, isAuthenticated } from "../../lib/auth";

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className={clsx(
        "rounded-xl px-3 py-2 text-xs font-semibold transition-all",
        copied
          ? "bg-emerald-500/20 text-emerald-300"
          : "bg-surface-card border border-surface-border text-slate-300 hover:bg-white/5"
      )}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function DraftCard({ title, text, meta }) {
  return (
    <div className="card space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="section-kicker">Broadcast Draft</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-100">{title}</h3>
        </div>
        <CopyButton text={text} />
      </div>

      {meta ? (
        <div className="flex flex-wrap gap-2">
          {meta.bias ? <span className="stat-pill">{meta.bias}</span> : null}
          {meta.probability != null ? <span className="stat-pill">{meta.probability}%</span> : null}
          {meta.impact_score != null ? <span className="stat-pill">Impact {meta.impact_score}</span> : null}
          {meta.source ? <span className="stat-pill">{meta.source}</span> : null}
        </div>
      ) : null}

      <textarea
        readOnly
        value={text}
        className="min-h-[240px] w-full rounded-[1.25rem] border border-surface-border bg-white/5 px-4 py-3 text-sm leading-relaxed text-slate-200"
      />
    </div>
  );
}

export default function AdminBroadcasts() {
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadDesk = () => {
    setLoading(true);
    adminApi
      .broadcastDesk()
      .then(setData)
      .catch((e) => setError(e.message || "Failed to load broadcast desk"))
      .finally(() => setLoading(false));
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
    loadDesk();
  }, [router]);

  if (!authChecked || !getStoredUser()?.is_admin) {
    return <Layout><div className="card h-64 animate-pulse" /></Layout>;
  }

  const posts = data?.posts || {};

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-slate-100">Broadcast Desk</h2>
            <p className="mt-1 text-xs text-slate-500">
              Copy-ready WhatsApp channel posts with rotating Optionthropic links and critical news context.
            </p>
            {data?.generated_at_ist ? (
              <p className="mt-1 text-[11px] text-slate-500">Generated: {data.generated_at_ist}</p>
            ) : null}
          </div>
          <button onClick={loadDesk} className="btn-ghost text-sm">
            Refresh Drafts
          </button>
        </div>

        {loading ? <div className="card h-48 animate-pulse" /> : null}
        {error ? <div className="card border border-red-500/30 text-red-300">{error}</div> : null}

        {data && !loading ? (
          <>
            <div className="card grid gap-4 md:grid-cols-3">
              <div>
                <p className="section-kicker">Market Bias</p>
                <p className="mt-2 text-2xl font-semibold text-slate-100">
                  {data.market_bias?.bias} {data.market_bias?.probability}%
                </p>
              </div>
              <div>
                <p className="section-kicker">News Impact</p>
                <p className="mt-2 text-2xl font-semibold text-slate-100">{data.news_impact_score}/100</p>
              </div>
              <div>
                <p className="section-kicker">Top Headlines</p>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">
                  {(data.news_headlines || []).slice(0, 2).join(" | ") || "No critical headline dominating the desk."}
                </p>
              </div>
            </div>

            <div className="grid gap-6 xl:grid-cols-2">
              <DraftCard title="Morning Bias" text={posts.morning_bias?.text || ""} meta={posts.morning_bias} />
              <DraftCard title="Intraday Update" text={posts.intraday_update?.text || ""} meta={posts.intraday_update} />
            </div>

            <DraftCard title="Closing Wrap" text={posts.closing_wrap?.text || ""} meta={posts.closing_wrap} />

            <div className="space-y-4">
              <div>
                <p className="section-kicker">Critical News Alerts</p>
                <h3 className="mt-1 text-lg font-semibold text-slate-100">Manual alert drafts</h3>
              </div>
              <div className="grid gap-6 xl:grid-cols-2">
                {(posts.news_alerts || []).length ? (
                  posts.news_alerts.map((item) => (
                    <DraftCard
                      key={item.id}
                      title={item.title}
                      text={item.text}
                      meta={{ impact_score: item.impact_score, source: item.source }}
                    />
                  ))
                ) : (
                  <div className="card text-sm text-slate-400">No critical news alert draft right now.</div>
                )}
              </div>
            </div>
          </>
        ) : null}
      </div>
    </Layout>
  );
}
