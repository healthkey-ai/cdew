import { Fragment, useMemo, useState } from "react";
import { toast } from "sonner";
import { ChevronRight, FlaskConical, Loader2, Plus, Save, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useDocuments } from "@/features/documents/api";
import { cn } from "@/lib/utils";
import {
  type DryRunRow,
  type PromptDefinition,
  type PromptVersion,
  type TestSample,
  usePromptActions,
  useTestSampleActions,
  useTestSamples,
} from "./api";

/** Labeled test set for a classifier or extractor (design §8.3): add documents,
 * label the expected value, dry-run the selected version, and expand a sample to
 * inspect the extracted results and edit its expected value. */
export function TestSetPanel({ def, version }: { def: PromptDefinition; version: PromptVersion | null }) {
  const samples = useTestSamples(def.id);
  const sactions = useTestSampleActions(def.id);
  const dryRun = usePromptActions(def.id).dryRun;
  const docs = useDocuments();

  const [results, setResults] = useState<Record<number, DryRunRow>>({});
  const [docId, setDocId] = useState("");
  const [label, setLabel] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expectedText, setExpectedText] = useState("");

  const isClassifier = def.kind === "classifier";
  const types = useMemo(
    () => (isClassifier ? ((version?.taxonomy as { type: string }[] | undefined)?.map((t) => t.type) ?? []) : []),
    [isClassifier, version],
  );
  const parsedDocs = useMemo(() => (docs.data?.results ?? []).filter((d) => d.has_text), [docs.data]);
  // value → label map so the Select trigger shows the filename, not the id.
  const docItems = useMemo(
    () => Object.fromEntries(parsedDocs.map((d) => [String(d.id), d.original_filename || `doc#${d.id}`])),
    [parsedDocs],
  );

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

  const runAll = () => {
    if (!version) return;
    dryRun.mutate(version.id, {
      onSuccess: (d) => {
        const by: Record<number, DryRunRow> = {};
        d.results.forEach((r) => (by[r.sample_id] = r));
        setResults(by);
        const scored = d.results.filter((r) => r.passed !== undefined);
        if (scored.length) {
          const pass = scored.filter((r) => r.passed).length;
          toast[pass === scored.length ? "success" : "info"](`${pass}/${scored.length} passed`);
        } else {
          toast.info("Ran — expand a row to see results, then set the expected value");
        }
      },
      onError: (err) => {
        const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        toast.error(detail ?? "Dry-run failed — is the LLM configured for this environment?");
      },
    });
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

  const setExpectedFromRun = (s: TestSample) => {
    const row = results[s.id];
    if (!row?.facts) {
      toast.error("Run the test set first");
      return;
    }
    const expected = row.facts.map((f) => f.data);
    sactions.update.mutate(
      { id: s.id, expected_payload: expected },
      {
        onSuccess: () => {
          toast.success("Expected set from current output");
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

  const passBadge = (r?: DryRunRow) =>
    !r || r.passed === undefined ? null : (
      <Badge variant={r.passed ? "secondary" : "destructive"} className={r.passed ? "text-success" : ""}>
        {r.passed ? "pass" : "fail"}
      </Badge>
    );

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Test set{samples.data ? ` (${samples.data.length})` : ""}</CardTitle>
        <Button size="sm" onClick={runAll} disabled={!version || !samples.data?.length || dryRun.isPending}>
          {dryRun.isPending ? <Loader2 className="animate-spin" /> : <FlaskConical />}
          {dryRun.isPending ? "Running…" : "Run test set"}
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
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {samples.data?.map((s) => {
              const r = results[s.id];
              const open = expandedId === s.id;
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
                      {!r ? (
                        <span className="text-muted-foreground">—</span>
                      ) : isClassifier ? (
                        <div className="space-y-1">
                          {passBadge(r)}
                          <button onClick={() => toggle(s)} className="block text-xs text-muted-foreground hover:underline">
                            routed: {r.routed_types?.join(", ") || "—"}
                          </button>
                          {!!r.missing?.length && (
                            <div className="text-xs text-destructive">missing: {r.missing.join(", ")}</div>
                          )}
                          {!!r.extra?.length && <div className="text-xs text-warning">extra: {r.extra.join(", ")}</div>}
                        </div>
                      ) : (
                        <div className="space-y-1">
                          {passBadge(r)}
                          <button onClick={() => toggle(s)} className="block text-xs text-muted-foreground hover:underline">
                            {r.facts?.length ?? 0} facts extracted · view
                          </button>
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        aria-label="Remove sample"
                        onClick={() => sactions.remove.mutate(s.id)}
                      >
                        <Trash2 className="text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>

                  {open && (
                    <TableRow>
                      <TableCell colSpan={4} className="bg-muted/30">
                        <div className="grid gap-4 lg:grid-cols-2">
                          {/* extracted results (this run) */}
                          <div>
                            <div className="mb-1 text-xs font-medium">
                              Extracted results{!isClassifier && r?.facts ? ` (${r.facts.length})` : ""}
                            </div>
                            {!r ? (
                              <p className="text-xs text-muted-foreground">Run the test set to see the extraction.</p>
                            ) : isClassifier ? (
                              <div className="space-y-1 text-xs">
                                <div className="text-muted-foreground">
                                  outcome: {r.outcome} · routed: {r.routed_types?.join(", ") || "—"}
                                </div>
                                <ul className="space-y-0.5">
                                  {r.scores?.map((sc, i) => (
                                    <li key={i} className="text-muted-foreground">
                                      {sc.type}: {sc.confidence?.toFixed?.(2) ?? sc.confidence}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ) : (
                              <ul className="max-h-72 space-y-1 overflow-auto">
                                {r.facts?.map((f, i) => (
                                  <li key={i} className="rounded-md border bg-background p-1.5 text-xs">
                                    <code className="block break-all">{JSON.stringify(f.data)}</code>
                                    <div className="mt-0.5 text-muted-foreground">
                                      “{f.snippet}”
                                      {f.resolved ? "" : " · unresolved span"}
                                      {typeof f.confidence === "number" ? ` · ${f.confidence.toFixed(2)}` : ""}
                                    </div>
                                  </li>
                                ))}
                                {r.facts && r.facts.length === 0 && (
                                  <li className="text-xs text-muted-foreground">No facts extracted.</li>
                                )}
                              </ul>
                            )}
                          </div>

                          {/* expected editor */}
                          <div>
                            <div className="mb-1 flex items-center justify-between gap-2">
                              <span className="text-xs font-medium">Expected — JSON</span>
                              {!isClassifier && (
                                <Button variant="outline" size="sm" onClick={() => setExpectedFromRun(s)}>
                                  Set from run
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
                        </div>
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
            ? "Expected = the types this document should route to. Run, then expand a row to inspect scores and edit it."
            : "Expected = the facts this document should yield. Run to see the extraction, expand a row to inspect it, then “Set from run” / edit the JSON."}
        </p>
      </CardContent>
    </Card>
  );
}
