import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Check, FileText, Image as ImageIcon, Loader2, Plus, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  type ExtractionRecord,
  type Geometry,
  useDocument,
  useDocumentExtractions,
  useDocumentText,
  useGeometry,
  useTriggerGeometry,
} from "@/features/documents/api";
import { isJobActive, useJobs } from "@/features/workflow/api";
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

/** Vertical center (0..1) of a fact's dominant bbox cluster on a page. A fact's
 * boxes usually share one row; if a stray box lands elsewhere, cluster by y and
 * take the largest group so we scroll to where the boxes actually cluster. */
function clusterCenterY(rects: number[][]): number {
  const ys = rects.map((r) => (r[1] + r[3]) / 2).sort((a, b) => a - b);
  if (ys.length === 0) return 0;
  const GAP = 0.05; // > one row-height apart → a separate cluster
  let bestStart = 0;
  let bestLen = 1;
  let curStart = 0;
  for (let i = 1; i <= ys.length; i++) {
    if (i === ys.length || ys[i] - ys[i - 1] > GAP) {
      if (i - curStart > bestLen) {
        bestLen = i - curStart;
        bestStart = curStart;
      }
      curStart = i;
    }
  }
  const cluster = ys.slice(bestStart, bestStart + bestLen);
  return cluster.reduce((a, b) => a + b, 0) / cluster.length;
}

/** One page image with SVG bbox overlays. Normalized boxes (0..1) map to the
 * image via a 0 0 1 1 viewBox. Click a box → select the fact. */
