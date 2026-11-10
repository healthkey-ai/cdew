import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { type PromptDefinition, useDefinitionActions } from "@/features/prompts/api";
import { cn } from "@/lib/utils";

/** Checklist of the active taxonomy's document types; a selected type the taxonomy
 * no longer has stays listed (flagged) so it can be removed. */
export function TriggerPicker({
  taxonomyTypes,
  selected,
  onChange,
  disabled,
}: {
  taxonomyTypes: string[];
  selected: string[];
  onChange: (types: string[]) => void;
  disabled?: boolean;
}) {
  const unknown = selected.filter((t) => !taxonomyTypes.includes(t));
  const toggle = (t: string, on: boolean) => onChange(on ? [...selected, t] : selected.filter((x) => x !== t));
  return (
    <div className="flex flex-wrap gap-1.5">
      {[...taxonomyTypes, ...unknown].map((t) => {
        const on = selected.includes(t);
        const stale = unknown.includes(t);
        return (
          <label
            key={t}
            title={stale ? "Not in the active classifier taxonomy — this never fires" : undefined}
            className={cn(
              "flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-xs",
              on ? "border-primary/50 bg-primary/5" : "bg-card text-muted-foreground",
              stale && "border-warning/60 text-warning",
              disabled && "cursor-default opacity-70",
            )}
          >
            <Checkbox checked={on} disabled={disabled} onCheckedChange={(c) => toggle(t, c === true)} />
            {t}
          </label>
        );
      })}
      {taxonomyTypes.length === 0 && <span className="text-xs text-muted-foreground">No taxonomy loaded.</span>}
    </div>
  );
}

/**
 * An extractor's routing: which document types run it, and whether it runs at
 * all. Not versioned — a change applies to the next classified document.
 */
export function RoutingEditor({ def, taxonomyTypes }: { def: PromptDefinition; taxonomyTypes: string[] }) {
  const { update } = useDefinitionActions();
  const [triggers, setTriggers] = useState(def.triggers_on_types);
  const [enabled, setEnabled] = useState(def.enabled);
  useEffect(() => {
    setTriggers(def.triggers_on_types);
    setEnabled(def.enabled);
  }, [def.id, def.triggers_on_types, def.enabled]);

  const dirty = enabled !== def.enabled || JSON.stringify(triggers) !== JSON.stringify(def.triggers_on_types);
  const save = () =>
    update.mutate(
      { id: def.id, triggers_on_types: triggers, enabled },
      { onSuccess: () => toast.success("Routing saved"), onError: () => toast.error("Could not save routing") },
    );

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Runs on</Label>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-sm">
            <Checkbox checked={enabled} onCheckedChange={(c) => setEnabled(c === true)} />
            Enabled
          </label>
          <Button size="sm" variant="outline" disabled={!dirty || update.isPending} onClick={save}>
            {update.isPending ? "Saving…" : "Save routing"}
          </Button>
        </div>
      </div>
      <TriggerPicker taxonomyTypes={taxonomyTypes} selected={triggers} onChange={setTriggers} />
      <p className="text-xs text-muted-foreground">
        Classified documents of these types run this extractor’s active version. Routing isn’t versioned — a change
        applies to the next document classified.
        {!def.active_version && " Nothing runs until a version is published."}
        {!enabled && " Disabled: it doesn’t run at all."}
      </p>
      {def.unknown_triggers.length > 0 && (
        <p className="text-xs text-warning">
          Not in the active classifier taxonomy, so these never fire: {def.unknown_triggers.join(", ")}.
        </p>
      )}
    </div>
  );
}
