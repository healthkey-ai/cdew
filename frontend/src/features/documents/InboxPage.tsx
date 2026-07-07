import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useJob } from "@/features/pipeline/api";
import { ReviewPanel } from "@/features/review/ReviewPanel";
import { useDocumentExtractions, useDocuments, useDocumentText, useUploadDocument } from "./api";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "needs_classification", label: "Needs classification" },
  { value: "classified", label: "Classified" },
  { value: "parse_failed", label: "Parse failed" },
];

/** Inbox queue (design §3): upload a document (runs the extract-document flow),
 * poll the job, browse the queue, and open a document to view text / review. */
export function InboxPage() {
  const qc = useQueryClient();
  const [patientRef, setPatientRef] = useState("PT-001");
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [reviewDoc, setReviewDoc] = useState<number | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const docs = useDocuments(patientRef || undefined, statusFilter || undefined);
  const text = useDocumentText(selected);
  const extractions = useDocumentExtractions(selected);
  const upload = useUploadDocument();
  const job = useJob(jobId);
  const jobStatus = job.data?.status;

  // Refresh the queue when the job reaches a terminal state.
  useEffect(() => {
    if (jobStatus === "completed" || jobStatus === "failed") {
      qc.invalidateQueries({ queryKey: ["documents"] });
    }
  }, [jobStatus, qc]);

  const onUpload = (e: React.FormEvent) => {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file || !patientRef) return;
    upload.mutate(
      { file, patientRef },
      {
        onSuccess: (d) => {
          setJobId(d.job_id ?? null);
          if (fileRef.current) fileRef.current.value = "";
        },
      },
    );
  };

  return (
    <section>
      <h1 className="text-lg font-semibold">Inbox</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Upload clinical documents; each runs ingest → parse → classify → extract, then lands in the
        queue for review.
      </p>

      {/* upload */}
      <form
        onSubmit={onUpload}
        className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 p-4"
      >
        <input
          className="rounded border border-neutral-300 px-2 py-1 text-sm"
          value={patientRef}
          onChange={(e) => setPatientRef(e.target.value)}
          placeholder="patient_ref"
        />
        <input ref={fileRef} type="file" className="text-sm" />
        <button
          type="submit"
          disabled={upload.isPending}
          className="rounded bg-neutral-900 px-3 py-1 text-sm text-white disabled:opacity-50"
        >
          {upload.isPending ? "uploading…" : "Upload"}
        </button>
        {upload.isError && <span className="text-sm text-red-600">upload failed</span>}
        {upload.data && (
          <span className="text-sm text-neutral-500">
            {upload.data.deduplicated ? "deduplicated → existing" : "uploaded"}
            {job.data && ` · job ${job.data.stage}/${job.data.status}`}
          </span>
        )}
      </form>

      {/* filters */}
      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        <input
          className="rounded border border-neutral-300 px-2 py-1"
          value={patientRef}
          onChange={(e) => setPatientRef(e.target.value)}
          placeholder="filter patient_ref"
        />
        <select
          className="rounded border border-neutral-300 px-2 py-1"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {STATUS_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>

      {/* queue */}
      <table className="mt-3 w-full text-left text-sm">
        <thead className="text-neutral-500">
          <tr>
            <th className="py-1">file</th>
            <th>status</th>
            <th>classification</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {docs.data?.results.map((d) => (
            <tr key={d.id} className="border-t border-neutral-100">
              <td className="py-1">{d.original_filename || `doc#${d.id}`}</td>
              <td>
                {d.status}
                {d.verified && <span className="ml-1 text-green-600">✓ verified</span>}
              </td>
              <td className="text-neutral-500">
                {!d.classification
                  ? "—"
                  : d.classification.outcome === "routed"
                    ? d.classification.routed_types.join(", ")
                    : `unclassified (${d.classification.reason})`}
              </td>
              <td className="space-x-2">
                {d.has_text && (
                  <button className="text-blue-600 hover:underline" onClick={() => setSelected(d.id)}>
                    view text
                  </button>
                )}
                {d.has_text && (
                  <button className="text-blue-600 hover:underline" onClick={() => setReviewDoc(d.id)}>
                    review
                  </button>
                )}
              </td>
            </tr>
          ))}
          {docs.data && docs.data.results.length === 0 && (
            <tr>
              <td colSpan={4} className="py-2 text-neutral-500">
                no documents match this filter
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {selected != null && (
        <div className="mt-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Parsed text · doc#{selected}</h3>
            <button className="text-xs text-neutral-500 hover:underline" onClick={() => setSelected(null)}>
              close
            </button>
          </div>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-neutral-50 p-3 text-xs">
            {text.isPending ? "loading…" : text.data?.content || "(empty)"}
          </pre>

          <h3 className="mt-3 text-sm font-semibold">
            Extracted facts{extractions.data ? ` (${extractions.data.length})` : ""}
          </h3>
          <ul className="mt-1 space-y-1 text-xs">
            {extractions.data?.map((f) => (
              <li key={f.id} className="rounded border border-neutral-100 p-2">
                <span className="mr-2 rounded bg-neutral-100 px-1">{f.domain || f.extractor_key}</span>
                {f.status !== "staged" && <span className="mr-2 text-amber-600">[{f.status}]</span>}
                <code>{JSON.stringify(f.payload)}</code>
                <div className="mt-0.5 text-neutral-500">“{f.provenance.snippet}”</div>
              </li>
            ))}
            {extractions.data && extractions.data.length === 0 && (
              <li className="text-neutral-500">no extracted facts</li>
            )}
          </ul>
        </div>
      )}

      {reviewDoc != null && <ReviewPanel docId={reviewDoc} onClose={() => setReviewDoc(null)} />}
    </section>
  );
}
