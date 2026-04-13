import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import clsx from "clsx";

import { clearSession, getStoredUser, isAuthenticated } from "../lib/auth";
import ThemeToggleButton from "./ThemeToggleButton";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/pro-signals", label: "Pro Desk" },
  { href: "/profile", label: "Profile" },
];

const ADMIN_NAV = [
  { href: "/admin/analytics", label: "Signal Analytics" },
  { href: "/admin/broadcasts", label: "Broadcast Desk" },
];

export default function Layout({ children, subheader }) {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [adminMenuOpen, setAdminMenuOpen] = useState(false);
  const adminMenuRef = useRef(null);

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

  useEffect(() => {
    setAdminMenuOpen(false);
  }, [router.pathname]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (!adminMenuRef.current?.contains(event.target)) {
        setAdminMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const isNavActive = (href) => {
    if (href === "/profile") {
      return router.pathname === "/profile" || router.pathname === "/settings";
    }
    return router.pathname === href;
  };

  const displayName = user?.first_name || user?.email?.split("@")?.[0] || "Member";

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
                  isNavActive(href)
                    ? "bg-brand-600/20 text-brand-300 shadow-sm"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
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
                  <span className="text-xs font-medium text-slate-200">{displayName}</span>
                  <span className="badge-blue">{user.plan}</span>
                </div>
              </div>
            ) : null}

            {user?.is_admin ? (
              <div className="relative hidden sm:block" ref={adminMenuRef}>
                <button
                  onClick={() => setAdminMenuOpen((open) => !open)}
                  className={clsx(
                    "flex items-center gap-2 rounded-2xl border px-3 py-2 text-xs font-semibold transition-all",
                    adminMenuOpen || router.pathname.startsWith("/admin")
                      ? "border-amber-400/30 bg-amber-400/12 text-amber-300"
                      : "border-white/10 bg-white/5 text-slate-300 hover:border-amber-500/20 hover:bg-amber-500/10 hover:text-amber-300"
                  )}
                >
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-300/20 text-[10px] font-bold text-amber-200">
                    A
                  </span>
                  Admin
                  <span className={clsx("text-[10px] transition-transform", adminMenuOpen ? "rotate-180" : "")}>
                    ▼
                  </span>
                </button>

                {adminMenuOpen ? (
                  <div className="absolute right-0 top-[calc(100%+0.75rem)] z-50 w-56 rounded-[1.25rem] border border-white/10 bg-[rgba(8,18,28,0.96)] p-2 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.65)] backdrop-blur-xl">
                    {ADMIN_NAV.map(({ href, label }) => (
                      <Link
                        key={href}
                        href={href}
                        className={clsx(
                          "block rounded-xl px-3 py-2.5 text-sm font-medium transition-all",
                          router.pathname === href
                            ? "bg-amber-400/15 text-amber-300"
                            : "text-slate-300 hover:bg-white/5 hover:text-slate-100"
                        )}
                      >
                        {label}
                      </Link>
                    ))}
                  </div>
                ) : null}
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
