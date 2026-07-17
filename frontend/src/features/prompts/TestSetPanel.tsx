import { type ComponentProps, Fragment, useMemo, useState } from "react";
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
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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
      <Table className="text-xs">
        <TableHeader className="sticky top-0 z-10 bg-muted">
          <TableRow>
            <TableHead className="h-8 w-8 text-muted-foreground">#</TableHead>
            {attrs.map((a) => (
              <TableHead key={a} className="h-8">
                {a}
              </TableHead>
            ))}
            {sources && <TableHead className="h-8 text-muted-foreground">source</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((data, i) => (
            <TableRow key={i} className="align-top">
              <TableCell className="py-1 text-muted-foreground">{i + 1}</TableCell>
              {attrs.map((a) => (
                <TableCell key={a} className="py-1">
                  {cell(data[a])}
                </TableCell>
              ))}
              {sources && (
                <TableCell className="max-w-[16rem] truncate py-1 text-muted-foreground" title={sources[i]}>
                  {sources[i] ? `“${sources[i]}”` : "—"}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Row-by-row diff of extracted vs expected facts (design §8.3). Each fact index
 * yields two rows — extracted then expected — with differing cells highlighted.
 * A missing row on either side shows as "—" (a whole highlighted row). */
function diffTable(extracted: Record<string, unknown>[], expected: Record<string, unknown>[], attrs: string[]) {
  const n = Math.max(extracted.length, expected.length);
  const differs = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);
  const line = (
    i: number,
    which: "extracted" | "expected",
    data: Record<string, unknown> | undefined,
    other: Record<string, unknown> | undefined,
  ) => (
    <TableRow key={`${i}-${which}`} className={cn(which === "extracted" && i > 0 && "border-t-2")}>
      {which === "extracted" && (
        <TableCell rowSpan={2} className="align-middle font-medium">
          {i + 1}
        </TableCell>
      )}
      <TableCell className="py-1 text-muted-foreground">{which}</TableCell>
      {attrs.map((a) => (
        <TableCell
          key={a}
          className={cn("py-1", differs(data?.[a], other?.[a]) && "bg-destructive/10 text-destructive")}
        >
          {data ? cell(data[a]) : <span className="text-muted-foreground">—</span>}
        </TableCell>
      ))}
    </TableRow>
  );
  return (
    <div className="max-h-96 overflow-auto rounded-md border bg-background">
      <Table className="text-xs">
        <TableHeader className="sticky top-0 z-10 bg-muted">
          <TableRow>
            <TableHead className="h-8 w-8 text-muted-foreground">#</TableHead>
            <TableHead className="h-8 w-20 text-muted-foreground">side</TableHead>
            {attrs.map((a) => (
              <TableHead key={a} className="h-8">
                {a}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: n }, (_, i) => (
            <Fragment key={i}>
              {line(i, "extracted", extracted[i], expected[i])}
              {line(i, "expected", expected[i], extracted[i])}
            </Fragment>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** A Button with a hover tooltip that explains the action in a bit more detail
 * than the label alone. Merges the tooltip trigger onto the Button (no extra DOM). */
function TipButton({ tip, ...props }: { tip: string } & ComponentProps<typeof Button>) {
  return (
    <Tooltip>
      <TooltipTrigger render={<Button {...props} />} />
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
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
        <TipButton
          tip="Run the extractor over every document in the test set and save each result"
          size="sm"
          onClick={() => extract()}
          disabled={!version || !samples.data?.length || dryRun.isPending}
        >
          {dryRun.isPending ? <Loader2 className="animate-spin" /> : <FlaskConical />}
          {dryRun.isPending ? "Extracting…" : "Extract"}
        </TipButton>
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
          <TipButton
            tip="Add the selected document to this test set as a sample"
            size="sm"
            variant="outline"
            onClick={addSample}
            disabled={!docId || sactions.create.isPending}
          >
            <Plus />
            Add
          </TipButton>
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
              // Extractor mismatch (both sides present and unequal) → offer a Diff tab.
              const showDiff = !isClassifier && passOf(s) === false;

              const expectedEditor = (
                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-xs font-medium">Expected — JSON</span>
                    {!isClassifier && (
                      <TipButton
                        tip="Copy the extracted facts into Expected as the baseline to compare against"
                        variant="outline"
                        size="sm"
                        onClick={() => setExpectedFromExtracted(s)}
                      >
                        Set from extraction
                      </TipButton>
                    )}
                  </div>
                  <Textarea
                    className="h-64 font-mono text-xs"
                    value={expectedText}
                    onChange={(e) => setExpectedText(e.target.value)}
                    placeholder={isClassifier ? '["lab_report"]' : '[{ "test_name": "…" }]'}
                  />
                  <TipButton
                    tip="Save this Expected value as the document's gold to compare future extractions against"
                    size="sm"
                    className="mt-1"
                    onClick={() => saveExpected(s)}
                  >
                    <Save />
                    Save
                  </TipButton>
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
                              <Tooltip key={t}>
                                <TooltipTrigger
                                  render={
                                    <Toggle
                                      size="sm"
                                      pressed={on}
                                      onPressedChange={() => toggleType(s, t)}
                                      className="h-6 border border-input px-1.5 text-xs data-[state=on]:border-primary data-[state=on]:bg-primary/10"
                                    >
                                      {t}
                                    </Toggle>
                                  }
                                />
                                <TooltipContent>
                                  {on ? `Remove “${t}” from the expected types` : `Mark “${t}” as an expected type for this document`}
                                </TooltipContent>
                              </Tooltip>
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
                        <TipButton
                          tip="Run the extractor on just this document and save its result"
                          variant="ghost"
                          size="icon"
                          className="size-8"
                          aria-label="Extract this document"
                          disabled={!version || dryRun.isPending}
                          onClick={() => extract([s.id])}
                        >
                          <FlaskConical />
                        </TipButton>
                        <TipButton
                          tip="Remove this document from the test set (does not delete the document)"
                          variant="ghost"
                          size="icon"
                          className="size-8"
                          aria-label="Remove sample"
                          onClick={() => sactions.remove.mutate(s.id)}
                        >
                          <Trash2 className="text-destructive" />
                        </TipButton>
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
                          <Tabs defaultValue={showDiff ? "diff" : "extracted"}>
                            <TabsList>
                              <TabsTrigger value="extracted">Extracted{facts ? ` (${facts.length})` : ""}</TabsTrigger>
                              <TabsTrigger value="expected">Expected</TabsTrigger>
                              {showDiff && (
                                <TabsTrigger value="diff" className="text-destructive data-active:text-destructive!">
                                  Diff
                                </TabsTrigger>
                              )}
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

                            {showDiff && (
                              <TabsContent value="diff" className="mt-3 space-y-2">
                                <p className="text-xs text-muted-foreground">
                                  Extracted ≠ Expected — differing fields are highlighted. Fix the extractor, or
                                  correct the Expected value.
                                </p>
                                {diffTable(
                                  facts?.map((f) => f.data) ?? [],
                                  (s.expected_payload as Record<string, unknown>[]) ?? [],
                                  attrs,
                                )}
                              </TabsContent>
                            )}

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
                                      <Table className="text-xs">
                                        <TableHeader className="bg-muted">
                                          <TableRow>
                                            {attrs.map((a) => (
                                              <TableHead key={a} className="h-8">
                                                {a}
                                              </TableHead>
                                            ))}
                                            <TableHead className="h-8 w-8" />
                                          </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                          {expectedRows.map((row, ri) => (
                                            <TableRow key={ri}>
                                              {attrs.map((a) => (
                                                <TableCell key={a} className="p-1">
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
                                                </TableCell>
                                              ))}
                                              <TableCell className="p-1">
                                                <TipButton
                                                  tip="Remove this expected fact row"
                                                  variant="ghost"
                                                  size="icon"
                                                  className="size-7"
                                                  aria-label="Remove row"
                                                  onClick={() => removeExpectedRow(ri)}
                                                >
                                                  <Trash2 className="size-3.5 text-destructive" />
                                                </TipButton>
                                              </TableCell>
                                            </TableRow>
                                          ))}
                                          {expectedRows.length === 0 && (
                                            <TableRow>
                                              <TableCell
                                                colSpan={attrs.length + 1}
                                                className="py-3 text-center text-muted-foreground"
                                              >
                                                No expected facts yet.
                                              </TableCell>
                                            </TableRow>
                                          )}
                                        </TableBody>
                                      </Table>
                                    </div>
                                  )}
                                  <div className="flex flex-wrap gap-2">
                                    <TipButton
                                      tip="Add an empty expected fact row to fill in"
                                      variant="outline"
                                      size="sm"
                                      onClick={addExpectedRow}
                                    >
                                      <Plus />
                                      Row
                                    </TipButton>
                                    <TipButton
                                      tip="Copy the extracted facts into Expected as the baseline to compare against"
                                      variant="outline"
                                      size="sm"
                                      onClick={() => setExpectedFromExtracted(s)}
                                    >
                                      Set from extraction
                                    </TipButton>
                                    <TipButton
                                      tip="Save these expected facts as the document's gold"
                                      size="sm"
                                      onClick={() => saveExpected(s)}
                                    >
                                      <Save />
                                      Save
                                    </TipButton>
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
