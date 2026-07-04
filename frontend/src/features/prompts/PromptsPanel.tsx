import { useEffect, useState } from "react";

import {
  type LintResult,
  type PromptVersion,
  usePromptActions,
  usePromptDefinitions,
  usePromptVersions,
} from "./api";

/** Phase 5 authoring UI (design §8): pick a definition, edit a draft's prompt +
 * schema/taxonomy, validate, dry-run, publish; activate an older version. */
export function PromptsPanel() {
  const defs = usePromptDefinitions();
  const [defId, setDefId] = useState<number | null>(null);
  const [selVersion, setSelVersion] = useState<PromptVersion | null>(null);

  const versions = usePromptVersions(defId);
  const actions = usePromptActions(defId);

  const def = defs.data?.find((d) => d.id === defId) ?? null;
  const [prompt, setPrompt] = useState("");
  const [bodyText, setBodyText] = useState(""); // JSON: schema (extractor) or taxonomy (classifier)
  const [model, setModel] = useState("");
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const [lint, setLint] = useState<LintResult | null>(null);
  const [dryRows, setDryRows] = useState<unknown[] | null>(null);

  // Load the selected version into the editor.
  useEffect(() => {
    if (!selVersion) return;
    setPrompt(selVersion.prompt_text);
    setModel(selVersion.model);
    const body = def?.kind === "classifier" ? selVersion.taxonomy : selVersion.json_schema;
    setBodyText(JSON.stringify(body, null, 2));
    setLint(null);
    setDryRows(null);
  }, [selVersion, def?.kind]);

  const isDraft = selVersion?.status === "draft";

  const parseBody = (): Record<string, unknown> | unknown[] | null => {
    try {
      const v = JSON.parse(bodyText);
      setJsonErr(null);
      return v;
    } catch (e) {
      setJsonErr((e as Error).message);
      return null;
    }
  };

  const onSave = () => {
    if (!selVersion) return;
    const body = parseBody();
    if (body === null) return;
    const patch: Partial<PromptVersion> & { id: number } = { id: selVersion.id, prompt_text: prompt, model };
    if (def?.kind === "classifier") patch.taxonomy = body as unknown[];
    else patch.json_schema = body as Record<string, unknown>;
    actions.saveDraft.mutate(patch, { onSuccess: (v) => setSelVersion(v) });
  };

  return (
    <section className="mt-4 rounded-lg border border-neutral-200 p-4">
      <h2 className="font-semibold">Prompts &amp; schemas</h2>
      <div className="mt-3 grid grid-cols-[200px_1fr] gap-4">
        {/* definitions */}
        <div className="text-sm">
          {defs.data?.map((d) => (
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
                {d.kind === "classifier" ? "clf" : d.domain} · v{d.active_version?.version ?? "—"}
              </span>
            </button>
          ))}
        </div>

        {/* versions + editor */}
        <div className="text-sm">
          {!def ? (
            <p className="text-neutral-500">select a definition</p>
          ) : (
            <>
              <div className="mb-2 flex items-center gap-2">
                <span className="font-medium">{def.key}</span>
                <button
                  className="rounded bg-neutral-900 px-2 py-0.5 text-xs text-white"
                  onClick={() => actions.createDraft.mutate(undefined, { onSuccess: (v) => setSelVersion(v) })}
                >
                  + draft from active
                </button>
              </div>

              <div className="mb-2 flex flex-wrap gap-1">
                {versions.data?.map((v) => (
                  <button
                    key={v.id}
                    onClick={() => setSelVersion(v)}
                    className={`rounded border px-2 py-0.5 text-xs ${selVersion?.id === v.id ? "border-neutral-900" : "border-neutral-200"}`}
                  >
                    v{v.version} · {v.status}
                    {def.active_version?.id === v.id && " ★"}
                    {v.status === "published" && def.active_version?.id !== v.id && (
                      <span
                        className="ml-1 text-blue-600"
                        onClick={(e) => {
                          e.stopPropagation();
                          actions.activate.mutate(v.id);
                        }}
                      >
                        activate
                      </span>
                    )}
                  </button>
                ))}
              </div>

              {selVersion && (
                <div className="space-y-2">
                  <label className="block text-xs text-neutral-500">prompt</label>
                  <textarea
                    className="h-24 w-full rounded border border-neutral-300 p-2 font-mono text-xs"
                    value={prompt}
                    disabled={!isDraft}
                    onChange={(e) => setPrompt(e.target.value)}
                  />
                  <label className="block text-xs text-neutral-500">
                    {def.kind === "classifier" ? "taxonomy (JSON)" : "data schema (JSON)"}
                  </label>
                  <textarea
                    className="h-40 w-full rounded border border-neutral-300 p-2 font-mono text-xs"
                    value={bodyText}
                    disabled={!isDraft}
                    onChange={(e) => setBodyText(e.target.value)}
                  />
                  <input
                    className="rounded border border-neutral-300 px-2 py-1 text-xs"
                    value={model}
                    disabled={!isDraft}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="model"
                  />
                  {jsonErr && <p className="text-xs text-red-600">invalid JSON: {jsonErr}</p>}

                  <div className="flex flex-wrap gap-2">
                    {isDraft && (
                      <button className="rounded border px-2 py-1 text-xs" onClick={onSave}>
                        save
                      </button>
                    )}
                    <button
                      className="rounded border px-2 py-1 text-xs"
                      onClick={() => actions.validate.mutate(selVersion.id, { onSuccess: setLint })}
                    >
                      validate
                    </button>
                    <button
                      className="rounded border px-2 py-1 text-xs"
                      onClick={() =>
                        actions.dryRun.mutate(selVersion.id, {
                          onSuccess: (d: { results: unknown[] }) => setDryRows(d.results),
                        })
                      }
                    >
                      dry-run
                    </button>
                    {isDraft && (
                      <button
                        className="rounded bg-neutral-900 px-2 py-1 text-xs text-white"
                        onClick={() =>
                          actions.publish.mutate(selVersion.id, {
                            onError: (err) => {
                              const data = (err as { response?: { data?: { lint?: LintResult } } }).response?.data;
                              if (data?.lint) setLint(data.lint);
                            },
                          })
                        }
                      >
                        publish
                      </button>
                    )}
                  </div>

                  {lint && (
                    <div className="text-xs">
                      <span className={lint.ok ? "text-green-600" : "text-red-600"}>
                        {lint.ok ? "lint ok" : "lint failed"}
                      </span>
                      <ul className="mt-1 space-y-0.5">
                        {lint.findings.map((f, i) => (
                          <li key={i} className={f.level === "error" ? "text-red-600" : "text-amber-600"}>
                            [{f.code}] {f.path}: {f.message}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {dryRows && (
                    <pre className="max-h-48 overflow-auto rounded bg-neutral-50 p-2 text-xs">
                      {JSON.stringify(dryRows, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
