import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FileText, Image as ImageIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { type ExtractionRecord, useDocument, useDocumentExtractions, useDocumentText } from "./api";
import { statusLabel, statusVariant } from "./status";

/** Authed blob URL for the original document; fetched only when `enabled` (the
 * Original tab is open), revoked on unmount. */
function useDocumentFileUrl(id: number | null, enabled: boolean): string | null {
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

/** Document view (design §3, §9): the parsed document on its own page, with the
 * extracted facts — click a fact to highlight its supporting span in the text. */
export function DocumentViewPage() {
  const { docId } = useParams();
  const id = docId ? Number(docId) : null;

  const doc = useDocument(id);
  const text = useDocumentText(id);
  const facts = useDocumentExtractions(id);

  const [active, setActive] = useState<ExtractionRecord | null>(null);
  const [view, setView] = useState<"original" | "parsed">("original");
  const fileUrl = useDocumentFileUrl(id, view === "original");
  const mime = doc.data?.mime ?? "";

  const content = text.data?.content ?? "";
  const highlighted = useMemo(() => {
    if (!active) return content;
    const { char_start: s, char_end: e } = active.provenance;
    return [content.slice(0, s), content.slice(s, e), content.slice(e)];
  }, [content, active]);

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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
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
              !fileUrl ? (
                <Skeleton className="h-[70vh] w-full" />
              ) : mime === "application/pdf" ? (
                <iframe src={fileUrl} title="Original document" className="h-[70vh] w-full rounded-md border" />
              ) : mime.startsWith("image/") ? (
                <img src={fileUrl} alt="Original document" className="max-h-[70vh] w-full rounded-md border object-contain" />
              ) : (
                <div className="rounded-md border p-6 text-center text-sm text-muted-foreground">
                  No inline preview for {mime || "this file type"}.{" "}
                  <a href={fileUrl} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                    Open in a new tab
                  </a>
                  . Switch to <span className="font-medium">Parsed</span> to read the extracted text.
                </div>
              )
            ) : text.isPending ? (
              <Skeleton className="h-96 w-full" />
            ) : text.isError ? (
              <p className="text-sm text-muted-foreground">No parsed text for this document.</p>
            ) : (
              <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-4 text-xs leading-relaxed">
                {Array.isArray(highlighted) ? (
                  <>
                    {highlighted[0]}
                    <mark className="rounded bg-warning/40 px-0.5">{highlighted[1]}</mark>
                    {highlighted[2]}
                  </>
                ) : (
                  content || "(empty)"
                )}
              </pre>
            )}
          </CardContent>
        </Card>

        {/* extracted facts */}
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Extracted facts{facts.data ? ` (${facts.data.length})` : ""}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {facts.isPending && <Skeleton className="h-16 w-full" />}
              {facts.data?.map((f) => (
                <li key={f.id}>
                  <button
                    className={cn(
                      "w-full rounded-md border p-2 text-left text-xs transition-colors hover:bg-muted",
                      active?.id === f.id && "border-warning ring-1 ring-warning/40",
                    )}
                    onClick={() => {
                      const next = active?.id === f.id ? null : f;
                      setActive(next);
                      if (next) setView("parsed"); // the span highlight lives in the parsed text
                    }}
                  >
                    <div className="flex items-center gap-1.5">
                      <Badge variant="secondary">{f.domain || f.extractor_key}</Badge>
                      {f.status !== "staged" && <Badge variant="outline">{f.status}</Badge>}
                    </div>
                    <code className="mt-1 block break-all">{JSON.stringify(f.payload)}</code>
                    <div className="mt-0.5 text-muted-foreground">“{f.provenance.snippet}”</div>
                  </button>
                </li>
              ))}
              {facts.data && facts.data.length === 0 && (
                <li className="text-xs text-muted-foreground">No extracted facts yet.</li>
              )}
            </ul>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
