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
import {
  isObjectTyped,
  type ObjectType,
  type PromptVersion,
  useObjectTypes,
  usePromptActions,
  usePromptDefinitions,
  usePromptVersions,
} from "@/features/prompts/api";
import { TestSetPanel } from "@/features/prompts/TestSetPanel";
import { VersionToolbar } from "@/features/prompts/VersionToolbar";
import { humanize } from "@/lib/utils";
import { ObjectTypesEditor } from "./ObjectTypesEditor";
import { type AttrRow, ATTR_TYPES, rowsToSchema, schemaToRows } from "./schema";

const EMPTY_ROW: AttrRow = { name: "", type: "string", description: "", required: false, nullable: false };

/** Extractors (design §8, alignment §6.1): each extractor targets one or more
 * catalog object types (synced from promop) with optional per-object technique
 * guidance; the prompt is composed from them. Older extractors authored a single
 * `data` schema + prompt — those still open in the legacy editor. */
export function ExtractorsPage() {
  const defs = usePromptDefinitions();
  const extractors = useMemo(() => defs.data?.filter((d) => d.kind === "extractor") ?? [], [defs.data]);
  const [defId, setDefId] = useState<number | null>(null);

  const def = extractors.find((d) => d.id === defId) ?? null;
  const versions = usePromptVersions(defId);
  const actions = usePromptActions(defId);
  const catalog = useObjectTypes();

  const [selVersion, setSelVersion] = useState<PromptVersion | null>(null);
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("");
  const [rows, setRows] = useState<AttrRow[]>([]);
  const [objectTypes, setObjectTypes] = useState<string[]>([]);
  const [guidance, setGuidance] = useState<Record<string, string>>({});
  const [convert, setConvert] = useState(false); // a legacy draft being moved onto object types

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
    setObjectTypes(selVersion.object_types ?? []);
    setGuidance(selVersion.guidance ?? {});
    setConvert(false);
  }, [selVersion]);

  const isDraft = selVersion?.status === "draft";
  const objectMode = !!selVersion && (isObjectTyped(selVersion) || convert);
  const setRow = (i: number, patch: Partial<AttrRow>) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  // A published version extracts against its snapshot; a draft against the live catalog.
  const definitions = useMemo<Record<string, ObjectType>>(() => {
    const snap = selVersion?.object_type_snapshot ?? {};
    if (Object.keys(snap).length) return snap;
    return Object.fromEntries((catalog.data ?? []).map((o) => [o.key, o]));
  }, [selVersion, catalog.data]);

  const onSave = () => {
    if (!selVersion) return;
    const body = objectMode
      ? {
          id: selVersion.id,
          model,
          prompt_text: "",
          json_schema: {},
          object_types: objectTypes,
          guidance: Object.fromEntries(objectTypes.filter((k) => guidance[k]?.trim()).map((k) => [k, guidance[k]])),
        }
      : { id: selVersion.id, prompt_text: prompt, model, json_schema: rowsToSchema(rows) };
    actions.saveDraft.mutate(body, {
      onSuccess: (v) => {
        setSelVersion(v);
        toast.success("Draft saved");
      },
    });
  };

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Extractors</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Each extractor pulls facts of the object types you pick — measurements, conditions, drugs, procedures,
          observations — whose fields come from promop. Add extraction guidance per type, then publish a new version.
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
                <span className="text-xs text-muted-foreground">v{d.active_version?.version ?? "—"}</span>
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
              {selVersion && objectMode
                ? objectTypes.map((k) => (
                    <Badge key={k} variant="outline" className="font-mono">
                      {k}
                    </Badge>
                  ))
                : def.domain && <Badge variant="outline">{def.domain} · legacy schema</Badge>}
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

              {selVersion && objectMode && (
                <ObjectTypesEditor
                  catalog={catalog.data}
                  definitions={definitions}
                  selected={objectTypes}
                  guidance={guidance}
                  editable={isDraft}
                  onSelectedChange={setObjectTypes}
                  onGuidanceChange={(k, text) => setGuidance((g) => ({ ...g, [k]: text }))}
                />
              )}

              {selVersion && !objectMode && (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed p-2.5 text-xs text-muted-foreground">
                    <span>
                      This version uses a hand-written schema. New versions should pick catalog object types instead.
                    </span>
                    {isDraft && (
                      <Button size="sm" variant="outline" onClick={() => setConvert(true)}>
                        Use object types
                      </Button>
                    )}
                  </div>
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
                </>
              )}

              {selVersion && (
                <>
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
