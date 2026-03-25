import { useMemo, useState } from "react";
import clsx from "clsx";

import Layout from "../components/Layout";

const CONCEPTS = [
  {
    id: "aurora",
    name: "Aurora Desk",
    tag: "Cinematic pro desk",
    description:
      "A high-contrast trading workspace with deep navy surfaces, electric mint highlights, and strong signal hierarchy.",
    dark: {
      shell: "bg-[#08131f]",
      frame: "border-[#15344c] bg-[radial-gradient(circle_at_top_left,rgba(29,233,182,0.12),transparent_26%),linear-gradient(180deg,#09121c,#0d1725)]",
      panel: "border-[#143247] bg-[#0d1b2a]",
      soft: "border-[#173852] bg-[#0e2133]",
      text: "text-[#ecf6ff]",
      muted: "text-[#84a4bb]",
      subtle: "text-[#5f7c93]",
      accent: "bg-[#28d7a1] text-[#05291d]",
      accentSoft: "border-[#1fa882]/30 bg-[#1fa882]/12 text-[#82f3cf]",
      secondary: "border-[#2ec5ff]/30 bg-[#2ec5ff]/12 text-[#7bdfff]",
      signal: "from-[#1de9b6] via-[#2ec5ff] to-[#85f7d0]",
    },
    light: {
      shell: "bg-[#eef6fb]",
      frame: "border-[#bfdae8] bg-[radial-gradient(circle_at_top_left,rgba(32,193,124,0.10),transparent_26%),linear-gradient(180deg,#f7fbff,#e9f3fa)]",
      panel: "border-[#c5dae7] bg-[#fcfeff]",
      soft: "border-[#d5e5ef] bg-[#f2f8fb]",
      text: "text-[#102132]",
      muted: "text-[#4e6477]",
      subtle: "text-[#7b92a4]",
      accent: "bg-[#0f9f72] text-white",
      accentSoft: "border-[#0f9f72]/20 bg-[#0f9f72]/10 text-[#0d7c5a]",
      secondary: "border-[#1b79a8]/20 bg-[#1b79a8]/10 text-[#155f84]",
      signal: "from-[#12b886] via-[#38bdf8] to-[#90f1d2]",
    },
  },
  {
    id: "linen",
    name: "Linen Terminal",
    tag: "Editorial clarity",
    description:
      "A softer, premium style with warm neutrals, crisp type contrast, and elegant chart-like cards that feel calm under pressure.",
    dark: {
      shell: "bg-[#15110e]",
      frame: "border-[#3a2d24] bg-[radial-gradient(circle_at_top_right,rgba(251,191,36,0.10),transparent_24%),linear-gradient(180deg,#17110d,#1b140f)]",
      panel: "border-[#423228] bg-[#201813]",
      soft: "border-[#4c392d] bg-[#261d17]",
      text: "text-[#faf1e8]",
      muted: "text-[#bda995]",
      subtle: "text-[#8f7866]",
      accent: "bg-[#f59e0b] text-[#1f1408]",
      accentSoft: "border-[#f59e0b]/25 bg-[#f59e0b]/10 text-[#f7c977]",
      secondary: "border-[#f97316]/25 bg-[#f97316]/10 text-[#f7b07d]",
      signal: "from-[#f59e0b] via-[#fb7185] to-[#facc15]",
    },
    light: {
      shell: "bg-[#f7f2ed]",
      frame: "border-[#ddcfc1] bg-[radial-gradient(circle_at_top_right,rgba(245,158,11,0.10),transparent_24%),linear-gradient(180deg,#fffdf9,#f3ece5)]",
      panel: "border-[#e1d4c9] bg-[#fffdfa]",
      soft: "border-[#eadfd5] bg-[#f7f1eb]",
      text: "text-[#231913]",
      muted: "text-[#69574d]",
      subtle: "text-[#9a8578]",
      accent: "bg-[#d97706] text-white",
      accentSoft: "border-[#d97706]/20 bg-[#d97706]/10 text-[#b85f00]",
      secondary: "border-[#dc2626]/20 bg-[#dc2626]/10 text-[#b91c1c]",
      signal: "from-[#f59e0b] via-[#fb7185] to-[#facc15]",
    },
  },
  {
    id: "pulse",
    name: "Pulse Grid",
    tag: "Modern data lab",
    description:
      "A cleaner, more modular dashboard with cool neutrals, bold coral accents, and a sharper product feel for dark and light mode.",
    dark: {
      shell: "bg-[#0b0d13]",
      frame: "border-[#22283a] bg-[radial-gradient(circle_at_bottom_left,rgba(251,113,133,0.14),transparent_26%),linear-gradient(180deg,#0d1018,#101522)]",
      panel: "border-[#252b3d] bg-[#121827]",
      soft: "border-[#2d3448] bg-[#171e31]",
      text: "text-[#f5f7fb]",
      muted: "text-[#9aa6bc]",
      subtle: "text-[#68758d]",
      accent: "bg-[#fb7185] text-[#20070c]",
      accentSoft: "border-[#fb7185]/25 bg-[#fb7185]/10 text-[#fda4af]",
      secondary: "border-[#60a5fa]/25 bg-[#60a5fa]/10 text-[#93c5fd]",
      signal: "from-[#fb7185] via-[#60a5fa] to-[#c084fc]",
    },
    light: {
      shell: "bg-[#f4f7fb]",
      frame: "border-[#d8dfeb] bg-[radial-gradient(circle_at_bottom_left,rgba(251,113,133,0.10),transparent_24%),linear-gradient(180deg,#ffffff,#eef3fb)]",
      panel: "border-[#d8dfeb] bg-[#ffffff]",
      soft: "border-[#e2e8f2] bg-[#f3f6fb]",
      text: "text-[#172033]",
      muted: "text-[#5a6477]",
      subtle: "text-[#8a96aa]",
      accent: "bg-[#e11d48] text-white",
      accentSoft: "border-[#e11d48]/20 bg-[#e11d48]/10 text-[#be123c]",
      secondary: "border-[#2563eb]/20 bg-[#2563eb]/10 text-[#1d4ed8]",
      signal: "from-[#fb7185] via-[#60a5fa] to-[#c084fc]",
    },
  },
];

