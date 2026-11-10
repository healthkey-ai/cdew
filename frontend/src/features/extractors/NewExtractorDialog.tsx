import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { type PromptDefinition, useDefinitionActions } from "@/features/prompts/api";
import { TriggerPicker } from "./RoutingEditor";

const SLUG = /^[a-z][a-z0-9_]*$/;

/** A slug from a name: "Office visit notes" → "office_visit_notes". */
const slugify = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^(\d)/, "x$1");

/**
 * "+ Extractor": create an extractor — key, name, description and the document
 * types it runs on. It starts with an empty draft; the author then picks its
 * object types and publishes (it isn't routed until a version is published).
 */
export function NewExtractorDialog({
  open,
  onOpenChange,
  taxonomyTypes,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  taxonomyTypes: string[];
  onCreated: (d: PromptDefinition) => void;
}) {
  const { create } = useDefinitionActions();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [triggers, setTriggers] = useState<string[]>([]);

  const effectiveKey = keyEdited ? key : slugify(name);
  const keyOk = SLUG.test(effectiveKey) && effectiveKey !== "ad_hoc";

  const reset = () => {
    setName("");
    setKey("");
    setKeyEdited(false);
    setDescription("");
    setTriggers([]);
  };

  const submit = () =>
    create.mutate(
      { key: effectiveKey, name: name.trim(), description: description.trim(), triggers_on_types: triggers },
      {
        onSuccess: (d) => {
          toast.success(`Created ${d.key} — pick its object types, then publish`);
          reset();
          onOpenChange(false);
          onCreated(d);
        },
        onError: (err) => {
          const data = (err as { response?: { data?: Record<string, string[] | string> } }).response?.data;
          const first = data && Object.values(data)[0];
          toast.error((Array.isArray(first) ? first[0] : first) ?? "Could not create the extractor");
        },
      },
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>New extractor</DialogTitle>
          <DialogDescription>
            An extractor pulls facts of the object types you pick from documents of the types it runs on. It starts as
            a draft and runs once you publish a version.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="ext-name">Name</Label>
            <Input id="ext-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Office visit extractor" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ext-key">Key</Label>
            <Input
              id="ext-key"
              className="font-mono"
              value={effectiveKey}
              onChange={(e) => {
                setKeyEdited(true);
                setKey(e.target.value);
              }}
              placeholder="office_visit"
            />
            <p className={keyOk || !effectiveKey ? "text-xs text-muted-foreground" : "text-xs text-destructive"}>
              Lowercase letters, digits and underscores. Fixed once created — it's recorded on every fact.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ext-desc">Description (optional)</Label>
            <Textarea id="ext-desc" className="min-h-16" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Runs on</Label>
            <TriggerPicker taxonomyTypes={taxonomyTypes} selected={triggers} onChange={setTriggers} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!name.trim() || !keyOk || create.isPending} onClick={submit}>
            {create.isPending ? "Creating…" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
