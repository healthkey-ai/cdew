import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FileText, Image as ImageIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useDocument, useDocumentText } from "./api";
import { OriginalDocument } from "./OriginalDocument";
import { statusLabel, statusVariant } from "./status";

/** Document view (design §3, §9): the document on its own page — the original
 * upload (PDF/image preview) or its parsed text. Fact review lives in Review. */
export function DocumentViewPage() {
  const { docId } = useParams();
  const id = docId ? Number(docId) : null;

  const doc = useDocument(id);
  const text = useDocumentText(id);

  const [view, setView] = useState<"original" | "parsed">("original");
  const mime = doc.data?.mime ?? "";
  const content = text.data?.content ?? "";

  const d = doc.data;
  const title = d?.original_filename || `Document #${id}`;

  return (
    <section className="space-y-5">
      <div className="space-y-3">
        <Link to="/inbox" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2 w-fit")}>
          <ArrowLeft />
          Inbox
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {d && <Badge variant={statusVariant(d.status)}>{statusLabel(d.status)}</Badge>}
          {d?.verified && <Badge variant="secondary">✓ verified</Badge>}
        </div>
        {d && (
          <div className="text-sm text-muted-foreground">
            patient {d.patient_ref} · {d.mime}
            {d.classification &&
              ` · ${
                d.classification.outcome === "routed"
                  ? d.classification.routed_types.join(", ")
                  : `unclassified · ${d.classification.reason}`
              }`}
          </div>
        )}
      </div>

      {/* document: original preview or parsed text */}
      <Card>
          <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
            <CardTitle>{view === "original" ? "Original document" : "Parsed document"}</CardTitle>
            <div className="inline-flex items-center gap-1 rounded-lg bg-muted p-1 text-xs">
              <Button
                variant={view === "original" ? "secondary" : "ghost"}
                size="sm"
                className="h-7"
                onClick={() => setView("original")}
              >
                <ImageIcon className="size-3.5" /> Original
              </Button>
              <Button
                variant={view === "parsed" ? "secondary" : "ghost"}
                size="sm"
                className="h-7"
                onClick={() => setView("parsed")}
              >
                <FileText className="size-3.5" /> Parsed
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {view === "original" ? (
              id != null && <OriginalDocument docId={id} mime={mime} />
            ) : text.isPending ? (
              <Skeleton className="h-96 w-full" />
            ) : text.isError ? (
              <p className="text-sm text-muted-foreground">No parsed text for this document.</p>
            ) : (
              <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-4 text-xs leading-relaxed">
                {content || "(empty)"}
              </pre>
            )}
          </CardContent>
        </Card>
    </section>
  );
}
