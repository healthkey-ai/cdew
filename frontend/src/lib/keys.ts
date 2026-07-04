/**
 * Centralized react-query key factory. Feature api.ts modules reference these
 * so invalidation is consistent across the app (house convention).
 */
export const KEYS = {
  health: ["health"] as const,
  me: ["me"] as const,
  documents: (patientRef?: string) => ["documents", patientRef ?? "all"] as const,
  documentText: (id: number) => ["documents", id, "text"] as const,
  // Phase 3+: prompts: ["prompts"], promptVersions: (id: number) => ["prompts", id, "versions"],
};
