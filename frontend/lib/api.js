import axios from "axios";
import Cookies from "js-cookie";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api = axios.create({ baseURL: BASE_URL });
let dashboardOverviewCache = { ts: 0, promise: null };

api.interceptors.request.use((config) => {
  const token = Cookies.get("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      Cookies.remove("token");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  signup: (email, password) =>
    api.post("/auth/signup", { email, password }).then((r) => r.data),
  login: (email, password) =>
    api.post("/auth/login", { email, password }).then((r) => r.data),
  me: () => api.get("/auth/me").then((r) => r.data),
};

export const analyticsApi = {
  dashboardOverview: (force = false) => {
    const now = Date.now();
    if (!force && dashboardOverviewCache.promise && now - dashboardOverviewCache.ts < 3000) {
      return dashboardOverviewCache.promise;
    }
    dashboardOverviewCache.ts = now;
    dashboardOverviewCache.promise = api
      .get("/api/dashboard-overview")
      .then((r) => r.data)
      .catch(() => ({ symbols: {} }));
    return dashboardOverviewCache.promise;
  },
  optionsChain: (symbol) =>
    api.get(`/api/options-chain/${symbol}`).then((r) => r.data),
  supportResistance: (symbol) =>
    api.get(`/api/support-resistance/${symbol}`).then((r) => r.data),
  gammaWalls: (symbol) =>
    api.get(`/api/gamma-walls/${symbol}`).then((r) => r.data),
  maxPain: (symbol) =>
    api.get(`/api/max-pain/${symbol}`).then((r) => r.data),
  optionsFlow: (symbol, topN = 20) =>
    api.get(`/api/options-flow/${symbol}?top_n=${topN}`).then((r) => r.data),
  positioningShifts: (symbol) =>
    api.get(`/api/positioning-shifts/${symbol}`).then((r) => r.data),
  liquidityTraps: (symbol) =>
    api.get(`/api/liquidity-traps/${symbol}`).then((r) => r.data),
  alerts: (symbol, limit = 50) =>
    api.get(`/api/alerts/${symbol}?limit=${limit}`).then((r) => r.data),
  marketSummary: (symbol) =>
    api.get(`/api/market-summary/${symbol}`).then((r) => r.data),
  /** Tick-by-tick prices when Zerodha WebSocket connected. Poll every 5s for live feel. */
  liveTicks: () =>
    api.get("/api/live-ticks").then((r) => r.data).catch(() => ({})),
  /** Persist buy signal for analytics. */
  saveBuySignal: (body) =>
    api.post("/api/buy-signal-history", body).then((r) => r.data).catch(() => null),
  /** Fetch buy signal history for Quick Signals. */
  buySignalHistory: (symbol) =>
    api.get("/api/buy-signal-history", { params: symbol ? { symbol } : {} }).then((r) => r.data?.history ?? []).catch(() => []),
  /** No auth required. Returns { token_set, token_valid, bfo_sensex_instruments, message }. */
  zerodhaStatus: () =>
    api.get("/api/zerodha-status").then((r) => r.data).catch(() => ({ token_set: false, token_valid: false, message: "Could not reach backend" })),
  /** No auth. Returns { last_refresh_utc: "ISO8601" } from DB (when data was last refreshed). */
  lastRefresh: () =>
    api.get("/api/last-refresh").then((r) => r.data).catch(() => ({ last_refresh_utc: null })),
  /** Time factor: key intraday windows (10:30–10:55, 12:30, 1:20, 2:55 PM IST) + bias. */
  timeFactor: (symbol = "NIFTY") =>
    api.get(`/api/time-factor?symbol=${encodeURIComponent(symbol)}`).then((r) => r.data).catch(() => ({ ist_now: "", window: null, bias: "NEUTRAL", message: "Time factor unavailable", in_window: false })),
  /** Movement detector: has the underlying moved meaningfully in last 5m/1h. */
  movement: (symbol) =>
    api.get(`/api/movement/${symbol}`).then((r) => r.data).catch(() => ({ movement_significant: false })),
  /** Multi-timeframe trading signal (backend-generated). */
  tradingSignal: (symbol) =>
    api.get(`/api/trading-signal/${symbol}`).then((r) => r.data),
  /** Latest underlying prices for all symbols — used by the top ticker. */
  marketPrices: () =>
    api.get("/api/market-prices").then((r) => r.data).catch(() => ({})),
  /** 10-minute OI buildup quick signal (put/call writing, unwinding, buying). */
  quickSignal: (symbol) =>
    api.get(`/api/quick-signal/${symbol}`).then((r) => r.data).catch(() => ({ quick_signal: "Wait", reason: "Unavailable" })),
  /** High-speed 6-step engine: momentum · volume spike · breakout · OI · trap filter. */
  quickSignalEngine: (symbol) =>
    api.get(`/api/quick-signal-engine/${symbol}`).then((r) => r.data).catch(() => ({ quick_signal: "Wait", reason: "Unavailable" })),
  /** MCX ticker (nearest futures): CRUDEOIL, NATGAS. */
  mcxPrices: () =>
    api.get("/api/mcx-prices").then((r) => r.data).catch(() => ({})),
  /** Commodities: quick signal (futures-based). */
  commodityQuickSignal: (symbol) =>
    api.get(`/api/commodity/quick-signal/${encodeURIComponent(symbol)}`).then((r) => r.data),
  /** Commodities: long-term signal (futures-based). */
  commodityLongSignal: (symbol) =>
    api.get(`/api/commodity/long-signal/${encodeURIComponent(symbol)}`).then((r) => r.data),
  /** Commodities: AI insights (lightweight cached). */
  commodityInsights: (symbol) =>
    api.get(`/api/commodity/insights/${encodeURIComponent(symbol)}`).then((r) => r.data),
};

export const adminApi = {
  userStats: () => api.get("/admin/user-stats").then((r) => r.data),
  usageStats: () => api.get("/admin/usage-stats").then((r) => r.data),
  systemHealth: () => api.get("/admin/system-health").then((r) => r.data),
  signalAnalytics: (days = 7, limit = 200) =>
    api.get("/admin/signal-analytics", { params: { days, limit } }).then((r) => r.data),
};

export default api;
