import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";

import { authApi } from "../lib/api";
import { saveSession } from "../lib/auth";
import ThemeToggleButton from "../components/ThemeToggleButton";

export default function Signup() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);

    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setLoading(true);
    try {
      const data = await authApi.signup(email, password);
      saveSession(data);
      router.push("/dashboard");
    } catch (err) {
      setError(err.response?.data?.detail || "Signup failed. Please try again.");
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
          <p className="section-kicker">Build your desk</p>
          <h1 className="mt-3 text-4xl font-semibold leading-tight text-slate-100">
            A sharper interface for serious options decision-making.
          </h1>
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-slate-400">
            Clean theme, calmer surfaces, stronger contrast, and signals that stay visually ahead
            of everything else. This is the new Aurora foundation.
          </p>

          <div className="mt-8 space-y-3">
            {[
              "Long-term signals remain clear for every user.",
              "Quick signals and desk context stay premium and faster to scan.",
              "Dark and light modes now feel like two designed products, not one inverted skin.",
            ].map((item) => (
              <div key={item} className="rounded-[1.25rem] border border-white/10 bg-white/5 px-4 py-3">
                <p className="text-sm leading-relaxed text-slate-300">{item}</p>
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
            <p className="section-kicker">Create account</p>
            <h2 className="mt-2 text-3xl font-semibold text-slate-100">Start with the clean desk</h2>
            <p className="mt-2 text-sm text-slate-400">
              Set up your account and step into the new Aurora workspace.
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
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-slate-400">Password</label>
              <input
                type="password"
                className="input"
                placeholder="Minimum 8 characters"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-slate-400">Confirm password</label>
              <input
                type="password"
                className="input"
                placeholder="Repeat your password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                required
              />
            </div>

            <button type="submit" className="btn-primary w-full py-3" disabled={loading}>
              {loading ? "Creating account..." : "Create account"}
            </button>

            <p className="text-center text-sm text-slate-500">
              Already have an account?{" "}
              <Link href="/login" className="text-brand-400 hover:text-brand-300">
                Sign in
              </Link>
            </p>
          </form>
        </section>
      </div>
    </div>
  );
}
