/** Shared display helpers for a document's `status` (DocumentStatus). */

const STATUS_LABELS: Record<string, string> = {
  received: "Received",
  parsed: "Parsed",
  classified: "Classified",
  parse_failed: "Parse failed",
  needs_classification: "Needs classification",
};

/** Friendly label for a status value (matches the Inbox status filter). */
export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "parse_failed") return "destructive";
  if (status === "needs_classification") return "outline";
  if (status === "classified") return "secondary";
  return "secondary";
}
