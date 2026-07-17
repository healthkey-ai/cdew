import { Fragment, useMemo, useState } from "react";
import { toast } from "sonner";
import { ChevronRight, FlaskConical, Loader2, Plus, Save, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useDocuments } from "@/features/documents/api";
import { cn } from "@/lib/utils";
import {
  type DryRunFact,
  type PromptDefinition,
  type PromptVersion,
  type TestSample,
  usePromptActions,
  useTestSampleActions,
  useTestSamples,
} from "./api";

/** Best-effort coerce a table-cell string to a JSON value (140 → number, else string). */
const coerce = (v: string): unknown => {
  if (v === "") return "";
  try {
    return JSON.parse(v);
  } catch {
    return v;
  }
};

/** Render one attribute value into a read-only table cell. */
function cell(v: unknown) {
  if (v === null || v === undefined) return <span className="text-muted-foreground">—</span>;
  if (typeof v === "object") return <code className="text-[11px]">{JSON.stringify(v)}</code>;
  return String(v);
}

/** Render facts as rows × the extractor's attributes (+ optional source snippets). */
function factsTable(rows: Record<string, unknown>[], attrs: string[], sources?: (string | undefined)[]) {
  return (
    <div className="max-h-72 overflow-auto rounded-md border bg-background">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted">
          <tr className="border-b">
            <th className="px-2 py-1 text-left font-medium text-muted-foreground">#</th>
            {attrs.map((a) => (
              <th key={a} className="px-2 py-1 text-left font-medium">
                {a}
              </th>
            ))}
            {sources && <th className="px-2 py-1 text-left font-medium text-muted-foreground">source</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((data, i) => (
            <tr key={i} className="border-b align-top last:border-0">
              <td className="px-2 py-1 text-muted-foreground">{i + 1}</td>
              {attrs.map((a) => (
                <td key={a} className="px-2 py-1">
                  {cell(data[a])}
                </td>
              ))}
              {sources && (
                <td className="max-w-[16rem] truncate px-2 py-1 text-muted-foreground" title={sources[i]}>
                  {sources[i] ? `“${sources[i]}”` : "—"}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Labeled test set for a classifier or extractor (design §8.3): add documents,
 * Extract (whole set or one document) to save the extraction, then compare and
 * edit the Expected value (as JSON or in the table). */
export function TestSetPanel({ def, version }: { def: PromptDefinition; version: PromptVersion | null }) {
  const samples = useTestSamples(def.id);
  const sactions = useTestSampleActions(def.id);
  const dryRun = usePromptActions(def.id).dryRun;
  const docs = useDocuments();

  const [docId, setDocId] = useState("");
  const [label, setLabel] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expectedText, setExpectedText] = useState("");

  const isClassifier = def.kind === "classifier";
  const types = useMemo(
    () => (isClassifier ? ((version?.taxonomy as { type: string }[] | undefined)?.map((t) => t.type) ?? []) : []),
    [isClassifier, version],
  );
  // The extractor's "attributes to extract" (schema properties) → result columns.
  const attrs = useMemo(
    () =>
      isClassifier
        ? []
        : Object.keys((version?.json_schema as { properties?: Record<string, unknown> } | undefined)?.properties ?? {}),
    [isClassifier, version],
  );
  const parsedDocs = useMemo(() => (docs.data?.results ?? []).filter((d) => d.has_text), [docs.data]);
  const docItems = useMemo(
    () => Object.fromEntries(parsedDocs.map((d) => [String(d.id), d.original_filename || `doc#${d.id}`])),
    [parsedDocs],
  );

  // Expected rows parsed from the editor text (null = the JSON isn't a valid array).
  const expectedRows = useMemo<Record<string, unknown>[] | null>(() => {
    try {
      const v = JSON.parse(expectedText || "[]");
      return Array.isArray(v) ? (v as Record<string, unknown>[]) : null;
    } catch {
      return null;
    }
  }, [expectedText]);

  const extractedFacts = (s: TestSample) => (s.extracted_payload as DryRunFact[] | null) ?? null;

  const passOf = (s: TestSample): boolean | undefined => {
    if (s.expected_payload == null || s.extracted_payload == null) return undefined;
    if (isClassifier) {
      const routed = new Set((s.extracted_payload as { routed_types?: string[] }).routed_types ?? []);
      const exp = new Set(s.expected_payload as string[]);
      return routed.size === exp.size && [...routed].every((t) => exp.has(t));
    }
    const facts = (extractedFacts(s) ?? []).map((f) => f.data);
    return JSON.stringify(facts) === JSON.stringify(s.expected_payload);
  };

  const addSample = () =>
    sactions.create.mutate(
      { document: Number(docId), label },
      {
        onSuccess: () => {
          setDocId("");
          setLabel("");
          toast.success("Sample added");
        },
      },
    );

  const extract = (sampleIds?: number[]) => {
    if (!version) return;
    dryRun.mutate(
      { id: version.id, sampleIds },
      {
        onSuccess: (d) => {
          const scored = d.results.filter((r) => r.passed !== undefined);
          if (scored.length) {
            const pass = scored.filter((r) => r.passed).length;
            toast[pass === scored.length ? "success" : "info"](`${pass}/${scored.length} passed`);
          } else {
            toast.success(sampleIds ? "Extracted" : "Extracted all");
          }
        },
        onError: (err) => {
          const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
          toast.error(detail ?? "Extract failed — is the LLM configured for this environment?");
        },
      },
    );
  };

  const toggle = (s: TestSample) => {
    if (expandedId === s.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(s.id);
    setExpectedText(s.expected_payload != null ? JSON.stringify(s.expected_payload, null, 2) : "");
  };

  const toggleType = (s: TestSample, type: string) => {
    const cur = new Set((s.expected_payload as string[] | null) ?? []);
    if (cur.has(type)) cur.delete(type);
    else cur.add(type);
    sactions.update.mutate({ id: s.id, expected_payload: [...cur] });
  };

  const setExpectedFromExtracted = (s: TestSample) => {
    const facts = extractedFacts(s);
    if (!facts) {
      toast.error("Extract this document first");
      return;
    }
    const expected = facts.map((f) => f.data);
    sactions.update.mutate(
      { id: s.id, expected_payload: expected },
      {
        onSuccess: () => {
          toast.success("Expected set from extraction");
          if (expandedId === s.id) setExpectedText(JSON.stringify(expected, null, 2));
        },
      },
    );
  };

  const saveExpected = (s: TestSample) => {
    let payload: unknown = null;
    if (expectedText.trim()) {
      try {
        payload = JSON.parse(expectedText);
      } catch {
        toast.error("Invalid JSON");
        return;
      }
    }
    sactions.update.mutate({ id: s.id, expected_payload: payload }, { onSuccess: () => toast.success("Expected saved") });
  };

  // Editable-table helpers (operate on the shared expectedText).
  const setExpectedCell = (ri: number, attr: string, value: string) => {
    if (expectedRows === null) return;
    setExpectedText(
      JSON.stringify(
        expectedRows.map((row, i) => (i === ri ? { ...row, [attr]: coerce(value) } : row)),
        null,
        2,
      ),
    );
  };
  const addExpectedRow = () => setExpectedText(JSON.stringify([...(expectedRows ?? []), {}], null, 2));
  const removeExpectedRow = (ri: number) =>
    expectedRows !== null && setExpectedText(JSON.stringify(expectedRows.filter((_, i) => i !== ri), null, 2));

  const passBadge = (s: TestSample) => {
    const p = passOf(s);
    return p === undefined ? null : (
      <Badge variant={p ? "secondary" : "destructive"} className={p ? "text-success" : ""}>
        {p ? "pass" : "fail"}
      </Badge>
    );
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Test set{samples.data ? ` (${samples.data.length})` : ""}</CardTitle>
        <Button size="sm" onClick={() => extract()} disabled={!version || !samples.data?.length || dryRun.isPending}>
          {dryRun.isPending ? <Loader2 className="animate-spin" /> : <FlaskConical />}
          {dryRun.isPending ? "Extracting…" : "Extract"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={docId} onValueChange={(v) => setDocId(v ?? "")} items={docItems}>
            <SelectTrigger className="h-8 w-64">
              <SelectValue placeholder="Add a parsed document…" />
            </SelectTrigger>
            <SelectContent>
              {parsedDocs.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {d.original_filename || `doc#${d.id}`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            className="h-8 w-40"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="label (optional)"
          />
          <Button size="sm" variant="outline" onClick={addSample} disabled={!docId || sactions.create.isPending}>
            <Plus />
            Add
          </Button>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Document</TableHead>
              <TableHead>Expected</TableHead>
              <TableHead>Result</TableHead>
              <TableHead className="w-16 text-right" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {samples.data?.map((s) => {
              const open = expandedId === s.id;
              const facts = extractedFacts(s);

              const expectedEditor = (
                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-xs font-medium">Expected — JSON</span>
                    {!isClassifier && (
                      <Button variant="outline" size="sm" onClick={() => setExpectedFromExtracted(s)}>
                        Set from extraction
                      </Button>
                    )}
                  </div>
                  <Textarea
                    className="h-64 font-mono text-xs"
                    value={expectedText}
                    onChange={(e) => setExpectedText(e.target.value)}
                    placeholder={isClassifier ? '["lab_report"]' : '[{ "test_name": "…" }]'}
                  />
                  <Button size="sm" className="mt-1" onClick={() => saveExpected(s)}>
                    <Save />
                    Save
                  </Button>
                </div>
              );

              return (
                <Fragment key={s.id}>
                  <TableRow className="align-top">
                    <TableCell className="font-medium">
                      <button onClick={() => toggle(s)} className="flex items-start gap-1.5 text-left hover:underline">
                        <ChevronRight
                          className={cn(
                            "mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform",
                            open && "rotate-90",
                          )}
                        />
                        <span>
                          {s.document_filename || `doc#${s.document}`}
                          {s.label && <div className="text-xs font-normal text-muted-foreground">{s.label}</div>}
                        </span>
                      </button>
                    </TableCell>
                    <TableCell>
                      {isClassifier ? (
                        <div className="flex flex-wrap gap-1">
                          {types.map((t) => {
                            const on = ((s.expected_payload as string[] | null) ?? []).includes(t);
                            return (
                              <button
                                key={t}
                                onClick={() => toggleType(s, t)}
                                className={cn(
                                  "rounded border px-1.5 py-0.5 text-xs transition-colors",
                                  on
                                    ? "border-primary bg-primary/10 font-medium"
                                    : "border-input text-muted-foreground hover:bg-muted",
                                )}
                              >
                                {t}
                              </button>
                            );
                          })}
                          {types.length === 0 && (
                            <span className="text-xs text-muted-foreground">no taxonomy types</span>
                          )}
                        </div>
                      ) : (
                        <div className="text-xs text-muted-foreground">
                          {(s.expected_payload as unknown[] | null)?.length
                            ? `${(s.expected_payload as unknown[]).length} expected fact(s)`
                            : "not set"}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      {!s.extracted_at ? (
                        <span className="text-xs text-muted-foreground">not extracted</span>
                      ) : (
                        <div className="space-y-1">
                          {passBadge(s)}
                          <button
                            onClick={() => toggle(s)}
                            className="block text-xs text-muted-foreground hover:underline"
                          >
                            {isClassifier
                              ? `routed: ${(s.extracted_payload as { routed_types?: string[] }).routed_types?.join(", ") || "—"}`
                              : `${facts?.length ?? 0} facts`}{" "}
                            · view
                          </button>
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8"
                          aria-label="Extract this document"
                          title="Extract this document"
                          disabled={!version || dryRun.isPending}
                          onClick={() => extract([s.id])}
                        >
                          <FlaskConical />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8"
                          aria-label="Remove sample"
                          onClick={() => sactions.remove.mutate(s.id)}
                        >
                          <Trash2 className="text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>

                  {open && (
                    <TableRow>
                      <TableCell colSpan={4} className="bg-muted/30">
                        {isClassifier ? (
                          <Tabs defaultValue="result">
                            <TabsList>
                              <TabsTrigger value="result">Result</TabsTrigger>
                              <TabsTrigger value="expected">Expected</TabsTrigger>
                            </TabsList>
                            <TabsContent value="result" className="mt-3">
                              {!s.extracted_at ? (
                                <p className="text-xs text-muted-foreground">Extract to see results.</p>
                              ) : (
                                <div className="space-y-1 text-xs">
                                  <div className="text-muted-foreground">
                                    outcome: {(s.extracted_payload as { outcome?: string }).outcome} · routed:{" "}
                                    {(s.extracted_payload as { routed_types?: string[] }).routed_types?.join(", ") ||
                                      "—"}
                                  </div>
                                  <ul className="space-y-0.5">
                                    {(s.extracted_payload as { scores?: { type: string; confidence: number }[] }).scores?.map(
                                      (sc, i) => (
                                        <li key={i} className="text-muted-foreground">
                                          {sc.type}: {sc.confidence?.toFixed?.(2) ?? sc.confidence}
                                        </li>
                                      ),
                                    )}
                                  </ul>
                                </div>
                              )}
                            </TabsContent>
                            <TabsContent value="expected" className="mt-3">
                              {expectedEditor}
                            </TabsContent>
                          </Tabs>
                        ) : (
                          <Tabs defaultValue="extracted">
                            <TabsList>
                              <TabsTrigger value="extracted">Extracted{facts ? ` (${facts.length})` : ""}</TabsTrigger>
                              <TabsTrigger value="expected">Expected</TabsTrigger>
                            </TabsList>

                            <TabsContent value="extracted" className="mt-3">
                              <Tabs defaultValue="table">
                                <TabsList variant="line">
                                  <TabsTrigger value="table">Table</TabsTrigger>
                                  <TabsTrigger value="json">JSON</TabsTrigger>
                                </TabsList>
                                <TabsContent value="table" className="mt-2">
                                  {!facts ? (
                                    <p className="text-xs text-muted-foreground">Extract to see the results.</p>
                                  ) : !facts.length ? (
                                    <p className="text-xs text-muted-foreground">No facts extracted.</p>
                                  ) : (
                                    factsTable(
                                      facts.map((f) => f.data),
                                      attrs,
                                      facts.map((f) => f.snippet),
                                    )
                                  )}
                                </TabsContent>
                                <TabsContent value="json" className="mt-2">
                                  <pre className="max-h-72 overflow-auto rounded-md bg-background p-2 font-mono text-xs">
                                    {JSON.stringify(facts?.map((f) => f.data) ?? [], null, 2)}
                                  </pre>
                                </TabsContent>
                              </Tabs>
                            </TabsContent>

                            <TabsContent value="expected" className="mt-3">
                              <Tabs defaultValue="table">
                                <TabsList variant="line">
                                  <TabsTrigger value="table">Table</TabsTrigger>
                                  <TabsTrigger value="json">JSON</TabsTrigger>
                                </TabsList>

                                <TabsContent value="table" className="mt-2 space-y-2">
                                  {expectedRows === null ? (
                                    <p className="text-xs text-muted-foreground">
                                      The expected JSON isn't a valid array — fix it in the JSON tab.
                                    </p>
                                  ) : (
                                    <div className="overflow-auto rounded-md border bg-background">
                                      <table className="w-full text-xs">
                                        <thead className="bg-muted">
                                          <tr className="border-b">
                                            {attrs.map((a) => (
                                              <th key={a} className="px-2 py-1 text-left font-medium">
                                                {a}
                                              </th>
                                            ))}
                                            <th className="w-8" />
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {expectedRows.map((row, ri) => (
                                            <tr key={ri} className="border-b last:border-0">
                                              {attrs.map((a) => (
                                                <td key={a} className="px-1 py-0.5">
                                                  <Input
                                                    className="h-7"
                                                    value={
                                                      row[a] == null
                                                        ? ""
                                                        : typeof row[a] === "object"
                                                          ? JSON.stringify(row[a])
                                                          : String(row[a])
                                                    }
                                                    onChange={(e) => setExpectedCell(ri, a, e.target.value)}
                                                  />
                                                </td>
                                              ))}
                                              <td className="px-1">
                                                <Button
                                                  variant="ghost"
                                                  size="icon"
                                                  className="size-7"
                                                  aria-label="Remove row"
                                                  onClick={() => removeExpectedRow(ri)}
                                                >
                                                  <Trash2 className="size-3.5 text-destructive" />
                                                </Button>
                                              </td>
                                            </tr>
                                          ))}
                                          {expectedRows.length === 0 && (
                                            <tr>
                                              <td colSpan={attrs.length + 1} className="px-2 py-3 text-center text-muted-foreground">
                                                No expected facts yet.
                                              </td>
                                            </tr>
                                          )}
                                        </tbody>
                                      </table>
                                    </div>
                                  )}
                                  <div className="flex flex-wrap gap-2">
                                    <Button variant="outline" size="sm" onClick={addExpectedRow}>
                                      <Plus />
                                      Row
                                    </Button>
                                    <Button variant="outline" size="sm" onClick={() => setExpectedFromExtracted(s)}>
                                      Set from extraction
                                    </Button>
                                    <Button size="sm" onClick={() => saveExpected(s)}>
                                      <Save />
                                      Save
                                    </Button>
                                  </div>
                                </TabsContent>

                                <TabsContent value="json" className="mt-2">
                                  {expectedEditor}
                                </TabsContent>
                              </Tabs>
                            </TabsContent>
                          </Tabs>
                        )}
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
            {samples.data && samples.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">
                  No test samples yet — add a parsed document above.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>

        <p className="text-xs text-muted-foreground">
          {isClassifier
            ? "Add documents, Extract to run the classifier, then set the Expected types to compare (pass/fail)."
            : "Add documents, Extract (whole set or per document) to save the extraction, then set the Expected facts — “Set from extraction”, or edit them in the table or JSON."}
        </p>
      </CardContent>
    </Card>
  );
}
