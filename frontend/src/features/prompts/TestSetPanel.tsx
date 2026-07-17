import { type ComponentProps, Fragment, type MouseEvent as ReactMouseEvent, useEffect, useMemo, useRef, useState } from "react";
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

const DEFAULT_COL_W = 140;

/** Per-column widths for the result tables, persisted for the browser session
 * (sessionStorage, keyed per definition). Widths are keyed by column name so the
 * same attribute stays in sync across the Extracted / Expected / Diff tables. */
function useColWidths(key: number | string) {
  const storeKey = `cdew:test-set-colw:${key}`;
  const [widths, setWidths] = useState<Record<string, number>>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(storeKey) || "{}");
    } catch {
      return {};
    }
  });
  useEffect(() => {
    sessionStorage.setItem(storeKey, JSON.stringify(widths));
  }, [storeKey, widths]);

  const drag = useRef<{ col: string; startX: number; startW: number } | null>(null);
  useEffect(() => {
    const move = (e: MouseEvent) => {
      const d = drag.current;
      if (!d) return;
      setWidths((p) => ({ ...p, [d.col]: Math.max(56, d.startW + e.clientX - d.startX) }));
    };
    const up = () => {
      drag.current = null;
      document.body.style.cursor = "";
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, []);

  const startResize = (col: string, e: ReactMouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    drag.current = { col, startX: e.clientX, startW: widths[col] ?? DEFAULT_COL_W };
    document.body.style.cursor = "col-resize";
  };
  const widthOf = (col: string) => widths[col] ?? DEFAULT_COL_W;
  return { widthOf, startResize };
}
type ColWidths = ReturnType<typeof useColWidths>;

/** Drag handle on a resizable column's right edge — always visible (a thin grip
 * that thickens/points on hover). Requires a `relative` header cell. */
function ColHandle({ col, cols }: { col: string; cols: ColWidths }) {
  return (
    <span
      role="separator"
      aria-orientation="vertical"
      title="Drag to resize column"
      onMouseDown={(e) => cols.startResize(col, e)}
      onClick={(e) => e.stopPropagation()}
      className="group/handle absolute top-0 right-0 z-20 flex h-full w-3 cursor-col-resize touch-none items-center justify-center select-none"
    >
      <span className="h-4 w-0.5 rounded bg-border transition-all group-hover/handle:h-full group-hover/handle:w-1 group-hover/handle:bg-primary" />
    </span>
  );
}

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
function factsTable(
  rows: Record<string, unknown>[],
  attrs: string[],
  cols: ColWidths,
  sources?: (string | undefined)[],
) {
  const total = 40 + attrs.reduce((n, a) => n + cols.widthOf(a), 0) + (sources ? 256 : 0);
  return (
    <div className="max-h-72 overflow-auto rounded-md border bg-background">
      <Table className="table-fixed text-xs" style={{ width: total }}>
        <colgroup>
          <col style={{ width: 40 }} />
          {attrs.map((a) => (
            <col key={a} style={{ width: cols.widthOf(a) }} />
          ))}
          {sources && <col style={{ width: 256 }} />}
        </colgroup>
        <TableHeader className="sticky top-0 z-10 bg-muted">
          <TableRow>
            <TableHead className="h-8 text-muted-foreground">#</TableHead>
            {attrs.map((a) => (
              <TableHead key={a} className="relative h-8 truncate">
                {a}
                <ColHandle col={a} cols={cols} />
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
                <TableCell key={a} className="truncate py-1" title={String(data[a] ?? "")}>
                  {cell(data[a])}
                </TableCell>
              ))}
              {sources && (
                <TableCell className="truncate py-1 text-muted-foreground" title={sources[i]}>
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

type FactRow = Record<string, unknown>;
type FactPair = { ex?: FactRow; exp?: FactRow; kind: "same" | "changed" | "extra" | "missing" };

/** Stable stringify (object keys sorted) so equality is order-of-keys independent. */
const stable = (o: unknown) =>
  JSON.stringify(o, (_k, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.keys(v as object)
          .sort()
          .reduce((a, k) => ({ ...a, [k]: (v as Record<string, unknown>)[k] }), {})
      : v,
  );

/** Align two fact bags **without any domain key** (works for every extractor):
 *  1) match byte-identical facts 1:1 (multiset intersection) → `same`,
 *  2) greedily pair leftovers by field similarity → `changed` (field-level diff),
 *  3) whatever is left is `extra` (extracted-only) or `missing` (expected-only).
 * Order never matters; duplicate copies with no counterpart surface as extra/missing. */
function alignFacts(extracted: FactRow[], expected: FactRow[], attrs: string[]): FactPair[] {
  const pairs: FactPair[] = [];
  const expKeys = expected.map(stable);
  const usedExp = new Set<number>();
  const leftoverEx: FactRow[] = [];

  for (const e of extracted) {
    const k = stable(e);
    const j = expKeys.findIndex((ek, idx) => !usedExp.has(idx) && ek === k);
    if (j >= 0) {
      usedExp.add(j);
      pairs.push({ ex: e, exp: expected[j], kind: "same" });
    } else {
      leftoverEx.push(e);
    }
  }

  const leftoverExp = expected.filter((_, idx) => !usedExp.has(idx));
  const usedR = new Set<number>();
  const sim = (a: FactRow, b: FactRow) =>
    attrs.reduce((n, k) => n + (JSON.stringify(a[k]) === JSON.stringify(b[k]) ? 1 : 0), 0);

  for (const e of leftoverEx) {
    let best = -1;
    let bestScore = 0;
    leftoverExp.forEach((g, idx) => {
      if (usedR.has(idx)) return;
      const sc = sim(e, g);
      if (sc > bestScore) {
        bestScore = sc;
        best = idx;
      }
    });
    if (best >= 0) {
      usedR.add(best);
      pairs.push({ ex: e, exp: leftoverExp[best], kind: "changed" });
    } else {
      pairs.push({ ex: e, kind: "extra" });
    }
  }
  leftoverExp.forEach((g, idx) => {
    if (!usedR.has(idx)) pairs.push({ exp: g, kind: "missing" });
  });
  return pairs;
}

/** Two fact bags are equal iff, ignoring order, every fact pairs 1:1 (multiset). */
const factsEqual = (a: FactRow[], b: FactRow[]) =>
  a.length === b.length && alignFacts(a, b, []).every((p) => p.kind === "same");

const KIND_LABEL: Record<FactPair["kind"], string> = {
  same: "match",
  changed: "changed",
  extra: "extra",
  missing: "missing",
};

/** Diff of extracted vs expected facts (design §8.3), order-insensitive: facts are
 * aligned by identity/similarity (see {@link alignFacts}), not by position. Only
 * differing pairs are shown — each as two rows (extracted then expected) with the
 * changed cells highlighted; a side with no counterpart shows "—". Matched-identical
 * rows are hidden (their count is noted). */
function diffTable(
  extracted: Record<string, unknown>[],
  expected: Record<string, unknown>[],
  attrs: string[],
  cols: ColWidths,
) {
  const total = 40 + 80 + attrs.reduce((m, a) => m + cols.widthOf(a), 0);
  const differs = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);
  const pairs = alignFacts(extracted, expected, attrs);
  const diffs = pairs.filter((p) => p.kind !== "same");
  const sameCount = pairs.length - diffs.length;

  const line = (
    gi: number,
    which: "extracted" | "expected",
    data: Record<string, unknown> | undefined,
    other: Record<string, unknown> | undefined,
    kind: FactPair["kind"],
  ) => (
    <TableRow key={`${gi}-${which}`} className={cn(which === "extracted" && gi > 0 && "border-t-2")}>
      {which === "extracted" && (
        <TableCell rowSpan={2} className="align-middle">
          <Badge
            variant={kind === "changed" ? "secondary" : "destructive"}
            className={cn("font-normal", kind === "changed" && "text-destructive")}
          >
            {KIND_LABEL[kind]}
          </Badge>
        </TableCell>
      )}
      <TableCell className="py-1 text-muted-foreground">{which}</TableCell>
      {attrs.map((a) => (
        <TableCell
          key={a}
          title={data ? String(data[a] ?? "") : ""}
          className={cn("truncate py-1", differs(data?.[a], other?.[a]) && "bg-destructive/10 text-destructive")}
        >
          {data ? cell(data[a]) : <span className="text-muted-foreground">—</span>}
        </TableCell>
      ))}
    </TableRow>
  );
  return (
    <div className="max-h-96 overflow-auto rounded-md border bg-background">
      <Table className="table-fixed text-xs" style={{ width: total }}>
        <colgroup>
          <col style={{ width: 40 }} />
          <col style={{ width: 80 }} />
          {attrs.map((a) => (
            <col key={a} style={{ width: cols.widthOf(a) }} />
          ))}
        </colgroup>
        <TableHeader className="sticky top-0 z-10 bg-muted">
          <TableRow>
            <TableHead className="h-8 text-muted-foreground" />
            <TableHead className="h-8 text-muted-foreground">side</TableHead>
            {attrs.map((a) => (
              <TableHead key={a} className="relative h-8 truncate">
                {a}
                <ColHandle col={a} cols={cols} />
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {diffs.map((p, gi) => (
            <Fragment key={gi}>
              {line(gi, "extracted", p.ex, p.exp, p.kind)}
              {line(gi, "expected", p.exp, p.ex, p.kind)}
            </Fragment>
          ))}
          {sameCount > 0 && (
            <TableRow>
              <TableCell colSpan={attrs.length + 2} className="py-1.5 text-center text-muted-foreground">
                {sameCount} matching {sameCount === 1 ? "fact" : "facts"} hidden
              </TableCell>
            </TableRow>
          )}
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
  // Session-persisted column widths shared across the result tables (resizable).
  const cols = useColWidths(def.id);

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
    // Order-insensitive: extracted facts are an unordered bag, compared as a multiset.
    const facts = (extractedFacts(s) ?? []).map((f) => f.data);
    return factsEqual(facts, (s.expected_payload as FactRow[]) ?? []);
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

  // Drop byte-identical duplicate facts from Expected (generic across extractors).
  const dedupeExpected = (s: TestSample) => {
    const arr = (s.expected_payload as FactRow[] | null) ?? [];
    const seen = new Set<string>();
    const unique = arr.filter((f) => {
      const k = stable(f);
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
    if (unique.length === arr.length) {
      toast.info("No duplicate facts");
      return;
    }
    sactions.update.mutate(
      { id: s.id, expected_payload: unique },
      {
        onSuccess: () => {
          toast.success(`Removed ${arr.length - unique.length} duplicate fact(s)`);
          if (expandedId === s.id) setExpectedText(JSON.stringify(unique, null, 2));
        },
      },
    );
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
              // Per-tab counts. Expected: fact/type count; Result (classifier): routed types.
              const expectedArr = Array.isArray(s.expected_payload) ? (s.expected_payload as unknown[]) : null;
              const routedCount = (s.extracted_payload as { routed_types?: string[] } | null)?.routed_types?.length;
              const diffCount = showDiff
                ? alignFacts(facts?.map((f) => f.data) ?? [], (s.expected_payload as FactRow[]) ?? [], attrs).filter(
                    (p) => p.kind !== "same",
                  ).length
                : 0;

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
                        <div className="flex items-center gap-2">
                          {passBadge(s)}
                          <span className="text-xs text-muted-foreground">
                            {isClassifier
                              ? `routed: ${(s.extracted_payload as { routed_types?: string[] }).routed_types?.join(", ") || "—"}`
                              : `${facts?.length ?? 0} facts`}
                          </span>
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
                              <TabsTrigger value="result">
                                Result{routedCount === undefined ? "" : ` (${routedCount})`}
                              </TabsTrigger>
                              <TabsTrigger value="expected">Expected{expectedArr ? ` (${expectedArr.length})` : ""}</TabsTrigger>
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
                              <TabsTrigger value="expected">Expected{expectedArr ? ` (${expectedArr.length})` : ""}</TabsTrigger>
                              {showDiff && (
                                <TabsTrigger value="diff" className="text-destructive data-active:text-destructive!">
                                  Diff ({diffCount})
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
                                      cols,
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
                                  cols,
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
                                      <Table
                                        className="table-fixed text-xs"
                                        style={{ width: attrs.reduce((m, a) => m + cols.widthOf(a), 0) + 44 }}
                                      >
                                        <colgroup>
                                          {attrs.map((a) => (
                                            <col key={a} style={{ width: cols.widthOf(a) }} />
                                          ))}
                                          <col style={{ width: 44 }} />
                                        </colgroup>
                                        <TableHeader className="bg-muted">
                                          <TableRow>
                                            {attrs.map((a) => (
                                              <TableHead key={a} className="relative h-8 truncate">
                                                {a}
                                                <ColHandle col={a} cols={cols} />
                                              </TableHead>
                                            ))}
                                            <TableHead className="h-8" />
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
                                      tip="Remove byte-identical duplicate facts from Expected"
                                      variant="outline"
                                      size="sm"
                                      onClick={() => dedupeExpected(s)}
                                    >
                                      De-dupe
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
