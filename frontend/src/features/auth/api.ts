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

export function useLogin() {
  return useMutation({
    mutationFn: async (creds: { email: string; password: string }) =>
      (await api.post<LoginResponse>("/auth/login/", creds)).data,
    onSuccess: (data) => authStore.setTokens({ access: data.access, refresh: data.refresh }),
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
