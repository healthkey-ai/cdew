import { useEffect, useMemo, useState } from "react";

import { type PromptVersion, usePromptActions, usePromptDefinitions, usePromptVersions } from "@/features/prompts/api";
import { VersionToolbar } from "@/features/prompts/VersionToolbar";

interface TaxRow {
  type: string;
  description: string;
  threshold: number;
}

const EMPTY_ROW: TaxRow = { type: "", description: "", threshold: 0.5 };

function toRows(taxonomy: unknown[]): TaxRow[] {
  return (taxonomy as Partial<TaxRow>[]).map((t) => ({
    type: t.type ?? "",
    description: t.description ?? "",
    threshold: typeof t.threshold === "number" ? t.threshold : 0.5,
  }));
}

/** Taxonomies (design §8): the classifier's prompt + the list of document types
 * it scores. Each row is a type with the description that guides classification
 * and the confidence threshold to route it. */
export function TaxonomiesPage() {
  const defs = usePromptDefinitions();
  const classifiers = useMemo(() => defs.data?.filter((d) => d.kind === "classifier") ?? [], [defs.data]);
  const [defId, setDefId] = useState<number | null>(null);

  // Default to the (usually single) classifier definition.
  useEffect(() => {
    if (defId == null && classifiers.length) setDefId(classifiers[0].id);
  }, [classifiers, defId]);

  const def = classifiers.find((d) => d.id === defId) ?? null;
  const versions = usePromptVersions(defId);
  const actions = usePromptActions(defId);

  const [selVersion, setSelVersion] = useState<PromptVersion | null>(null);
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("");
  const [rows, setRows] = useState<TaxRow[]>([]);

  // Default the selected version to the active one (or the latest).
  useEffect(() => {
    if (!versions.data?.length) return;
    if (selVersion && versions.data.some((v) => v.id === selVersion.id)) return;
    const active = versions.data.find((v) => v.id === def?.active_version?.id);
    setSelVersion(active ?? versions.data[versions.data.length - 1]);
  }, [versions.data, def?.active_version?.id, selVersion]);

  // Load the selected version into the editor.
  useEffect(() => {
    if (!selVersion) return;
    setPrompt(selVersion.prompt_text);
    setModel(selVersion.model);
    setRows(toRows(selVersion.taxonomy));
  }, [selVersion]);

  const isDraft = selVersion?.status === "draft";

  const setRow = (i: number, patch: Partial<TaxRow>) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const onSave = () => {
    if (!selVersion) return;
    actions.saveDraft.mutate(
      { id: selVersion.id, prompt_text: prompt, model, taxonomy: rows },
      { onSuccess: (v) => setSelVersion(v) },
    );
  };

  if (!classifiers.length) {
    return <p className="text-sm text-neutral-500">No classifier definition found.</p>;
  }

  return (
    <section>
      <h1 className="text-lg font-semibold">Taxonomies</h1>
      <p className="mt-1 text-sm text-neutral-500">
        The document types the classifier scores. Edit the classification prompt and each type’s
        description + routing threshold, then publish a new version.
      </p>

      {classifiers.length > 1 && (
        <div className="mt-3 flex gap-1">
          {classifiers.map((c) => (
            <button
              key={c.id}
              onClick={() => {
                setDefId(c.id);
                setSelVersion(null);
              }}
              className={`rounded px-2 py-1 text-sm ${c.id === defId ? "bg-neutral-100 font-medium" : ""}`}
            >
              {c.key}
            </button>
          ))}
        </div>
      )}

      {def && (
        <div className="mt-4 space-y-4">
          <VersionToolbar
            def={def}
            versions={versions.data}
            selVersion={selVersion}
            onSelect={setSelVersion}
            actions={actions}
            onSave={onSave}
            canSave={isDraft}
          />

          {selVersion && (
            <>
              <div>
                <label className="mb-1 block text-xs text-neutral-500">classification prompt</label>
                <textarea
                  className="h-24 w-full rounded border border-neutral-300 p-2 font-mono text-xs"
                  value={prompt}
                  disabled={!isDraft}
                  onChange={(e) => setPrompt(e.target.value)}
                />
              </div>

              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="text-xs text-neutral-500">types</label>
                  {isDraft && (
                    <button
                      className="rounded border px-2 py-0.5 text-xs"
                      onClick={() => setRows((rs) => [...rs, { ...EMPTY_ROW }])}
                    >
                      + type
                    </button>
                  )}
                </div>
                <table className="w-full text-left text-xs">
                  <thead className="text-neutral-500">
                    <tr>
                      <th className="py-1 pr-2">type (slug)</th>
                      <th className="pr-2">description (how to classify it)</th>
                      <th className="pr-2">threshold</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className="border-t border-neutral-100 align-top">
                        <td className="py-1 pr-2">
                          <input
                            className="w-32 rounded border border-neutral-300 px-1 py-0.5 font-mono"
                            value={r.type}
                            disabled={!isDraft}
                            onChange={(e) => setRow(i, { type: e.target.value })}
                            placeholder="lab_report"
                          />
                        </td>
                        <td className="pr-2">
                          <textarea
                            className="h-10 w-full rounded border border-neutral-300 px-1 py-0.5"
                            value={r.description}
                            disabled={!isDraft}
                            onChange={(e) => setRow(i, { description: e.target.value })}
                          />
                        </td>
                        <td className="pr-2">
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.05}
                            className="w-16 rounded border border-neutral-300 px-1 py-0.5"
                            value={r.threshold}
                            disabled={!isDraft}
                            onChange={(e) => setRow(i, { threshold: Number(e.target.value) })}
                          />
                        </td>
                        <td>
                          {isDraft && (
                            <button
                              className="text-red-500 hover:underline"
                              onClick={() => setRows((rs) => rs.filter((_, idx) => idx !== i))}
                            >
                              remove
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {rows.length === 0 && (
                      <tr>
                        <td colSpan={4} className="py-2 text-neutral-500">
                          no types yet
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div>
                <label className="mb-1 block text-xs text-neutral-500">model</label>
                <input
                  className="rounded border border-neutral-300 px-2 py-1 text-xs"
                  value={model}
                  disabled={!isDraft}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="gemini-2.5-flash"
                />
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
