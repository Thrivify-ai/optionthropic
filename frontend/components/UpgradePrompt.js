import Link from "next/link";

export default function UpgradePrompt() {
  return (
    <div className="max-w-4xl mx-auto">
      <div className="overflow-hidden rounded-[2rem] border border-white/10 bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.16),_transparent_28%),linear-gradient(135deg,rgba(15,23,42,0.98),rgba(12,18,30,0.92))] px-8 py-12 shadow-2xl shadow-black/30">
        <div className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-start">
          <div className="space-y-6">
            <div className="inline-flex h-16 w-16 items-center justify-center rounded-2xl border border-amber-400/20 bg-amber-400/10 text-2xl font-semibold text-amber-300">
              P
            </div>

            <div>
              <h2 className="text-3xl font-semibold text-slate-100 mb-3">
                Pro Desk - Upgrade Required
              </h2>
              <p className="text-slate-300 text-base leading-relaxed">
                Long-term trade signals can stay free. The paid edge is the faster intraday layer:
                quick signals, market desk context, and the intelligence stack that will soon include
                global macro and world-news alerts.
              </p>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-2xl border border-amber-500/20 bg-amber-500/8 p-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-amber-300">
                  Pro Unlocks
                </p>
                <p className="mt-2 text-xl font-semibold text-slate-100">Quick Signals</p>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">
                  Intraday entries designed for active traders chasing disciplined 30-40 point index moves.
                </p>
              </div>
              <div className="rounded-2xl border border-sky-500/20 bg-sky-500/8 p-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-sky-300">
                  Free Context
                </p>
                <p className="mt-2 text-xl font-semibold text-slate-100">Trade Signal Bias</p>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">
                  Long/trade signals remain available on the dashboard so users still get directional context.
                </p>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-3">
              <a
                href="mailto:hello@optionthropic.io?subject=Upgrade%20to%20Pro%20Desk"
                className="btn-primary inline-flex items-center justify-center gap-2"
              >
                Upgrade to Pro
              </a>
              <Link
                href="/profile"
                className="btn-ghost inline-flex items-center justify-center"
              >
                View your plan
              </Link>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-black/20 p-6">
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-slate-500">
              Why It Can Be Payable
            </p>
            <ul className="mt-5 space-y-3 text-sm text-slate-200">
              <li className="flex gap-3">
                <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-400" />
                Quick intraday signals are scarce, actionable, and built for execution rather than generic commentary.
              </li>
              <li className="flex gap-3">
                <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-amber-300" />
                Users get a niche desk surface: quick signals, long-context framing, AI notes, and market conditions in one place.
              </li>
              <li className="flex gap-3">
                <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-sky-300" />
                The next premium layer is global alerts: macro events, overnight leads, and world-news triggers that impact Indian indices.
              </li>
            </ul>

            <p className="mt-6 text-[11px] leading-relaxed text-slate-500">
              Contact us to activate Pro access. The goal is not more signals - it is better timing,
              better context, and a premium workflow serious traders will keep open.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
