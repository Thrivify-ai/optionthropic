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
      plan: tokenData.plan,
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
    return JSON.parse(localStorage.getItem(USER_KEY));
  } catch {
    return null;
  }
}

export function isAuthenticated() {
  return Boolean(getToken());
}
