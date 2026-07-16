import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { type PromptVersion, usePromptActions, usePromptDefinitions, usePromptVersions } from "@/features/prompts/api";
import { TestSetPanel } from "@/features/prompts/TestSetPanel";
import { VersionToolbar } from "@/features/prompts/VersionToolbar";
import { humanize } from "@/lib/utils";
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
    setRows(schemaToRows(selVersion.json_schema));
  }, [selVersion]);

  const isDraft = selVersion?.status === "draft";
  const setRow = (i: number, patch: Partial<AttrRow>) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const onSave = () => {
    if (!selVersion) return;
    actions.saveDraft.mutate(
      { id: selVersion.id, prompt_text: prompt, model, json_schema: rowsToSchema(rows) },
      { onSuccess: (v) => { setSelVersion(v); toast.success("Draft saved"); } },
    );
  };

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Extractors</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Each extractor pulls structured attributes from a document domain. Edit the extraction prompt
          and the attributes to extract, then publish a new version.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-[220px_1fr]">
        {/* extractor list */}
        <Card className="h-fit">
          <CardContent className="flex flex-col gap-0.5 p-2">
            {extractors.map((d) => (
              <button
                key={d.id}
                onClick={() => {
                  setDefId(d.id);
                  setSelVersion(null);
                }}
                className={
                  "flex flex-col items-start rounded-md px-2.5 py-1.5 text-left text-sm transition-colors " +
                  (d.id === defId ? "bg-accent font-medium text-accent-foreground" : "hover:bg-muted")
                }
              >
                <span className="font-mono">{d.key}</span>
                <span className="text-xs text-muted-foreground">
                  {d.domain} · v{d.active_version?.version ?? "—"}
                </span>
              </button>
            ))}
            {extractors.length === 0 && (
              <p className="p-2 text-sm text-muted-foreground">No extractors.</p>
            )}
          </CardContent>
        </Card>

        {/* editor */}
        {!def ? (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              Select an extractor to edit.
            </CardContent>
          </Card>
        ) : (
          <Tabs defaultValue="editor">
            <div className="flex items-center gap-2">
              <TabsList>
                <TabsTrigger value="editor">{humanize(def.key)}</TabsTrigger>
                <TabsTrigger value="testset">Test Set</TabsTrigger>
              </TabsList>
              <Badge variant="outline">{def.domain}</Badge>
            </div>

            <TabsContent value="editor" className="mt-4">
              <Card>
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
                    <Label>Extraction prompt</Label>
                    <Textarea
                      className="h-24 font-mono text-xs"
                      value={prompt}
                      disabled={!isDraft}
                      onChange={(e) => setPrompt(e.target.value)}
                    />
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <Label>Attributes to extract</Label>
                      {isDraft && (
                        <Button variant="outline" size="sm" onClick={() => setRows((rs) => [...rs, { ...EMPTY_ROW }])}>
                          <Plus />
                          Attribute
                        </Button>
                      )}
                    </div>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Name</TableHead>
                          <TableHead className="w-28">Type</TableHead>
                          <TableHead>Description (extraction guidance)</TableHead>
                          <TableHead className="w-12 text-center">Req</TableHead>
                          <TableHead className="w-12 text-center">Null</TableHead>
                          <TableHead className="w-10" />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {rows.map((r, i) => (
                          <TableRow key={i} className="align-top">
                            <TableCell>
                              <Input
                                className="w-32 font-mono"
                                value={r.name}
                                disabled={!isDraft}
                                onChange={(e) => setRow(i, { name: e.target.value })}
                                placeholder="test_name"
                              />
                            </TableCell>
                            <TableCell>
                              <Select
                                value={r.type}
                                onValueChange={(v) => setRow(i, { type: v as AttrRow["type"] })}
                                disabled={!isDraft}
                              >
                                <SelectTrigger className="w-28">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {ATTR_TYPES.map((t) => (
                                    <SelectItem key={t} value={t}>
                                      {t}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </TableCell>
                            <TableCell className="whitespace-normal">
                              <Textarea
                                className="min-h-9"
                                value={r.description}
                                disabled={!isDraft}
                                onChange={(e) => setRow(i, { description: e.target.value })}
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Checkbox
                                checked={r.required}
                                disabled={!isDraft}
                                onCheckedChange={(c) => setRow(i, { required: c === true })}
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Checkbox
                                checked={r.nullable}
                                disabled={!isDraft}
                                onCheckedChange={(c) => setRow(i, { nullable: c === true })}
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
                            <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                              No attributes yet.
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                    <p className="text-xs text-muted-foreground">
                      Provenance (snippet + char range) is added by the system on every fact — you don’t
                      author it here.
                    </p>
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
            </TabsContent>

            <TabsContent value="testset" className="mt-4">
              {selVersion ? (
                <TestSetPanel def={def} version={selVersion} />
              ) : (
                <p className="text-sm text-muted-foreground">Select a version to run the test set.</p>
              )}
            </TabsContent>
          </Tabs>
        )}
      </div>
    </section>
  );
}