function PageOverlay({
  docId,
  page,
  facts,
  active,
  onPick,
}: {
  docId: number;
  page: number;
  facts: ExtractionRecord[];
  active: ExtractionRecord | null;
  onPick: (f: ExtractionRecord) => void;
}) {
  const url = usePageImageUrl(docId, page);
  const anchorRef = useRef<HTMLDivElement>(null);
  const activeBox = active?.provenance.bbox?.page === page ? active?.provenance.bbox : null;
  const anchorY = activeBox ? clusterCenterY(activeBox.rects) : 0;
  // Scroll the active fact's cluster into view on every selection change — even
  // when the next fact is on the same page (a per-page flag wouldn't re-fire).
  useEffect(() => {
    if (activeBox) anchorRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [active?.id, activeBox, anchorY]);
  const pageFacts = facts.filter((f) => f.provenance.bbox?.page === page);
  return (
    <div className="relative overflow-hidden rounded border bg-white">
      {activeBox && (
        <div ref={anchorRef} className="pointer-events-none absolute" style={{ top: `${anchorY * 100}%` }} />
      )}
      {url ? (
        <img src={url} alt={`page ${page}`} className="block w-full" />
      ) : (
        <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">loading page {page}…</div>
      )}
      <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        {pageFacts.flatMap((f) => {
          const isActive = active?.id === f.id;
          const pad = isActive ? 0.005 : 0; // grow the selected box a few px so it doesn't clip the text
          return (f.provenance.bbox?.rects ?? []).map((r, i) => (
            <rect
              key={`${f.id}-${i}`}
              x={r[0] - pad}
              y={r[1] - pad}
              width={Math.max(0, r[2] - r[0]) + pad * 2}
              height={Math.max(0, r[3] - r[1]) + pad * 2}
              vectorEffect="non-scaling-stroke"
              strokeWidth={isActive ? 2.5 : 1.5}
              onClick={() => onPick(f)}
              className={cn(
                "cursor-pointer transition-colors",
                isActive
                  ? "fill-transparent stroke-warning"
                  : "fill-transparent stroke-transparent hover:fill-primary/10 hover:stroke-primary/50",
              )}
            />
          ));
        })}
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
    <div className="min-h-0 flex-1 space-y-3 overflow-auto">
      {geometry.pages.map((p) => (
        <PageOverlay key={p.page} docId={docId} page={p.page} facts={facts} active={active} onPick={onPick} />
      ))}
    </div>
  );
}

const CATEGORIES = ["office_visit", "diagnosis_hrv", "labs", "biopsy", "imaging", "other"];

// Fallback fields per type when the document has no existing fact of that type to
// mirror. When it does, the Add-a-fact form uses that fact's field set instead.
const FIELD_TEMPLATES: Record<string, string[]> = {
  labs: ["test_name", "value", "unit", "ref_low", "ref_high", "abnormal_flag", "collected_date"],
  imaging: ["modality", "body_site", "finding", "impression"],
  office_visit: ["assessment", "plan"],
  diagnosis_hrv: ["condition", "status", "date"],
  biopsy: ["site", "diagnosis", "result"],
  other: ["name", "value"],
};

function statusBadge(status: string): { variant: "secondary" | "destructive" | "outline"; className?: string } {
  if (status === "approved") return { variant: "secondary", className: "text-success" };
  if (status === "rejected") return { variant: "destructive" };
  if (status === "flagged") return { variant: "outline", className: "text-warning" };
  return { variant: "secondary" };
}

/** One fact rendered as an editable form card (labeled fields, not raw JSON).
 * Selecting the card highlights its provenance on the document. */
function FactCard({
  fact,
  active,
  saving,
  showNotLocated,
  onSelect,
  onSave,
  onApprove,
  onReject,
}: {
  fact: ExtractionRecord;
  active: boolean;
  saving: boolean;
  showNotLocated: boolean;
  onSelect: () => void;
  onSave: (payload: Record<string, unknown>) => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const [draft, setDraft] = useState<Record<string, unknown>>(fact.payload);
  const dirty = JSON.stringify(draft) !== JSON.stringify(fact.payload);
  const sb = statusBadge(fact.status);

  const setField = (key: string, raw: string) => {
    const orig = fact.payload[key];
    let value: unknown = raw;
    if (typeof orig === "number") value = raw.trim() === "" ? null : Number(raw);
    if (typeof value === "number" && Number.isNaN(value)) value = raw; // keep unparseable input as text
    setDraft((d) => ({ ...d, [key]: value }));
  };

  return (
    <li
      onClick={onSelect}
      className={cn(
        "cursor-pointer rounded-md border p-2.5 transition-colors hover:border-warning/60",
        active && "border-warning ring-1 ring-warning/40",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Badge variant="secondary">{fact.domain || fact.extractor_key}</Badge>
          <Badge variant={sb.variant} className={sb.className}>
            {fact.status}
          </Badge>
          {showNotLocated && <span className="text-[10px] text-muted-foreground">not located</span>}
        </div>
        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
          <Button
            variant="ghost"
            size="icon"
            className={cn("size-7 text-success", fact.status === "approved" && "bg-success/15 ring-1 ring-success/40")}
            aria-label={fact.status === "approved" ? "Undo approve" : "Approve"}
            aria-pressed={fact.status === "approved"}
            onClick={onApprove}
          >
            <Check />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              "size-7 text-destructive",
              fact.status === "rejected" && "bg-destructive/15 ring-1 ring-destructive/40",
            )}
            aria-label={fact.status === "rejected" ? "Undo reject" : "Reject"}
            aria-pressed={fact.status === "rejected"}
            onClick={onReject}
          >
            <X />
          </Button>
        </div>
      </div>

      {/* No stopPropagation: clicking a field also selects the fact (shows its bboxes). */}
      <div className="mt-2 space-y-1">
        {Object.keys(draft).length === 0 && <p className="text-xs text-muted-foreground">No fields.</p>}
        {Object.entries(draft).map(([key, value]) => (
          <div key={key} className="grid grid-cols-[7.5rem_1fr] items-center gap-2">
            <Label htmlFor={`f${fact.id}-${key}`} className="truncate text-[11px] font-normal text-muted-foreground">
              {key}
            </Label>
            <Input
              id={`f${fact.id}-${key}`}
              className="h-7 text-xs"
              value={value == null ? "" : String(value)}
              onChange={(e) => setField(key, e.target.value)}
            />
          </div>
        ))}
        {dirty && (
          <Button variant="outline" size="sm" className="mt-1 h-7" disabled={saving} onClick={() => onSave(draft)}>
            Save changes
          </Button>
        )}
      </div>
    </li>
  );
}

/** Phase 6 Review UI (design §6): the document (image with bbox overlays by
 * default, or parsed text) beside per-fact editable form cards; verify. */
export function ReviewPanel({ docId }: { docId: number }) {
  const doc = useDocument(docId);
  const text = useDocumentText(docId);
  const facts = useDocumentExtractions(docId);
  const actions = useReviewActions(docId);
  const name = doc.data?.original_filename || `Document #${docId}`;
  const verified = doc.data?.verified ?? false;

  const [active, setActive] = useState<ExtractionRecord | null>(null);

  // Document view: the image with bbox overlays (default, #70) or the parsed text.
  const [docView, setDocView] = useState<"image" | "text">("image");
  const geometry = useGeometry(docId, docView === "image");
  const triggerGeom = useTriggerGeometry(docId);
  // Compute geometry on demand when the Document (image) view is shown and it
  // isn't ready/pending yet — including on first mount, since image is default.
  useEffect(() => {
    if (
      docView === "image" &&
      triggerGeom.isIdle &&
      geometry.data?.status !== "ready" &&
      geometry.data?.status !== "pending"
    ) {
      triggerGeom.mutate();
    }
  }, [docView, geometry.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Geometry populates each fact's bbox server-side; refetch the extractions once
  // it's ready so the overlay picks up the boxes without needing a manual edit.
  const qc = useQueryClient();
  const geomStatus = geometry.data?.status;
  useEffect(() => {
    if (geomStatus === "ready") {
      qc.invalidateQueries({ queryKey: ["documents", docId, "extractions"] });
    }
  }, [geomStatus, docId, qc]);

  // Facts are written at the end of the extraction run. If the panel is opened
  // mid-run, refetch when this doc's job finishes so they appear without a reload.
  const jobs = useJobs();
  const job = jobs.data?.find((j) => j.document === docId);
  const extracting = job ? isJobActive(job.status) : false;
  useEffect(() => {
    if (job && !isJobActive(job.status)) {
      qc.invalidateQueries({ queryKey: ["documents", docId, "extractions"] });
    }
  }, [job?.status, docId, qc]); // eslint-disable-line react-hooks/exhaustive-deps

  const [addOpen, setAddOpen] = useState(false);
  const [newSnippet, setNewSnippet] = useState("");
  const [newDomain, setNewDomain] = useState("labs");
  const [newFields, setNewFields] = useState<Record<string, string>>({});

  // A representative existing fact of the chosen type (its fields become the form,
  // and its value types drive number coercion on submit).
  const sampleFor = (domain: string) =>
    facts.data?.find((f) => (f.domain || f.extractor_key) === domain)?.payload;
  const fieldsForDomain = (domain: string): string[] => {
    const sample = sampleFor(domain);
    if (sample && Object.keys(sample).length) return Object.keys(sample);
    return FIELD_TEMPLATES[domain] ?? ["name", "value"];
  };
  // Reset the form fields to the type's template whenever the dialog opens or the
  // type changes.
  useEffect(() => {
    if (addOpen) setNewFields(Object.fromEntries(fieldsForDomain(newDomain).map((k) => [k, ""])));
  }, [addOpen, newDomain]); // eslint-disable-line react-hooks/exhaustive-deps

  const openAdd = () => {
    const sel = window.getSelection()?.toString().trim();
    if (sel) setNewSnippet(sel); // pre-fill from any current document selection
    setAddOpen(true);
  };

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

  const addFact = () => {
    const sample = sampleFor(newDomain);
    const payload: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(newFields)) {
      const numeric = sample && typeof sample[k] === "number";
      if (v.trim() === "") payload[k] = numeric ? null : "";
      else payload[k] = numeric && !Number.isNaN(Number(v)) ? Number(v) : v;
    }
    actions.addFact.mutate(
      { document: docId, domain: newDomain, snippet: newSnippet, payload },
      {
        onSuccess: () => {
          setAddOpen(false);
          setNewSnippet("");
          toast.success("Fact added");
        },
        onError: () => toast.error("Could not add fact (snippet must match the text)"),
      },
    );
  };

  const onVerifyToggle = () => {
    if (verified) {
      actions.unverify.mutate(undefined, { onSuccess: () => toast.success("Verification undone") });
      return;
    }
    actions.verify.mutate(undefined, {
      onSuccess: () => toast.success("Document verified"),
      onError: (err) => {
        const status = (err as { response?: { status?: number } }).response?.status;
        toast.error(status === 409 ? "Resolve all staged/flagged facts first" : "Verify failed");
      },
    });
  };

  return (
    <Card>
      <CardContent>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="truncate text-base font-semibold tracking-tight">
            Reviewing · <span className="font-normal text-muted-foreground">{name}</span>
          </h2>
          <Button
            size="sm"
            variant={verified ? "outline" : "default"}
            className={cn("shrink-0", verified && "border-success/50 text-success")}
            aria-pressed={verified}
            disabled={actions.verify.isPending || actions.unverify.isPending}
            onClick={onVerifyToggle}
          >
            <Check className="size-4" />
            {verified ? "Verified" : "Verify"}
          </Button>
        </div>
        <div className="grid grid-cols-1 gap-4 lg:h-[calc(100vh-15rem)] lg:grid-cols-[360px_1fr]">
          {/* left: facts as editable form cards + verify */}
          <div className="flex min-h-0 flex-col gap-3">
            <div className="flex shrink-0 items-center justify-between">
              <h3 className="text-sm font-semibold">Facts{facts.data ? ` (${facts.data.length})` : ""}</h3>
              <Button variant="outline" size="sm" className="h-8" onClick={openAdd}>
                <Plus className="size-4" /> Add fact
              </Button>
            </div>
            <ul className="min-h-0 flex-1 space-y-2 overflow-auto pr-1">
              {facts.data?.map((f) => (
                <FactCard
                  key={f.id}
                  fact={f}
                  active={active?.id === f.id}
                  saving={actions.editFact.isPending}
                  showNotLocated={docView === "image" && !f.provenance.bbox}
                  onSelect={() => setActive(f)}
                  onSave={(payload) =>
                    actions.editFact.mutate({ id: f.id, payload }, { onSuccess: () => toast.success("Fact updated") })
                  }
                  onApprove={() => {
                    const undo = f.status === "approved";
                    actions.editFact.mutate(
                      { id: f.id, status: undo ? "staged" : "approved" },
                      { onSuccess: () => toast.success(undo ? "Approval undone" : "Approved") },
                    );
                  }}
                  onReject={() => {
                    const undo = f.status === "rejected";
                    actions.editFact.mutate(
                      { id: f.id, status: undo ? "staged" : "rejected" },
                      { onSuccess: () => toast.success(undo ? "Rejection undone" : "Rejected") },
                    );
                  }}
                />
              ))}
              {facts.data && facts.data.length === 0 && (
                <li className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  {extracting && <Loader2 className="size-3 animate-spin" />}
                  {extracting ? "Extracting facts…" : "No facts."}
                </li>
              )}
            </ul>
          </div>

          {/* right: document — image with bbox overlays (default) or parsed text */}
          <div className="flex min-h-0 flex-col gap-2">
            <div className="flex shrink-0 items-center gap-1">
              <Button
                variant={docView === "image" ? "secondary" : "ghost"}
                size="sm"
                className="h-7"
                onClick={() => setDocView("image")}
              >
                <ImageIcon className="size-3.5" />
                Document
              </Button>
              <Button
                variant={docView === "text" ? "secondary" : "ghost"}
                size="sm"
                className="h-7"
                onClick={() => setDocView("text")}
              >
                <FileText className="size-3.5" />
                Text
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
              <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs leading-relaxed">
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
          </div>
        </div>

        <Dialog open={addOpen} onOpenChange={setAddOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add a fact</DialogTitle>
              <DialogDescription>
                Manually add a fact grounded in a verbatim snippet from the document.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              <div className="grid grid-cols-[6rem_1fr] items-center gap-2">
                <Label>Type</Label>
                <Select value={newDomain} onValueChange={(v) => setNewDomain(v ?? "labs")}>
                  <SelectTrigger>
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

              <div className="grid grid-cols-[6rem_1fr] items-start gap-2">
                <Label className="pt-2">Snippet</Label>
                <div className="space-y-1.5">
                  <Input
                    value={newSnippet}
                    onChange={(e) => setNewSnippet(e.target.value)}
                    placeholder="exact text from the document"
                  />
                  <Button variant="outline" size="sm" onClick={useSelection}>
                    Use selection
                  </Button>
                </div>
              </div>

              <div className="space-y-1.5 border-t pt-3">
                {Object.entries(newFields).map(([key, value]) => (
                  <div key={key} className="grid grid-cols-[6rem_1fr] items-center gap-2">
                    <Label htmlFor={`new-${key}`} className="truncate text-xs font-normal text-muted-foreground">
                      {key}
                    </Label>
                    <Input
                      id={`new-${key}`}
                      className="h-8"
                      value={value}
                      onChange={(e) => setNewFields((s) => ({ ...s, [key]: e.target.value }))}
                    />
                  </div>
                ))}
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => setAddOpen(false)}>
                Cancel
              </Button>
              <Button onClick={addFact} disabled={actions.addFact.isPending || !newSnippet.trim()}>
                Add fact
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
