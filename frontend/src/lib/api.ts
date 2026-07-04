import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

import { authStore } from "./auth";

/** API base — defaults to `/api/v1` (Vite proxy → Django). Override with VITE_API_URL. */
export const API_BASE_URL = import.meta.env.VITE_API_URL || "/api/v1";

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// ── Request: attach JWT ─────────────────────────────────────────
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = authStore.getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── Response: refresh on 401, single retry ──────────────────────
let refreshPromise: Promise<string | null> | null = null;

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
    if (error.response?.status === 401 && !original._retry && authStore.getRefreshToken()) {
      original._retry = true;
      try {
        if (!refreshPromise) {
          refreshPromise = (async () => {
            const refresh = authStore.getRefreshToken();
            if (!refresh) return null;
            const r = await axios.post(`${API_BASE_URL}/auth/token/refresh/`, { refresh });
            const newAccess = r.data.access as string;
            authStore.setTokens({ access: newAccess, refresh });
            return newAccess;
          })();
        }
        const newAccess = await refreshPromise;
        refreshPromise = null;
        if (newAccess) {
          original.headers.Authorization = `Bearer ${newAccess}`;
          return api.request(original);
        }
      } catch {
        refreshPromise = null;
        authStore.clear();
      }
    }
    return Promise.reject(error);
  },
);
