import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/router";
import clsx from "clsx";

import Layout from "../components/Layout";
import { isAuthenticated } from "../lib/auth";
import { publishingApi } from "../lib/api";

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

function StatusButton({ active, tone, children, onClick }) {
  const tones = {
    draft: active
      ? "border-slate-400/30 bg-slate-400/15 text-slate-100"
      : "border-white/10 bg-white/5 text-slate-400 hover:text-slate-200",
    approved: active
      ? "border-sky-500/30 bg-sky-500/15 text-sky-300"
      : "border-white/10 bg-white/5 text-slate-400 hover:text-slate-200",
    published: active
      ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-300"
      : "border-white/10 bg-white/5 text-slate-400 hover:text-slate-200",
  };

  return (
    <button
      onClick={onClick}
      className={clsx(
        "rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-all",
        tones[tone]
      )}
    >
      {children}
    </button>
  );
}

function DraftCard({ draft, onStatusChange, busy }) {
  const status = draft?.status || "draft";

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="section-kicker">{draft.post_type?.replaceAll("_", " ")}</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-100">{draft.title}</h3>
          <p className="mt-1 text-[11px] text-slate-500">{draft.generated_at_ist}</p>
        </div>
        <CopyButton text={draft.text} />
      </div>

      <div className="flex flex-wrap gap-2">
        {draft.bias ? <span className="stat-pill">{draft.bias}</span> : null}
        {draft.probability != null ? <span className="stat-pill">{draft.probability}%</span> : null}
        {draft.impact_score != null ? <span className="stat-pill">Impact {draft.impact_score}</span> : null}
        {draft.source ? <span className="stat-pill">{draft.source}</span> : null}
      </div>

      <div className="flex flex-wrap gap-2">
        <StatusButton tone="draft" active={status === "draft"} onClick={() => onStatusChange(draft.id, "draft")}>
          {busy ? "Saving..." : "Draft"}
        </StatusButton>
        <StatusButton tone="approved" active={status === "approved"} onClick={() => onStatusChange(draft.id, "approved")}>
          Approve
        </StatusButton>
        <StatusButton tone="published" active={status === "published"} onClick={() => onStatusChange(draft.id, "published")}>
          Published
        </StatusButton>
      </div>

      <textarea
        readOnly
        value={draft.text}
        className="min-h-[220px] w-full rounded-[1.25rem] border border-surface-border bg-white/5 px-4 py-3 text-sm leading-relaxed text-slate-200"
      />

      <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-xs text-slate-400">
        <span className="font-semibold text-slate-300">CTA</span>
        {" · "}
        {draft.link_label || "optionthropic.com"}
      </div>
    </div>
  );
}

