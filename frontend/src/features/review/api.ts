import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface EditFact {
  id: number;
  status?: "staged" | "approved" | "rejected";
  payload?: Record<string, unknown>;
  span?: { char_start: number; char_end: number };
}

export interface NewFact {
  document: number;
  object_type: string; // a catalog object type (#96); its fields are the payload's
  snippet: string;
  payload: Record<string, unknown>;
}

/** Review mutations (design §6). Invalidates the document's extractions + list. */
export function useReviewActions(docId: number) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["documents", docId, "extractions"] });
    qc.invalidateQueries({ queryKey: ["documents"] });
  };

  return {
    editFact: useMutation({
      mutationFn: async ({ id, ...body }: EditFact) => (await api.patch(`/extractions/${id}/`, body)).data,
      onSuccess: invalidate,
    }),
    addFact: useMutation({
      mutationFn: async (f: NewFact) => (await api.post("/extractions/", f)).data,
      onSuccess: invalidate,
    }),
    /** Ad-hoc extraction (#114): extract this document for the picked object types.
     * Returns the job; the panel refreshes its facts when the job finishes. */
    extractAdHoc: useMutation({
      mutationFn: async (objectTypes: string[]) =>
        (await api.post(`/documents/${docId}/extract-ad-hoc/`, { object_types: objectTypes })).data,
      onSuccess: () => {
        invalidate();
        qc.invalidateQueries({ queryKey: ["jobs"] });
      },
    }),
    verify: useMutation({
      mutationFn: async () => (await api.post(`/documents/${docId}/verify/`, {})).data,
      onSuccess: invalidate,
    }),
    unverify: useMutation({
      mutationFn: async () => (await api.post(`/documents/${docId}/unverify/`, {})).data,
      onSuccess: invalidate,
    }),
  };
}
