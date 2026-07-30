import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { useDocument } from "@/features/documents/api";

import { ReviewPanel } from "./ReviewPanel";

/** Route wrapper for the interactive review surface (design §6/§9): mounts the
 * ReviewPanel (parsed text / document image + bbox overlays, approve/reject/verify). */
export function ReviewDocumentPage() {
  const { docId } = useParams();
  const id = Number(docId);
  const doc = useDocument(id || null);
  if (!id) return null;
  const name = doc.data?.original_filename || `Document #${id}`;
  return (
    <section className="space-y-4">
      <div className="space-y-1.5">
        <Link
          to="/review"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4 shrink-0" />
          Review
        </Link>
        <h1 className="text-xl font-semibold tracking-tight">
          Reviewing · <span className="font-normal text-muted-foreground">{name}</span>
        </h1>
      </div>
      <ReviewPanel docId={id} />
    </section>
  );
}
