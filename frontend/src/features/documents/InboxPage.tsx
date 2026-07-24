import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, Eye, FileText, Loader2, Trash2, UploadCloud } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/features/auth/api";
import { useJob } from "@/features/pipeline/api";
import { cn } from "@/lib/utils";
import { DOCUMENTS_PAGE_SIZE, type SourceDocument, useDeleteDocument, useDocuments, useUploadDocument } from "./api";
import { statusLabel } from "./status";

const TABS = [
  { value: "all", label: "All Documents" },
  { value: "needs_classification", label: "Needs Classification" },
  { value: "classified", label: "Classified" },
  { value: "parse_failed", label: "Parse Failed" },
];

function timeAgo(iso: string): string {
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

/** Colored uppercase status pill (matches the row-status affordance). */
function statusPill(d: SourceDocument): { label: string; className: string } {
  if (d.verified) return { label: "Verified", className: "bg-emerald-600 text-white" };
  switch (d.status) {
    case "needs_classification":
      return { label: "Needs classification", className: "bg-destructive text-white" };
    case "classified":
      return { label: "Classified", className: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300" };
    case "parse_failed":
      return { label: "Parse failed", className: "bg-destructive/15 text-destructive" };
    case "received":
    case "parsed":
      return { label: "Processing", className: "bg-blue-600 text-white" };
    default:
      return { label: statusLabel(d.status), className: "bg-muted text-muted-foreground" };
  }
}

function iconTint(d: SourceDocument): string {
  if (d.verified) return "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400";
  if (d.status === "needs_classification" || d.status === "parse_failed")
    return "bg-red-100 text-red-500 dark:bg-red-500/15 dark:text-red-400";
  if (d.status === "classified") return "bg-indigo-100 text-indigo-500 dark:bg-indigo-500/15 dark:text-indigo-400";
  return "bg-blue-100 text-blue-500 dark:bg-blue-500/15 dark:text-blue-400";
}

function classificationText(d: SourceDocument): string {
  if (!d.classification) return d.status === "needs_classification" ? "Pending Review" : "—";
  return d.classification.outcome === "routed"
    ? d.classification.routed_types.join(", ")
    : `Unclassified · ${d.classification.reason}`;
}

function buildPages(cur: number, total: number): (number | "…")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | "…")[] = [1];
  const l = Math.max(2, cur - 1);
  const r = Math.min(total - 1, cur + 1);
  if (l > 2) pages.push("…");
  for (let i = l; i <= r; i++) pages.push(i);
  if (r < total - 1) pages.push("…");
  pages.push(total);
  return pages;
}

/** Drop-zone hero: drag-and-drop or pick a file, tagged with a patient ref. */
function UploadHero({ patientRef, setPatientRef }: { patientRef: string; setPatientRef: (v: string) => void }) {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useUploadDocument();
  const job = useJob(jobId);
  const jobStatus = job.data?.status;

  useEffect(() => {
    if (jobStatus === "completed") {
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast.success("Document processed");
    } else if (jobStatus === "failed") {
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast.error("Processing failed");
    }
  }, [jobStatus, qc]);

  const doUpload = (file?: File | null) => {
    if (!file) return;
    if (!patientRef.trim()) {
      toast.error("Enter a patient ref first");
      return;
    }
    upload.mutate(
      { file, patientRef: patientRef.trim() },
      {
        onSuccess: (d) => {
          setJobId(d.job_id ?? null);
          if (fileRef.current) fileRef.current.value = "";
          toast.info(d.deduplicated ? "Deduplicated to existing document" : "Uploaded — processing…");
          qc.invalidateQueries({ queryKey: ["documents"] });
        },
        onError: () => toast.error("Upload failed"),
      },
    );
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        doUpload(e.dataTransfer.files?.[0]);
      }}
      className={cn(
        "rounded-xl border-2 border-dashed p-8 text-center transition-colors",
        dragging ? "border-primary bg-primary/5" : "border-border bg-muted/30",
      )}
    >
      <input
        ref={fileRef}
        type="file"
        className="hidden"
        onChange={(e) => doUpload(e.target.files?.[0])}
      />
      <div className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
        {upload.isPending ? <Loader2 className="size-7 animate-spin" /> : <UploadCloud className="size-7" />}
      </div>
      <h2 className="mt-4 text-lg font-semibold">Upload Source Documents</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
        Drag and drop patient charts, lab results, imaging reports, or office visit notes here. Supports PDF, HL7,
        and DICOM formats.
      </p>

      <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
        <Button onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? "Uploading…" : "Select File"}
        </Button>
      </div>

      <div className="mx-auto mt-4 flex max-w-xs items-center justify-center gap-2">
        <span className="text-xs text-muted-foreground">Patient ref</span>
        <Input
          className="h-8 w-40 bg-background"
          value={patientRef}
          onChange={(e) => setPatientRef(e.target.value)}
          placeholder="PT-001"
        />
      </div>
    </div>
  );
}

