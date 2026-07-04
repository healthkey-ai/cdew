import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface ExtractionJob {
  id: number;
  document: number;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  progress: number;
  errors: { code: string }[];
  prefect_flow_run_id: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

const TERMINAL = new Set(["completed", "failed"]);

/** Poll a job until it reaches a terminal state (design §6 UI polling). */
export function useJob(jobId: number | null) {
  return useQuery({
    queryKey: ["jobs", jobId],
    enabled: jobId != null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : 1000;
    },
    queryFn: async () => (await api.get<ExtractionJob>(`/jobs/${jobId}/`)).data,
  });
}
