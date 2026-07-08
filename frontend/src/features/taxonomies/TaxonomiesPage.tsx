import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { type PromptVersion, usePromptActions, usePromptDefinitions, usePromptVersions } from "@/features/prompts/api";
import { VersionToolbar } from "@/features/prompts/VersionToolbar";

interface TaxRow {
  type: string;
  prompt: string;
  threshold: number;
}

const EMPTY_ROW: TaxRow = { type: "", prompt: "", threshold: 0.5 };

// `prompt` is the canonical per-type field; older versions used `description`.
function toRows(taxonomy: unknown[]): TaxRow[] {
  return (taxonomy as { type?: string; prompt?: string; description?: string; threshold?: number }[]).map((t) => ({
    type: t.type ?? "",
    prompt: t.prompt ?? t.description ?? "",
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

  useEffect(() => {
    if (!versions.data?.length) return;
    if (selVersion && versions.data.some((v) => v.id === selVersion.id)) return;
    const active = versions.data.find((v) => v.id === def?.active_version?.id);
    setSelVersion(active ?? versions.data[versions.data.length - 1]);
  }, [versions.data, def?.active_version?.id, selVersion]);

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
      { onSuccess: (v) => { setSelVersion(v); toast.success("Draft saved"); } },
    );
  };

  if (!classifiers.length) {
    return <p className="text-sm text-muted-foreground">No classifier definition found.</p>;
  }

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Taxonomies</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The document types the classifier scores. Add, edit, or remove types; each type carries a
          per-type <span className="font-medium">prompt</span> that the classifier uses{" "}
          <span className="font-medium">together with</span> the overall Classification prompt below.
          Edit on a draft, then publish a new version.
        </p>
      </div>

      {classifiers.length > 1 && (
        <div className="flex gap-1">
          {classifiers.map((c) => (
            <Button
              key={c.id}
              variant={c.id === defId ? "secondary" : "ghost"}
              size="sm"
              onClick={() => {
                setDefId(c.id);
                setSelVersion(null);
              }}
            >
              {c.key}
            </Button>
          ))}
        </div>
      )}

      {def && (
        <Card>
          <CardHeader>
            <CardTitle>{def.key}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
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
                <div className="space-y-1.5">
                  <Label>Classification prompt</Label>
                  <p className="text-xs text-muted-foreground">
                    Applied to every document, combined with each type’s per-type prompt below.
                  </p>
                  <Textarea
                    className="h-24 font-mono text-xs"
                    value={prompt}
                    disabled={!isDraft}
                    onChange={(e) => setPrompt(e.target.value)}
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label>Types</Label>
                    {isDraft && (
                      <Button variant="outline" size="sm" onClick={() => setRows((rs) => [...rs, { ...EMPTY_ROW }])}>
                        <Plus />
                        Type
                      </Button>
                    )}
                  </div>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Type (slug)</TableHead>
                        <TableHead>Prompt (how to classify it)</TableHead>
                        <TableHead className="w-24">Threshold</TableHead>
                        <TableHead className="w-10" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.map((r, i) => (
                        <TableRow key={i} className="align-top">
                          <TableCell>
                            <Input
                              className="w-36 font-mono"
                              value={r.type}
                              disabled={!isDraft}
                              onChange={(e) => setRow(i, { type: e.target.value })}
                              placeholder="lab_report"
                            />
                          </TableCell>
                          <TableCell className="whitespace-normal">
                            <Textarea
                              className="min-h-9"
                              value={r.prompt}
                              disabled={!isDraft}
                              onChange={(e) => setRow(i, { prompt: e.target.value })}
                              placeholder="How to recognise this type…"
                            />
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              min={0}
                              max={1}
                              step={0.05}
                              className="w-20"
                              value={r.threshold}
                              disabled={!isDraft}
                              onChange={(e) => setRow(i, { threshold: Number(e.target.value) })}
                            />
                          </TableCell>
                          <TableCell>
                            {isDraft && (
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label="Remove"
                                onClick={() => setRows((rs) => rs.filter((_, idx) => idx !== i))}
                              >
                                <Trash2 className="text-destructive" />
                              </Button>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                      {rows.length === 0 && (
                        <TableRow>
                          <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">
                            No types yet.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>

                <div className="space-y-1.5">
                  <Label>Model</Label>
                  <Input
                    className="w-64"
                    value={model}
                    disabled={!isDraft}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="gemini-2.5-flash"
                  />
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}
    </section>
  );
}