function PreviewChip({ children, className }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.2em]",
        className
      )}
    >
      {children}
    </span>
  );
}

function MetricCard({ palette, label, value, tone = "accent", detail }) {
  const toneClass = tone === "secondary" ? palette.secondary : palette.accentSoft;
  return (
    <div className={clsx("rounded-[1.25rem] border p-4", palette.soft)}>
      <div className="flex items-center justify-between gap-3">
        <p className={clsx("text-[10px] font-semibold uppercase tracking-[0.22em]", palette.subtle)}>
          {label}
        </p>
        <PreviewChip className={toneClass}>{tone === "secondary" ? "Monitor" : "Live"}</PreviewChip>
      </div>
      <p className={clsx("mt-3 text-2xl font-semibold tracking-tight", palette.text)}>{value}</p>
      <p className={clsx("mt-2 text-xs leading-relaxed", palette.muted)}>{detail}</p>
    </div>
  );
}

function PreviewFrame({ concept, mode }) {
  const palette = concept[mode];

  return (
    <div className={clsx("rounded-[2rem] border p-4 shadow-2xl", palette.shell, palette.frame)}>
      <div className={clsx("flex items-center justify-between rounded-[1.4rem] border px-4 py-3", palette.panel)}>
        <div>
          <p className={clsx("text-[10px] font-semibold uppercase tracking-[0.24em]", palette.subtle)}>
            Optionthropic
          </p>
          <h3 className={clsx("mt-1 text-lg font-semibold tracking-tight", palette.text)}>
            {concept.name}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <PreviewChip className={palette.accentSoft}>{mode}</PreviewChip>
          <PreviewChip className={palette.secondary}>Signals First</PreviewChip>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-4">
          <div className={clsx("rounded-[1.5rem] border p-5", palette.panel)}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className={clsx("text-[10px] font-semibold uppercase tracking-[0.22em]", palette.subtle)}>
                  Markets
                </p>
                <h4 className={clsx("mt-2 text-2xl font-semibold tracking-tight", palette.text)}>
                  Fast, clean, confidence-led.
                </h4>
                <p className={clsx("mt-2 max-w-xl text-sm leading-relaxed", palette.muted)}>
                  A denser professional layout for quick signals, long bias, and market context without turning the page into noise.
                </p>
              </div>
              <button className={clsx("rounded-full px-3 py-2 text-xs font-semibold shadow-lg", palette.accent)}>
                Pro Desk
              </button>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-3">
              <MetricCard
                palette={palette}
                label="Quick Signal"
                value="Buy CE"
                detail="Momentum confirmed across the fast tape with headroom to resistance."
              />
              <MetricCard
                palette={palette}
                label="Long Bias"
                value="Bullish"
                tone="secondary"
                detail="Higher-timeframe structure still points up, but entry timing stays selective."
              />
              <MetricCard
                palette={palette}
                label="Market State"
                value="Trend Day"
                detail="Writers are defending downside while breadth stays constructive."
              />
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-[1.1fr_0.9fr]">
            <div className={clsx("rounded-[1.5rem] border p-4", palette.panel)}>
              <div className="flex items-center justify-between">
                <p className={clsx("text-[10px] font-semibold uppercase tracking-[0.22em]", palette.subtle)}>
                  Signal Grid
                </p>
                <span className={clsx("text-xs font-medium", palette.muted)}>3 indices</span>
              </div>
              <div className="mt-4 space-y-3">
                {[
                  { symbol: "NIFTY", signal: "Buy CE", level: "22,431", conf: "84" },
                  { symbol: "BANKNIFTY", signal: "Wait", level: "48,992", conf: "61" },
                  { symbol: "SENSEX", signal: "Buy PE", level: "74,188", conf: "79" },
                ].map((row) => (
                  <div key={row.symbol} className={clsx("rounded-[1rem] border px-3 py-3", palette.soft)}>
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className={clsx("text-xs font-semibold tracking-[0.16em]", palette.text)}>
                          {row.symbol}
                        </p>
                        <p className={clsx("mt-1 text-[11px]", palette.muted)}>Spot {row.level}</p>
                      </div>
                      <div className="text-right">
                        <span className={clsx("text-sm font-semibold", palette.text)}>{row.signal}</span>
                        <p className={clsx("mt-1 text-[11px]", palette.muted)}>Conf {row.conf}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className={clsx("rounded-[1.5rem] border p-4", palette.panel)}>
              <div className="flex items-center justify-between">
                <p className={clsx("text-[10px] font-semibold uppercase tracking-[0.22em]", palette.subtle)}>
                  News Rail
                </p>
                <span className={clsx("text-xs font-medium", palette.muted)}>Critical only</span>
              </div>
              <div className="mt-4 space-y-3">
                {[
                  { title: "Fed rhetoric cools yields", score: 82 },
                  { title: "Oil supply headline hits Asia risk", score: 89 },
                  { title: "Rupee watch after overnight dollar move", score: 74 },
                ].map((item) => (
                  <div key={item.title} className={clsx("rounded-[1rem] border p-3", palette.soft)}>
                    <div className="flex items-start justify-between gap-3">
                      <p className={clsx("text-xs font-medium leading-relaxed", palette.text)}>{item.title}</p>
                      <PreviewChip className={palette.accentSoft}>Score {item.score}</PreviewChip>
                    </div>
                    <div className={clsx("mt-3 h-2 overflow-hidden rounded-full", palette.soft)}>
                      <div
                        className={clsx("h-full rounded-full bg-gradient-to-r", palette.signal)}
                        style={{ width: `${item.score}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className={clsx("rounded-[1.5rem] border p-4", palette.panel)}>
          <p className={clsx("text-[10px] font-semibold uppercase tracking-[0.22em]", palette.subtle)}>
            Why this concept works
          </p>
          <div className="mt-4 space-y-3">
            {[
              "Signals stay the visual priority, not the chrome.",
              "Light mode feels intentional, not like a dark theme inverted.",
              "Cards have stronger separation, so dense data reads faster.",
              "The accent system makes Buy CE / Buy PE / Wait feel clearer without shouting.",
            ].map((point) => (
              <div key={point} className={clsx("rounded-[1rem] border px-3 py-3", palette.soft)}>
                <p className={clsx("text-sm leading-relaxed", palette.muted)}>{point}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function DesignLabPage() {
  const [active, setActive] = useState(CONCEPTS[0].id);
  const [mode, setMode] = useState("dark");

  const concept = useMemo(
    () => CONCEPTS.find((item) => item.id === active) || CONCEPTS[0],
    [active]
  );

  return (
    <Layout>
      <div className="space-y-6">
        <section className="rounded-[2rem] border border-white/10 bg-[linear-gradient(135deg,rgba(15,23,42,0.98),rgba(12,18,30,0.92))] p-6 shadow-2xl shadow-black/25">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-300/90">
                Design Lab
              </p>
              <h1 className="mt-2 text-3xl font-semibold leading-tight text-slate-100">
                Pick the feel before we reskin the product.
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
                These are isolated preview concepts only. The live dashboard and Pro Desk remain untouched until you choose a direction.
              </p>
            </div>

            <div className="flex gap-2 rounded-xl border border-surface-border bg-surface-card p-1">
              {["dark", "light"].map((item) => (
                <button
                  key={item}
                  onClick={() => setMode(item)}
                  className={clsx(
                    "rounded-lg px-4 py-2 text-sm font-medium transition-all",
                    mode === item
                      ? "bg-brand-600 text-white shadow"
                      : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
                  )}
                >
                  {item === "dark" ? "Dark mode" : "Light mode"}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-3">
          {CONCEPTS.map((item) => {
            const selected = item.id === active;
            return (
              <button
                key={item.id}
                onClick={() => setActive(item.id)}
                className={clsx(
                  "rounded-[1.75rem] border p-5 text-left transition-all duration-200",
                  selected
                    ? "border-amber-400/50 bg-amber-400/10 shadow-xl shadow-amber-400/10"
                    : "border-white/10 bg-surface-card/70 hover:-translate-y-1 hover:border-white/20 hover:bg-surface-card"
                )}
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                      {item.tag}
                    </p>
                    <h2 className="mt-2 text-xl font-semibold text-slate-100">{item.name}</h2>
                  </div>
                  {selected ? (
                    <PreviewChip className="border-amber-400/30 bg-amber-400/10 text-amber-300">
                      Selected
                    </PreviewChip>
                  ) : null}
                </div>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">{item.description}</p>
              </button>
            );
          })}
        </section>

        <section className="space-y-4">
          <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
                Active Preview
              </p>
              <h2 className="mt-1 text-2xl font-semibold text-slate-100">{concept.name}</h2>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
                {concept.description}
              </p>
            </div>
            <PreviewChip className="border-sky-500/30 bg-sky-500/10 text-sky-300">
              {mode === "dark" ? "Dark preview" : "Light preview"}
            </PreviewChip>
          </div>

          <PreviewFrame concept={concept} mode={mode} />
        </section>
      </div>
    </Layout>
  );
}
