import { Link, useNavigate } from "react-router-dom";
import { FileText } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocuments } from "@/features/documents/api";
import { classificationText, iconTint, statusPill, timeAgo } from "@/features/documents/status";
import { cn } from "@/lib/utils";

const COLS = "grid-cols-[1fr_8rem_10rem_1fr_6rem]";

/** Review (design §6): processed documents ready to review, as a card-row list
 * (matching the Inbox). Open one to verify facts on the document. */
export function ReviewPage() {
  const navigate = useNavigate();
  // Ready for review = classified (routed + extracted). Excludes docs still
  // needing classification, parse failures, and in-flight ones.
  const docs = useDocuments(undefined, "classified");
  const rows = docs.data?.results ?? [];

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Review</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Processed documents ready to review. Open one to verify facts on the document (text or image with bounding
          boxes) and approve/correct/reject.
        </p>
      </div>

      <div>
        <div
          className={cn(
            "grid gap-3 border-b px-4 pb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground",
            COLS,
          )}
        >
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
                  className={cn(
                    "grid cursor-pointer items-center gap-3 rounded-lg border bg-card px-4 py-3 transition-colors hover:border-primary/40 hover:bg-accent/40",
                    COLS,
                  )}
                  onClick={() => navigate(`/review/${d.id}`)}
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
                  <div className="flex justify-end" onClick={(e) => e.stopPropagation()}>
                    <Link to={`/review/${d.id}`} className={cn(buttonVariants({ size: "sm" }))}>
                      Review
                    </Link>
                  </div>
                </div>
              );
            })}

          {!docs.isPending && rows.length === 0 && (
            <div className="rounded-lg border border-dashed py-12 text-center text-sm text-muted-foreground">
              No processed documents yet.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
