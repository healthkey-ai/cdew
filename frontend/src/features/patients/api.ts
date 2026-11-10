import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SourceDocument } from "@/features/documents/api";
import { api } from "@/lib/api";
import { KEYS } from "@/lib/keys";

/** A patient from the admin's directory (promop), searched with their own token (#31 Part B). */
export interface DirectoryPatient {
  person_id: number;
  name: string;
  email: string;
  organization: string;
  patient_ref: string; // "promop:42"
}

export interface DirectoryStatus {
  host: string | null; // label of the directory host, null when the sign-in host has none
  connected: boolean; // a host session is kept — false means "sign in again"
}

/** Whether the patient picker is available (admins only — pass `enabled`). */
export function usePatientDirectory(enabled: boolean) {
  return useQuery({
    queryKey: KEYS.patientDirectory,
    enabled,
    queryFn: async () => (await api.get<DirectoryStatus>("/patients/directory/")).data,
    staleTime: 60_000,
  });
}

/** Directory search; `q` should already be debounced. Under 2 chars → no request. */
export function usePatientSearch(q: string, enabled: boolean) {
  const query = q.trim();
  return useQuery({
    queryKey: KEYS.patientSearch(query),
    enabled: enabled && query.length >= 2,
    queryFn: async () =>
      (await api.get<{ results: DirectoryPatient[] }>("/patients/", { params: { search: query } })).data.results,
    staleTime: 30_000,
    retry: false,
  });
}

/** Assign an inbox document to a directory patient (admin-gated). */
export function useAssignPatient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ documentId, personId }: { documentId: number; personId: number }) =>
      (await api.post<SourceDocument>(`/documents/${documentId}/patient/`, { person_id: personId })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}

/** The server's message for a failed directory call, if it sent one. */
export function directoryErrorDetail(err: unknown): string | undefined {
  return (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
}
