/**
 * UpgradePrompt — shown when free users try to access Pro Signals.
 */
import Link from "next/link";

export default function UpgradePrompt() {
  return (
    <div className="max-w-md mx-auto">
      <div className="card text-center py-12 px-8 space-y-6">
        <div className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-600/20 text-brand-400 text-3xl">
          ⭐
        </div>
        <div>
          <h2 className="text-xl font-bold text-slate-100 mb-2">
            Pro Signals — Upgrade Required
          </h2>
          <p className="text-slate-400 text-sm leading-relaxed">
            Live ticks, 10-second quick signals, swing trends, and AI explanations
            are available on the Pro plan.
          </p>
        </div>

        <ul className="text-left text-sm text-slate-300 space-y-2 bg-surface/50 rounded-xl p-4 border border-surface-border">
          <li className="flex items-center gap-2">
            <span className="text-emerald-400">✓</span>
            Live tick data (NIFTY, BANKNIFTY, SENSEX)
          </li>
          <li className="flex items-center gap-2">
            <span className="text-emerald-400">✓</span>
            10-second quick signals
          </li>
          <li className="flex items-center gap-2">
            <span className="text-emerald-400">✓</span>
            Swing trend signals with explanations
          </li>
          <li className="flex items-center gap-2">
            <span className="text-emerald-400">✓</span>
            Commodity signals (Crude, Gold, Silver, NatGas)
          </li>
        </ul>

        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <a
            href="mailto:hello@optionthropic.io?subject=Upgrade%20to%20Pro"
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

        <p className="text-[10px] text-slate-500">
          Contact us to subscribe. We&apos;ll set up your Pro access.
        </p>
      </div>
    </div>
  );
}
