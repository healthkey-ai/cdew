import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type JobStage = "ingest" | "parse" | "classify" | "extract" | "done";

export interface Job {
  id: number;
  document: number;
  document_filename: string;
  status: JobStatus;
  stage: JobStage;
  progress: number; // 0..1
  errors: { code: string }[];
  stage_history: { stage: string; at: string }[]; // pipeline timeline (#28)
  prefect_flow_run_id: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export const isJobActive = (s: JobStatus) => s === "queued" || s === "running";

/** Poll the pipeline jobs (design §6, #57). Faster cadence while anything is
 * active; a slow tick otherwise so new runs still show up. */
export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: async () => {
      const d = (await api.get<{ results: Job[] } | Job[]>("/jobs/")).data;
      return Array.isArray(d) ? d : d.results;
    },
    refetchInterval: (q: { state: { data?: Job[] } }) =>
      q.state.data?.some((j) => isJobActive(j.status)) ? 2000 : 6000,
  });
}

/** Non-sensitive frontend config (the Prefect UI base URL for run links). */
export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: async () => (await api.get<{ prefect_ui_url: string }>("/config/")).data,
    staleTime: Infinity,
  });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => (await api.post<Job>(`/jobs/${id}/cancel/`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}