function BatchSummary({ batch, selected, onSelect }) {
  const statusCounts = batch?.status_counts || {};

  return (
    <button
      onClick={onSelect}
      className={clsx(
        "w-full rounded-[1.5rem] border p-4 text-left transition-all",
        selected
          ? "border-brand-500/40 bg-brand-500/10 shadow-[0_16px_40px_-28px_rgba(63,203,255,0.5)]"
          : "border-surface-border bg-white/5 hover:border-white/20 hover:bg-white/10"
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="section-kicker">{batch.channel_type}</p>
          <h3 className="mt-1 text-sm font-semibold text-slate-100">
            {batch.bias || "Neutral"} {batch.probability != null ? `${batch.probability}%` : ""}
          </h3>
        </div>
        <span className="stat-pill">Impact {batch.impact_score ?? 0}</span>
      </div>

      <p className="mt-2 text-xs text-slate-500">{batch.generated_at_ist}</p>

      <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-slate-300">
          {batch.draft_count} drafts
        </span>
        <span className="rounded-full border border-sky-500/20 bg-sky-500/10 px-2 py-1 text-sky-300">
          {statusCounts.approved || 0} approved
        </span>
        <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-emerald-300">
          {statusCounts.published || 0} published
        </span>
      </div>
    </button>
  );
}

function replaceDraftInBatch(batch, updatedDraft) {
  if (!batch || !updatedDraft) return batch;
  if (batch.batch_id !== updatedDraft.batch_id) return batch;

  const drafts = (batch.drafts || []).map((draft) => (draft.id === updatedDraft.id ? updatedDraft : draft));
  const statusCounts = { draft: 0, approved: 0, published: 0 };
  drafts.forEach((draft) => {
    statusCounts[draft.status] = (statusCounts[draft.status] || 0) + 1;
  });

  return {
    ...batch,
    drafts,
    status_counts: statusCounts,
  };
}

export default function PublishingPage() {
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [selectedBatchId, setSelectedBatchId] = useState(null);
  const [busyDraftId, setBusyDraftId] = useState(null);

  const loadWorkspace = (loader = publishingApi.workspace, { selectLatest = false } = {}) => {
    setError(null);
    return loader("whatsapp")
      .then((payload) => {
        setData(payload);
        setSelectedBatchId((current) => {
          if (selectLatest) {
            return payload?.current_batch?.batch_id || payload?.history?.[0]?.batch_id || null;
          }
          return current || payload?.current_batch?.batch_id || payload?.history?.[0]?.batch_id || null;
        });
      })
      .catch((e) => setError(e.message || "Failed to load publishing workspace"))
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    setAuthChecked(true);
    loadWorkspace();
  }, [router]);

  const selectedBatch = useMemo(() => {
    const history = data?.history || [];
    return history.find((item) => item.batch_id === selectedBatchId) || data?.current_batch || null;
  }, [data, selectedBatchId]);

  const handleRefresh = () => {
    setRefreshing(true);
    loadWorkspace(publishingApi.refreshWorkspace, { selectLatest: true });
  };

  const handleStatusChange = async (draftId, status) => {
    try {
      setBusyDraftId(draftId);
      const updatedDraft = await publishingApi.updateDraftStatus(draftId, status);
      setData((current) => {
        if (!current) return current;
        return {
          ...current,
          current_batch: replaceDraftInBatch(current.current_batch, updatedDraft),
          history: (current.history || []).map((batch) => replaceDraftInBatch(batch, updatedDraft)),
        };
      });
    } catch (e) {
      setError(e.message || "Failed to update draft status");
    } finally {
      setBusyDraftId(null);
    }
  };

  if (!authChecked) {
    return (
      <Layout>
        <div className="card h-64 animate-pulse" />
      </Layout>
    );
  }

  const livePreview = data?.live_preview || {};

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="section-kicker">Publishing Workspace</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-100">Manual channel drafts, organized.</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
              Generate channel-ready market posts from live desk context, approve them internally, and mark them published after posting to WhatsApp manually.
            </p>
          </div>
          <button onClick={handleRefresh} className="btn-ghost text-sm">
            {refreshing ? "Generating..." : "Generate New Batch"}
          </button>
        </div>

        {loading ? <div className="card h-48 animate-pulse" /> : null}
        {error ? <div className="card border border-red-500/30 text-red-300">{error}</div> : null}

        {data && !loading ? (
          <>
            <div className="card grid gap-4 md:grid-cols-4">
              <div>
                <p className="section-kicker">Channel</p>
                <p className="mt-2 text-2xl font-semibold text-slate-100">{data.channel_type}</p>
              </div>
              <div>
                <p className="section-kicker">Live Bias</p>
                <p className="mt-2 text-2xl font-semibold text-slate-100">
                  {livePreview.market_bias?.bias} {livePreview.market_bias?.probability}%
                </p>
              </div>
              <div>
                <p className="section-kicker">News Impact</p>
                <p className="mt-2 text-2xl font-semibold text-slate-100">{livePreview.news_impact_score || 0}/100</p>
              </div>
              <div>
                <p className="section-kicker">Latest Drafts</p>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">
                  {data.current_batch?.generated_at_ist || "Not generated yet"}
                </p>
              </div>
            </div>

            <div className="space-y-4">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="section-kicker">Current Batch</p>
                  <h3 className="mt-1 text-lg font-semibold text-slate-100">
                    {data.current_batch?.bias || "Neutral"} {data.current_batch?.probability != null ? `${data.current_batch.probability}%` : ""}
                  </h3>
                </div>
                <span className="stat-pill">
                  {data.current_batch?.draft_count || 0} drafts
                </span>
              </div>

              <div className="grid gap-6 xl:grid-cols-2">
                {(data.current_batch?.drafts || []).map((draft) => (
                  <DraftCard
                    key={draft.id}
                    draft={draft}
                    busy={busyDraftId === draft.id}
                    onStatusChange={handleStatusChange}
                  />
                ))}
              </div>
            </div>

            <div className="grid gap-6 xl:grid-cols-[340px,minmax(0,1fr)]">
              <div className="space-y-3">
                <div>
                  <p className="section-kicker">Saved History</p>
                  <h3 className="mt-1 text-lg font-semibold text-slate-100">Recent draft batches</h3>
                </div>
                {(data.history || []).map((batch) => (
                  <BatchSummary
                    key={batch.batch_id}
                    batch={batch}
                    selected={selectedBatchId === batch.batch_id}
                    onSelect={() => setSelectedBatchId(batch.batch_id)}
                  />
                ))}
              </div>

              <div className="space-y-4">
                <div>
                  <p className="section-kicker">Batch Preview</p>
                  <h3 className="mt-1 text-lg font-semibold text-slate-100">
                    {selectedBatch?.generated_at_ist || "Select a batch"}
                  </h3>
                </div>

                {selectedBatch ? (
                  <div className="grid gap-6 xl:grid-cols-2">
                    {(selectedBatch.drafts || []).map((draft) => (
                      <DraftCard
                        key={draft.id}
                        draft={draft}
                        busy={busyDraftId === draft.id}
                        onStatusChange={handleStatusChange}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="card text-sm text-slate-400">No saved batches yet.</div>
                )}
              </div>
            </div>
          </>
        ) : null}
      </div>
    </Layout>
  );
}
