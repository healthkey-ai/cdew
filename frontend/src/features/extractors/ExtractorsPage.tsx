import { useEffect, useMemo, useState } from "react";

import { type PromptVersion, usePromptActions, usePromptDefinitions, usePromptVersions } from "@/features/prompts/api";
import { VersionToolbar } from "@/features/prompts/VersionToolbar";
import { type AttrRow, ATTR_TYPES, rowsToSchema, schemaToRows } from "./schema";

const EMPTY_ROW: AttrRow = { name: "", type: "string", description: "", required: false, nullable: false };

/** Extractors (design §8): one extractor per document domain. Each has an
 * extraction prompt and a list of attributes to pull out — every attribute is a
 * field of the `data` schema, with the description that guides its extraction. */
export function ExtractorsPage() {
  const defs = usePromptDefinitions();
  const extractors = useMemo(() => defs.data?.filter((d) => d.kind === "extractor") ?? [], [defs.data]);
  const [defId, setDefId] = useState<number | null>(null);

  const def = extractors.find((d) => d.id === defId) ?? null;
  const versions = usePromptVersions(defId);
  const actions = usePromptActions(defId);

  const [selVersion, setSelVersion] = useState<PromptVersion | null>(null);
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("");
  const [rows, setRows] = useState<AttrRow[]>([]);

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
    setRows(schemaToRows(selVersion.json_schema));
  }, [selVersion]);

  const isDraft = selVersion?.status === "draft";

  const setRow = (i: number, patch: Partial<AttrRow>) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const onSave = () => {
    if (!selVersion) return;
    actions.saveDraft.mutate(
      { id: selVersion.id, prompt_text: prompt, model, json_schema: rowsToSchema(rows) },
      { onSuccess: (v) => setSelVersion(v) },
    );
  };

  return (
    <section>
      <h1 className="text-lg font-semibold">Extractors</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Each extractor pulls structured attributes from a document domain. Edit the extraction prompt
        and the attributes to extract, then publish a new version.
      </p>

      <div className="mt-4 grid grid-cols-[200px_1fr] gap-6">
        {/* extractor list */}
        <div className="text-sm">
          {extractors.map((d) => (
            <button
              key={d.id}
              onClick={() => {
                setDefId(d.id);
                setSelVersion(null);
              }}
              className={`block w-full rounded px-2 py-1 text-left ${d.id === defId ? "bg-neutral-100 font-medium" : ""}`}
            >
              {d.key}
              <span className="ml-1 text-xs text-neutral-500">
                {d.domain} · v{d.active_version?.version ?? "—"}
              </span>
            </button>
          ))}
          {extractors.length === 0 && <p className="text-neutral-500">no extractors</p>}
        </div>

        {/* editor */}
        <div>
          {!def ? (
            <p className="text-sm text-neutral-500">select an extractor</p>
          ) : (
            <div className="space-y-4">
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
                    <label className="mb-1 block text-xs text-neutral-500">extraction prompt</label>
                    <textarea
                      className="h-24 w-full rounded border border-neutral-300 p-2 font-mono text-xs"
                      value={prompt}
                      disabled={!isDraft}
                      onChange={(e) => setPrompt(e.target.value)}
                    />
                  </div>

                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <label className="text-xs text-neutral-500">attributes to extract</label>
                      {isDraft && (
                        <button
                          className="rounded border px-2 py-0.5 text-xs"
                          onClick={() => setRows((rs) => [...rs, { ...EMPTY_ROW }])}
                        >
                          + attribute
                        </button>
                      )}
                    </div>
                    <table className="w-full text-left text-xs">
                      <thead className="text-neutral-500">
                        <tr>
                          <th className="py-1 pr-2">name</th>
                          <th className="pr-2">type</th>
                          <th className="pr-2">description (extraction guidance)</th>
                          <th className="pr-2">req</th>
                          <th className="pr-2">null</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, i) => (
                          <tr key={i} className="border-t border-neutral-100 align-top">
                            <td className="py-1 pr-2">
                              <input
                                className="w-28 rounded border border-neutral-300 px-1 py-0.5 font-mono"
                                value={r.name}
                                disabled={!isDraft}
                                onChange={(e) => setRow(i, { name: e.target.value })}
                                placeholder="test_name"
                              />
                            </td>
                            <td className="pr-2">
                              <select
                                className="rounded border border-neutral-300 px-1 py-0.5"
                                value={r.type}
                                disabled={!isDraft}
                                onChange={(e) => setRow(i, { type: e.target.value as AttrRow["type"] })}
                              >
                                {ATTR_TYPES.map((t) => (
                                  <option key={t}>{t}</option>
                                ))}
                              </select>
                            </td>
                            <td className="pr-2">
                              <textarea
                                className="h-10 w-full rounded border border-neutral-300 px-1 py-0.5"
                                value={r.description}
                                disabled={!isDraft}
                                onChange={(e) => setRow(i, { description: e.target.value })}
                              />
                            </td>
                            <td className="pr-2 text-center">
                              <input
                                type="checkbox"
                                checked={r.required}
                                disabled={!isDraft}
                                onChange={(e) => setRow(i, { required: e.target.checked })}
                              />
                            </td>
                            <td className="pr-2 text-center">
                              <input
                                type="checkbox"
                                checked={r.nullable}
                                disabled={!isDraft}
                                onChange={(e) => setRow(i, { nullable: e.target.checked })}
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
                            <td colSpan={6} className="py-2 text-neutral-500">
                              no attributes yet
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                    <p className="mt-1 text-xs text-neutral-400">
                      Provenance (snippet + char range) is added by the system on every fact — you don’t
                      author it here.
                    </p>
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
        </div>
      </div>
    </section>
  );
}
