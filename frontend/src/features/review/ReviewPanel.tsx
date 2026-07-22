import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Check, FileText, Image as ImageIcon, Loader2, Pencil, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  type ExtractionRecord,
  type Geometry,
  useDocumentExtractions,
  useDocumentText,
  useGeometry,
  useTriggerGeometry,
} from "@/features/documents/api";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useReviewActions } from "./api";

/** Fetch a page image as an authed blob → object URL (an <img src> can't send the
 * Bearer token). Revokes on unmount. */
function usePageImageUrl(docId: number, page: number): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let obj: string | null = null;
    let cancelled = false;
    api
      .get(`/documents/${docId}/pages/${page}/image/`, { responseType: "blob" })
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
  }, [docId, page]);
  return url;
}

/** One page image with SVG bbox overlays. Normalized boxes (0..1) map to the
 * image via a 0 0 1 1 viewBox. Click a box → select the fact. */
function PageOverlay({
  docId,
  page,
  facts,
  activeId,
  onPick,
  scrollTo,
}: {
  docId: number;
  page: number;
  facts: ExtractionRecord[];
  activeId: number | null;
  onPick: (f: ExtractionRecord) => void;
  scrollTo: boolean;
}) {
  const url = usePageImageUrl(docId, page);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollTo) ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [scrollTo]);
  const pageFacts = facts.filter((f) => f.provenance.bbox?.page === page);
  return (
    <div ref={ref} className="relative overflow-hidden rounded border bg-white">
      {url ? (
        <img src={url} alt={`page ${page}`} className="block w-full" />
      ) : (
        <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">loading page {page}…</div>
      )}
      <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        {pageFacts.flatMap((f) =>
          (f.provenance.bbox?.rects ?? []).map((r, i) => (
            <rect
              key={`${f.id}-${i}`}
              x={r[0]}
              y={r[1]}
              width={Math.max(0, r[2] - r[0])}
              height={Math.max(0, r[3] - r[1])}
              vectorEffect="non-scaling-stroke"
              strokeWidth={1.5}
              onClick={() => onPick(f)}
              className={cn(
                "cursor-pointer transition-colors",
                activeId === f.id
                  ? "fill-warning/30 stroke-warning"
                  : "fill-primary/5 stroke-primary/40 hover:fill-primary/20",
              )}
            />
          )),
        )}
      </svg>
    </div>
  );
}

/** The document-image view: pages with fact bbox overlays, or loading/failed state. */
function DocumentImageView({
  docId,
  geometry,
  facts,
  active,
  onPick,
}: {
  docId: number;
  geometry: Geometry | undefined;
  facts: ExtractionRecord[];
  active: ExtractionRecord | null;
  onPick: (f: ExtractionRecord) => void;
}) {
  if (!geometry || geometry.status === "pending") {
    return (
      <div className="flex h-40 items-center justify-center gap-2 rounded-md border text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Extracting document geometry…
      </div>
    );
  }
  if (geometry.status === "failed") {
    return (
      <div className="rounded-md border p-3 text-xs text-destructive">
        Couldn't extract geometry ({geometry.errors?.[0]?.code ?? "error"}). Use the Text view.
      </div>
    );
  }
  return (
    <div className="max-h-[32rem] space-y-3 overflow-auto">
      {geometry.pages.map((p) => (
        <PageOverlay
          key={p.page}
          docId={docId}
          page={p.page}
          facts={facts}
          activeId={active?.id ?? null}
          onPick={onPick}
          scrollTo={active?.provenance.bbox?.page === p.page}
        />
      ))}
    </div>
  );
}

const CATEGORIES = ["office_visit", "diagnosis_hrv", "labs", "biopsy", "imaging", "other"];

function statusBadge(status: string): { variant: "secondary" | "destructive" | "outline"; className?: string } {
  if (status === "approved") return { variant: "secondary", className: "text-success" };
  if (status === "rejected") return { variant: "destructive" };
  if (status === "flagged") return { variant: "outline", className: "text-warning" };
  return { variant: "secondary" };
}

/** Phase 6 Review UI (design §6): parsed text with click-to-highlight on the
 * left; per-fact approve/reject/edit + add-a-fact on the right; verify. */