/** Inbox (design §3): upload a document, browse recent activity, open one to review. */
export function InboxPage() {
  const navigate = useNavigate();
  const [patientRef, setPatientRef] = useState("PT-001");
  const [tab, setTab] = useState("all");
  const [page, setPage] = useState(1);

  const docs = useDocuments(undefined, tab === "all" ? undefined : tab, page);
  const del = useDeleteDocument();
  const me = useMe();
  const canDelete = (me.data?.roles ?? []).some((r) => r === "reviewer" || r === "admin");

  const rows = docs.data?.results ?? [];
  const count = docs.data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(count / DOCUMENTS_PAGE_SIZE));
  const first = count === 0 ? 0 : (page - 1) * DOCUMENTS_PAGE_SIZE + 1;
  const last = (page - 1) * DOCUMENTS_PAGE_SIZE + rows.length;

  const onDelete = (d: SourceDocument) => {
    const label = d.original_filename || `doc#${d.id}`;
    if (!window.confirm(`Delete “${label}”? This permanently removes the document and all its extractions.`)) return;
    del.mutate(d.id, {
      onSuccess: () => toast.success("Document deleted"),
      onError: (err) => {
        const s = (err as { response?: { status?: number } }).response?.status;
        toast.error(s === 403 ? "You need the reviewer role to delete" : "Delete failed");
      },
    });
  };

  return (
    <section className="space-y-8">
      <UploadHero patientRef={patientRef} setPatientRef={setPatientRef} />

      {/* Recent activity */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-tight">Recent Activity</h2>
          <div className="inline-flex items-center gap-1 rounded-lg bg-muted p-1 text-sm">
            {TABS.map((t) => (
              <button
                key={t.value}
                onClick={() => {
                  setTab(t.value);
                  setPage(1);
                }}
                className={cn(
                  "rounded-md px-3 py-1.5 font-medium transition-colors",
                  tab === t.value
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* column headers */}
        <div className="mt-4 grid grid-cols-[1fr_8rem_10rem_1fr_11.5rem] gap-3 border-b px-4 pb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <span>Document Name &amp; ID</span>
          <span>Date Added</span>
          <span>Status</span>
          <span>Classification</span>
          <span className="text-right">Action</span>
        </div>

        <div className="mt-3 space-y-3">
          {docs.isPending &&
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 rounded-lg border bg-card p-3">
                <Skeleton className="size-10 rounded-lg" />
                <Skeleton className="h-4 w-56" />
              </div>
            ))}

          {!docs.isPending &&
            rows.map((d) => {
              const pill = statusPill(d);
              return (
                <div
                  key={d.id}
                  className="grid cursor-pointer grid-cols-[1fr_8rem_10rem_1fr_11.5rem] items-center gap-3 rounded-lg border bg-card px-4 py-3 transition-colors hover:border-primary/40 hover:bg-accent/40"
                  onClick={() => navigate(`/inbox/${d.id}`)}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg", iconTint(d))}>
                      <FileText className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold">{d.original_filename || `doc#${d.id}`}</div>
                      <div className="font-mono text-xs text-muted-foreground">{d.patient_ref}</div>
                    </div>
                  </div>
                  <div className="text-sm text-muted-foreground">{timeAgo(d.created_at)}</div>
                  <div>
                    <span
                      className={cn(
                        "inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                        pill.className,
                      )}
                    >
                      {pill.label}
                    </span>
                  </div>
                  <div className="truncate text-sm text-muted-foreground">{classificationText(d)}</div>
                  <div className="flex justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8"
                      onClick={() => navigate(`/inbox/${d.id}`)}
                    >
                      <Eye className="size-4" /> View
                    </Button>
                    {canDelete && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 text-muted-foreground hover:text-destructive"
                        disabled={del.isPending}
                        onClick={() => onDelete(d)}
                      >
                        <Trash2 className="size-4" /> Delete
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}

          {!docs.isPending && rows.length === 0 && (
            <div className="rounded-lg border border-dashed py-12 text-center text-sm text-muted-foreground">
              No documents in this queue yet.
            </div>
          )}
        </div>

        {/* pagination */}
        {count > 0 && (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t pt-4 text-sm">
            <span className="text-muted-foreground">
              Showing {first}–{last} of {count} document{count === 1 ? "" : "s"}
            </span>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="icon"
                className="size-8"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                aria-label="Previous page"
              >
                <ChevronLeft className="size-4" />
              </Button>
              {buildPages(page, totalPages).map((p, i) =>
                p === "…" ? (
                  <span key={`e${i}`} className="px-2 text-muted-foreground">
                    …
                  </span>
                ) : (
                  <Button
                    key={p}
                    variant={p === page ? "default" : "outline"}
                    size="icon"
                    className="size-8"
                    onClick={() => setPage(p)}
                  >
                    {p}
                  </Button>
                ),
              )}
              <Button
                variant="outline"
                size="icon"
                className="size-8"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                aria-label="Next page"
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
