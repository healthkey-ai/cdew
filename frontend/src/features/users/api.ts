import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { KEYS } from "@/lib/keys";

export const ROLES = ["reviewer", "prompt_author", "admin"] as const;
export type RoleName = (typeof ROLES)[number];

export interface AdminUser {
  id: number;
  email: string;
  name: string;
  is_active: boolean;
  is_staff: boolean;
  roles: string[];
  created_at: string;
}

export interface NewUser {
  email: string;
  name: string;
  password: string;
  roles: string[];
}

/** Local identities (admin-gated). The list endpoint returns a plain array. */
export function useUsers() {
  return useQuery({
    queryKey: KEYS.users,
    queryFn: async () => (await api.get<AdminUser[]>("/auth/users/")).data,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (u: NewUser) => (await api.post<AdminUser>("/auth/users/", u)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.users }),
  });
}

export function useSetRoles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, roles }: { id: number; roles: string[] }) =>
      (await api.patch<AdminUser>(`/auth/users/${id}/roles/`, { roles })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.users }),
  });
}
