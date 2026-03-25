import clsx from "clsx";

const PREVIEW_CARDS = [
  {
    title: "Alert Scoring Engine",
    status: "Preview",
    border: "border-amber-500/30",
    accent: "text-amber-300",
    items: [
      "Rank alerts by market move potential, not just raw headlines",
      "Combine source credibility, timing, and affected symbols into one score",
      "Only the strongest events would survive the final desk filter",
    ],
  },
  {
    title: "Event Windows",
    status: "Planned",
    border: "border-sky-500/30",
    accent: "text-sky-300",
    items: [
      "Opening, midday, and close behave differently for macro shocks",
      "Expiry and overnight events get their own mode-aware handling",
      "Desk alerts can surface only when the tape is actually vulnerable",
    ],
  },
  {
    title: "World Watchlist",
    status: "Later",
    border: "border-emerald-500/30",
    accent: "text-emerald-300",
    items: [
      "RBI, Fed, CPI, OPEC, and overnight Asia shock tracking",
      "Global cues mapped to NIFTY, BANKNIFTY, and SENSEX exposure",
      "Premium users see the event context before the tape moves",
    ],
  },
];

function PreviewCard({ card }) {
  return (
    <div className={clsx("rounded-2xl border bg-surface-card/70 p-5 shadow-lg shadow-black/20", card.border)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
            Premium Preview
          </p>
          <h4 className={clsx("mt-1 text-lg font-semibold", card.accent)}>{card.title}</h4>
        </div>
        <span className={clsx("rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider", card.border, card.accent)}>
          {card.status}
        </span>
      </div>
      <div className="mt-4 space-y-2">
        {card.items.map((item) => (
          <p key={item} className="text-sm leading-relaxed text-slate-300">
            {item}
          </p>
        ))}
      </div>
    </div>
  );
}

export default function ProNewsPreview() {
  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-300/90">
            Premium Roadmap
          </p>
          <h3 className="mt-1 text-2xl font-semibold text-slate-100">
            The next layer is richer market intelligence
          </h3>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
            The live critical-alert feed is now part of the desk. This roadmap preview shows how
            the product can expand into deeper alert scoring, event windows, and world-watch
            coverage without turning the feed noisy.
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {PREVIEW_CARDS.map((card) => (
          <PreviewCard key={card.title} card={card} />
        ))}
      </div>
    </div>
  );
}
