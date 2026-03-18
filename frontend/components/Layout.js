import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import { clearSession, getStoredUser, isAuthenticated } from "../lib/auth";
import clsx from "clsx";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/pro-signals", label: "Pro Signals" },
  { href: "/alerts",    label: "Alerts"    },
  { href: "/profile",   label: "Profile"   },
  { href: "/settings",  label: "Settings"  },
];

function SunIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <circle cx="12" cy="12" r="5"/>
      <line x1="12" y1="1"  x2="12" y2="3"/>
      <line x1="12" y1="21" x2="12" y2="23"/>
      <line x1="4.22" y1="4.22"  x2="5.64" y2="5.64"/>
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
      <line x1="1"  y1="12" x2="3"  y2="12"/>
      <line x1="21" y1="12" x2="23" y2="12"/>
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  );
}

export default function Layout({ children, subheader }) {
  const router = useRouter();
  const [user, setUser]       = useState(null);
  const [theme, setTheme]     = useState("dark"); // start dark, load from LS on mount

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    setUser(getStoredUser());
  }, []);

  // Load persisted theme once on mount and apply to <html>
  useEffect(() => {
    const saved = localStorage.getItem("or-theme") || "dark";
    applyTheme(saved);
    setTheme(saved);
  }, []);

  function applyTheme(t) {
    const html = document.documentElement;
    if (t === "light") {
      html.classList.add("light");
      html.classList.remove("dark");
    } else {
      html.classList.add("dark");
      html.classList.remove("light");
    }
  }

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
    localStorage.setItem("or-theme", next);
  }

  const logout = () => {
    clearSession();
    router.push("/login");
  };

  const isDark = theme === "dark";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-surface-border bg-surface-card/60 backdrop-blur sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2">
            <span className="h-7 w-7 rounded-lg bg-brand-600 flex items-center justify-center text-white font-bold text-sm">
              OR
            </span>
            <span className="font-bold text-slate-100 tracking-tight">
              Optionthropic
            </span>
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={clsx(
                  "px-3 py-1.5 rounded-lg text-sm transition-colors",
                  router.pathname === href
                    ? "bg-brand-600/20 text-brand-400"
                    : "text-slate-400 hover:text-slate-100 hover:bg-white/5"
                )}
              >
                {label}
              </Link>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            {user && (
              <span className="text-xs text-slate-500 hidden sm:block">
                {user.email}
                <span className="ml-1.5 badge-blue">{user.plan}</span>
              </span>
            )}

            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              title={isDark ? "Switch to light mode" : "Switch to dark mode"}
              className={clsx(
                "flex items-center justify-center h-8 w-8 rounded-lg border transition-colors duration-200",
                isDark
                  ? "border-slate-600 text-slate-400 hover:text-amber-300 hover:border-amber-400/50 hover:bg-amber-400/5"
                  : "border-slate-300 text-slate-500 hover:text-brand-600 hover:border-brand-400/50 hover:bg-brand-400/5"
              )}
            >
              {isDark ? <SunIcon /> : <MoonIcon />}
            </button>

            <button onClick={logout} className="btn-ghost text-sm">
              Sign out
            </button>
          </div>
        </div>
      </header>

      {subheader && <div className="w-full">{subheader}</div>}

      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 py-6">
        {children}
      </main>

      <footer className="border-t border-surface-border text-center py-4 text-xs text-slate-600">
        Optionthropic © {new Date().getFullYear()} · For informational purposes only.
        Not investment advice.
      </footer>
    </div>
  );
}
