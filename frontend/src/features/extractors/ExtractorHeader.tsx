import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Pencil, Trash2 } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { type PromptDefinition, useDefinitionActions } from "@/features/prompts/api";

const detail = (err: unknown) =>
  (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;

/**
 * An extractor's name and description — editable — with its fixed key, and
 * Delete. Delete is refused once the extractor has produced facts (their
 * provenance must stay resolvable); disabling it in Runs on is the alternative.
 */
export function ExtractorHeader({ def, onDeleted }: { def: PromptDefinition; onDeleted: () => void }) {
  const { update, remove } = useDefinitionActions();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [name, setName] = useState(def.name);
  const [description, setDescription] = useState(def.description);
  useEffect(() => {
    setName(def.name);
    setDescription(def.description);
    setEditing(false);
  }, [def.id, def.name, def.description]);

  const save = () =>
    update.mutate(
      { id: def.id, name: name.trim(), description: description.trim() },
      {
        onSuccess: () => {
          setEditing(false);
          toast.success("Extractor updated");
        },
        onError: (err) => toast.error(detail(err) ?? "Could not update the extractor"),
      },
    );

  const del = () =>
    remove.mutate(def.id, {
      onSuccess: () => {
        toast.success(`Deleted ${def.name}`);
        onDeleted();
      },
      onError: (err) => toast.error(detail(err) ?? "Could not delete the extractor"),
    });

  if (editing) {
    return (
      <div className="space-y-2 rounded-lg border p-3">
        <div className="space-y-1.5">
          <Label htmlFor="ext-edit-name">Name</Label>
          <Input id="ext-edit-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ext-edit-desc">Description</Label>
          <Textarea
            id="ext-edit-desc"
            className="min-h-16"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          The key <span className="font-mono">{def.key}</span> stays — it’s recorded on every fact.
        </p>
        <div className="flex gap-2">
          <Button size="sm" disabled={!name.trim() || update.isPending} onClick={save}>
            {update.isPending ? "Saving…" : "Save"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <h2 className="text-base font-semibold">{def.name}</h2>
        <p className="font-mono text-xs text-muted-foreground">{def.key}</p>
        {def.description && <p className="mt-1 text-sm text-muted-foreground">{def.description}</p>}
      </div>
      <div className="flex gap-1">
        <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
          <Pencil /> Edit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground hover:text-destructive"
          disabled={remove.isPending}
          onClick={() => setConfirming(true)}
        >
          <Trash2 /> Delete
        </Button>
      </div>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {def.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the extractor, all its versions and its test set. It’s only possible while it has never
              produced facts — otherwise turn off <span className="font-medium">Enabled</span> under Runs on instead.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction className={buttonVariants({ variant: "destructive" })} onClick={del}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
