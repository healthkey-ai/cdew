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
    extractor: { key: string; version_id: number };
  };
  confidence: number;
  status: string;
}

interface Paginated<T> {
  count: number;
  results: T[];
}

export function useDocuments(patientRef?: string, status?: string) {
  return useQuery({
    queryKey: KEYS.documents(patientRef, status),
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (patientRef) params.patient_ref = patientRef;
      if (status) params.status = status;
      return (await api.get<Paginated<SourceDocument>>("/documents/", { params })).data;
    },
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