export function ReviewPanel({ docId, onClose }: { docId: number; onClose: () => void }) {
  const text = useDocumentText(docId);
  const facts = useDocumentExtractions(docId);
  const actions = useReviewActions(docId);

  const [active, setActive] = useState<ExtractionRecord | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [editJson, setEditJson] = useState("");
  const [category, setCategory] = useState("labs");

  // Document view: parsed text (default) or the image with bbox overlays (#70).
  const [docView, setDocView] = useState<"text" | "image">("text");
  const geometry = useGeometry(docId, docView === "image");
  const triggerGeom = useTriggerGeometry(docId);
  const showImage = () => {
    setDocView("image");
    if (geometry.data?.status !== "ready") triggerGeom.mutate(); // POST is a no-op if already ready
  };

  const [newSnippet, setNewSnippet] = useState("");
  const [newDomain, setNewDomain] = useState("labs");
  const [newPayload, setNewPayload] = useState('{"test_name": "", "value": "", "unit": ""}');

  const content = text.data?.content ?? "";
  const highlighted = useMemo(() => {
    if (!active) return content;
    const { char_start: s, char_end: e } = active.provenance;
    return [content.slice(0, s), content.slice(s, e), content.slice(e)];
  }, [content, active]);

  const useSelection = () => {
    const sel = window.getSelection()?.toString().trim();
    if (sel) setNewSnippet(sel);
    else toast.info("Select text in the document first");
  };

  const saveEdit = (f: ExtractionRecord) => {
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(editJson);
    } catch {
      toast.error("Invalid JSON");
      return;
    }
    actions.editFact.mutate(
      { id: f.id, payload },
      { onSuccess: () => { setEditId(null); toast.success("Fact updated"); } },
    );
  };

  const addFact = () => {
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(newPayload);
    } catch {
      toast.error("Invalid JSON payload");
      return;
    }
    actions.addFact.mutate(
      { document: docId, domain: newDomain, snippet: newSnippet, payload },
      {
        onSuccess: () => { setNewSnippet(""); toast.success("Fact added"); },
        onError: () => toast.error("Could not add fact (snippet must match the text)"),
      },
    );
  };

  const onVerify = () => {
    actions.verify.mutate(category, {
      onSuccess: () => toast.success("Document verified"),
      onError: (err) => {
        const status = (err as { response?: { status?: number } }).response?.status;
        toast.error(status === 409 ? "Resolve all staged/flagged facts first" : "Verify failed");
      },
    });
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Review · document #{docId}</CardTitle>
        <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose}>
          <X />
        </Button>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* left: document — parsed text with char highlight, or image with bbox overlays */}
          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <Button
                variant={docView === "text" ? "secondary" : "ghost"}
                size="sm"
                className="h-7"
                onClick={() => setDocView("text")}
              >
                <FileText className="size-3.5" />
                Text
              </Button>
              <Button
                variant={docView === "image" ? "secondary" : "ghost"}
                size="sm"
                className="h-7"
                onClick={showImage}
              >
                <ImageIcon className="size-3.5" />
                Document
              </Button>
            </div>

            {docView === "image" ? (
              <DocumentImageView
                docId={docId}
                geometry={geometry.data}
                facts={facts.data ?? []}
                active={active}
                onPick={setActive}
              />
            ) : (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs leading-relaxed">
                {Array.isArray(highlighted) ? (
                  <>
                    {highlighted[0]}
                    <mark className="rounded bg-warning/40 px-0.5">{highlighted[1]}</mark>
                    {highlighted[2]}
                  </>
                ) : (
                  highlighted || "(no text)"
                )}
              </pre>
            )}

            <div className="space-y-2 rounded-md border p-3">
              <Label>Add a fact</Label>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  className="w-56"
                  value={newSnippet}
                  onChange={(e) => setNewSnippet(e.target.value)}
                  placeholder="snippet (exact text)"
                />
                <Button variant="outline" size="sm" onClick={useSelection}>
                  Use selection
                </Button>
                <Select value={newDomain} onValueChange={(v) => setNewDomain(v ?? "labs")}>
                  <SelectTrigger className="w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Textarea
                className="h-16 font-mono text-xs"
                value={newPayload}
                onChange={(e) => setNewPayload(e.target.value)}
              />
              <Button size="sm" onClick={addFact}>
                Add fact
              </Button>
            </div>
          </div>

          {/* right: facts */}
          <div className="space-y-3">
            <ul className="space-y-1.5">
              {facts.data?.map((f) => {
                const sb = statusBadge(f.status);
                return (
                  <li
                    key={f.id}
                    className={cn(
                      "rounded-md border p-2 text-xs transition-colors",
                      active?.id === f.id && "border-warning ring-1 ring-warning/40",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <button className="flex items-center gap-1.5 text-left" onClick={() => setActive(f)}>
                        <Badge variant="secondary">{f.domain || f.extractor_key}</Badge>
                        <Badge variant={sb.variant} className={sb.className}>
                          {f.status}
                        </Badge>
                      </button>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7 text-success"
                          aria-label="Approve"
                          onClick={() =>
                            actions.editFact.mutate({ id: f.id, status: "approved" }, { onSuccess: () => toast.success("Approved") })
                          }
                        >
                          <Check />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7 text-destructive"
                          aria-label="Reject"
                          onClick={() =>
                            actions.editFact.mutate({ id: f.id, status: "rejected" }, { onSuccess: () => toast.success("Rejected") })
                          }
                        >
                          <X />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          aria-label="Edit"
                          onClick={() => {
                            setEditId(f.id);
                            setEditJson(JSON.stringify(f.payload, null, 0));
                          }}
                        >
                          <Pencil />
                        </Button>
                      </div>
                    </div>
                    {editId === f.id ? (
                      <div className="mt-2 space-y-1.5">
                        <Textarea
                          className="h-16 font-mono text-xs"
                          value={editJson}
                          onChange={(e) => setEditJson(e.target.value)}
                        />
                        <Button variant="outline" size="sm" onClick={() => saveEdit(f)}>
                          Save
                        </Button>
                      </div>
                    ) : (
                      <code className="mt-1 block break-all text-muted-foreground">
                        {JSON.stringify(f.payload)}
                      </code>
                    )}
                  </li>
                );
              })}
              {facts.data && facts.data.length === 0 && (
                <li className="text-xs text-muted-foreground">No facts.</li>
              )}
            </ul>

            <div className="flex items-center gap-2 border-t pt-3">
              <Select value={category} onValueChange={(v) => setCategory(v ?? "labs")}>
                <SelectTrigger className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button onClick={onVerify}>Verify document</Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
