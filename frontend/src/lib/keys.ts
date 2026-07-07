/**
 * Centralized react-query key factory. Feature api.ts modules reference these
 * so invalidation is consistent across the app (house convention).
 */
export const KEYS = {
  health: ["health"] as const,
  me: ["me"] as const,
  users: ["users"] as const,
  documents: (patientRef?: string, status?: string) =>
    ["documents", patientRef ?? "all", status ?? "any"] as const,
  documentText: (id: number) => ["documents", id, "text"] as const,
  promptDefinitions: ["prompts", "definitions"] as const,
  promptVersions: (id: number) => ["prompts", "definitions", id, "versions"] as const,
};
