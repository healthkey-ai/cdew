import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { KEYS } from "@/lib/keys";

export interface SourceDocument {
  id: number;
  patient_ref: string;
  origin: string;
  original_filename: string;
  mime: string;
  sha256: string;
  byte_size: number;
  status: string;
  created_at: string;
  has_text: boolean;
  classification: { outcome: string; routed_types: string[]; reason: string } | null;
  category: string;
  verified: boolean;
  verified_at: string | null;
  deduplicated?: boolean;
  job_id?: number | null;
  job?: { status: string; stage: string } | null; // latest pipeline job (live)
}

/** Is the document's pipeline job actively running? */
export function isDocProcessing(d: SourceDocument): boolean {
  return d.job?.status === "queued" || d.job?.status === "running";
}

export interface DocumentText {
  document: number;
  parser: string;
  version: string;
  content: string;
  char_len: number;
  pages: { index: number; char_start: number; char_end: number; char_len: number }[];
}

export interface ExtractionRecord {
  id: number;
  document: number;
  extractor_key: string;
  domain: string;
  payload: Record<string, unknown>;
  provenance: {
    char_start: number;
    char_end: number;
    snippet: string;
    bbox: { page: number; rects: number[][] } | null; // normalized 0..1, #68
    extractor: { key: string; version_id: number };
  };
  confidence: number;
  status: string;
}

export interface Geometry {
  status: "pending" | "ready" | "failed";
  pages: { page: number; width: number; height: number; has_image: boolean }[];
  errors: { code: string }[];
}

interface Paginated<T> {
  count: number;
  results: T[];
}

export const DOCUMENTS_PAGE_SIZE = 50; // DRF PAGE_SIZE (settings/base.py)

export function useDocuments(patientRef?: string, status?: string, page?: number) {
  return useQuery({
    queryKey: [...KEYS.documents(patientRef, status), page ?? 1],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (patientRef) params.patient_ref = patientRef;
      if (status) params.status = status;
      if (page && page > 1) params.page = String(page);
      return (await api.get<Paginated<SourceDocument>>("/documents/", { params })).data;
    },
    // Poll while any document on the page is still being processed.
    refetchInterval: (q: { state: { data?: Paginated<SourceDocument> } }) =>
      (q.state.data?.results ?? []).some(isDocProcessing) ? 1500 : false,
  });
}

export function useDocument(id: number | null) {
  return useQuery({
    queryKey: id ? ["documents", id, "detail"] : ["documents", "none", "detail"],
    enabled: id != null,
    queryFn: async () => (await api.get<SourceDocument>(`/documents/${id}/`)).data,
  });
}

export function useDocumentText(id: number | null) {
  return useQuery({
    queryKey: id ? KEYS.documentText(id) : ["documents", "none", "text"],
    enabled: id != null,
    queryFn: async () => (await api.get<DocumentText>(`/documents/${id}/text/`)).data,
  });
}

export function useDocumentExtractions(id: number | null) {
  return useQuery({
    queryKey: id ? ["documents", id, "extractions"] : ["documents", "none", "extractions"],
    enabled: id != null,
    queryFn: async () => (await api.get<ExtractionRecord[]>(`/documents/${id}/extractions/`)).data,
  });
}

/** Geometry status for the review overlay (#69/#70). Polls while pending. Only
 * fetched when `enabled` (the reviewer switched to the document-image view). */
export function useGeometry(id: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["documents", id, "geometry"],
    enabled: enabled && id != null,
    queryFn: async () => (await api.get<Geometry>(`/documents/${id}/geometry/`)).data,
    refetchInterval: (q: { state: { data?: Geometry } }) => (q.state.data?.status === "pending" ? 1500 : false),
  });
}

/** Trigger on-demand geometry compute; seeds the poll query with the result. */
export function useTriggerGeometry(id: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post<Geometry>(`/documents/${id}/geometry/`)).data,
    onSuccess: (d) => qc.setQueryData(["documents", id, "geometry"], d),
  });
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, patientRef }: { file: File; patientRef: string }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("patient_ref", patientRef);
      return (
        await api.post<SourceDocument>("/documents/", form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}

/** Delete a document (reviewer-gated). Cascades text/classification/extractions. */
export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/documents/${id}/`);
      return id;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}
