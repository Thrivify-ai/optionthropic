import Cookies from "js-cookie";

const TOKEN_KEY = "token";
const USER_KEY = "or_user";

export function saveSession(tokenData) {
  Cookies.set(TOKEN_KEY, tokenData.access_token, {
    expires: tokenData.expires_in / 86400,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
  });
  if (typeof window !== "undefined") {
    localStorage.setItem(USER_KEY, JSON.stringify({
      id: tokenData.user_id,
      email: tokenData.email,
      first_name: tokenData.first_name ?? null,
      plan: tokenData.plan,
      is_admin: tokenData.is_admin ?? false,
    }));
  }
}

export function clearSession() {
  Cookies.remove(TOKEN_KEY);
  if (typeof window !== "undefined") localStorage.removeItem(USER_KEY);
}

export function getToken() {
  return Cookies.get(TOKEN_KEY);
}

export function getStoredUser() {
  if (typeof window === "undefined") return null;
  try {
    const raw = JSON.parse(localStorage.getItem(USER_KEY));
    if (!raw) return null;
    const email = typeof raw.email === "string" ? raw.email : "";
    const derivedFirstName = email
      ? email.split("@")[0].replace(/[._-]+/g, " ").trim().split(/\s+/)[0]
      : "";
    return {
      ...raw,
      first_name: raw.first_name || (derivedFirstName ? derivedFirstName.charAt(0).toUpperCase() + derivedFirstName.slice(1) : null),
    };
  } catch {
    return null;
  }
}

export function isAuthenticated() {
  return Boolean(getToken());
}
