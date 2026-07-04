import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface ActiveVersion {
  id: number;
  version: number;
  status: string;
}
export interface PromptDefinition {
  id: number;
  kind: "classifier" | "extractor";
  key: string;
  name: string;
  domain: string;
  enabled: boolean;
  triggers_on_types: string[];
  active_version: ActiveVersion | null;
}
export interface PromptVersion {
  id: number;
  definition: number;
  version: number;
  status: "draft" | "published" | "archived";
  prompt_text: string;
  json_schema: Record<string, unknown>;
  taxonomy: unknown[];
  model: string;
  params: Record<string, unknown>;
  notes: string;
  published_at: string | null;
}
export interface LintFinding {
  level: "error" | "warning";
  code: string;
  path: string;
  message: string;
}
export interface LintResult {
  ok: boolean;
  findings: LintFinding[];
}

const P = "/prompts";

export function usePromptDefinitions() {
  return useQuery({
    queryKey: ["prompts", "definitions"],
    // The definitions list is paginated (DRF default) → unwrap results.
    queryFn: async () => (await api.get<{ results: PromptDefinition[] }>(`${P}/definitions/`)).data.results,
  });
}

export function usePromptVersions(defId: number | null) {
  return useQuery({
    queryKey: ["prompts", "definitions", defId, "versions"],
    enabled: defId != null,
    queryFn: async () => (await api.get<PromptVersion[]>(`${P}/definitions/${defId}/versions/`)).data,
  });
}

/** Mutations for the authoring lifecycle. Invalidates definitions + versions. */
export function usePromptActions(defId: number | null) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["prompts", "definitions"] });
  };

  return {
    createDraft: useMutation({
      mutationFn: async () => (await api.post<PromptVersion>(`${P}/definitions/${defId}/versions/`, {})).data,
      onSuccess: invalidate,
    }),
    saveDraft: useMutation({
      mutationFn: async (v: Partial<PromptVersion> & { id: number }) =>
        (await api.patch<PromptVersion>(`${P}/versions/${v.id}/`, v)).data,
      onSuccess: invalidate,
    }),
    validate: useMutation({
      mutationFn: async (id: number) => (await api.post<LintResult>(`${P}/versions/${id}/validate/`)).data,
    }),
    publish: useMutation({
      mutationFn: async (id: number) => (await api.post(`${P}/versions/${id}/publish/`)).data,
      onSuccess: invalidate,
    }),
    activate: useMutation({
      mutationFn: async (versionId: number) =>
        (await api.post(`${P}/definitions/${defId}/activate/`, { version_id: versionId })).data,
      onSuccess: invalidate,
    }),
    dryRun: useMutation({
      mutationFn: async (id: number) => (await api.post(`${P}/versions/${id}/dry-run/`)).data,
    }),
  };
}
