import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Upload, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useJob } from "@/features/pipeline/api";
import { ReviewPanel } from "@/features/review/ReviewPanel";
import { type SourceDocument } from "./api";
import { useDocumentExtractions, useDocuments, useDocumentText, useUploadDocument } from "./api";

const STATUS_FILTERS = [
  { value: "all", label: "All statuses" },
  { value: "needs_classification", label: "Needs classification" },
  { value: "classified", label: "Classified" },
  { value: "parse_failed", label: "Parse failed" },
];

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "parse_failed") return "destructive";
  if (status === "needs_classification") return "outline";
  if (status === "classified") return "secondary";
  return "secondary";
}

function classificationText(d: SourceDocument) {
  if (!d.classification) return "—";
  return d.classification.outcome === "routed"
    ? d.classification.routed_types.join(", ")
    : `unclassified · ${d.classification.reason}`;
}

/** Inbox queue (design §3): upload a document (runs the extract-document flow),
 * poll the job, browse the queue, and open a document to view text / review. */
export function InboxPage() {
  const qc = useQueryClient();
  const [patientRef, setPatientRef] = useState("PT-001");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [reviewDoc, setReviewDoc] = useState<number | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const docs = useDocuments(patientRef || undefined, statusFilter === "all" ? undefined : statusFilter);
  const text = useDocumentText(selected);
  const extractions = useDocumentExtractions(selected);
  const upload = useUploadDocument();
  const job = useJob(jobId);
  const jobStatus = job.data?.status;

  // Refresh the queue + notify when the job reaches a terminal state.
  useEffect(() => {
    if (jobStatus === "completed") {
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast.success("Document processed");
    } else if (jobStatus === "failed") {
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast.error("Processing failed");
    }
  }, [jobStatus, qc]);

  const onUpload = (e: React.FormEvent) => {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file || !patientRef) {
      toast.error("Pick a file and a patient_ref first");
      return;
    }
    upload.mutate(
      { file, patientRef },
      {
        onSuccess: (d) => {
          setJobId(d.job_id ?? null);
          if (fileRef.current) fileRef.current.value = "";
          toast.info(d.deduplicated ? "Deduplicated to existing document" : "Uploaded — processing…");
        },
        onError: () => toast.error("Upload failed"),
      },
    );
  };

  const rows = docs.data?.results ?? [];

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Inbox</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload clinical documents; each runs ingest → parse → classify → extract, then lands in the
          queue for review.
        </p>
      </div>

      {/* upload */}
      <Card>
        <CardHeader>
          <CardTitle>Upload</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onUpload} className="flex flex-wrap items-center gap-2">
            <Input
              className="h-9 w-40"
              value={patientRef}
              onChange={(e) => setPatientRef(e.target.value)}
              placeholder="patient_ref"
            />
            <Input ref={fileRef} type="file" className="h-9 w-auto py-1.5" />
            <Button type="submit" disabled={upload.isPending}>
              {upload.isPending ? <Loader2 className="animate-spin" /> : <Upload />}
              {upload.isPending ? "Uploading…" : "Upload"}
            </Button>
            {job.data && jobId != null && (
              <Badge variant="outline" className="font-normal">
                job · {job.data.stage}/{job.data.status}
              </Badge>
            )}
          </form>
        </CardContent>
      </Card>

      {/* queue */}
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <CardTitle>Queue</CardTitle>
          <div className="flex items-center gap-2">
            <Input
              className="h-8 w-36"
              value={patientRef}
              onChange={(e) => setPatientRef(e.target.value)}
              placeholder="filter patient_ref"
            />
            <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v ?? "all")}>
              <SelectTrigger className="h-8 w-48">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_FILTERS.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>File</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Classification</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.isPending &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 4 }).map((__, j) => (
                      <TableCell key={j}>
                        <Skeleton className="h-4 w-24" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              {rows.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-medium">{d.original_filename || `doc#${d.id}`}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      <Badge variant={statusVariant(d.status)}>{d.status}</Badge>
                      {d.verified && <Badge variant="secondary">✓ verified</Badge>}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{classificationText(d)}</TableCell>
                  <TableCell className="text-right">
                    {d.has_text && (
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setSelected(d.id)}>
                          text
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setReviewDoc(d.id)}>
                          review
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {!docs.isPending && rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                    No documents match this filter.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* parsed text + facts */}
      {selected != null && (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle>Document #{selected}</CardTitle>
            <Button variant="ghost" size="icon" aria-label="Close" onClick={() => setSelected(null)}>
              <X />
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">Parsed text</div>
              {text.isPending ? (
                <Skeleton className="h-40 w-full" />
              ) : (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                  {text.data?.content || "(empty)"}
                </pre>
              )}
            </div>
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">
                Extracted facts{extractions.data ? ` (${extractions.data.length})` : ""}
              </div>
              <ul className="space-y-1.5">
                {extractions.data?.map((f) => (
                  <li key={f.id} className="rounded-md border p-2 text-xs">
                    <div className="flex items-center gap-1.5">
                      <Badge variant="secondary">{f.domain || f.extractor_key}</Badge>
                      {f.status !== "staged" && <Badge variant="outline">{f.status}</Badge>}
                    </div>
                    <code className="mt-1 block break-all">{JSON.stringify(f.payload)}</code>
                    <div className="mt-0.5 text-muted-foreground">“{f.provenance.snippet}”</div>
                  </li>
                ))}
                {extractions.data && extractions.data.length === 0 && (
                  <li className="text-xs text-muted-foreground">No extracted facts.</li>
                )}
              </ul>
            </div>
          </CardContent>
        </Card>
      )}

      {reviewDoc != null && <ReviewPanel docId={reviewDoc} onClose={() => setReviewDoc(null)} />}
    </section>
  );
}
