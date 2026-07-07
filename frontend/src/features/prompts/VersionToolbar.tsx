import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, FlaskConical, Plus, Save, Send, Star, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { type LintResult, type PromptDefinition, type PromptVersion, usePromptActions } from "./api";

interface Props {
  def: PromptDefinition;
  versions: PromptVersion[] | undefined;
  selVersion: PromptVersion | null;
  onSelect: (v: PromptVersion | null) => void;
  actions: ReturnType<typeof usePromptActions>;
  /** Page-specific: persist the edited draft body. */
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
    <div className="space-y-3">
      {/* version chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        {versions?.map((v) => {
          const active = def.active_version?.id === v.id;
          const selected = selVersion?.id === v.id;
          return (
            <div key={v.id} className="flex items-center">
              <Button
                variant={selected ? "secondary" : "outline"}
                size="sm"
                className={cn("gap-1", selected && "ring-1 ring-ring")}
                onClick={() => onSelect(v)}
              >
                {active && <Star className="fill-current text-warning" />}v{v.version}
                <span className="text-muted-foreground">· {v.status}</span>
              </Button>
              {v.status === "published" && !active && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="px-1.5 text-xs text-muted-foreground"
                  onClick={() =>
                    actions.activate.mutate(v.id, {
                      onSuccess: () => toast.success(`Activated v${v.version}`),
                    })
                  }
                >
                  activate
                </Button>
              )}
            </div>
          );
        })}
        <Button
          size="sm"
          className="ml-1"
          onClick={() =>
            actions.createDraft.mutate(undefined, {
              onSuccess: (v) => {
                onSelect(v);
                toast.success(`Draft v${v.version} created`);
              },
            })
          }
        >
          <Plus />
          Draft from active
        </Button>
      </div>

      {/* lifecycle actions */}
      {selVersion && (
        <div className="flex flex-wrap gap-2">
          {isDraft && (
            <Button variant="outline" size="sm" disabled={!canSave} onClick={onSave}>
              <Save />
              Save
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              actions.validate.mutate(selVersion.id, {
                onSuccess: (r) => {
                  setLint(r);
                  toast[r.ok ? "success" : "error"](r.ok ? "Lint passed" : "Lint failed");
                },
              })
            }
          >
            <CheckCircle2 />
            Validate
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              actions.dryRun.mutate(selVersion.id, {
                onSuccess: (d: { results: unknown[] }) => setDryRows(d.results),
              })
            }
          >
            <FlaskConical />
            Dry-run
          </Button>
          {isDraft && (
            <Button
              size="sm"
              onClick={() =>
                actions.publish.mutate(selVersion.id, {
                  onSuccess: () => toast.success("Published"),
                  onError: (err) => {
                    const data = (err as { response?: { data?: { lint?: LintResult } } }).response?.data;
                    if (data?.lint) setLint(data.lint);
                    toast.error("Publish blocked by lint");
                  },
                })
              }
            >
              <Send />
              Publish
            </Button>
          )}
        </div>
      )}

      {/* lint output */}
      {lint && (
        <div className="rounded-md border p-2 text-xs">
          <div
            className={cn(
              "flex items-center gap-1.5 font-medium",
              lint.ok ? "text-success" : "text-destructive",
            )}
          >
            {lint.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
            {lint.ok ? "Lint OK" : "Lint failed"}
          </div>
          {lint.findings.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {lint.findings.map((f, i) => (
                <li key={i} className={f.level === "error" ? "text-destructive" : "text-warning"}>
                  <span className="font-mono">[{f.code}]</span> {f.path}: {f.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* dry-run output */}
      {dryRows && (
        <pre className="max-h-48 overflow-auto rounded-md bg-muted p-2 text-xs">
          {JSON.stringify(dryRows, null, 2)}
        </pre>
      )}
    </div>
  );
}
