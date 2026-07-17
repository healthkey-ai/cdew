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

/** A labeled test sample scoped to one definition (design §8.3). `expected_payload`
 * is the gold: classifier → string[] of type slugs; extractor → object[] of fact data. */
export interface TestSample {
  id: number;
  definition: number;
  document: number;
  document_filename: string;
  document_has_text: boolean;
  definition_kind: "classifier" | "extractor";
  label: string;
  expected_payload: unknown | null;
  notes: string;
}

export interface DryRunFact {
  data: Record<string, unknown>;
  snippet: string;
  char_start: number;
  char_end: number;
  resolved: boolean;
  confidence: number | null;
}

/** One dry-run result row (keyed to a sample). Fields depend on the kind. */
export interface DryRunRow {
  sample_id: number;
  label: string;
  document_id: number;
  passed?: boolean;
  // extractor
  facts?: DryRunFact[];
  expected?: unknown;
  // classifier
  scores?: { type: string; confidence: number }[];
  routed_types?: string[];
  outcome?: string;
  reason?: string | null;
  expected_types?: string[];
  missing?: string[];
  extra?: string[];
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
      mutationFn: async (id: number) =>
        (await api.post<{ results: DryRunRow[] }>(`${P}/versions/${id}/dry-run/`)).data,
    }),
    deleteVersion: useMutation({
      mutationFn: async (id: number) => {
        await api.delete(`${P}/versions/${id}/`);
        return id;
      },
      onSuccess: invalidate,
    }),
  };
}

/** The definition's labeled test set. */
export function useTestSamples(defId: number | null) {
  return useQuery({
    queryKey: ["prompts", "test-set", defId],
    enabled: defId != null,
    queryFn: async () =>
      (await api.get<{ results: TestSample[] }>(`${P}/test-set/`, { params: { definition: defId } })).data.results,
  });
}

export function useTestSampleActions(defId: number | null) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["prompts", "test-set", defId] });
  return {
    create: useMutation({
      mutationFn: async (s: { document: number; label?: string; expected_payload?: unknown }) =>
        (await api.post<TestSample>(`${P}/test-set/`, { ...s, definition: defId })).data,
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: async ({ id, ...body }: { id: number } & Partial<TestSample>) =>
        (await api.patch<TestSample>(`${P}/test-set/${id}/`, body)).data,
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: async (id: number) => {
        await api.delete(`${P}/test-set/${id}/`);
        return id;
      },
      onSuccess: invalidate,
    }),
  };
}
