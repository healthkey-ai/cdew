import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { ReviewPanel } from "./ReviewPanel";

/** Route wrapper for the interactive review surface (design §6/§9): mounts the
 * ReviewPanel (parsed text / document image + bbox overlays, approve/reject/verify). */
export function ReviewDocumentPage() {
  const { docId } = useParams();
  const id = Number(docId);
  if (!id) return null;
  return (
    <section className="space-y-3">
      <Link
        to="/review"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4 shrink-0" />
        Review list
      </Link>
      <ReviewPanel docId={id} />
    </section>
  );
}
