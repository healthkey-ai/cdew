import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ObjectType } from "@/features/prompts/api";
import { cn } from "@/lib/utils";

/**
 * Ad-hoc extraction (#114, alignment §6.2): pick object types and extract this
 * document only, with the catalog's default guidance — no extractor to author.
 * The new facts join this document's review list; earlier facts stay as they are.
 */
export function AdHocExtractDialog({
  open,
  onOpenChange,
  catalog,
  running,
  onRun,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog: ObjectType[] | undefined;
  running: boolean;
  onRun: (objectTypes: string[]) => Promise<unknown>;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (key: string, on: boolean) => setPicked((p) => (on ? [...p, key] : p.filter((k) => k !== key)));

  const run = () =>
    onRun(picked).then(
      () => {
        toast.info("Extracting… new facts appear here when it finishes");
        setPicked([]);
        onOpenChange(false);
      },
      (err) =>
        toast.error(
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Could not start extraction",
        ),
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Extract more from this document</DialogTitle>
          <DialogDescription>
            Pick the kinds of facts to look for. This runs on this document only, with the catalog’s default guidance;
            the facts already here are kept.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
          {(catalog ?? []).map((o) => {
            const on = picked.includes(o.key);
            return (
              <label
                key={o.key}
                className={cn(
                  "flex cursor-pointer items-start gap-2.5 rounded-md border p-2.5 text-sm",
                  on ? "border-primary/50 bg-primary/5" : "bg-card",
                )}
              >
                <Checkbox className="mt-0.5" checked={on} onCheckedChange={(c) => toggle(o.key, c === true)} />
                <span className="min-w-0">
                  <span className="font-medium">{o.label}</span>
                  <span className="block text-xs text-muted-foreground">{o.description}</span>
                </span>
              </label>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!picked.length || running} onClick={run}>
            {running ? "Starting…" : "Extract"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
