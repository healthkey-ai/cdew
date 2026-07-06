/**
 * In-memory access token + persistent refresh token (localStorage).
 * Access token stays in memory to mitigate XSS exfiltration; refresh token
 * persists across reloads. Mirrors the hk-labs pattern.
 */
const REFRESH_KEY = "cdew_refresh";

let accessToken: string | null = null;
const subscribers = new Set<() => void>();

export const authStore = {
  getAccessToken: () => accessToken,
  getRefreshToken: () => localStorage.getItem(REFRESH_KEY),
  setTokens: ({ access, refresh }: { access: string; refresh: string }) => {
    accessToken = access;
    localStorage.setItem(REFRESH_KEY, refresh);
    subscribers.forEach((cb) => cb());
  },
  clear: () => {
    accessToken = null;
    localStorage.removeItem(REFRESH_KEY);
    subscribers.forEach((cb) => cb());
  },
  subscribe: (cb: () => void) => {
    subscribers.add(cb);
    return () => subscribers.delete(cb);
  },
  isAuthenticated: () => Boolean(accessToken || localStorage.getItem(REFRESH_KEY)),
};
