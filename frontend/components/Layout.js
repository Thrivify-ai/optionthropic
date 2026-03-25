import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import clsx from "clsx";

import { clearSession, getStoredUser, isAuthenticated } from "../lib/auth";
import ThemeToggleButton from "./ThemeToggleButton";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/pro-signals", label: "Pro Desk" },
  { href: "/alerts", label: "Alerts" },
  { href: "/profile", label: "Profile" },
  { href: "/settings", label: "Settings" },
];

const ADMIN_NAV = [{ href: "/admin/analytics", label: "Signal Analytics" }];

export default function Layout({ children, subheader }) {
  const router = useRouter();
  const [user, setUser] = useState(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    setUser(getStoredUser());
  }, [router]);

  const logout = () => {
    clearSession();
    router.push("/login");
  };

  return (
    <div className="app-shell flex min-h-screen flex-col">
      <div className="app-backdrop" />

      <header
        className="sticky top-0 z-40 border-b backdrop-blur-xl"
        style={{
          backgroundColor: "var(--color-header-surface)",
          borderColor: "var(--color-surface-border)",
        }}
      >
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
          <Link href="/dashboard" className="group flex items-center gap-3">
            <span
              className="flex h-10 w-10 items-center justify-center rounded-2xl text-sm font-extrabold shadow-lg"
              style={{
                backgroundImage: "linear-gradient(135deg, var(--color-brand), var(--color-secondary))",
                color: "#04131c",
              }}
            >
              OT
            </span>
            <div className="leading-tight">
              <span className="section-kicker block">Aurora Desk</span>
              <span className="block text-sm font-semibold text-slate-100 transition-colors group-hover:text-brand-300">
                Optionthropic
              </span>
            </div>
          </Link>

          <nav className="hidden items-center gap-1 rounded-2xl border border-white/10 bg-white/5 p-1 md:flex">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={clsx(
                  "nav-pill",
                  router.pathname === href
                    ? "bg-brand-600/20 text-brand-300 shadow-sm"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
                )}
              >
                {label}
              </Link>
            ))}
            {user?.is_admin &&
              ADMIN_NAV.map(({ href, label }) => (
                <Link
                  key={href}
                  href={href}
                  className={clsx(
                    "nav-pill border",
                    router.pathname === href
                      ? "border-amber-400/30 bg-amber-400/15 text-amber-300"
                      : "border-amber-500/20 text-amber-400 hover:bg-amber-500/10"
                  )}
                >
                  {label}
                </Link>
              ))}
          </nav>

          <div className="flex items-center gap-2">
            {user ? (
              <div className="hidden rounded-2xl border border-white/10 bg-white/5 px-3 py-2 sm:block">
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  Signed in
                </p>
                <div className="mt-1 flex items-center gap-2">
                  <span className="text-xs text-slate-300">{user.email}</span>
                  {user.is_admin ? (
                    <span className="badge-yellow">Admin</span>
                  ) : (
                    <span className="badge-blue">{user.plan}</span>
                  )}
                </div>
              </div>
            ) : null}

            <ThemeToggleButton />

            <button onClick={logout} className="btn-ghost text-sm">
              Sign out
            </button>
          </div>
        </div>
      </header>

      {subheader ? <div className="relative z-10 w-full">{subheader}</div> : null}

      <main className="relative z-10 mx-auto flex-1 w-full max-w-7xl px-4 py-6 sm:px-6">
        {children}
      </main>

      <footer className="relative z-10 border-t border-surface-border/80 px-4 py-4 text-center text-xs text-slate-500">
        Optionthropic {new Date().getFullYear()} - Signals, structure, and discipline.
      </footer>
    </div>
  );
}
