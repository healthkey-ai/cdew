import { useMemo, useState } from "react";

import { type ExtractionRecord, useDocumentExtractions, useDocumentText } from "@/features/documents/api";
import { useReviewActions } from "./api";

const CATEGORIES = ["office_visit", "diagnosis_hrv", "labs", "biopsy", "imaging", "other"];
const STATUS_COLOR: Record<string, string> = {
  staged: "text-neutral-500",
  approved: "text-green-600",
  rejected: "text-red-500 line-through",
  flagged: "text-amber-600",
};

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
  const [verifyErr, setVerifyErr] = useState<string | null>(null);

  // add-fact form
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
  };

  const saveEdit = (f: ExtractionRecord) => {
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(editJson);
    } catch {
      return;
    }
    actions.editFact.mutate({ id: f.id, payload }, { onSuccess: () => setEditId(null) });
  };

  const addFact = () => {
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(newPayload);
    } catch {
      return;
    }
    actions.addFact.mutate(
      { document: docId, domain: newDomain, snippet: newSnippet, payload },
      { onSuccess: () => setNewSnippet("") },
    );
  };

  const onVerify = () => {
    setVerifyErr(null);
    actions.verify.mutate(category, {
      onError: (err) => {
        const status = (err as { response?: { status?: number } }).response?.status;
        setVerifyErr(status === 409 ? "Resolve all staged/flagged facts first." : "verify failed");
      },
    });
  };

  return (
    <section className="mt-4 rounded-lg border border-neutral-300 p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Review · doc#{docId}</h2>
        <button className="text-xs text-neutral-500 hover:underline" onClick={onClose}>close</button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-4">
        {/* left: parsed text with highlight */}
        <div>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-neutral-50 p-3 text-xs">
            {Array.isArray(highlighted) ? (
              <>
                {highlighted[0]}
                <mark className="bg-yellow-200">{highlighted[1]}</mark>
                {highlighted[2]}
              </>
            ) : (
              highlighted || "(no text)"
            )}
          </pre>
          <div className="mt-2 rounded border border-neutral-200 p-2 text-xs">
            <div className="font-medium">Add a fact</div>
            <div className="mt-1 flex flex-wrap items-center gap-1">
              <input
                className="w-56 rounded border border-neutral-300 px-1 py-0.5"
                value={newSnippet}
                onChange={(e) => setNewSnippet(e.target.value)}
                placeholder="snippet (exact text)"
              />
              <button className="rounded border px-1" onClick={useSelection}>use selection</button>
              <select className="rounded border border-neutral-300 px-1 py-0.5" value={newDomain} onChange={(e) => setNewDomain(e.target.value)}>
                {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <textarea
              className="mt-1 h-14 w-full rounded border border-neutral-300 p-1 font-mono"
              value={newPayload}
              onChange={(e) => setNewPayload(e.target.value)}
            />
            <button className="mt-1 rounded bg-neutral-900 px-2 py-0.5 text-white" onClick={addFact}>add fact</button>
          </div>
        </div>

        {/* right: facts */}
        <div className="text-xs">
          <ul className="space-y-1">
            {facts.data?.map((f) => (
              <li key={f.id} className={`rounded border p-2 ${active?.id === f.id ? "border-yellow-400" : "border-neutral-100"}`}>
                <div className="flex items-center justify-between">
                  <button className="text-left" onClick={() => setActive(f)}>
                    <span className="mr-1 rounded bg-neutral-100 px-1">{f.domain || f.extractor_key}</span>
                    <span className={STATUS_COLOR[f.status]}>{f.status}</span>
                  </button>
                  <span className="flex gap-1">
                    <button className="rounded border border-green-300 px-1 text-green-700"
                      onClick={() => actions.editFact.mutate({ id: f.id, status: "approved" })}>✓</button>
                    <button className="rounded border border-red-300 px-1 text-red-600"
                      onClick={() => actions.editFact.mutate({ id: f.id, status: "rejected" })}>✗</button>
                    <button className="rounded border px-1"
                      onClick={() => { setEditId(f.id); setEditJson(JSON.stringify(f.payload, null, 0)); }}>edit</button>
                  </span>
                </div>
                {editId === f.id ? (
                  <div className="mt-1">
                    <textarea className="h-12 w-full rounded border border-neutral-300 p-1 font-mono"
                      value={editJson} onChange={(e) => setEditJson(e.target.value)} />
                    <button className="mt-1 rounded border px-2" onClick={() => saveEdit(f)}>save</button>
                  </div>
                ) : (
                  <code className="mt-1 block text-neutral-600">{JSON.stringify(f.payload)}</code>
                )}
              </li>
            ))}
            {facts.data && facts.data.length === 0 && <li className="text-neutral-500">no facts</li>}
          </ul>

          <div className="mt-3 flex items-center gap-2">
            <select className="rounded border border-neutral-300 px-1 py-0.5" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
            <button className="rounded bg-green-700 px-2 py-1 text-white" onClick={onVerify}>Verify document</button>
            {verifyErr && <span className="text-red-600">{verifyErr}</span>}
          </div>
        </div>
      </div>
    </section>
  );
}
