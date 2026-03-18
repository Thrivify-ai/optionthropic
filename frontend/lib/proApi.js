/**
 * Pro Signals API — live ticks and combined signals.
 * Uses same axios instance as main api (inherits auth).
 */
import api from "./api";

export const proApi = {
  ticks: () => api.get("/api/pro/ticks").then((r) => r.data).catch(() => ({})),
  signals: () =>
    api.get("/api/pro/signals").then((r) => r.data).catch(() => ({})),
  commodities: () =>
    api.get("/api/pro/commodities").then((r) => r.data).catch(() => ({})),
};
