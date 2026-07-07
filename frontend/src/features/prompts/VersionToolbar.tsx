import { useEffect, useState } from "react";

import { type LintResult, type PromptDefinition, type PromptVersion, usePromptActions } from "./api";

interface Props {
  def: PromptDefinition;
  versions: PromptVersion[] | undefined;
  selVersion: PromptVersion | null;
  onSelect: (v: PromptVersion | null) => void;
  actions: ReturnType<typeof usePromptActions>;
  /** Page-specific: persist the edited draft body; returns the saved version. */
  onSave: () => void;
  canSave: boolean;
}

/** Shared prompt-version lifecycle controls (design §8): version chips +
 * save / validate / dry-run / publish / activate + lint + dry-run output. */
export function VersionToolbar({ def, versions, selVersion, onSelect, actions, onSave, canSave }: Props) {
  const [lint, setLint] = useState<LintResult | null>(null);
  const [dryRows, setDryRows] = useState<unknown[] | null>(null);

  // Reset transient results when the selected version changes.
  useEffect(() => {
    setLint(null);
    setDryRows(null);
  }, [selVersion?.id]);

  const isDraft = selVersion?.status === "draft";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1">
        {versions?.map((v) => (
          <button
            key={v.id}
            onClick={() => onSelect(v)}
            className={`rounded border px-2 py-0.5 text-xs ${
              selVersion?.id === v.id ? "border-neutral-900" : "border-neutral-200"
            }`}
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
        <button
          className="ml-2 rounded bg-neutral-900 px-2 py-0.5 text-xs text-white"
          onClick={() => actions.createDraft.mutate(undefined, { onSuccess: (v) => onSelect(v) })}
        >
          + draft from active
        </button>
      </div>

      {selVersion && (
        <div className="flex flex-wrap gap-2">
          {isDraft && (
            <button className="rounded border px-2 py-1 text-xs disabled:opacity-40" disabled={!canSave} onClick={onSave}>
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
      )}

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
  );
}
