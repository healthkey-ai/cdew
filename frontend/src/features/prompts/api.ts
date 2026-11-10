import { useEffect, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { KEYS } from "@/lib/keys";

export interface ActiveVersion {
  id: number;
  version: number;
  status: string;
}
export interface PromptDefinition {
  id: number;
  kind: "classifier" | "extractor";
  key: string; // fixed once created
  name: string;
  description: string;
  domain: string;
  enabled: boolean;
  triggers_on_types: string[]; // routing: taxonomy types that run this extractor
  active_version: ActiveVersion | null;
  unknown_triggers: string[]; // routed types the active taxonomy doesn't have — they never fire
}

/** Create an extractor (it starts with an empty object-typed draft), or update a
 * definition's name / description / routing / enabled flag. */
export function useDefinitionActions() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: KEYS.promptDefinitions });
  return {
    create: useMutation({
      mutationFn: async (d: Pick<PromptDefinition, "key" | "name" | "description" | "triggers_on_types">) =>
        (await api.post<PromptDefinition>(`${P}/definitions/`, { ...d, kind: "extractor", enabled: true })).data,
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: async ({ id, ...d }: Partial<PromptDefinition> & { id: number }) =>
        (await api.patch<PromptDefinition>(`${P}/definitions/${id}/`, d)).data,
      onSuccess: invalidate,
    }),
    /** Delete an extractor — refused (409) once it has produced facts; disable it instead. */
    remove: useMutation({
      mutationFn: async (id: number) => {
        await api.delete(`${P}/definitions/${id}/`);
        return id;
      },
      onSuccess: invalidate,
    }),
  };
}

/** The active classifier's taxonomy types — what an extractor can be routed on. */
export function useTaxonomyTypes(): string[] {
  const defs = usePromptDefinitions();
  const classifier = defs.data?.find((d) => d.kind === "classifier") ?? null;
  const versions = usePromptVersions(classifier?.id ?? null);
  const active = versions.data?.find((v) => v.id === classifier?.active_version?.id);
  return ((active?.taxonomy ?? []) as { type?: string }[]).map((t) => t.type ?? "").filter(Boolean);
}
export interface PromptVersion {
  id: number;
  definition: number;
  version: number;
  status: "draft" | "published" | "archived";
  prompt_text: string;
  json_schema: Record<string, unknown>; // legacy extractors
  taxonomy: unknown[];
  /** Object-typed extractors (#95): catalog keys, per-object guidance, and (once
   * published) the pinned definitions. Empty `object_types` = a legacy extractor. */
  object_types: string[];
  guidance: Record<string, string>;
  object_type_snapshot: Record<string, ObjectType>;
  model: string;
  params: Record<string, unknown>;
  notes: string;
  published_at: string | null;
}
/** A JSON Schema property as the catalog writes it. */
export interface CatalogField {
  type: string | string[];
  format?: string;
  description?: string;
}

/** One object type of the catalog (alignment §3.1, #94), synced from promop. */
export interface ObjectType {
  key: string;
  label: string;
  description: string;
  omop_target: string;
  promop_endpoint: string;
  source_schema: { properties: Record<string, CatalogField>; required: string[] };
  field_guide: Record<string, string>;
  default_guidance: string;
  extraction_only: string[];
  commit_required: string[];
  promop_required?: string[]; // promop's whole required list — the commit contract (P4)
  commit_enabled?: boolean; // this type's commit path is live (P5)
  commit_adapter?: "bulk_upsert" | "genomics" | "none";
  omop_targets?: string[];
  commit_hold?: string; // why facts of this type can't be committed yet (e.g. genomics: promop#1245)
  promop_schema_version: string;
}

/** Reviewer-facing labels for fields whose API names mislead (genomics-integration.md). */
export const FIELD_LABELS: Record<string, string> = {
  allelic_frequency: "Sample VAF",
  allelic_frequency_unit: "Sample VAF unit",
  variant: "Transcript DNA change",
  amino_acid_change: "Protein change",
  interpretation: "Reported interpretation",
  variant_analysis_method_type: "Analysis method",
};

/** Is this extractor version object-typed (vs a legacy json_schema one)? A new,
 * empty draft counts as object-typed — that's the only kind authors create now. */
export const isObjectTyped = (v: Pick<PromptVersion, "object_types" | "json_schema">) =>
  v.object_types.length > 0 || Object.keys(v.json_schema ?? {}).length === 0;

/** The comparable shape of an extracted fact (alignment §7.3): object-typed facts
 * are `{object_type, ...data}` rows, so test-set gold is a list of those. */
