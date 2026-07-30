/** Shared display helpers for a document's `status` (DocumentStatus) and its
 * row presentation (used by the Inbox and Review lists). */
import type { SourceDocument } from "./api";

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

export function timeAgo(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} sec${s === 1 ? "" : "s"} ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d} day${d === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString();
}

/** Colored uppercase status pill — the document's real lifecycle status. */
export function statusPill(d: SourceDocument): { label: string; className: string } {
  if (d.verified) return { label: "Verified", className: "bg-emerald-600 text-white" };
  switch (d.status) {
    case "received":
      return { label: "Received", className: "bg-slate-200 text-slate-700 dark:bg-slate-500/25 dark:text-slate-300" };
    case "parsed":
      return { label: "Parsed", className: "bg-blue-600 text-white" };
    case "needs_classification":
      return { label: "Needs classification", className: "bg-destructive text-white" };
    case "classified":
      return { label: "Ready for review", className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300" };
    case "parse_failed":
      return { label: "Parse failed", className: "bg-destructive/15 text-destructive" };
    default:
      return { label: statusLabel(d.status), className: "bg-muted text-muted-foreground" };
  }
}

/** Tinted background for the row's file icon, echoing the status. */
export function iconTint(d: SourceDocument): string {
  if (d.verified) return "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400";
  if (d.status === "needs_classification" || d.status === "parse_failed")
    return "bg-red-100 text-red-500 dark:bg-red-500/15 dark:text-red-400";
  if (d.status === "classified") return "bg-emerald-100 text-emerald-500 dark:bg-emerald-500/15 dark:text-emerald-400";
  if (d.status === "received") return "bg-slate-100 text-slate-500 dark:bg-slate-500/15 dark:text-slate-400";
  return "bg-blue-100 text-blue-500 dark:bg-blue-500/15 dark:text-blue-400";
}

export function classificationText(d: SourceDocument): string {
  if (!d.classification) return d.status === "needs_classification" ? "Pending Review" : "—";
  return d.classification.outcome === "routed"
    ? d.classification.routed_types.join(", ")
    : `Unclassified · ${d.classification.reason}`;
}
