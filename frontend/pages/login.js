import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";

import { authApi } from "../lib/api";
import { saveSession } from "../lib/auth";
import ThemeToggleButton from "../components/ThemeToggleButton";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await authApi.login(email, password);
      saveSession(data);
      router.push("/dashboard");
    } catch (err) {
      setError(err.response?.data?.detail || "Login failed. Please check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell px-4">
      <div className="absolute right-6 top-6 z-10">
        <ThemeToggleButton />
      </div>

      <div className="mx-auto grid min-h-screen max-w-6xl grid-cols-1 items-center gap-6 py-10 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="auth-panel hidden lg:block">
          <p className="section-kicker">Aurora Desk</p>
          <h1 className="mt-3 text-4xl font-semibold leading-tight text-slate-100">
            Institutional signal design, made readable.
          </h1>
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-slate-400">
            Optionthropic turns options structure into clean conviction, not noisy dashboards.
            This Aurora pass keeps the interface sharper, calmer, and faster to scan.
          </p>

          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {[
              { label: "Signals", value: "Sparse", detail: "High-conviction output over chatter." },
              { label: "Modes", value: "2", detail: "Dark and light, both intentionally designed." },
              { label: "Workflow", value: "Desk", detail: "Signals first, context second." },
            ].map((item) => (
              <div key={item.label} className="rounded-[1.25rem] border border-white/10 bg-white/5 p-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-500">
                  {item.label}
                </p>
                <p className="mt-3 text-2xl font-semibold text-slate-100">{item.value}</p>
                <p className="mt-2 text-xs leading-relaxed text-slate-400">{item.detail}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="auth-panel mx-auto w-full max-w-md">
          <div className="text-center">
            <div
              className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl text-lg font-extrabold shadow-lg"
              style={{
                backgroundImage: "linear-gradient(135deg, var(--color-brand), var(--color-secondary))",
                color: "#04131c",
              }}
            >
              OT
            </div>
            <p className="section-kicker">Welcome back</p>
            <h2 className="mt-2 text-3xl font-semibold text-slate-100">Sign in to Optionthropic</h2>
            <p className="mt-2 text-sm text-slate-400">
              Your signals, context, and desk workflow are ready.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="mt-8 space-y-4">
            {error ? (
              <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2">
                <p className="text-sm text-red-300">{error}</p>
              </div>
            ) : null}

            <div>
              <label className="mb-1.5 block text-sm text-slate-400">Email</label>
              <input
                type="email"
                className="input"
                placeholder="you@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoComplete="email"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-slate-400">Password</label>
              <input
                type="password"
                className="input"
                placeholder="Enter your password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                autoComplete="current-password"
              />
            </div>

            <button type="submit" className="btn-primary w-full py-3" disabled={loading}>
              {loading ? "Signing in..." : "Sign in"}
            </button>

            <p className="text-center text-sm text-slate-500">
              Don&apos;t have an account?{" "}
              <Link href="/signup" className="text-brand-400 hover:text-brand-300">
                Create one
              </Link>
            </p>
          </form>
        </section>
      </div>
    </div>
  );
}
