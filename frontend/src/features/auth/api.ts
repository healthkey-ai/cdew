import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { authStore } from "@/lib/auth";
import { KEYS } from "@/lib/keys";

export interface Identity {
  id: number;
  issuer: string;
  sub: string;
  email: string;
  name: string;
  is_staff: boolean;
  roles: string[];
}

export interface Health {
  status: string;
  service: string;
}

export function useHealth() {
  return useQuery({
    queryKey: KEYS.health,
    queryFn: async () => (await api.get<Health>("/health/")).data,
  });
}

export function useMe(enabled = true) {
  return useQuery({
    queryKey: KEYS.me,
    enabled,
    queryFn: async () => (await api.get<Identity>("/auth/me/")).data,
  });
}

interface LoginResponse {
  access: string;
  refresh: string;
  identity: Identity;
}

/** A partner identity host that takes a password sign-in (promop, phr). */
export interface PasswordHost {
  key: string;
  label: string;
  kind: "password";
}

/** Public Firebase web config (apiKey, authDomain, projectId, …) — not a secret. */
export type FirebaseWebConfig = Record<string, string>;

export interface AuthConfig {
  local: boolean;
  providers: PasswordHost[];
  firebase: FirebaseWebConfig | null;
}

/** Which sign-in options this deployment offers (design §11, #31). */
export function useAuthConfig() {
  return useQuery({
    queryKey: KEYS.authConfig,
    queryFn: async () => (await api.get<AuthConfig>("/auth/config/")).data,
    staleTime: Infinity,
  });
}

const storeTokens = (data: LoginResponse) =>
  authStore.setTokens({ access: data.access, refresh: data.refresh });

/** CDEW-local account (dev, break-glass). */
export function useLogin() {
  return useMutation({
    mutationFn: async (creds: { email: string; password: string }) =>
      (await api.post<LoginResponse>("/auth/login/", creds)).data,
    onSuccess: storeTokens,
  });
}

/** A promop or phr account. CDEW's backend signs in to the host server-side and
 * answers with a CDEW token pair, so the host's tokens never reach the browser. */
export function usePartnerLogin() {
  return useMutation({
    mutationFn: async (creds: { provider: string; email: string; password: string }) =>
      (await api.post<LoginResponse>("/auth/partner-login/", creds)).data,
    onSuccess: storeTokens,
  });
}

/** An org-owned Firebase account: Google sign-in in a popup, then the Firebase ID
 * token is exchanged for a CDEW pair. The Firebase SDK loads only when used. */
export function useFirebaseLogin() {
  return useMutation({
    mutationFn: async (config: FirebaseWebConfig) => {
      const [{ initializeApp, getApps }, { getAuth, GoogleAuthProvider, signInWithPopup, signOut }] =
        await Promise.all([import("firebase/app"), import("firebase/auth")]);
      const app = getApps().find((a) => a.name === "cdew") ?? initializeApp(config, "cdew");
      const auth = getAuth(app);
      const result = await signInWithPopup(auth, new GoogleAuthProvider());
      const token = await result.user.getIdToken();
      // CDEW keeps its own session from here; don't leave a Firebase one behind.
      await signOut(auth);
      return (await api.post<LoginResponse>("/auth/partner-token/", { token })).data;
    },
    onSuccess: storeTokens,
  });
}

/** Reactive auth state — re-renders when tokens are set/cleared. */
export function useAuth() {
  const [authed, setAuthed] = useState(authStore.isAuthenticated());
  useEffect(() => {
    const unsub = authStore.subscribe(() => setAuthed(authStore.isAuthenticated()));
    return () => {
      unsub();
    };
  }, []);
  return authed;
}