export const factRow = (f: { object_type?: string; data: Record<string, unknown> }) =>
  f.object_type ? { object_type: f.object_type, ...f.data } : f.data;

/** One of promop's document types (P3, #97) — what a taxonomy type maps to. */
export interface DocumentType {
  code: string; // e.g. LAB_RESULTS
  label: string;
}

export function useDocumentTypes() {
  return useQuery({
    queryKey: KEYS.documentTypes,
    queryFn: async () => (await api.get<DocumentType[]>(`${P}/document-types/`)).data,
    staleTime: 5 * 60_000,
  });
}

/** The object catalog — read by authors (selection) and reviewers (manual facts). */
export function useObjectTypes() {
  return useQuery({
    queryKey: KEYS.objectTypes,
    queryFn: async () => (await api.get<ObjectType[]>(`${P}/object-types/`)).data,
    staleTime: 5 * 60_000,
  });
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
  extracted_payload: unknown | null;
  extracted_version_id: number | null;
  extracted_at: string | null;
  notes: string;
}

export interface DryRunFact {
  object_type?: string; // object-typed extractors
  data: Record<string, unknown>;
  snippet: string;
  char_start: number;
  char_end: number;
  resolved: boolean;
  confidence: number | null;
}

export type DryRunStatus = "queued" | "running" | "completed" | "failed";

/** An async dry-run job (#55). Per-sample results persist on the samples; this is
 * status + safe summary counts, polled to completion. */
export interface DryRunJob {
  id: number;
  version: number;
  sample_ids: number[]; // [] = whole set
  status: DryRunStatus;
  summary: { total?: number; scored?: number; passed?: number };
  errors: { code: string }[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

const P = "/prompts";
const isTerminal = (s: DryRunStatus) => s === "completed" || s === "failed";

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

/** Submit + poll async dry-run jobs (#55). Supports **concurrent** jobs: each
 * submit (whole set or a single sample) is tracked and polled independently; on
 * completion the test set is invalidated and `onDone(job)` fires (for a toast).
 * `sampleIds` empty/undefined = the whole set. In `local` dispatch the job comes
 * back already terminal, so no polling happens. */
export function useDryRunJobs(
  defId: number | null,
  onDone?: (job: DryRunJob) => void,
  onError?: (err: unknown) => void,
) {
  const qc = useQueryClient();
  const [active, setActive] = useState<{ id: number; sampleIds: number[] }[]>([]);
  const invalidateSet = () => qc.invalidateQueries({ queryKey: ["prompts", "test-set", defId] });

  const submit = useMutation({
    mutationFn: async ({ versionId, sampleIds }: { versionId: number; sampleIds?: number[] }) =>
      (await api.post<DryRunJob>(`${P}/versions/${versionId}/dry-run/`, sampleIds ? { sample_ids: sampleIds } : {}))
        .data,
    onSuccess: (job) => {
      if (isTerminal(job.status)) {
        invalidateSet();
        onDone?.(job);
      } else {
        setActive((a) => [...a, { id: job.id, sampleIds: job.sample_ids }]);
      }
    },
    onError: (err) => onError?.(err),
  });

  const polled = useQueries({
    queries: active.map((j) => ({
      queryKey: ["dry-run-job", j.id],
      queryFn: async () => (await api.get<DryRunJob>(`${P}/dry-run-jobs/${j.id}/`)).data,
      refetchInterval: (q: { state: { data?: DryRunJob } }) =>
        q.state.data && isTerminal(q.state.data.status) ? false : 1200,
    })),
  });

  const doneKey = polled.map((r) => `${r.data?.id}:${r.data?.status}`).join();
  useEffect(() => {
    const done = polled.map((r) => r.data).filter((j): j is DryRunJob => !!j && isTerminal(j.status));
    if (!done.length) return;
    invalidateSet();
    done.forEach((j) => onDone?.(j));
    const ids = new Set(done.map((j) => j.id));
    setActive((a) => a.filter((j) => !ids.has(j.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doneKey]);

  const wholeSetRunning = active.some((j) => j.sampleIds.length === 0);
  const runningSamples = new Set(active.flatMap((j) => j.sampleIds));

  return {
    submit: (versionId: number, sampleIds?: number[]) => submit.mutate({ versionId, sampleIds }),
    isSampleRunning: (id: number) => wholeSetRunning || runningSamples.has(id),
    wholeSetRunning: wholeSetRunning || submit.isPending,
    anyRunning: active.length > 0 || submit.isPending,
  };
}
