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
  domain: string;
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
    verify: useMutation({
      mutationFn: async (category: string) =>
        (await api.post(`/documents/${docId}/verify/`, { category })).data,
      onSuccess: invalidate,
    }),
  };
}
