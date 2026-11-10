import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Authed blob URL for the original document; fetched only when `enabled`,
 * revoked on unmount (the JWT isn't a cookie, so a plain `src` URL can't load it). */
function useDocumentFileUrl(id: number | null, enabled = true): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled || id == null) return;
    let obj: string | null = null;
    let cancelled = false;
    api
      .get(`/documents/${id}/file/`, { responseType: "blob" })
      .then((r) => {
        if (!cancelled) {
          obj = URL.createObjectURL(r.data as Blob);
          setUrl(obj);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [id, enabled]);
  return url;
}

/** The original upload, previewed inline: a PDF in the browser's viewer, an image
 * as is, anything else as a link. Used by the document page and, when there's
 * no geometry, by the review panel instead of the highlight overlay. */
export function OriginalDocument({
  docId,
  mime,
  className = "h-[70vh]",
}: {
  docId: number;
  mime: string;
  className?: string;
}) {
  const url = useDocumentFileUrl(docId);
  if (!url) return <Skeleton className={cn("w-full", className)} />;
  if (mime === "application/pdf") {
    return <iframe src={url} title="Original document" className={cn("w-full rounded-md border", className)} />;
  }
  if (mime.startsWith("image/")) {
    return <img src={url} alt="Original document" className={cn("w-full rounded-md border object-contain", className)} />;
  }
  return (
    <div className="rounded-md border p-6 text-center text-sm text-muted-foreground">
      No inline preview for {mime || "this file type"}.{" "}
      <a href={url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
        Open in a new tab
      </a>
      , or read its parsed text.
    </div>
  );
}
